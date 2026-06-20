"""Platform for button integration."""

import logging
from typing import TYPE_CHECKING

from habitron_client import HbtnCommand, Logic, Module, Router, SmartController

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._helpers import hbtn_device_info
from .coordinator import HabitronConfigEntry

if TYPE_CHECKING:
    from .smart_hub import SmartHub

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add button for passed config_entry in HA."""
    smhub = entry.runtime_data
    hbtn_rt = smhub.router

    new_devices: list[ButtonEntity] = []
    for hbt_module in hbtn_rt.modules:
        new_devices.extend(
            DirCmdButton(dir_cmd, hbt_module, smhub)
            for dir_cmd in hbt_module.dir_commands
        )
        new_devices.extend(
            VisCmdButton(vis_cmd, hbt_module, smhub)
            for vis_cmd in hbt_module.vis_commands
        )
        for mod_logic in hbt_module.logic:
            if mod_logic.type == 5:
                new_devices.append(CountUpButton(mod_logic, hbt_module, smhub))
                new_devices.append(CountDownButton(mod_logic, hbt_module, smhub))
        if (
            isinstance(hbt_module, SmartController)
            and hbt_module.mod_type == "Smart Controller Touch"
        ):
            new_devices.append(SpeechButton(hbt_module, smhub))
        new_devices.append(RestartButton(hbt_module, smhub))
    # Router-level commands as buttons
    new_devices.extend(
        CollCmdButton(coll_cmd, smhub) for coll_cmd in hbtn_rt.coll_commands
    )
    new_devices.append(RestartButton(hbtn_rt, smhub))
    new_devices.append(RestartFwdTableButton(hbtn_rt, smhub))
    new_devices.append(RestartAllButton(hbtn_rt, smhub))
    new_devices.append(RestartHubButton(smhub))
    new_devices.append(RebootHubButton(smhub))
    new_devices.extend(
        ResetChannelPowerButton(hbtn_rt, smhub, ch + 1) for ch in range(4)
    )

    if new_devices:
        async_add_entities(new_devices)


class CollCmdButton(ButtonEntity):
    """Button to trigger a collective (router) command."""

    _attr_has_entity_name = True

    def __init__(self, coll_cmd: HbtnCommand, smhub: SmartHub) -> None:
        """Initialize a collective-command button."""
        self._smhub = smhub
        self._nmbr = coll_cmd.nmbr
        self._attr_name = f"Cmd {self._nmbr}: {coll_cmd.name}"
        self._attr_unique_id = f"Mod_{smhub.uid}_ccmd{self._nmbr}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the router device."""
        return hbtn_device_info(self._smhub.router.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.comm.async_call_coll_command(self._nmbr)


class DirCmdButton(ButtonEntity):
    """Button to trigger a direct command on a module."""

    _attr_has_entity_name = True

    def __init__(self, dir_cmd: HbtnCommand, module: Module, smhub: SmartHub) -> None:
        """Initialize a direct-command button."""
        self._module = module
        self._smhub = smhub
        self._nmbr = dir_cmd.nmbr
        self._attr_name = f"DirectCmd {self._nmbr}: {dir_cmd.name}"
        self._attr_unique_id = f"Mod_{module.uid}_dcmd{self._nmbr}"
        self._attr_device_info = hbtn_device_info(module.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.comm.async_call_dir_command(self._module.addr, self._nmbr)


class VisCmdButton(ButtonEntity):
    """Button to trigger a visualization command on a module."""

    _attr_has_entity_name = True

    def __init__(self, vis_cmd: HbtnCommand, module: Module, smhub: SmartHub) -> None:
        """Initialize a visualization-command button."""
        self._module = module
        self._smhub = smhub
        self._nmbr = vis_cmd.nmbr
        no_hi = int(self._nmbr / 256)
        no_lo = self._nmbr - no_hi * 256
        self._attr_name = f"VisCmd {no_hi}/{no_lo}: {vis_cmd.name}"
        self._attr_unique_id = f"Mod_{module.uid}_vcmd{self._nmbr}"
        self._attr_device_info = hbtn_device_info(module.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.comm.async_call_vis_command(self._module.addr, self._nmbr)


class RestartButton(ButtonEntity):
    """Button to restart a single module or the router."""

    _attr_has_entity_name = True
    _attr_translation_key = "module_reset"
    _attr_name = "Reset"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, target: Module | Router, smhub: SmartHub) -> None:
        """Initialize a restart button for a module or the router."""
        self._target = target
        self._smhub = smhub
        self._attr_unique_id = f"Mod_{target.uid}_restart"
        self._attr_device_info = hbtn_device_info(target.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        if isinstance(self._target, Module):
            raddr = self._target.addr - self._smhub.router.id
            await self._smhub.comm.module_restart(raddr)
        else:
            await self._smhub.comm.module_restart(0)


class RestartFwdTableButton(ButtonEntity):
    """Button to restart the router forwarding table."""

    _attr_has_entity_name = True
    _attr_translation_key = "restart_fwd_table"
    _attr_name = "Restart Forward Table"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, router: Router, smhub: SmartHub) -> None:
        """Initialize the forward-table restart button."""
        self._smhub = smhub
        self._attr_unique_id = f"Mod_{router.uid}_restartfwdtable"
        self._attr_device_info = hbtn_device_info(router.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.comm.restart_fwd_tbl()


class RestartAllButton(ButtonEntity):
    """Button to restart all modules."""

    _attr_has_entity_name = True
    _attr_translation_key = "router_reset_all"
    _attr_name = "Reset all modules"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, router: Router, smhub: SmartHub) -> None:
        """Initialize the reset-all button."""
        self._smhub = smhub
        self._attr_unique_id = f"Rt_{router.uid}_restart_all"
        self._attr_device_info = hbtn_device_info(router.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.comm.module_restart(0xFF)


class RestartHubButton(ButtonEntity):
    """Button to restart the SmartHub."""

    _attr_has_entity_name = True
    _attr_translation_key = "hub_restart"
    _attr_name = "Restart Hub"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, smhub: SmartHub) -> None:
        """Initialize the hub-restart button."""
        self._smhub = smhub
        self._attr_unique_id = f"Hub_{smhub.uid}_restart"
        self._attr_device_info = hbtn_device_info(smhub.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.restart(self._smhub.router.id)


class RebootHubButton(ButtonEntity):
    """Button to reboot the SmartHub."""

    _attr_has_entity_name = True
    _attr_translation_key = "hub_reboot"
    _attr_name = "Reboot Hub"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, smhub: SmartHub) -> None:
        """Initialize the hub-reboot button."""
        self._smhub = smhub
        self._attr_unique_id = f"Hub_{smhub.uid}_reboot"
        self._attr_device_info = hbtn_device_info(smhub.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.reboot()


class CountUpButton(ButtonEntity):
    """Button to increment a counter."""

    _attr_has_entity_name = True
    _attr_translation_key = "count_up"

    def __init__(self, counter: Logic, module: Module, smhub: SmartHub) -> None:
        """Initialize a count-up button."""
        self._module = module
        self._smhub = smhub
        self._nmbr = counter.nmbr + 1
        self._attr_name = f"Count up {self._nmbr}: {counter.name}"
        self._attr_unique_id = f"Mod_{module.uid}_cntup{self._nmbr}"
        self._attr_device_info = hbtn_device_info(module.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.comm.async_inc_dec_counter(self._module.addr, self._nmbr, 1)


class CountDownButton(ButtonEntity):
    """Button to decrement a counter."""

    _attr_has_entity_name = True
    _attr_translation_key = "count_down"

    def __init__(self, counter: Logic, module: Module, smhub: SmartHub) -> None:
        """Initialize a count-down button."""
        self._module = module
        self._smhub = smhub
        self._nmbr = counter.nmbr + 1
        self._attr_name = f"Count down {self._nmbr}: {counter.name}"
        self._attr_unique_id = f"Mod_{module.uid}_cntdown{self._nmbr}"
        self._attr_device_info = hbtn_device_info(module.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.comm.async_inc_dec_counter(self._module.addr, self._nmbr, 2)


class ResetChannelPowerButton(ButtonEntity):
    """Button to power-cycle a router channel."""

    _attr_has_entity_name = True
    _attr_translation_key = "power_cycle"

    def __init__(self, router: Router, smhub: SmartHub, channel: int) -> None:
        """Initialize a power-cycle button."""
        self._smhub = smhub
        self._chan = channel
        self._attr_name = f"Power cycle router channel {self._chan}"
        self._attr_unique_id = f"Rt_{router.uid}_powcyc{self._chan}"
        self._attr_device_info = hbtn_device_info(router.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._smhub.comm.async_power_cycle_channel(self._chan)


class SpeechButton(ButtonEntity):
    """Button to trigger a voice-input request on a Smart Controller Touch."""

    _attr_has_entity_name = True
    _attr_translation_key = "voice_input"
    _attr_name = "Activate voice input"

    def __init__(self, module: SmartController, smhub: SmartHub) -> None:
        """Initialize a speech button."""
        self._module = module
        self._stream_name = module.stream_name
        self._provider = smhub.ws_provider
        self._attr_unique_id = f"Mod_{module.uid}_Activate voice input"
        self._attr_device_info = hbtn_device_info(module.uid)

    async def async_press(self) -> None:
        """Handle the button press by sending a WebSocket message to the client."""
        connections = self._provider.active_ws_connections if self._provider else {}
        ws_connection = connections.get(self._stream_name)
        if not ws_connection:
            _LOGGER.info(
                "Could not send voice activate request: no client for stream '%s'",
                self._stream_name,
            )
            return
        satellite = (
            self._provider.assist_satellites.get(self._stream_name)
            if self._provider
            else None
        )
        if satellite is not None and not satellite.recognition_disabled:
            ws_connection.send_message(
                {
                    "type": "habitron/voice_activate_request",
                    "payload": {"entity_id": satellite.entity_id},
                }
            )
        else:
            _LOGGER.info(
                "Voice recognition disabled for stream '%s'; not activating",
                self._stream_name,
            )
