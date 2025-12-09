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
        _LOGGER.debug("Starting async_step_user...")

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

        endpoint = user_input[CONFIG_ENDPOINT]
        password = user_input[CONFIG_PASSWORD]
        file = user_input[CONFIG_FILE]
        cert = user_input.get(CONFIG_CERT)
        encrypt_password = user_input.get(CONFIG_ENCRYPT_PASSWORD)
        
        # Handle legacy CONFIG_UNIT by converting to CONFIG_CURRENCY
        if CONFIG_UNIT in user_input and CONFIG_CURRENCY not in user_input:
            user_input[CONFIG_CURRENCY] = user_input[CONFIG_UNIT]
        
        if cert == "SKIP":
            cert = False

        # Use file ID as unique identifier
        unique_id = file.lower()
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        error = await self._test_connection(
            endpoint, password, file, cert, encrypt_password
        )
        if error:
            return self.async_show_form(
                step_id="user", data_schema=DATA_SCHEMA, errors={"base": error}
            )
        else:
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
        _LOGGER.debug("Testing connection with endpoint=%s, file=%s", endpoint, file)
        api = ActualAPI(self.hass, endpoint, password, file, cert, encrypt_password)
        return await api.test_connection()
