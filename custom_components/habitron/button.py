"""Platform for button integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SMARTIP_COMMAND_STRINGS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add button for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router

    new_devices = []

    # Add router commands as buttons
    for coll_cmd in hbtn_rt.coll_commands:
        new_devices.append(CollCmdButton(coll_cmd, hbtn_rt))

    if new_devices:
        async_add_entities(new_devices)


# This entire class could be written to extend a base class to ensure common attributes
# are kept identical/in sync. It's broken apart here between the Cover and Sensors to
# be explicit about what is returned, and the comments outline where the overlap is.
class CollCmdButton(ButtonEntity):
    """Representation of a button to trigger a collective command."""

    def __init__(self, coll_cmd, module) -> None:
        """Initialize an HbtnShutter."""
        self._module = module
        self._name = coll_cmd.name
        self._nmbr = coll_cmd.nmbr
        self._attr_unique_id = "Cmd_" + str(coll_cmd.nmbr) + "_" + coll_cmd.name

        # This is the name for this *entity*, the "name" attribute from "device_info"
        # is used as the device name for device screens in the UI. This name is used on
        # entity screens, and used to build the Entity ID that's used is automations etc.
        self._attr_name = f"Cmd {self._nmbr} {self._name}"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.name)}}

    async def async_press(self) -> None:
        """Handle the button press."""
        cmd_str = SMARTIP_COMMAND_STRINGS["CALL_COLL_COMMAND"]
        cmd_str = cmd_str.replace("\xfd", chr(self._nmbr))
        resp = await self._module.comm.async_send_command(cmd_str)
        print(resp)
