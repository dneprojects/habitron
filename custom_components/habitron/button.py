"""Platform for button integration."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import _LOGGER
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._helpers import hbtn_device_info
from .coordinator import HabitronConfigEntry
from .interfaces import CmdDescriptor, LgcDescriptor
from .module import HbtnModule, SmartController
from .router import HbtnRouter

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add button for passed config_entry in HA."""
    hbtn_rt: HbtnRouter = entry.runtime_data.router

    new_devices: list[ButtonEntity] = []

    for hbt_module in hbtn_rt.modules:
        new_devices.extend(
            DirCmdButton(dir_cmd, hbt_module) for dir_cmd in hbt_module.dir_commands
        )
        new_devices.extend(
            VisCmdButton(vis_cmd, hbt_module) for vis_cmd in hbt_module.vis_commands
        )
        for mod_logic in hbt_module.logic:
            if mod_logic.type == 5:
                new_devices.append(CountUpButton(mod_logic, hbt_module))
                new_devices.append(CountDownButton(mod_logic, hbt_module))
        if (
            isinstance(hbt_module, SmartController)
            and hbt_module.mod_type == "Smart Controller Touch"
        ):
            new_devices.append(SpeechButton(hbt_module))
        new_devices.append(RestartButton(hbt_module))
    # Add router commands as buttons
    new_devices.extend(
        CollCmdButton(coll_cmd, hbtn_rt) for coll_cmd in hbtn_rt.coll_commands
    )
    new_devices.append(RestartButton(hbtn_rt))
    new_devices.append(RestartFwdTableButton(hbtn_rt))
    new_devices.append(RestartAllButton(hbtn_rt))
    new_devices.append(RestartHubButton(hbtn_rt))
    new_devices.append(RebootHubButton(hbtn_rt))
    new_devices.extend([ResetChannelPowerButton(hbtn_rt, ch + 1) for ch in range(4)])

    if new_devices:
        async_add_entities(new_devices)


# This entire class could be written to extend a base class to ensure common attributes
# are kept identical/in sync. It's broken apart here between the Cover and Sensors to
# be explicit about what is returned, and the comments outline where the overlap is.
class CollCmdButton(ButtonEntity):
    """Representation of a button to trigger a collective command."""

    _attr_has_entity_name = True

    def __init__(self, coll_cmd: CmdDescriptor, module: HbtnRouter) -> None:
        """Initialize an CollCommand."""
        self._module = module
        self._nmbr = coll_cmd.nmbr
        self._attr_name = f"Cmd {self._nmbr}: {coll_cmd.name}"
        self._attr_unique_id = f"Mod_{module.b_uid}_ccmd{self._nmbr}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def name(self) -> str | None:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_call_coll_command(self._nmbr)


class DirCmdButton(ButtonEntity):
    """Representation of a button to trigger a visualization command."""

    _attr_has_entity_name = True

    def __init__(self, dir_cmd: CmdDescriptor, module: HbtnModule) -> None:
        """Initialize an DirectCommand."""
        self._module = module
        self._nmbr = dir_cmd.nmbr
        self._attr_name = f"DirectCmd {self._nmbr}: {dir_cmd.name}"
        self._attr_unique_id = f"Mod_{self._module.uid}_dcmd{self._nmbr}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def name(self) -> str | None:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_call_dir_command(
            self._module.mod_addr, self._nmbr
        )


class VisCmdButton(ButtonEntity):
    """Representation of a button to trigger a visualization command."""

    _attr_has_entity_name = True

    def __init__(self, vis_cmd: CmdDescriptor, module: HbtnModule) -> None:
        """Initialize an VisCommand."""
        self._module = module
        self._nmbr = vis_cmd.nmbr
        no_hi = int(self._nmbr / 256)
        no_lo = self._nmbr - no_hi * 256
        self._attr_name = f"VisCmd {no_hi}/{no_lo}: {vis_cmd.name}"
        self._attr_unique_id = f"Mod_{self._module.uid}_vcmd{self._nmbr}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def name(self) -> str | None:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_call_vis_command(
            self._module.mod_addr, self._nmbr
        )


class RestartButton(ButtonEntity):
    """Representation of a button to trigger a router restart command."""

    _attr_has_entity_name = True
    _attr_translation_key = "module_reset"

    def __init__(self, module: HbtnModule | HbtnRouter) -> None:
        """Initialize an restart button."""
        self._name = "restart"
        self._module = module
        self._attr_unique_id = f"Mod_{self._module.uid}_{self._name}"
        self._attr_name = "Reset"
        self._attr_entity_category = EntityCategory.CONFIG

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.async_reset()


class RestartFwdTableButton(ButtonEntity):
    """Representation of a button to trigger a router forward table restart command."""

    _attr_has_entity_name = True
    _attr_translation_key = "restart_fwd_table"

    def __init__(self, module: HbtnRouter) -> None:
        """Initialize an restart button."""
        self._name = "restartfwdtable"
        self._module = module
        self._attr_unique_id = f"Mod_{self._module.uid}_{self._name}"
        self._attr_name = "Restart Forward Table"
        self._attr_entity_category = EntityCategory.CONFIG

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.async_restart_fwd_tbl()


