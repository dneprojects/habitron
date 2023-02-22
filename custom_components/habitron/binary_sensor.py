"""Platform for switch integration."""

from __future__ import annotations

# Import the device class from the component that you want to support
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

# from homeassistant.helpers.entity import Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add binary sensors for Habitron flgs and inputs."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for mod_input in hbt_module.inputs:
            if abs(mod_input.type) == 2:  # switch
                new_devices.append(
                    InputSwitch(mod_input, hbt_module, hbtn_cord, len(new_devices))
                )
            if abs(mod_input.type) == 1:  # pulse switch
                new_devices.append(
                    InputButton(mod_input, hbt_module, hbtn_cord, len(new_devices))
                )
                # new_devices.append(InputPressShort(mod_input, hbt_module))
                # new_devices.append(InputPressLong(mod_input, hbt_module))
        for mod_flg in hbt_module.flags:
            new_devices.append(
                HbtnFlag(mod_flg, hbt_module, hbtn_cord, len(new_devices))
            )
        for mod_sensor in hbt_module.sensors:
            if mod_sensor.name == "Movement":
                new_devices.append(
                    MotionSensor(mod_sensor, hbt_module, hbtn_cord, len(new_devices))
                )
    for rt_flg in hbtn_rt.flags:
        new_devices.append(HbtnFlag(rt_flg, hbtn_rt, hbtn_cord, len(new_devices)))

    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead
    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices
        async_add_entities(new_devices)


class InputSwitch(CoordinatorEntity, BinarySensorEntity):
    """Representation of habitron switch input entities."""

    device_class = "plug"

    def __init__(self, inpt, module, coord, idx) -> None:
        """Initialize an InputSwitch, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._input = inpt
        self._module = module
        self._name = inpt.name
        self._nmbr = inpt.nmbr
        self._state = False
        self._attr_unique_id = f"{self._module.id}_In{self._nmbr}"
        if inpt.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.mod_id)}}

    @property
    def name(self) -> str:
        """Return the display name of this switch."""
        return self._name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.inputs[self._nmbr].value == 1
        self._state = self._attr_is_on
        self.async_write_ha_state()


class InputButton(InputSwitch):
    """Representation of habitron button switch input."""

    device_class = "running"


class HbtnFlag(CoordinatorEntity, BinarySensorEntity):
    """Representation of habitron flag entities."""

    def __init__(self, flag, module, coord, idx) -> None:
        """Initialize an HbtnFlag, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._flag = flag
        self._module = module
        self._name = flag.name
        self._idx = flag.idx
        self._nmbr = flag.nmbr
        self._state = False
        self._attr_unique_id = f"{self._module.id}_flag_{flag.nmbr}"
        self._attr_name = f"{self._module.name}: Flag {flag.nmbr} {flag.name}"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        if isinstance(self._module.id, int):
            return {"identifiers": {(DOMAIN, self._module.name)}}  # router
        return {"identifiers": {(DOMAIN, self._module.mod_id)}}

    @property
    def available(self) -> bool:
        """Return True if module and smip is available."""
        return True

    @property
    def name(self) -> str:
        """Return the display name of this flag."""
        return self._name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.flags[self._idx].value == 1
        self._state = self._attr_is_on
        self.async_write_ha_state()


class MotionSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of habitron button switch input."""

    def __init__(self, sensor, module, coord, idx) -> None:
        super().__init__(coord, context=idx)
        self.idx = idx
        self._sensor = sensor
        self._module = module
        self._name = f"{self._module.name}: Motion"
        self._nmbr = sensor.nmbr
        self._state = False
        self._attr_unique_id = f"{self._module.id}_motion"
        self._attr_name = f"{self._module.name}: Motion"
        self._attr_icon = "mdi:motion-sensor"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        if isinstance(self._module.id, int):
            return {"identifiers": {(DOMAIN, self._module.name)}}  # router
        return {"identifiers": {(DOMAIN, self._module.mod_id)}}

    @property
    def available(self) -> bool:
        """Return True if module and smip is available."""
        return True

    @property
    def name(self) -> str:
        """Return the display name of this flag."""
        return self._name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.sensors[self._nmbr].value > 0
        self._state = self._attr_is_on
        self.async_write_ha_state()
