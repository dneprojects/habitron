"""Platform for number integration."""

from habitron_client import Dimmer, Module, SetValue

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from ._helpers import async_assign_entity_area, hbtn_device_info
from .coordinator import HabitronConfigEntry, HbtnCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add input_number for passed config_entry in HA."""
    smhub = entry.runtime_data
    hbtn_rt = smhub.router
    hbtn_cord = smhub.coordinator

    new_devices: list[NumberEntity] = []
    for hbt_module in hbtn_rt.modules:
        for set_val in hbt_module.setvalues:
            new_devices.append(
                HbtnSetTemperature(set_val, hbt_module, hbtn_cord, len(new_devices))
            )
        for analog_out in hbt_module.analog_outputs:
            if abs(analog_out.type) == 8:  # analogue output
                new_devices.append(
                    HbtnAnalogOutput(
                        analog_out, hbt_module, hbtn_cord, len(new_devices)
                    )
                )

    if new_devices:
        async_add_entities(new_devices)

    registry: er.EntityRegistry = er.async_get(hass)
    area_names = {area.nmbr: slugify(area.name) for area in hbtn_rt.areas}

    for hbt_module in hbtn_rt.modules:
        for analog_out in hbt_module.analog_outputs:
            if abs(analog_out.type) == 8:  # analogue output
                async_assign_entity_area(
                    registry,
                    domain="number",
                    unique_id=f"Mod_{hbt_module.uid}_out{analog_out.nmbr}",
                    area_index=analog_out.area,
                    area_member=hbt_module.area,
                    area_names=area_names,
                )


class HbtnSetTemperature(CoordinatorEntity[HbtnCoordinator], NumberEntity):
    """Representation of a settable temperature value."""

    _attr_has_entity_name = True
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_max_value = 27.5
    _attr_native_min_value = 12.5
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(
        self, setval: SetValue, module: Module, coord: HbtnCoordinator, idx: int
    ) -> None:
        """Initialize a Habitron set value, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._setval = setval
        self._module = module
        self._nmbr = setval.nmbr
        self._attr_name = setval.name
        self._attr_unique_id = f"Mod_{module.uid}_number{48 + setval.nmbr}"
        self._attr_native_value = setval.value

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def name(self) -> str | None:
        """Return the display name of this number."""
        return self._attr_name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._setval.value
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set the new value."""
        self._attr_native_value = value
        int_val = int(value) * 10
        await self.coordinator.comm.async_set_setpoint(
            self._module.addr, self._setval.nmbr + 1, int_val
        )
        await self.coordinator.async_request_refresh()


class HbtnAnalogOutput(CoordinatorEntity[HbtnCoordinator], NumberEntity):
    """Representation of an analogue output number."""

    _attr_has_entity_name = True
    _attr_device_class = NumberDeviceClass.VOLTAGE
    _attr_native_max_value = 100.0
    _attr_native_min_value = 0.0
    _attr_translation_key = "analog_output"
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self, output: Dimmer, module: Module, coord: HbtnCoordinator, idx: int
    ) -> None:
        """Initialize a Habitron analogue value, pass coordinator to base."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._output = output
        self._module = module
        self._attr_name = (
            output.name if output.name.strip() else f"Out {output.nmbr + 1}"
        )
        self._nmbr: int = output.nmbr
        self._attr_unique_id: str | None = f"Mod_{module.uid}_out{output.nmbr}"
        if output.type < 0:
            self._attr_entity_registry_enabled_default = False
        self._attr_device_info = hbtn_device_info(module.uid)

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def name(self) -> str | None:
        """Return the display name of this number."""
        return self._attr_name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._output.brightness
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set the new value."""
        self._attr_native_value = value
        int_val = int(value)
        self._output.brightness = int_val
        await self.coordinator.comm.async_set_analog_val(
            self._module.addr, self._output.nmbr + 1, int_val
        )
        await self.coordinator.async_request_refresh()
