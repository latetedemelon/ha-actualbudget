"""Actual Budget API wrapper for Home Assistant."""

from __future__ import annotations

from decimal import Decimal
import logging
from dataclasses import dataclass
from typing import List
from datetime import datetime, timedelta
import threading

from actual import Actual
from actual.exceptions import (
    UnknownFileId,
    InvalidFile,
    InvalidZipFile,
    AuthorizationError,
)
from actual.queries import (
    get_accounts,
    get_account,
    get_budgets,
    get_category,
    get_transactions,
)
from requests.exceptions import ConnectionError, SSLError

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SESSION_TIMEOUT = timedelta(minutes=30)


@dataclass
class BudgetAmount:
    """Represents a budget amount for a specific month."""
    month: str
    amount: float | None


@dataclass
class Budget:
    """Represents a budget category."""
    id: str | None
    name: str
    group_name: str | None
    amounts: List[BudgetAmount]
    balance: Decimal


@dataclass
class Account:
    """Represents an account."""
    id: str | None
    name: str | None
    balance: Decimal


class ActualAPI:
    """API wrapper for Actual Budget."""

    def __init__(
        self,
        hass: HomeAssistant,
        endpoint: str,
        password: str,
        file: str,
        cert: str | bool,
        encrypt_password: str | None,
    ):
        """Initialize the Actual API."""
        self.hass = hass
        self.endpoint = endpoint
        self.password = password
        self.file = file
        self.cert = cert
        self.encrypt_password = encrypt_password
        self.actual = None
        self.session_started_at = datetime.now()
        self._lock = threading.Lock()

    def get_session(self):
        """Get Actual session if it exists, or create a new one safely."""
        with self._lock:
            # Invalidate session if it is too old
            if (
                self.actual
                and self.session_started_at + SESSION_TIMEOUT < datetime.now()
            ):
                try:
                    self.actual.__exit__(None, None, None)
                except Exception as e:
                    _LOGGER.error("Error closing session: %s", e)
                self.actual = None

            # Validate existing session
            if self.actual:
                try:
                    result = self.actual.validate()
                    if not result.data.validated:
                        raise Exception("Session not validated")
                    # Request sync when session already exists
                    self.actual.sync()
                except Exception as e:
                    _LOGGER.error("Error validating session: %s", e)
                    self.actual = None

            # Create a new session if needed
            if not self.actual:
                self.actual = self._create_session()
                self.session_started_at = datetime.now()

        return self.actual.session

    def _create_session(self):
        """Create a new Actual session."""
        # Use file ID for data directory to support multiple files
        data_dir = self.hass.config.path("actualbudget", self.file)
        
        actual = Actual(
            base_url=self.endpoint,
            password=self.password,
            cert=self.cert,
            encryption_password=self.encrypt_password,
            file=self.file,
            data_dir=data_dir,
        )
        actual.__enter__()
        result = actual.validate()
        if not result.data.validated:
            raise Exception("Session not validated")
        return actual

    async def sync(self) -> None:
        """Sync all accounts with bank."""
        return await self.hass.async_add_executor_job(self._sync)

    def _sync(self) -> None:
        """Sync all accounts with bank (synchronous)."""
        with self._lock:
            session = self.get_session()
            if self.actual:
                self.actual.sync()

    async def get_accounts(self) -> List[Account]:
        """Get accounts."""
        return await self.hass.async_add_executor_job(self._get_accounts)

    def _get_accounts(self) -> List[Account]:
        """Get accounts (synchronous)."""
        session = self.get_session()
        accounts = get_accounts(session)
        return [
            Account(id=a.id, name=a.name, balance=a.balance) for a in accounts
        ]

    async def get_account(self, account_name: str) -> Account:
        """Get a specific account."""
        return await self.hass.async_add_executor_job(
            self._get_account,
            account_name,
        )

    def _get_account(self, account_name: str) -> Account:
        """Get a specific account (synchronous)."""
        session = self.get_session()
        account = get_account(session, account_name)
        if not account:
            raise Exception(f"Account {account_name} not found")
        return Account(id=account.id, name=account.name, balance=account.balance)

    async def get_budgets(self) -> List[Budget]:
        """Get budgets."""
        return await self.hass.async_add_executor_job(self._get_budgets)

    def _get_budgets(self) -> List[Budget]:
        """Get budgets (synchronous)."""
        session = self.get_session()
        budgets_raw = get_budgets(session)
        budgets: dict[str, Budget] = {}
        
        for budget_raw in budgets_raw:
            if not budget_raw.category:
                continue
            
            category = budget_raw.category
            category_name = str(category.name)
            group_name = None
            
            # Include group name if available
            if hasattr(category, 'group') and category.group:
                group_name = str(category.group.name)
                display_name = f"{group_name} - {category_name}"
            else:
                display_name = category_name
            
            amount = None if not budget_raw.amount else (float(budget_raw.amount) / 100)
            month = str(budget_raw.month)
            
            if display_name not in budgets:
                budgets[display_name] = Budget(
                    id=category.id,
                    name=category_name,
                    group_name=group_name,
                    amounts=[],
                    balance=Decimal(0),
                )
            budgets[display_name].amounts.append(
                BudgetAmount(month=month, amount=amount)
            )
        
        for category_key in budgets:
            budgets[category_key].amounts = sorted(
                budgets[category_key].amounts, key=lambda x: x.month
            )
            category_data = get_category(session, budgets[category_key].name)
            budgets[category_key].balance = (
                category_data.balance if category_data else Decimal(0)
            )
        
        return list(budgets.values())

    async def get_budget(self, budget_name: str) -> Budget:
        """Get a specific budget."""
        return await self.hass.async_add_executor_job(
            self._get_budget,
            budget_name,
        )

    def _get_budget(self, budget_name: str) -> Budget:
        """Get a specific budget (synchronous)."""
        session = self.get_session()
        budgets_raw = get_budgets(session, None, budget_name)
        if not budgets_raw or not budgets_raw[0]:
            raise Exception(f"Budget {budget_name} not found")
        
        budget_raw = budgets_raw[0]
        category = budget_raw.category
        group_name = None
        
        if hasattr(category, 'group') and category.group:
            group_name = str(category.group.name)
        
        budget = Budget(
            id=category.id if category else None,
            name=budget_name,
            group_name=group_name,
            amounts=[],
            balance=Decimal(0),
        )
        
        for budget_raw in budgets_raw:
            amount = None if not budget_raw.amount else (float(budget_raw.amount) / 100)
            month = str(budget_raw.month)
            budget.amounts.append(BudgetAmount(month=month, amount=amount))
        
        budget.amounts = sorted(budget.amounts, key=lambda x: x.month)
        category_data = get_category(session, budget_name)
        budget.balance = category_data.balance if category_data else Decimal(0)
        return budget

    async def get_uncategorized_transactions_count(self) -> int:
        """Get count of uncategorized transactions."""
        return await self.hass.async_add_executor_job(
            self._get_uncategorized_transactions_count
        )

    def _get_uncategorized_transactions_count(self) -> int:
        """Get count of uncategorized transactions (synchronous)."""
        session = self.get_session()
        transactions = get_transactions(session)
        # Filter for uncategorized transactions (category is None)
        uncategorized = [t for t in transactions if t.category is None]
        return len(uncategorized)

    async def test_connection(self):
        """Test the connection to Actual Budget."""
        return await self.hass.async_add_executor_job(self._test_connection)

    def _test_connection(self):
        """Test the connection to Actual Budget (synchronous)."""
        try:
            session = self.get_session()
            if not session:
                return "failed_file"
        except SSLError:
            return "failed_ssl"
        except ConnectionError:
            return "failed_connection"
        except AuthorizationError:
            return "failed_auth"
        except UnknownFileId:
            return "failed_file"
        except InvalidFile:
            return "failed_file"
        except InvalidZipFile:
            return "failed_file"
        return None
