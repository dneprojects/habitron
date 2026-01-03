"""The Habitron integration."""

# remoteHA Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJmMWI4NWUzZDg3ODg0MGNiOTIzNDE2OWE4ZDMxZDZhOCIsImlhdCI6MTc2MjA3OTMxMCwiZXhwIjoyMDc3NDM5MzEwfQ.NnEjgKTM_gbkBoRsf_pHVLzskY88SPR7gqlgReMWxKU

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry

from .communicate import TimeoutException
from .const import (
    DOMAIN,
    EVNT_ARG1,
    EVNT_ARG2,
    EVNT_TYPE,
    FILE_MOD_NMBR,
    HUB_UID,
    MOD_NMBR,
    RESTART_ALL,
    RESTART_KEY_NMBR,
    ROUTER_NMBR,
)
from .smart_hub import SmartHub
from .system_health import system_health_info  # noqa: F401
from .ws_provider import HabitronWebRTCProvider

PLATFORMS: list[str] = [
    "assist_satellite",
    "binary_sensor",
    "button",
    "camera",
    "climate",
    "cover",
    "event",
    "light",
    "media_player",
    "notify",
    "number",
    "select",
    "sensor",
    "switch",
    "text",
    "update",
]
SERVICE_HUB_RESTART_SCHEMA = vol.Schema(
    {
        vol.Required(ROUTER_NMBR, default=1): int,  # type: ignore  # noqa: PGH003
    }
)
SERVICE_HUB_REBOOT_SCHEMA = vol.Schema({})
SERVICE_MOD_RESTART_SCHEMA = vol.Schema(
    {
        vol.Required(ROUTER_NMBR, default=1): int,  # type: ignore  # noqa: PGH003
        vol.Optional(RESTART_KEY_NMBR, default=1): int,  # type: ignore  # noqa: PGH003
    }
)
SERVICE_MOD_FILE_SCHEMA = vol.Schema(
    {
        vol.Required(ROUTER_NMBR, default=1): int,  # type: ignore  # noqa: PGH003
        vol.Required(FILE_MOD_NMBR, default=1): int,  # type: ignore  # noqa: PGH003
    }
)
SERVICE_RTR_FILE_SCHEMA = vol.Schema(
    {
        vol.Required(ROUTER_NMBR, default=1): int,  # type: ignore  # noqa: PGH003
    }
)
SERVICE_RTR_RESTART_SCHEMA = vol.Schema(
    {
        vol.Required(ROUTER_NMBR, default=1): int,  # type: ignore  # noqa: PGH003
    }
)
SERVICE_UPDATE_ENTITY_SCHEMA = vol.Schema(
    {
        vol.Required(HUB_UID): str,
        vol.Required(ROUTER_NMBR, default=1): int,  # type: ignore  # noqa: PGH003
        vol.Required(MOD_NMBR): int,
        vol.Required(EVNT_TYPE): int,
        vol.Required(EVNT_ARG1): int,
        vol.Required(EVNT_ARG2): int,
    }
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Habitron from a config entry."""

    try:
        # 1. Create the main SmartHub instance.
        smhub = SmartHub(hass, entry)

        # 2. Run the setup which initializes router, etc.
        await smhub.async_setup()

        # 3. Create the provider, passing it the router from the SmartHub.
        provider = HabitronWebRTCProvider(hass, smhub.router)
        smhub.ws_provider = provider

        # 4. Store ONLY the smhub object. Other platforms will access .router and .ws_provider from it.
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = smhub

        # 5. Register websocket handlers from the provider instance.
        provider.async_register_websocket_handlers()

        entry.async_on_unload(entry.add_update_listener(update_listener))

        # --- Service Registration ---
        async def restart_hub(call: ServiceCall):
            """Handle the service call."""
            rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
            await smhub.comm.hub_restart(rtr_id)

        async def reboot_hub(_call: ServiceCall):
            """Handle the service call."""
            await smhub.comm.hub_reboot()

        async def restart_module(call: ServiceCall):
            """Handle the service call."""
            rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
            mod_nmbr = call.data.get(RESTART_KEY_NMBR, RESTART_ALL)
            await smhub.comm.module_restart(rtr_id, rtr_id + mod_nmbr)

        async def restart_router(call: ServiceCall):
            """Handle the service call."""
            rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
            await smhub.comm.module_restart(rtr_id, 0)

        async def save_module_smc(call: ServiceCall):
            """Handle the service call."""
            rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
            mod_nmbr = call.data.get(FILE_MOD_NMBR, 1)
            await smhub.comm.save_smc_file(rtr_id + mod_nmbr)

        async def save_module_smg(call: ServiceCall):
            """Handle the service call."""
            rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
            mod_nmbr = call.data.get(FILE_MOD_NMBR, 1)
            await smhub.comm.save_smg_file(rtr_id + mod_nmbr)

        async def save_router_smr(call: ServiceCall):
            """Handle the service call."""
            rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
            await smhub.comm.save_smr_file(rtr_id)

        async def save_module_status(call: ServiceCall):
            """Handle the service call."""
            rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
            mod_nmbr = call.data.get(FILE_MOD_NMBR, 1)
            await smhub.comm.save_module_status(rtr_id + mod_nmbr)

        async def save_router_status(call: ServiceCall):
            """Handle the service call."""
            rtr_id = call.data.get(ROUTER_NMBR, 1) * 100
            await smhub.comm.save_router_status(rtr_id)

        async def update_entity(call: ServiceCall):
            """Handle the update service call."""
            hub_id = call.data.get(HUB_UID)
            rtr_id = call.data.get(ROUTER_NMBR, 1)
            mod_id = call.data.get(MOD_NMBR)
            evnt = call.data.get(EVNT_TYPE)
            arg1 = call.data.get(EVNT_ARG1)
            arg2 = call.data.get(EVNT_ARG2)
            for hub in smhub.hass.data["habitron"]:
                if smhub.hass.data["habitron"][hub].host == hub_id:
                    await smhub.hass.data["habitron"][hub].comm.update_entity(
                        hub_id, rtr_id, mod_id, evnt, arg1, arg2
                    )
                    break

        hass.services.async_register(
            DOMAIN, "hub_restart", restart_hub, schema=SERVICE_HUB_RESTART_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, "hub_reboot", reboot_hub, schema=SERVICE_HUB_REBOOT_SCHEMA
        )
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
            DOMAIN,
            "save_module_status",
            save_module_status,
            schema=SERVICE_MOD_FILE_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            "save_router_status",
            save_router_status,
            schema=SERVICE_RTR_FILE_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            "update_entity",
            update_entity,
            schema=SERVICE_UPDATE_ENTITY_SCHEMA,
        )

        # This creates each HA object for each platform your device requires.
        # It's done by calling the `async_setup_entry` function in each platform module.
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        return True  # noqa: TRY300

    except (TimeoutError, TimeoutException) as ex:
        raise ConfigEntryNotReady("Timeout while connecting to SmartHub") from ex
    except ConnectionRefusedError as ex:
        raise ConfigEntryNotReady(f"Connection refused to SmartHub: {ex}") from ex
    except Exception as ex:
        raise ConfigEntryNotReady(f"Error connecting to SmartHub: {ex}") from ex


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    smhub: SmartHub = hass.data[DOMAIN][config_entry.entry_id]
    return not any(
        identifier
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN and identifier[1] == smhub.uid
    )


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
    smhub: SmartHub = hass.data[DOMAIN][entry.entry_id]
    await smhub.router.comm.set_host(entry.options["habitron_host"])
    smhub.router.coord.set_update_interval(
        entry.options["update_interval"], entry.options["updates_enabled"]
    )
    await smhub.router.comm.send_network_info(entry.options["websock_token"])
