"""Platform for climate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add climate units for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        if hbt_module.mod_type == "Smart Controller":
            new_devices.append(HbtnClimate(hbt_module, hbtn_cord, len(new_devices)))
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


class HbtnClimate(CoordinatorEntity, ClimateEntity):
    """Representation of habitron climate entities."""

    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, module, coord, idx) -> None:
        """Initialize an HbtnLight, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._module = module
        self._attr_name = f"{self._module.name}: Climate"
        self._attr_unique_id = f"{self._module.id}_climate"
        self._state = None
        self._curr_hvac_mode = HVACMode.OFF
        self._curr_temperature = module.sensors[1].value
        self._curr_humidity = module.sensors[2].value
        self._target_temperature = module.setvalues[0].value
        self._attr_unique_id = f"{self._module.id}_{self._attr_name}"
        self._attr_hvac_modes = HVACMode.HEAT
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_target_temperature_high = 25
        self._attr_target_temperature_low = 15
        self._attr_target_temperature_step = 0.5
        self._attr_hvac_mode = HVACMode.HEAT

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.mod_id)}}

    @property
    def name(self) -> str:
        """Return the display name of this climate unit."""
        return self._attr_name

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return 12.5

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return 27.5

    @property
    def target_temperature_step(self) -> float:
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes."""
        return [HVACMode.HEAT, HVACMode.OFF]

    @property
    def current_temperature(self) -> float:
        """Return the current temperature."""
        return self._curr_temperature

    @property
    def current_humidity(self) -> int:
        """Return the current humidity."""
        return self._curr_humidity

    @property
    def target_temperature(self) -> float:
        return self._target_temperature

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation ie. heat, cool mode."""
        if self._target_temperature <= self._curr_temperature + 0.5:
            self._curr_hvac_mode = HVACMode.OFF
            return HVACMode.OFF
        self._curr_hvac_mode = HVACMode.HEAT
        return HVACMode.HEAT

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._curr_temperature = self._module.sensors[1].value
        self._curr_humidity = self._module.sensors[2].value
        self._target_temperature = self._module.setvalues[0].value
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        self._target_temperature = kwargs.get(ATTR_TEMPERATURE)
        int_val = int(self._target_temperature * 10)
        await self._module.comm.async_set_setpoint(self._module.mod_addr, 1, int_val)
        # Update the data
        # await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        self._curr_hvac_mode = hvac_mode
