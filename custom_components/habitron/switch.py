"""Platform for switch integration."""

from __future__ import annotations

from typing import Any

# Import the device class from the component that you want to support
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .communicate import HbtnComm as hbtn_com
from .const import DOMAIN, SMARTIP_COMMAND_STRINGS

# from homeassistant.helpers.entity import Entity


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add lights for passed config_entry in HA."""
    smip = hass.data[DOMAIN][config_entry.entry_id]
    router = smip.router

    new_devices = []
    for hbt_module in router.modules:
        for mod_input in hbt_module.inputs:
            if mod_input.nmbr >= 0:  # not disabled
                if mod_input.type == 1:  # switch
                    new_devices.append(InputSwitch(mod_input, hbt_module))
                if mod_input.type == 5:  # pulse switch
                    new_devices.append(InputPressShort(mod_input, hbt_module))
                    new_devices.append(InputPressLong(mod_input, hbt_module))

    if new_devices:
        async_add_entities(new_devices)


class InputSwitch(SwitchEntity):
    """Representation of habitron switch input entities."""

    def __init__(self, input, module) -> None:
        """Initialize an HbtnLight."""
        self._input = input
        self._module = module
        self._name = input.name
        self._nmbr = input.nmbr
        self._state = None
        self._attr_unique_id = f"{self._module._id}_{self._name}"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.mod_id)}}

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will reflect this.
    @property
    def available(self) -> bool:
        """Return True if module and smip is available."""
        return True

    @property
    def name(self) -> str:
        """Return the display name of this switch."""
        return self._name

    @property
    def is_on(self) -> bool | None:
        """Return true if light is on."""
        return self._state

    async def async_update(self) -> None:
        """Fetch new state data for this light."""
        self._state = self._module.inputs[self._nmbr].value == 1

    async def send_command(self, cmd_str):
        """Send command patches module and input numbers"""
        cmd_str = cmd_str.replace("\xff", chr(self._module.mod_addr))
        cmd_str = cmd_str.replace("\xfe", chr(self._nmbr + 1))
        await hbtn_com().send_command(cmd_str)


class InputPressShort(InputSwitch):
    """Representation of habitron light entities, dimmable."""

    def __init__(self, input, module) -> None:
        """Initialize a dimmable Habitron Light."""
        super().__init__(input, module)


class InputPressLong(InputSwitch):
    """Representation of habitron light entities, dimmable."""

    def __init__(self, input, module) -> None:
        """Initialize a dimmable Habitron Light."""
        super().__init__(input, module)
