"""Platform for switch integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

# Import the device class from the component that you want to support
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .interfaces import TYPE_DIAG, AreaDescriptor, IfDescriptor, StateDescriptor

if TYPE_CHECKING:
    from .module import HbtnModule
    from .router import HbtnRouter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add binary sensors for Habitron inputs."""
    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for mod_input in hbt_module.inputs:
            if abs(mod_input.type) == 2:  # switch
                new_devices.append(
                    InputSwitchPush(mod_input, hbt_module, hbtn_cord, len(new_devices))
                )
        for mod_sensor in hbt_module.sensors:
            if mod_sensor.name == "Movement":
                new_devices.append(
                    MotionSensorPush(
                        mod_sensor, hbt_module, hbtn_cord, len(new_devices)
                    )
                )
            elif mod_sensor.name == "Rain":
                new_devices.append(
                    RainSensor(mod_sensor, hbt_module, hbtn_cord, len(new_devices))
                )
        if hbt_module.mod_type == "Smart Controller Touch":
            listening_sensor = ListeningStatusSensor(hbt_module)
            hbt_module.vce_stat = listening_sensor
            new_devices.append(listening_sensor)
    for rt_stat in hbtn_rt.states:
        new_devices.append(HbtnState(rt_stat, hbtn_rt, hbtn_cord, len(new_devices)))

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices  # type: ignore  # noqa: PGH003
        async_add_entities(new_devices)

    registry: er.EntityRegistry = er.async_get(hass)
    area_names: dict[int, AreaDescriptor] = hbtn_rt.areas

    for hbt_module in hbtn_rt.modules:
        for mod_input in hbt_module.inputs:
            if (
                abs(mod_input.type) == 2
                and mod_input.area > 0
                and mod_input.area != hbt_module.area_member
            ):  # switch
                entity_entry = registry.async_get_entity_id(
                    "binary_sensor", DOMAIN, f"Mod_{hbt_module.uid}_in{mod_input.nmbr}"
                )
                if entity_entry:
                    registry.async_update_entity(
                        entity_entry, area_id=area_names[mod_input.area].get_name_id()
                    )


class HbtnBinSensor(CoordinatorEntity, BinarySensorEntity):
    """Representation of habitron switch input entities."""

    _attr_has_entity_name = True
    _attr_should_poll = True

    def __init__(
        self,
        sens_or_inpt: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize an InputSwitch, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._sens_or_inpt: IfDescriptor = sens_or_inpt
        self._module: HbtnModule = module
        self._attr_name: str = sens_or_inpt.name
        self._nmbr: int = sens_or_inpt.nmbr
        self._on_state: bool = False
        if sens_or_inpt.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this switch."""
        return self._attr_name

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._on_state


class InputSwitch(HbtnBinSensor):
    """Representation of habitron switch input entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        inpt: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize an InputSwitch, pass coordinator to CoordinatorEntity."""
        super().__init__(inpt, module, coord, idx)
        self._attr_unique_id: str = f"Mod_{self._module.uid}_in{self._nmbr}"

    @property
    def icon(self) -> str:
        """Icon of the led, based on number and state."""
        if self.is_on:
            return "mdi:toggle-switch-variant"
        return "mdi:toggle-switch-variant-off"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._on_state = self._module.inputs[self._nmbr].value == 1
        self.async_write_ha_state()


class InputSwitchPush(InputSwitch):
    """Representation of habitron switch input entities for push update."""

    _attr_should_poll = True  # for push updates, poll anyway

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._sens_or_inpt.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._sens_or_inpt.remove_callback(self._handle_coordinator_update)


class MotionSensor(HbtnBinSensor):
    """Representation of habitron button switch input."""

    _attr_device_class = BinarySensorDeviceClass.MOTION

    def __init__(
        self,
        sensor: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize motion sensor."""
        super().__init__(sensor, module, coord, idx)
        self._attr_unique_id = f"Mod_{self._module.uid}_motion"
        self._attr_name = "Motion"

    @property
    def icon(self) -> str:
        """Icon of the led, based on number and state."""
        if self.is_on:
            return "mdi:motion-sensor"
        return "mdi:motion-sensor-off"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._on_state = self._module.sensors[self._nmbr].value > 0
        self.async_write_ha_state()


class MotionSensorPush(MotionSensor):
    """Representation of habitron button switch input for push update."""

    _attr_should_poll = False  # for push updates

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._sens_or_inpt.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._sens_or_inpt.remove_callback(self._handle_coordinator_update)


class RainSensor(HbtnBinSensor):
    """Representation of habitron button switch input."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE

    def __init__(
        self,
        sensor: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize rain sensor."""
        super().__init__(sensor, module, coord, idx)
        self._attr_unique_id: str = f"Mod_{self._module.uid}_rain"
        self._attr_name: str = "Rain"
        self._attr_icon: str = "mdi:weather-rainy"

    @property
    def icon(self) -> str:
        """Icon of the led, based on number and state."""
        if self.is_on:
            return "mdi:weather-rainy"
        return "mdi:weather-partly-cloudy"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._on_state = self._module.sensors[self._nmbr].value == 74
        self.async_write_ha_state()


class HbtnState(CoordinatorEntity, BinarySensorEntity):
    """Representation of habitron state entities."""

    _attr_has_entity_name = True
    _attr_should_poll = True

    def __init__(
        self,
        state: StateDescriptor,
        module: HbtnModule | HbtnRouter,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize an Hbtnstate, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._state: StateDescriptor = state
        self._module: HbtnModule | HbtnRouter = module
        self._nmb: int = state.nmbr
        self._on_state: bool = False
        self._attr_unique_id: str = f"Mod_{self._module.uid}_state{state.nmbr}"
        self._attr_name: str = state.name
        if state.type == TYPE_DIAG:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False  # initally be disabled
        if state.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        if isinstance(self._module.id, int):
            return {"identifiers": {(DOMAIN, self._module.uid)}}  # router
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this switch."""
        return self._attr_name

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._on_state

    @property
    def icon(self) -> str:
        """Icon of the led, based on number and state."""
        if self.is_on:
            return "mdi:checkbox-marked-circle-outline"
        return "mdi:alert-circle-outline"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._on_state = self._state.value == 1
        self.async_write_ha_state()


class ListeningStatusSensor(BinarySensorEntity):
    """Representation of the speech satellite status."""

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_name: str = "Listening Status"
    _attr_device_class = BinarySensorDeviceClass.SOUND

    def __init__(
        self,
        module: HbtnModule,
    ) -> None:
        """Initialize."""
        # Note: No 'super().__init__(...)' call to a coordinator
        self._module: HbtnModule = module
        self._attr_is_on: bool = False  # Default state is off
        self._attr_unique_id: str = f"Mod_{self._module.uid}_listening_status"
        self._stream_name = module.name.lower().replace(" ", "_")

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def icon(self) -> str:
        """Icon of the sensor, based on state."""
        return "mdi:microphone-message" if self.is_on else "mdi:microphone-message-off"

    # This method allows us to update the state from outside
    def set_listening_state(self, is_listening: bool) -> None:
        """Update the sensor's state from the WebSocket handler."""
        if self._attr_is_on != is_listening:
            self._attr_is_on = is_listening
            self.async_write_ha_state()
