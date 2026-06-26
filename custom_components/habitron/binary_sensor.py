"""Platform for switch integration."""

from habitron_client import BusMember, Flag, Module, Router, decode_module_faults

# Import the device class from the component that you want to support
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._helpers import hbtn_device_info
from .const import DOMAIN
from .coordinator import HabitronConfigEntry, HbtnCoordinator

PARALLEL_UPDATES = 1
TYPE_DIAG = 10  # diagnostic entity, hidden by default (was interfaces.TYPE_DIAG)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add binary sensors for Habitron inputs."""
    smhub = entry.runtime_data
    hbtn_rt = smhub.router
    hbtn_cord = smhub.coordinator

    new_devices: list[BinarySensorEntity] = []
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
            new_devices.append(ListeningStatusSensor(hbt_module))
        new_devices.append(
            ModuleHealthSensor(hbt_module, hbtn_cord, len(new_devices))
        )
    for rt_stat in hbtn_rt.states:
        new_devices.append(HbtnState(rt_stat, hbtn_rt, hbtn_cord, len(new_devices)))

    if new_devices:
        async_add_entities(new_devices)

    registry: er.EntityRegistry = er.async_get(hass)
    area_reg = ar.async_get(hass)
    area_ids = {
        area.nmbr: area_reg.async_get_or_create(area.name).id for area in hbtn_rt.areas
    }

    for hbt_module in hbtn_rt.modules:
        for mod_input in hbt_module.inputs:
            if (
                abs(mod_input.type) == 2
                and mod_input.area > 0
                and mod_input.area != hbt_module.area
                and mod_input.area in area_ids
            ):  # switch
                entity_entry = registry.async_get_entity_id(
                    "binary_sensor", DOMAIN, f"Mod_{hbt_module.uid}_in{mod_input.nmbr}"
                )
                if entity_entry:
                    registry.async_update_entity(
                        entity_entry, area_id=area_ids[mod_input.area]
                    )


class HbtnBinSensor(CoordinatorEntity[HbtnCoordinator], BinarySensorEntity):
    """Representation of habitron switch input entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        sens_or_inpt: BusMember,
        module: Module,
        coord: HbtnCoordinator,
        idx: int,
    ) -> None:
        """Initialize an InputSwitch, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._sens_or_inpt: BusMember = sens_or_inpt
        self._module: Module = module
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
        return hbtn_device_info(self._module.uid)

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
    _attr_translation_key = "input_switch"

    def __init__(
        self,
        inp: BusMember,
        module: Module,
        coord: HbtnCoordinator,
        idx: int,
    ) -> None:
        """Initialize an InputSwitch, pass coordinator to CoordinatorEntity."""
        super().__init__(inp, module, coord, idx)
        self._attr_unique_id: str = f"Mod_{self._module.uid}_in{self._nmbr}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._on_state = self._module.inputs[self._nmbr].value == 1
        self.async_write_ha_state()


class InputSwitchPush(InputSwitch):
    """Representation of habitron switch input entities for push update."""

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._sens_or_inpt.add_listener(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._sens_or_inpt.remove_listener(self._handle_coordinator_update)


class MotionSensor(HbtnBinSensor):
    """Representation of habitron button switch input."""

    _attr_device_class = BinarySensorDeviceClass.MOTION
    _attr_translation_key = "motion"

    def __init__(
        self,
        sensor: BusMember,
        module: Module,
        coord: HbtnCoordinator,
        idx: int,
    ) -> None:
        """Initialize motion sensor."""
        super().__init__(sensor, module, coord, idx)
        self._attr_unique_id = f"Mod_{self._module.uid}_motion"
        self._attr_name = "Motion"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._on_state = int(self._module.sensors[self._nmbr].value or 0) > 0
        self.async_write_ha_state()


class MotionSensorPush(MotionSensor):
    """Representation of habitron button switch input for push update."""

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._sens_or_inpt.add_listener(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._sens_or_inpt.remove_listener(self._handle_coordinator_update)


class RainSensor(HbtnBinSensor):
    """Representation of habitron button switch input."""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_translation_key = "rain"

    def __init__(
        self,
        sensor: BusMember,
        module: Module,
        coord: HbtnCoordinator,
        idx: int,
    ) -> None:
        """Initialize rain sensor."""
        super().__init__(sensor, module, coord, idx)
        self._attr_unique_id: str = f"Mod_{self._module.uid}_rain"
        self._attr_name: str = "Rain"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._on_state = self._module.sensors[self._nmbr].value == 74
        self.async_write_ha_state()


class HbtnState(CoordinatorEntity[HbtnCoordinator], BinarySensorEntity):
    """Representation of habitron state entities."""

    _attr_has_entity_name = True
    _attr_translation_key = "hub_state"

    def __init__(
        self,
        state: Flag,
        module: Module | Router,
        coord: HbtnCoordinator,
        idx: int,
    ) -> None:
        """Initialize an Hbtnstate, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._state: Flag = state
        self._module: Module | Router = module
        self._nmb: int = state.nmbr
        self._on_state: bool = False
        self._attr_unique_id: str = f"Mod_{self._module.uid}_state{state.nmbr}"
        self._attr_name: str = state.name
        if state.type == TYPE_DIAG:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = False  # initially be disabled
        if state.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def name(self) -> str:
        """Return the display name of this switch."""
        return self._attr_name

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._on_state

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._on_state = self._state.value == 1
        self.async_write_ha_state()


class ModuleHealthSensor(CoordinatorEntity[HbtnCoordinator], BinarySensorEntity):
    """Per-module operate-mode health, fed by SmartHub ``SYS_ERR`` events.

    Bound to ``module.health`` (a one-byte fault bitmask, 0 = healthy). The
    entity is a diagnostic ``problem`` sensor; the active fault codes/labels are
    exposed as attributes. The user-facing "needs attention" surface is the
    repairs issue raised alongside it (see ``health.py``).
    """

    _attr_has_entity_name = True
    _attr_translation_key = "module_health"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        module: Module,
        coord: HbtnCoordinator,
        idx: int,
    ) -> None:
        """Initialize the health sensor, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._module: Module = module
        self._health: BusMember = module.health
        self._attr_unique_id: str = f"Mod_{module.uid}_health"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def is_on(self) -> bool:
        """Return True while the module reports at least one fault."""
        return self._module.health.value != 0

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        """Expose the active fault codes and their labels."""
        faults = decode_module_faults(self._module.health.value)
        return {
            "fault_codes": [fault.code for fault in faults],
            "faults": [f"{fault.code}: {fault.label}" for fault in faults],
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to the health member's push updates."""
        await super().async_added_to_hass()
        self._health.add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe the health listener."""
        self._health.remove_listener(self.async_write_ha_state)
        await super().async_will_remove_from_hass()


class ListeningStatusSensor(BinarySensorEntity):
    """Representation of the speech satellite status."""

    _attr_has_entity_name = True
    _attr_name: str = "Listening Status"
    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_translation_key = "listening_status"

    def __init__(
        self,
        module: Module,
    ) -> None:
        """Initialize."""
        # Note: No 'super().__init__(...)' call to a coordinator
        self._module: Module = module
        self._attr_is_on: bool = False  # Default state is off
        self._attr_unique_id: str = f"Mod_{self._module.uid}_listening_status"
        self._stream_name = module.name.lower().replace(" ", "_")

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    # This method allows us to update the state from outside
    def set_listening_state(self, is_listening: bool) -> None:
        """Update the sensor's state from the WebSocket handler."""
        if self._attr_is_on != is_listening:
            self._attr_is_on = is_listening
            self.async_write_ha_state()
