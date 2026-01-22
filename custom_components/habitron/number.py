"""Platform for number integration."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.components.number.const import NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .interfaces import AreaDescriptor, IfDescriptor
from .module import HbtnModule
from .router import HbtnRouter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add input_number for passed config_entry in HA."""
    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for set_val in hbt_module.setvalues:
            new_devices.append(
                HbtnSetTemperature(set_val, hbt_module, hbtn_cord, len(new_devices))
            )
        for mod_output in hbt_module.outputs:
            if abs(mod_output.type) == 8:  # analog
                new_devices.append(
                    HbtnAnalogOutput(
                        mod_output, hbt_module, hbtn_cord, len(new_devices)
                    )
                )

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        async_add_entities(new_devices)

    registry: er.EntityRegistry = er.async_get(hass)
    area_names: dict[int, AreaDescriptor] = hbtn_rt.areas

    for hbt_module in hbtn_rt.modules:
        for mod_output in hbt_module.outputs:
            if (
                abs(mod_output.type) == 8
                and mod_output.area > 0
                and mod_output.area != hbt_module.area_member
            ):  # standard
                entity_entry = registry.async_get_entity_id(
                    "switch", DOMAIN, f"Mod_{hbt_module.uid}_out{mod_output.nmbr}"
                )
                if entity_entry:
                    registry.async_update_entity(
                        entity_entry, area_id=area_names[mod_output.area].get_name_id()
                    )


class HbtnSetTemperature(CoordinatorEntity, NumberEntity):
    """Representation of a input number."""

    _attr_has_entity_name = True
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_max_value = 27.5
    _attr_native_min_value = 12.5
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, setval, module, coord, idx) -> None:
        """Initialize a Habitron set value, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._setval = setval
        self._module = module
        self._nmbr = setval.nmbr
        self._attr_name = setval.name
        self._attr_unique_id = f"Mod_{self._module.uid}_number{48 + setval.nmbr}"
        self._attr_native_value = setval.value

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

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
        int_val = int(self._attr_native_value) * 10
        await self._module.comm.async_set_setpoint(
            self._module.mod_addr,
            self._setval.nmbr + 1,
            int_val,
        )
        # Update the data
        await self.coordinator.async_request_refresh()


class HbtnAnalogOutput(CoordinatorEntity, NumberEntity):
    """Representation of an analog output number."""

    _attr_has_entity_name = True
    _attr_device_class = NumberDeviceClass.VOLTAGE
    _attr_native_max_value = 100.0
    _attr_native_min_value = 0.0
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        output: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize a Habitron analog value, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._output: IfDescriptor = output
        self._area_member: int = output.area
        self._module: HbtnModule = module
        if output.name.strip() == "":
            self._attr_name = f"Out {output.nmbr + 1}"
        else:
            self._attr_name = output.name
        self._nmbr: int = output.nmbr
        self._out_offs = 0  # Dimm 1 = Out 1 + offs
        self._attr_unique_id: str | None = f"Mod_{self._module.uid}_out{output.nmbr}"
        if output.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str | None:
        """Return the display name of this number."""
        return self._attr_name

    @property
    def icon(self) -> str:
        """Icon of the analog out."""
        return "mdi:sine-wave"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._output.value
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set the new value."""
        self._attr_native_value = value
        int_val = int(self._attr_native_value)
        self._output.value = int_val
        await self._module.comm.async_set_analog_val(
            self._module.mod_addr,
            self._output.nmbr + 1,
            int_val,
        )
        # Update the data
        await self.coordinator.async_request_refresh()
