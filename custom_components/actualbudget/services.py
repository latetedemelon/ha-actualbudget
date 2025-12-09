"""Services for Actual Budget integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .actual import ActualAPI

_LOGGER = logging.getLogger(__name__)

# Service schemas
SERVICE_GET_TRANSACTIONS = "get_transactions"
SERVICE_CREATE_SPLITS = "create_splits"
SERVICE_GET_ACCOUNTS = "get_accounts"
SERVICE_BANK_SYNC = "bank_sync"

SCHEMA_GET_TRANSACTIONS = vol.Schema({})
SCHEMA_CREATE_SPLITS = vol.Schema({})
SCHEMA_GET_ACCOUNTS = vol.Schema({})
SCHEMA_BANK_SYNC = vol.Schema({})


def _get_api_instance(hass: HomeAssistant) -> ActualAPI | None:
    """Get the first available API instance."""
    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        return None
    return list(hass.data[DOMAIN].values())[0]


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Actual Budget integration."""

    async def handle_get_transactions(call: ServiceCall) -> dict[str, Any]:
        """Handle the get_transactions service call."""
        api = _get_api_instance(hass)
        if not api:
            _LOGGER.error("No Actual Budget instances configured")
            return {"error": "No instances configured"}

        try:
            # TODO: Implement get_transactions in actual.py
            # This would need methods to retrieve and return transaction data
            _LOGGER.warning("get_transactions service is not yet fully implemented")
            return {"success": True, "message": "Service placeholder - not yet implemented"}
        except Exception as e:
            _LOGGER.error("Error getting transactions: %s", e)
            return {"error": str(e)}

    async def handle_create_splits(call: ServiceCall) -> dict[str, Any]:
        """Handle the create_splits service call."""
        api = _get_api_instance(hass)
        if not api:
            _LOGGER.error("No Actual Budget instances configured")
            return {"error": "No instances configured"}

        try:
            # TODO: Implement create_splits in actual.py
            # This would need methods to create transaction splits
            _LOGGER.warning("create_splits service is not yet fully implemented")
            return {"success": True, "message": "Service placeholder - not yet implemented"}
        except Exception as e:
            _LOGGER.error("Error creating splits: %s", e)
            return {"error": str(e)}

    async def handle_get_accounts(call: ServiceCall) -> dict[str, Any]:
        """Handle the get_accounts service call."""
        api = _get_api_instance(hass)
        if not api:
            _LOGGER.error("No Actual Budget instances configured")
            return {"error": "No instances configured"}

        try:
            accounts = await api.get_accounts()
            return {
                "accounts": [
                    {
                        "id": acc.id,
                        "name": acc.name,
                        "balance": float(acc.balance),
                    }
                    for acc in accounts
                ]
            }
        except Exception as e:
            _LOGGER.error("Error getting accounts: %s", e)
            return {"error": str(e)}

    async def handle_bank_sync(call: ServiceCall) -> dict[str, Any]:
        """Handle the bank_sync service call."""
        api = _get_api_instance(hass)
        if not api:
            _LOGGER.error("No Actual Budget instances configured")
            return {"error": "No instances configured"}

        try:
            await api.sync()
            _LOGGER.info("Bank sync completed successfully")
            return {"success": True}
        except Exception as e:
            _LOGGER.error("Error syncing bank accounts: %s", e)
            return {"error": str(e)}

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_TRANSACTIONS,
        handle_get_transactions,
        schema=SCHEMA_GET_TRANSACTIONS,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_SPLITS,
        handle_create_splits,
        schema=SCHEMA_CREATE_SPLITS,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ACCOUNTS,
        handle_get_accounts,
        schema=SCHEMA_GET_ACCOUNTS,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_BANK_SYNC,
        handle_bank_sync,
        schema=SCHEMA_BANK_SYNC,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload Actual Budget services."""
    hass.services.async_remove(DOMAIN, SERVICE_GET_TRANSACTIONS)
    hass.services.async_remove(DOMAIN, SERVICE_CREATE_SPLITS)
    hass.services.async_remove(DOMAIN, SERVICE_GET_ACCOUNTS)
    hass.services.async_remove(DOMAIN, SERVICE_BANK_SYNC)