class RestartAllButton(ButtonEntity):
    """Representation of a button to trigger a all modules restart command."""

    _attr_has_entity_name = True
    _attr_translation_key = "router_reset_all"

    def __init__(self, router: HbtnRouter) -> None:
        """Initialize restart all button."""
        self._name = "restart_all"
        self._router = router
        self._attr_unique_id = f"Rt_{self._router.uid}_{self._name}"
        self._attr_name = "Reset all modules"
        self._attr_entity_category = EntityCategory.CONFIG

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the router
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._router.uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._router.async_reset_all_modules()


class RestartHubButton(ButtonEntity):
    """Representation of a button to trigger a hub restart."""

    _attr_has_entity_name = True
    _attr_translation_key = "hub_restart"

    def __init__(self, router: HbtnRouter) -> None:
        """Initialize an hub restart button."""
        self._name = "restart"
        self._router = router
        self._attr_unique_id = f"Hub_{self._router.b_uid}_{self._name}"
        self._attr_name = "Restart Hub"
        self._attr_entity_category = EntityCategory.CONFIG

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._router.b_uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._router.smhub.restart(self._router.id)


class RebootHubButton(ButtonEntity):
    """Representation of a button to trigger a hub reboot."""

    _attr_has_entity_name = True
    _attr_translation_key = "hub_reboot"

    def __init__(self, router: HbtnRouter) -> None:
        """Initialize an hub reboot button."""
        self._name = "reboot"
        self._router = router
        self._attr_unique_id = f"Hub_{self._router.b_uid}_{self._name}"
        self._attr_name = "Reboot Hub"
        self._attr_entity_category = EntityCategory.CONFIG

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._router.b_uid)

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._router.smhub.reboot()


class CountUpButton(ButtonEntity):
    """Representation of a button to trigger a counter increment command."""

    _attr_has_entity_name = True
    _attr_translation_key = "count_up"

    def __init__(self, counter: LgcDescriptor, module: HbtnModule) -> None:
        """Initialize an Count button."""
        self._module = module
        self._nmbr = counter.nmbr + 1
        self._attr_name = f"Count up {self._nmbr}: {counter.name}"
        self._attr_unique_id = f"Mod_{module.uid}_cntup{self._nmbr}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def name(self) -> str | None:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_inc_dec_counter(
            self._module.mod_addr, self._nmbr, 1
        )


class CountDownButton(ButtonEntity):
    """Representation of a button to trigger a counter increment command."""

    _attr_has_entity_name = True
    _attr_translation_key = "count_down"

    def __init__(self, counter: LgcDescriptor, module: HbtnModule) -> None:
        """Initialize an Count button."""
        self._module = module
        self._nmbr = counter.nmbr + 1
        self._attr_name = f"Count down {self._nmbr}: {counter.name}"
        self._attr_unique_id = f"Mod_{module.uid}_cntdown{self._nmbr}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def name(self) -> str | None:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_inc_dec_counter(
            self._module.mod_addr, self._nmbr, 2
        )


class ResetChannelPowerButton(ButtonEntity):
    """Representation of a button to trigger a power cycle on a router channel."""

    _attr_has_entity_name = True
    _attr_translation_key = "power_cycle"

    def __init__(self, router: HbtnRouter, channel: int) -> None:
        """Initialize an Power Cycle button."""
        self._router = router
        self._chan = channel
        self._attr_name = f"Power cycle router channel {self._chan}"
        self._attr_unique_id = f"Rt_{router.uid}_powcyc{self._chan}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._router.uid)

    @property
    def name(self) -> str | None:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._router.comm.async_power_cycle_channel(self._chan)


class SpeechButton(ButtonEntity):
    """Representation of a button to trigger a speech command."""

    _attr_has_entity_name = True
    _attr_translation_key = "voice_input"

    def __init__(self, module: SmartController) -> None:
        """Initialize a speech button.

        Only ``SmartController`` (Touch) modules expose
        ``assist_entity_id`` / ``stream_name``, which is why the type
        narrows here.
        """
        self._name = "Activate voice input"
        self._module = module
        self._stream_name = module.stream_name
        self._provider = module.comm.router.smhub.ws_provider
        self._active_ws_connections = (
            self._provider.active_ws_connections if self._provider else {}
        )
        self._attr_unique_id = f"Mod_{self._module.uid}_{self._name}"
        self._attr_name = "Activate voice input"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    async def async_press(self) -> None:
        """Handle the button press by sending a WebSocket message to the client."""

        ws_connection = self._active_ws_connections.get(self._stream_name)

        if ws_connection:
            satellite = (
                self._provider.assist_satellites.get(self._stream_name)
                if self._provider
                else None
            )
            if satellite is not None and not satellite.recognition_disabled:
                ws_connection.send_message(
                    {
                        "type": "habitron/voice_activate_request",
                        "payload": {"entity_id": self._module.assist_entity_id},
                    }
                )
            else:
                _LOGGER.info(
                    "Voice recognition is currently disabled for stream '%s'; not sending activate request",
                    self._stream_name,
                )
        else:
            _LOGGER.info(
                "Could not send voice activate request: No active client for stream '%s'",
                self._stream_name,
            )
