"""The Habitron integration."""
from __future__ import annotations

import socket

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .smart_ip import SmartIP

# List of platforms to support. There should be a matching .py file for each
PLATFORMS: list[str] = [
    "sensor",
    "light",
    "cover",
    "number",
    "button",
    "binary_sensor",
    "select",
    # "climate",
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Habitron from a config entry."""
    # Store an instance of the "connecting" class that does the work of speaking
    # with your actual devices.
    smip = SmartIP(hass, entry)
    await smip.initialize(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = smip

    # Register update handler for runtime configuration of Habitron integration
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # This creates each HA object for each platform your device requires.
    # It's done by calling the `async_setup_entry` function in each platform module.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    hbtn_comm = hass.data[DOMAIN][entry.entry_id].router.comm
    hbtn_cord = hass.data[DOMAIN][entry.entry_id].router.coord
    hbtn_comm.set_host()
    hbtn_cord.set_update_interval()
