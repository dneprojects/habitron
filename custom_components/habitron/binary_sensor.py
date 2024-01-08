"""Platform for switch integration."""

from __future__ import annotations

# Import the device class from the component that you want to support
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .interfaces import TYPE_DIAG

# from homeassistant.helpers.entity import Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add binary sensors for Habitron inputs."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for mod_input in hbt_module.inputs:
            if abs(mod_input.type) == 2:  # switch
                if hbt_module.comm.is_smhub:
                    new_devices.append(
                        InputSwitchPush(mod_input, hbt_module, hbtn_cord, len(new_devices))
                    )
                else:
                    new_devices.append(
                        InputSwitch(mod_input, hbt_module, hbtn_cord, len(new_devices))
                    )
        for mod_sensor in hbt_module.sensors:
            if mod_sensor.name == "Movement":
                if hbt_module.comm.is_smhub:
                    new_devices.append(
                        MotionSensorPush(mod_sensor, hbt_module, hbtn_cord, len(new_devices))
                    )
                else:
                    new_devices.append(
                        MotionSensor(mod_sensor, hbt_module, hbtn_cord, len(new_devices))
                    )
            elif mod_sensor.name == "Rain":
                new_devices.append(
                    RainSensor(mod_sensor, hbt_module, hbtn_cord, len(new_devices))
                )
    for rt_stat in hbtn_rt.states:
        new_devices.append(HbtnState(rt_stat, hbtn_rt, hbtn_cord, len(new_devices)))

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices
        async_add_entities(new_devices)


class InputSwitch(CoordinatorEntity, BinarySensorEntity):
    """Representation of habitron switch input entities."""

    _attr_has_entity_name = True

    def __init__(self, inpt, module, coord, idx) -> None:
        """Initialize an InputSwitch, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._input = inpt
        self._module = module
        self._attr_name = inpt.name
        self._nmbr = inpt.nmbr
        self._state = False
        self._attr_unique_id = f"{self._module.uid}_In{self._nmbr}"
        if inpt.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this switch."""
        return self._attr_name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.inputs[self._nmbr].value == 1
        if self._attr_is_on:
            self._attr_icon = "mdi:toggle-switch-variant"
        else:
            self._attr_icon = "mdi:toggle-switch-variant-off"
        self._state = self._attr_is_on
        self.async_write_ha_state()

class InputSwitchPush(InputSwitch):
    """Representation of habitron switch input entities for push update."""

    should_poll = True  # for push updates

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._input.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._input.remove_callback(self._handle_coordinator_update)


class HbtnState(CoordinatorEntity, BinarySensorEntity):
    """Representation of habitron state entities."""

    _attr_has_entity_name = True

    def __init__(self, state, module, coord, idx) -> None:
        """Initialize an Hbtnstate, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._state = state
        self._module = module
        self._nmbr = state.nmbr
        self._state = False
        self._attr_unique_id = f"{self._module.uid}_state_{state.nmbr}"
        self._attr_name = state.name
        if state.type == TYPE_DIAG:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = (
                False  # Entity will initally be disabled
            )

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        if isinstance(self._module.id, int):
            return {"identifiers": {(DOMAIN, self._module.uid)}}  # router
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def available(self) -> bool:
        """Return True if module and smhub is available."""
        return True

    @property
    def name(self) -> str:
        """Return the display name of this state."""
        return self._attr_name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.states[self._nmbr].value == 1
        if self._attr_is_on:
            self._attr_icon = "mdi:checkbox-marked-circle-outline"
        else:
            self._attr_icon = "mdi:alert-circle-outline"
        self._state = self._attr_is_on
        self.async_write_ha_state()


class MotionSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of habitron button switch input."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    should_poll = True  # for push updates

    def __init__(self, sensor, module, coord, idx) -> None:
        """Initialize motion sensor."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._sensor = sensor
        self._module = module
        self._nmbr = sensor.nmbr
        self._state = False
        self._attr_unique_id = f"{self._module.uid}_motion"
        self._attr_name = f"{self._module.name}: Motion"
        self._attr_icon = "mdi:motion-sensor"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        if isinstance(self._module.id, int):
            return {"identifiers": {(DOMAIN, self._module.uid)}}  # router
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def available(self) -> bool:
        """Return True if module and smhub is available."""
        return True

    @property
    def name(self) -> str:
        """Return the display name of this flag."""
        return self._attr_name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.sensors[self._nmbr].value > 0
        if self._attr_is_on:
            self._attr_icon = "mdi:motion-sensor"
        else:
            self._attr_icon = "mdi:motion-sensor-off"
        self._state = self._attr_is_on
        self.async_write_ha_state()


class MotionSensorPush(MotionSensor):
    """Representation of habitron button switch input for push update."""

    should_poll = True  # for push updates

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._sensor.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._sensor.remove_callback(self._handle_coordinator_update)


class RainSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of habitron button switch input."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(self, sensor, module, coord, idx) -> None:
        """Initialize rain sensor."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._sensor = sensor
        self._module = module
        self._nmbr = sensor.nmbr
        self._state = False
        self._attr_unique_id = f"{self._module.uid}_rain"
        self._attr_name = f"{self._module.name}: Rain"
        self._attr_icon = "mdi:weather-rainy"

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        if isinstance(self._module.id, int):
            return {"identifiers": {(DOMAIN, self._module.uid)}}  # router
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def available(self) -> bool:
        """Return True if module and smhub is available."""
        return True

    @property
    def name(self) -> str:
        """Return the display name of this flag."""
        return self._attr_name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.sensors[self._nmbr].value == 74
        if self._attr_is_on:
            self._attr_icon = "mdi:weather-rainy"
        else:
            self._attr_icon = "mdi:weather-partly-cloudy"
        self._state = self._attr_is_on
        self.async_write_ha_state()
