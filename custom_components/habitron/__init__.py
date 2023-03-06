"""The Habitron integration."""
from __future__ import annotations

import asyncio
import voluptuous as vol

from homeassistant import exceptions
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, ROUTER_NMBR, RESTART_KEY_NMBR, FILE_MOD_NMBR, RESTART_ALL
from .smart_ip import SmartIP
from .communicate import TimeoutException

# List of platforms to support. There should be a matching .py file for each
PLATFORMS: list[str] = [
    "sensor",
    "light",
    "switch",
    "cover",
    "number",
    "button",
    "binary_sensor",
    "select",
    "climate",
]
SERVICE_MOD_RESTART_SCHEMA = vol.Schema(
    {
        vol.Required(ROUTER_NMBR, default=1): int,
        vol.Optional(RESTART_KEY_NMBR, default=1): int,
    }
)
SERVICE_MOD_FILE_SCHEMA = vol.Schema(
    {
        vol.Required(ROUTER_NMBR, default=1): int,
        vol.Required(FILE_MOD_NMBR, default=1): int,
    }
)
SERVICE_RTR_FILE_SCHEMA = vol.Schema(
    {
        vol.Required(ROUTER_NMBR, default=1): int,
    }
)
SERVICE_RTR_RESTART_SCHEMA = vol.Schema(
    {
        vol.Required(ROUTER_NMBR, default=1): int,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Habitron from a config entry."""
    # Store an instance of the "connecting" class that does the work of speaking
    # with your actual devices.

    async def restart_module(call: ServiceCall):
        """Handle the service call."""
        rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
        mod_nmbr = call.data.get(RESTART_KEY_NMBR, RESTART_ALL)
        await smip.comm.module_restart(rtr_id, rtr_id + mod_nmbr)

    async def restart_router(call: ServiceCall):
        """Handle the service call."""
        rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
        await smip.comm.module_restart(rtr_id, 0)

    async def save_module_smc(call: ServiceCall):
        """Handle the service call."""
        rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
        mod_nmbr = call.data.get(FILE_MOD_NMBR, 1)
        await smip.comm.save_smc_file(rtr_id + mod_nmbr)
        return

    async def save_module_smg(call: ServiceCall):
        """Handle the service call."""
        rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
        mod_nmbr = call.data.get(FILE_MOD_NMBR, 1)
        await smip.comm.save_smg_file(rtr_id + mod_nmbr)
        return

    async def save_router_smr(call: ServiceCall):
        """Handle the service call."""
        rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
        await smip.comm.save_smr_file(rtr_id)
        return

    async def save_module_status(call: ServiceCall):
        """Handle the service call."""
        rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
        mod_nmbr = call.data.get(FILE_MOD_NMBR, 1)
        await smip.comm.save_module_status(rtr_id + mod_nmbr)
        return

    async def save_router_status(call: ServiceCall):
        """Handle the service call."""
        rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
        await smip.comm.save_router_status(rtr_id)
        return

    smip = SmartIP(hass, entry)
    try:
        await smip.initialize(hass, entry)
    except (asyncio.TimeoutError, TimeoutException) as ex:
        raise ConfigEntryNotReady("Timeout while connecting to SmartIP") from ex

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = smip

    # Register update handler for runtime configuration of Habitron integration
    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Register services
    hass.services.async_register(
        DOMAIN, "mod_restart", restart_module, schema=SERVICE_MOD_RESTART_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "rtr_restart", restart_router, schema=SERVICE_RTR_RESTART_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "save_module_smc", save_module_smc, schema=SERVICE_MOD_FILE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "save_module_smg", save_module_smg, schema=SERVICE_MOD_FILE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "save_router_smr", save_router_smr, schema=SERVICE_RTR_FILE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "save_module_status", save_module_status, schema=SERVICE_MOD_FILE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, "save_router_status", save_router_status, schema=SERVICE_RTR_FILE_SCHEMA
    )

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
    await hbtn_comm.set_host(entry.options["habitron_host"])
    hbtn_cord.set_update_interval(entry.options["update_interval"])


class ConfigEntryNotReady(exceptions.HomeAssistantError):
    """Error to indicate timeout or other error during setup."""
