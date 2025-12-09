"""The actualbudget integration."""

from __future__ import annotations
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .services import async_setup_services, async_unload_services
from .actual import ActualAPI
from .const import (
    CONFIG_ENDPOINT,
    CONFIG_PASSWORD,
    CONFIG_FILE,
    CONFIG_CERT,
    CONFIG_ENCRYPT_PASSWORD,
)

__version__ = "3.1.1"
_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the component from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Create API instance
    config = entry.data
    endpoint = config[CONFIG_ENDPOINT]
    password = config[CONFIG_PASSWORD]
    file = config[CONFIG_FILE]
    cert = config.get(CONFIG_CERT)
    if cert == "SKIP":
        cert = False
    encrypt_password = config.get(CONFIG_ENCRYPT_PASSWORD)
    
    api = ActualAPI(hass, endpoint, password, file, cert, encrypt_password)
    
    # Store API instance
    hass.data[DOMAIN][entry.entry_id] = api
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Set up services (only once)
    if len(hass.data[DOMAIN]) == 1:
        await async_setup_services(hass)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Remove API instance
        hass.data[DOMAIN].pop(entry.entry_id)
        
        # Unload services if this was the last instance
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
