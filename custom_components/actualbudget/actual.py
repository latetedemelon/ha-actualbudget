"""Actual Budget API wrapper for Home Assistant.

Connection Information:
-----------------------
This integration connects directly to the Actual Budget server using actualpy.
It does NOT use the actual-http-api (jhonderson/actual-http-api) REST API wrapper.

Authentication:
- The 'password' parameter is the Actual Budget SERVER password (not an API key)
- This is the password you set when first starting the Actual Budget server
- It is NOT the optional file encryption password (that's separate)

Connection Parameters:
- endpoint: Full URL to Actual Budget server (e.g., https://actual.example.com or http://localhost:5006)
- password: Server password for authentication
- file: The budget file ID (UUID format, found in Actual Budget web interface)
- cert: SSL certificate path, or False/'SKIP' to skip certificate validation
- encrypt_password: Optional file encryption password (if the budget file is encrypted)

The actualpy library (https://github.com/bvanelli/actualpy) handles the low-level
communication with the Actual Budget server's sync protocol.
"""

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
        _LOGGER.debug("Creating new Actual session...")
        
        # Use file ID for data directory to support multiple files
        data_dir = self.hass.config.path("actualbudget", self.file)
        _LOGGER.debug("Data directory: %s", data_dir)
        
        _LOGGER.debug("Initializing Actual client with base_url=%s, file=%s", 
                     self.endpoint, self.file)
        
        actual = Actual(
            base_url=self.endpoint,
            password=self.password,
            cert=self.cert,
            encryption_password=self.encrypt_password,
            file=self.file,
            data_dir=data_dir,
        )
        
        _LOGGER.debug("Entering Actual context manager...")
        actual.__enter__()
        
        _LOGGER.debug("Validating session...")
        result = actual.validate()
        
        if not result.data.validated:
            _LOGGER.error("Session validation failed - server rejected the credentials")
            raise Exception("Session not validated")
        
        _LOGGER.info("Session created and validated successfully")
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
        _LOGGER.info("test_connection called - delegating to executor")
        try:
            result = await self.hass.async_add_executor_job(self._test_connection)
            _LOGGER.info("Executor job completed with result: %s", result)
            return result
        except Exception as e:
            _LOGGER.exception("Exception in async_add_executor_job for test_connection")
            _LOGGER.error("Exception type: %s", type(e).__name__)
            _LOGGER.error("Exception details: %s", str(e))
            return "failed_unknown"

    def _test_connection(self):
        """Test the connection to Actual Budget (synchronous)."""
        _LOGGER.info("=== ACTUAL BUDGET CONNECTION TEST (sync) ===")
        _LOGGER.info("Endpoint: %s", self.endpoint)
        _LOGGER.info("File ID: %s", self.file)
        _LOGGER.info("Certificate: %s", "configured" if self.cert else "none/skip")
        _LOGGER.info("Encryption: %s", "enabled" if self.encrypt_password else "disabled")
        
        try:
            _LOGGER.info("Attempting to create/get session...")
            session = self.get_session()
            
            if not session:
                _LOGGER.error("Session creation failed - no session returned")
                return "failed_file"
            
            _LOGGER.info("=== CONNECTION TEST SUCCESSFUL ===")
            return None
            
        except SSLError as e:
            _LOGGER.error("=== SSL/Certificate ERROR ===")
            _LOGGER.error("SSL error details: %s", str(e))
            _LOGGER.error("Check that the certificate is valid or use 'SKIP' to bypass certificate validation")
            return "failed_ssl"
        except ConnectionError as e:
            _LOGGER.error("=== NETWORK CONNECTION ERROR ===")
            _LOGGER.error("Connection error details: %s", str(e))
            _LOGGER.error("Verify that the endpoint URL is correct and the server is accessible")
            _LOGGER.error("Common issues: Wrong URL, server not running, firewall blocking connection")
            return "failed_connection"
        except AuthorizationError as e:
            _LOGGER.error("=== AUTHORIZATION FAILED ===")
            _LOGGER.error("Authorization error details: %s", str(e))
            _LOGGER.error("The password provided does not match the server password")
            _LOGGER.info("Note: This is the server password, NOT an API key")
            return "failed_auth"
        except UnknownFileId as e:
            _LOGGER.error("=== UNKNOWN FILE ID ===")
            _LOGGER.error("File ID error details: %s", str(e))
            _LOGGER.error("File ID provided: %s", self.file)
            _LOGGER.error("Please verify the file ID is correct in your Actual Budget server")
            return "failed_file"
        except InvalidFile as e:
            _LOGGER.error("=== INVALID FILE ===")
            _LOGGER.error("Invalid file details: %s", str(e))
            _LOGGER.error("This may indicate file corruption or incorrect encryption password")
            return "failed_file"
        except InvalidZipFile as e:
            _LOGGER.error("=== INVALID ZIP FILE ===")
            _LOGGER.error("Zip file error details: %s", str(e))
            _LOGGER.error("The budget file may need to be repaired or restored from backup")
            return "failed_file"
        except Exception as e:
            _LOGGER.exception("=== UNEXPECTED ERROR ===")
            _LOGGER.error("Error type: %s", type(e).__name__)
            _LOGGER.error("Error details: %s", str(e))
            _LOGGER.error("Full traceback logged above")
            return "failed_unknown"
