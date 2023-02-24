"""Platform for button integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add button for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router

    new_devices = []

    for hbt_module in hbtn_rt.modules:
        for dir_cmd in hbt_module.dir_commands:
            new_devices.append(DirCmdButton(dir_cmd, hbt_module))
        for vis_cmd in hbt_module.vis_commands:
            new_devices.append(VisCmdButton(vis_cmd, hbt_module))
        new_devices.append(RestartButton(hbt_module))
    # Add router commands as buttons
    for coll_cmd in hbtn_rt.coll_commands:
        new_devices.append(CollCmdButton(coll_cmd, hbtn_rt))
    new_devices.append(RestartButton(hbtn_rt))
    new_devices.append(RestartAllButton(hbtn_rt))

    if new_devices:
        async_add_entities(new_devices)


# This entire class could be written to extend a base class to ensure common attributes
# are kept identical/in sync. It's broken apart here between the Cover and Sensors to
# be explicit about what is returned, and the comments outline where the overlap is.
class CollCmdButton(ButtonEntity):
    """Representation of a button to trigger a collective command."""

    def __init__(self, coll_cmd, module) -> None:
        """Initialize an CollCommand."""
        self._module = module
        self._name = coll_cmd.name
        self._nmbr = coll_cmd.nmbr
        self._attr_unique_id = "Cmd_" + str(coll_cmd.nmbr) + "_" + coll_cmd.name

        # This is the name for this *entity*, the "name" attribute from "device_info"
        # is used as the device name for device screens in the UI. This name is used on
        # entity screens, and used to build the Entity ID that's used is automations etc.
        self._attr_name = f"Cmd {self._nmbr}: {self._name}"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_call_coll_command(
            self._module.mod_addr, self._nmbr
        )


class DirCmdButton(ButtonEntity):
    """Representation of a button to trigger a visualization command."""

    def __init__(self, dir_cmd, module) -> None:
        """Initialize an VisCommand."""
        self._module = module
        self._name = dir_cmd.name
        self._nmbr = dir_cmd.nmbr
        self._attr_unique_id = (
            f"Mod_{self._module.mod_addr}_DCmd{self._nmbr}_{self._name}"
        )

        # This is the name for this *entity*, the "name" attribute from "device_info"
        # is used as the device name for device screens in the UI. This name is used on
        # entity screens, and used to build the Entity ID that's used is automations etc.
        self._attr_name = f"{self._module.name} DirectCmd {self._nmbr}: {self._name}"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_call_vis_command(
            self._module.mod_addr, self._nmbr
        )


class VisCmdButton(ButtonEntity):
    """Representation of a button to trigger a visualization command."""

    def __init__(self, vis_cmd, module) -> None:
        """Initialize an VisCommand."""
        self._module = module
        self._name = vis_cmd.name
        self._nmbr = vis_cmd.nmbr
        self._attr_unique_id = (
            f"Mod_{self._module.mod_addr}_VCmd{self._nmbr}_{self._name}"
        )

        self._attr_name = f"{self._module.name} VisCmd {self._nmbr-256}: {self._name}"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._module.comm.async_call_vis_command(
            self._module.mod_addr, self._nmbr
        )


class RestartButton(ButtonEntity):
    """Representation of a button to trigger a visualization command."""

    def __init__(self, module) -> None:
        """Initialize an VisCommand."""
        self._name = "restart"
        self._module = module
        self._attr_unique_id = f"Mod_{self._module.uid}_{self._name}"
        self._attr_name = f"{module.name}: Reset"
        self._attr_entity_category = EntityCategory.CONFIG

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
    """Representation of a button to trigger a visualization command."""

    def __init__(self, router) -> None:
        """Initialize an VisCommand."""
        self._name = "restart_all"
        self._router = router
        self._attr_unique_id = f"Mod_{self._router.uid}_{self._name}"
        self._attr_name = f"{router.name}: Reset all modules"
        self._attr_entity_category = EntityCategory.CONFIG

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the router
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._router.uid)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        await self._router.async_reset_all_modules()
