"""Platform for sensor integration."""

from __future__ import annotations

from decimal import Decimal
import logging

from typing import Dict, Union
from urllib.parse import urlparse
import datetime

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.components.sensor.const import (
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_ICON_ACCOUNT,
    DEFAULT_ICON_BUDGET,
    DEFAULT_ICON_UNCATEGORIZED,
    DOMAIN,
    CONFIG_ENDPOINT,
    CONFIG_PASSWORD,
    CONFIG_FILE,
    CONFIG_CURRENCY,
    CONFIG_CERT,
    CONFIG_ENCRYPT_PASSWORD,
    # Legacy support
    CONFIG_UNIT,
)
from .actual import ActualAPI, BudgetAmount

_LOGGER = logging.getLogger(__name__)

# Time between updating data from API
SCAN_INTERVAL = datetime.timedelta(minutes=60)
MINIMUM_INTERVAL = datetime.timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Setup sensor platform."""
    config = config_entry.data
    
    # Get API instance from hass.data
    api: ActualAPI = hass.data[DOMAIN][config_entry.entry_id]
    
    # Get currency with backward compatibility
    currency = config.get(CONFIG_CURRENCY) or config.get(CONFIG_UNIT, "€")
    
    # Get file ID for unique identification
    file = config[CONFIG_FILE]
    unique_source_id = file

    # Create account sensors
    accounts = await api.get_accounts()
    last_update = datetime.datetime.now()
    account_sensors = [
        ActualAccountSensor(
            api,
            account.id,
            account.name,
            account.balance,
            unique_source_id,
            currency,
            last_update,
        )
        for account in accounts
    ]
    async_add_entities(account_sensors, update_before_add=True)

    # Create budget sensors
    budgets = await api.get_budgets()
    last_update = datetime.datetime.now()
    budget_sensors = [
        ActualBudgetSensor(
            api,
            budget.id,
            budget.name,
            budget.group_name,
            budget.amounts,
            budget.balance,
            unique_source_id,
            currency,
            last_update,
        )
        for budget in budgets
    ]
    async_add_entities(budget_sensors, update_before_add=True)

    # Create uncategorized transactions sensor
    uncategorized_sensor = ActualUncategorizedTransactionsSensor(
        api,
        unique_source_id,
        last_update,
    )
    async_add_entities([uncategorized_sensor], update_before_add=True)


class ActualAccountSensor(SensorEntity):
    """Representation of an Actual Budget Account Sensor."""

    def __init__(
        self,
        api: ActualAPI,
        account_id: str | None,
        name: str,
        balance: float,
        unique_source_id: str,
        currency: str,
        balance_last_updated: datetime.datetime,
    ):
        super().__init__()
        self._api = api
        self._account_id = account_id
        self._name = name
        self._balance = balance
        self._unique_source_id = unique_source_id
        self._currency = currency
        self._balance_last_updated = balance_last_updated

        self._icon = DEFAULT_ICON_ACCOUNT
        self._device_class = SensorDeviceClass.MONETARY
        self._state_class = SensorStateClass.MEASUREMENT
        self._available = True

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return f"{DOMAIN}-{self._unique_source_id}-{self._name}".lower()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def state(self) -> float:
        return self._balance

    @property
    def device_class(self):
        return self._device_class

    @property
    def state_class(self):
        return self._state_class

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return self._currency

    @property
    def icon(self):
        return self._icon

    @property
    def extra_state_attributes(self) -> Dict[str, Union[str, float]]:
        """Return extra state attributes."""
        attrs = {}
        if self._account_id:
            attrs["account_id"] = self._account_id
        return attrs

    async def async_update(self) -> None:
        if (
            self._balance_last_updated
            and datetime.datetime.now() - self._balance_last_updated < MINIMUM_INTERVAL
        ):
            return
        """Fetch new state data for the sensor."""
        try:
            account = await self._api.get_account(self._name)
            if account:
                self._balance = account.balance
                self._account_id = account.id
            self._balance_last_updated = datetime.datetime.now()
        except Exception as err:
            self._available = False
            _LOGGER.exception(
                "Unknown error updating data from ActualBudget API to account %s. %s",
                self._name,
                err,
            )


class ActualBudgetSensor(SensorEntity):
    """Representation of an Actual Budget Budget Sensor."""

    def __init__(
        self,
        api: ActualAPI,
        budget_id: str | None,
        name: str,
        group_name: str | None,
        amounts: list[BudgetAmount],
        balance: float,
        unique_source_id: str,
        currency: str,
        balance_last_updated: datetime.datetime,
    ):
        super().__init__()
        self._api = api
        self._budget_id = budget_id
        self._name = name
        self._group_name = group_name
        self._amounts = amounts
        self._balance = balance
        self._unique_source_id = unique_source_id
        self._currency = currency
        self._balance_last_updated = balance_last_updated

        self._icon = DEFAULT_ICON_BUDGET
        self._device_class = SensorDeviceClass.MONETARY
        self._state_class = SensorStateClass.MEASUREMENT
        self._available = True

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        if self._group_name:
            return f"budget_{self._group_name} - {self._name}"
        return f"budget_{self._name}"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return f"{DOMAIN}-{self._unique_source_id}-budget-{self._name}".lower()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def device_class(self):
        return self._device_class

    @property
    def state_class(self):
        return self._state_class

    @property
    def unit_of_measurement(self):
        """Return the unit the value is expressed in."""
        return self._currency

    @property
    def icon(self):
        return self._icon

    @property
    def state(self) -> float | None:
        total = 0
        for amount in self._amounts:
            if datetime.datetime.strptime(amount.month, '%Y%m') <= datetime.datetime.now():
                total += amount.amount if amount.amount else 0
        return round(self._balance + Decimal(total), 2)

    @property
    def extra_state_attributes(self) -> Dict[str, Union[str, float]]:
        extra_state_attributes = {}
        
        if self._budget_id:
            extra_state_attributes["category_id"] = self._budget_id
        if self._group_name:
            extra_state_attributes["group_name"] = self._group_name
        
        amounts = [amount for amount in self._amounts if datetime.datetime.strptime(amount.month, '%Y%m') <= datetime.datetime.now()]
        if amounts:
            current_month = amounts[-1].month
            if current_month:
                extra_state_attributes["current_month"] = current_month
                extra_state_attributes["current_amount"] = amounts[-1].amount
            if len(amounts) > 1:
                extra_state_attributes["previous_month"] = amounts[-2].month
                extra_state_attributes["previous_amount"] = amounts[-2].amount
                total = 0
                for amount in amounts:
                    total += amount.amount if amount.amount else 0
                extra_state_attributes["total_amount"] = total

        return extra_state_attributes

    async def async_update(self) -> None:
        if (
            self._balance_last_updated
            and datetime.datetime.now() - self._balance_last_updated < MINIMUM_INTERVAL
        ):
            return
        """Fetch new state data for the sensor."""
        try:
            budget = await self._api.get_budget(self._name)
            self._balance_last_updated = datetime.datetime.now()
            if budget:
                self._amounts = budget.amounts
                self._balance = budget.balance
                self._budget_id = budget.id
                self._group_name = budget.group_name
        except Exception as err:
            self._available = False
            _LOGGER.exception(
                "Unknown error updating data from ActualBudget API to budget %s. %s",
                self._name,
                err,
            )


class ActualUncategorizedTransactionsSensor(SensorEntity):
    """Representation of an Actual Budget Uncategorized Transactions Sensor."""

    def __init__(
        self,
        api: ActualAPI,
        unique_source_id: str,
        last_updated: datetime.datetime,
    ):
        super().__init__()
        self._api = api
        self._unique_source_id = unique_source_id
        self._count = 0
        self._last_updated = last_updated
        self._available = True

        self._icon = DEFAULT_ICON_UNCATEGORIZED

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return "Uncategorized Transactions"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return f"{DOMAIN}-{self._unique_source_id}-uncategorized-transactions".lower()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def state(self) -> int:
        return self._count

    @property
    def icon(self):
        return self._icon

    async def async_update(self) -> None:
        if (
            self._last_updated
            and datetime.datetime.now() - self._last_updated < MINIMUM_INTERVAL
        ):
            return
        """Fetch new state data for the sensor."""
        try:
            self._count = await self._api.get_uncategorized_transactions_count()
            self._last_updated = datetime.datetime.now()
        except Exception as err:
            self._available = False
            _LOGGER.exception(
                "Unknown error updating uncategorized transactions count. %s",
                err,
            )
