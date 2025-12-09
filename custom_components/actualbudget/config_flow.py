"""Config flow for actualbudget integration."""

from __future__ import annotations

import logging
import voluptuous as vol
from urllib.parse import urlparse

from homeassistant import config_entries

from .actual import ActualAPI
from .const import (
    DOMAIN,
    CONFIG_ENDPOINT,
    CONFIG_PASSWORD,
    CONFIG_FILE,
    CONFIG_CERT,
    CONFIG_ENCRYPT_PASSWORD,
    CONFIG_CURRENCY,
    # Legacy for backward compatibility
    CONFIG_UNIT,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONFIG_ENDPOINT): str,
        vol.Required(CONFIG_PASSWORD): str,
        vol.Required(CONFIG_FILE): str,
        vol.Required(CONFIG_CURRENCY, default="€"): str,
        vol.Optional(CONFIG_CERT): str,
        vol.Optional(CONFIG_ENCRYPT_PASSWORD): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """actualbudget config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user interface."""
        _LOGGER.info("=== ACTUAL BUDGET CONFIG FLOW STEP USER ===")
        _LOGGER.debug("User input received: %s", "None (showing form)" if user_input is None else "Data submitted")

        if user_input is None:
            _LOGGER.debug("Showing configuration form")
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

        _LOGGER.info("Processing submitted configuration data")
        endpoint = user_input[CONFIG_ENDPOINT]
        password = user_input[CONFIG_PASSWORD]
        file = user_input[CONFIG_FILE]
        cert = user_input.get(CONFIG_CERT)
        encrypt_password = user_input.get(CONFIG_ENCRYPT_PASSWORD)
        
        _LOGGER.debug("Extracted config - endpoint: %s, file: %s", endpoint, file)
        
        # Handle legacy CONFIG_UNIT by converting to CONFIG_CURRENCY
        if CONFIG_UNIT in user_input and CONFIG_CURRENCY not in user_input:
            user_input[CONFIG_CURRENCY] = user_input[CONFIG_UNIT]
        
        if cert == "SKIP":
            cert = False
            _LOGGER.debug("Certificate validation will be skipped")

        # Use file ID as unique identifier
        unique_id = file.lower()
        _LOGGER.debug("Setting unique_id: %s", unique_id)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        _LOGGER.info("Initiating connection test...")
        error = await self._test_connection(
            endpoint, password, file, cert, encrypt_password
        )
        
        if error:
            _LOGGER.error("Connection test failed with error: %s", error)
            return self.async_show_form(
                step_id="user", data_schema=DATA_SCHEMA, errors={"base": error}
            )
        else:
            _LOGGER.info("Connection test successful, creating config entry")
            domain = urlparse(endpoint).hostname
            port = urlparse(endpoint).port
            return self.async_create_entry(
                title=f"{domain}:{port} {file}",
                data=user_input,
            )

    async def _test_connection(self, endpoint, password, file, cert, encrypt_password):
        """Test the connection to Actual Budget.
        
        This tests the connection using actualpy library which connects directly
        to the Actual Budget server's sync protocol.
        
        Args:
            endpoint: Full URL to Actual Budget server
            password: Server password (NOT an API key - the password set on server startup)
            file: Budget file ID (UUID format)
            cert: SSL certificate or False to skip validation
            encrypt_password: Optional file encryption password
        """
        _LOGGER.info("=== ACTUAL BUDGET CONNECTION TEST STARTING ===")
        _LOGGER.info("Endpoint: %s", endpoint)
        _LOGGER.info("File ID: %s", file)
        _LOGGER.info("Certificate: %s", "SKIP" if cert is False else ("configured" if cert else "none"))
        _LOGGER.info("Encryption: %s", "enabled" if encrypt_password else "disabled")
        
        try:
            api = ActualAPI(self.hass, endpoint, password, file, cert, encrypt_password)
            result = await api.test_connection()
            
            _LOGGER.info("=== CONNECTION TEST RESULT: %s ===", result if result else "SUCCESS")
            return result
        except Exception as e:
            _LOGGER.exception("=== EXCEPTION IN CONFIG FLOW _test_connection ===")
            _LOGGER.error("Exception type: %s", type(e).__name__)
            _LOGGER.error("Exception message: %s", str(e))
            return "failed_unknown"
