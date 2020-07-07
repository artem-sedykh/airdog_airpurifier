"""Support for Xiaomi Miio."""
import logging

from homeassistant import config_entries, core


_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: core.HomeAssistant, config: dict):
    """Set up the Xiaomi Miio component."""
    return True


async def async_setup_entry(
        hass: core.HomeAssistant, entry: config_entries.ConfigEntry
):
    return True
