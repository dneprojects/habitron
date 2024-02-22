"""Platform for button integration."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGIC_INP_OFFS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add button for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []

    for hbt_module in hbtn_rt.modules:
        # for dir_cmd in hbt_module.dir_commands:
        #     new_devices.append(DirCmdButton(dir_cmd, hbt_module))
        for vis_cmd in hbt_module.vis_commands:
            new_devices.append(VisCmdButton(vis_cmd, hbt_module))
        for mod_logic in hbt_module.logic:
            if mod_logic.type == 5:
                new_devices.append(
                    CountUpButton(mod_logic, hbt_module)
                )
                new_devices.append(
                    CountDownButton(mod_logic, hbt_module))
        new_devices.append(RestartButton(hbt_module))
    # Add router commands as buttons
    for coll_cmd in hbtn_rt.coll_commands:
        new_devices.append(CollCmdButton(coll_cmd, hbtn_rt))
    new_devices.append(RestartButton(hbtn_rt))
    new_devices.append(RestartAllButton(hbtn_rt))
    new_devices.append(RestartHubButton(hbtn_rt))
    new_devices.append(RebootHubButton(hbtn_rt))

    if new_devices:
        async_add_entities(new_devices)


# This entire class could be written to extend a base class to ensure common attributes
# are kept identical/in sync. It's broken apart here between the Cover and Sensors to
# be explicit about what is returned, and the comments outline where the overlap is.
class CollCmdButton(ButtonEntity):
    """Representation of a button to trigger a collective command."""

    _attr_has_entity_name = True

    def __init__(self, coll_cmd, module) -> None:
        """Initialize an CollCommand."""
        self._module = module
        self._nmbr = coll_cmd.nmbr
        self._attr_name = f"Cmd {self._nmbr}: {coll_cmd.name}"
        self._attr_unique_id = f"{module.b_uid}_CCmd_{self._nmbr}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_call_coll_command(
            self._module.id, self._nmbr
        )


class DirCmdButton(ButtonEntity):
    """Representation of a button to trigger a visualization command."""

    _attr_has_entity_name = True

    def __init__(self, dir_cmd, module) -> None:
        """Initialize an VisCommand."""
        self._module = module
        self._nmbr = dir_cmd.nmbr
        self._attr_name = f"DirectCmd {self._nmbr}: {dir_cmd.name}"
        self._attr_unique_id = (
            f"Mod_{self._module.uid}_DCmd_{self._nmbr}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_call_vis_command(
            self._module.mod_addr, self._nmbr
        )


class VisCmdButton(ButtonEntity):
    """Representation of a button to trigger a visualization command."""

    _attr_has_entity_name = True

    def __init__(self, vis_cmd, module) -> None:
        """Initialize an VisCommand."""
        self._module = module
        self._nmbr = vis_cmd.nmbr
        no_hi = int(self._nmbr / 256)
        no_lo = self._nmbr - no_hi * 256
        self._attr_name = f"VisCmd {no_hi}/{no_lo}: {vis_cmd.name}"
        self._attr_unique_id = (
            f"Mod_{self._module.uid}_VCmd_{self._nmbr}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
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

    def __init__(self, module) -> None:
        """Initialize an restart button."""
        self._name = "restart"
        self._module = module
        self._attr_unique_id = f"Mod_{self._module.uid}_{self._name}"
        self._attr_name = "Reset"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:restart"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.async_reset()


class RestartAllButton(ButtonEntity):
    """Representation of a button to trigger a all modules restart command."""

    _attr_has_entity_name = True

    def __init__(self, router) -> None:
        """Initialize restart all button."""
        self._name = "restart_all"
        self._router = router
        self._attr_unique_id = f"Mod_{self._router.uid}_{self._name}"
        self._attr_name = "Reset all modules"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:restart"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the router
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._router.uid)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._router.async_reset_all_modules()

class RestartHubButton(ButtonEntity):
    """Representation of a button to trigger a hub restart."""

    _attr_has_entity_name = True

    def __init__(self, router) -> None:
        """Initialize an hub restart button."""
        self._name = "restart"
        self._router = router
        self._attr_unique_id = f"Hub_{self._router.b_uid}_{self._name}"
        self._attr_name = "Restart Hub"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:restart"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._router.b_uid)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._router.smhub.restart(self._router.id)


class RebootHubButton(ButtonEntity):
    """Representation of a button to trigger a hub reboot."""

    _attr_has_entity_name = True

    def __init__(self, router) -> None:
        """Initialize an hub reboot button."""
        self._name = "reboot"
        self._router = router
        self._attr_unique_id = f"Hub_{self._router.b_uid}_{self._name}"
        self._attr_name = "Reboot Hub"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:restart-alert"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._router.b_uid)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._router.smhub.reboot()


class CountUpButton(ButtonEntity):
    """Representation of a button to trigger a counter increment command."""

    _attr_has_entity_name = True

    def __init__(self, counter, module) -> None:
        """Initialize an Count button."""
        self._module = module
        self._nmbr = counter.nmbr + 1
        self._attr_name = f"Count up {self._nmbr}: {counter.name}"
        self._attr_unique_id = f"{module.uid}_Cntup_{self._nmbr}"
        self._attr_icon = "mdi:chevron-up-box-outline"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_inc_dec_counter(
            self._module.mod_addr, self._nmbr, 1)

class CountDownButton(ButtonEntity):
    """Representation of a button to trigger a counter increment command."""

    _attr_has_entity_name = True

    def __init__(self, counter, module) -> None:
        """Initialize an Count button."""
        self._module = module
        self._nmbr = counter.nmbr + 1
        self._attr_name = f"Count down {self._nmbr}: {counter.name}"
        self._attr_unique_id = f"{module.uid}_Cntdown_{self._nmbr}"
        self._attr_icon = "mdi:chevron-down-box-outline"


    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this button."""
        return self._attr_name

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_inc_dec_counter(
            self._module.mod_addr, self._nmbr, 2)
