"""Platform for climate integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .module import HbtnModule
from .router import HbtnRouter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add climate units for passed config_entry in HA."""
    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord: DataUpdateCoordinator = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        if (hbt_module.mod_type[:16] == "Smart Controller") or (
            hbt_module.mod_type == "Smart Sensor"
        ):
            # Always add first climate unit
            new_devices.append(HbtnClimate(hbt_module, hbtn_cord, 0))

            # Second unit
            if hbt_module.typ[0] == 1:
                climate2 = HbtnClimate(hbt_module, hbtn_cord, 1)
                new_devices.append(climate2)

                # Logic to monitor and toggle the second entity
                @callback
                def clean_enable_logic(module=hbt_module):
                    registry = er.async_get(hass)
                    u_id = f"Mod_{module.uid}_climate_2"
                    entity_id = registry.async_get_entity_id("climate", DOMAIN, u_id)

                    if entity_id:
                        entry_reg = registry.async_get(entity_id)
                        should_be_enabled = module.climate_ctl12 == 2

                        # Case: Module switched to dual mode but entity is disabled
                        if should_be_enabled and entry_reg and entry_reg.disabled_by:
                            _LOGGER.info("Enabling climate unit 2 for %s", module.uid)
                            registry.async_update_entity(entity_id, disabled_by=None)

                        # Case: Module switched to single mode but entity is enabled
                        elif (
                            not should_be_enabled
                            and entry_reg
                            and entry_reg.disabled_by is None
                        ):
                            _LOGGER.info("Disabling climate unit 2 for %s", module.uid)
                            registry.async_update_entity(
                                entity_id,
                                disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                            )

                # Connect the logic to the coordinator
                entry.async_on_unload(hbtn_cord.async_add_listener(clean_enable_logic))

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        async_add_entities(new_devices)


class HbtnClimate(CoordinatorEntity, ClimateEntity):
    """Representation of habitron climate entities."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TARGET_TEMPERATURE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _enable_turn_on_off_backwards_compatibility = False
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.HEAT_COOL]

    def __init__(
        self,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        controller_idx: int,
    ) -> None:
        """Initialize climate unit with instance index (0 or 1)."""
        super().__init__(coord, context=module.uid)
        self._module: HbtnModule = module
        self._controller_idx = controller_idx

        # Unique ID must differ for the second entity
        if self._controller_idx == 0:
            self._attr_unique_id = f"Mod_{self._module.uid}_climate"
            self._attr_name = "Climate"
        else:
            self._attr_unique_id = f"Mod_{self._module.uid}_climate_2"
            self._attr_name = "Climate 2"

        self._curr_hvac_mode = HVACMode.HEAT
        self._target_temperature = 20.0
        self._curr_temperature = 20.0
        self._curr_humidity = None

        self._attr_target_temperature_high = 25.0
        self._attr_target_temperature_low = 15.0
        self._attr_target_temperature_step = 0.5
        self._update_local_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Link to parent device."""
        return DeviceInfo(identifiers={(DOMAIN, self._module.uid)})

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Initial state for registry."""
        if self._controller_idx == 1:
            return self._module.climate_ctl12 == 2
        return True

    @property
    def min_temp(self) -> float:
        """Return minimum setpoint."""
        return 12.5

    @property
    def max_temp(self) -> float:
        """Return maximum setpoint."""
        return 27.5

    @property
    def current_temperature(self) -> float | None:
        """Return sensed temperature."""
        return self._curr_temperature

    @property
    def current_humidity(self) -> int | None:
        """Return sensed humidity."""
        return round(self._curr_humidity) if self._curr_humidity is not None else None

    @property
    def target_temperature(self) -> float:
        """Return active target temperature."""
        return self._target_temperature

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current operation mode."""
        return self._curr_hvac_mode

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return current activity based on state."""
        return self._attr_hvac_action

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update active entity state."""
        self._update_local_state()
        self.async_write_ha_state()

    def _update_local_state(self) -> None:
        """Sync internal state with module sensors."""
        # HVAC Mode mapping
        mode_map = {
            1: HVACMode.HEAT,
            2: HVACMode.COOL,
            3: HVACMode.HEAT_COOL,
            4: HVACMode.OFF,
        }
        self._curr_hvac_mode = mode_map.get(
            self._module.climate_settings, HVACMode.HEAT
        )

        # Map temperature sensors
        if len(self._module.sensors) > 1:
            if self._controller_idx == 0:
                self._curr_temperature = self._module.sensors[1].value
                self._target_temperature = self._module.setvalues[0].value
            else:
                self._curr_temperature = self._module.sensors[2].value
                self._target_temperature = self._module.setvalues[1].value

            # Map humidity if available
            if len(self._module.sensors) > 3:
                self._curr_humidity = self._module.sensors[3].value
        else:
            self._curr_temperature = self._module.sensors[0].value
            self._target_temperature = self._module.setvalues[0].value

        self.update_action()

    def update_action(self) -> None:
        """Update HVAC action."""
        self._attr_hvac_action = HVACAction.IDLE
        if self._curr_hvac_mode == HVACMode.OFF:
            self._attr_hvac_action = HVACAction.OFF
            return
        if (
            self._curr_hvac_mode == HVACMode.HEAT
            and self._curr_temperature < self._target_temperature - 1
        ):
            self._attr_hvac_action = HVACAction.HEATING
        elif (
            self._curr_hvac_mode == HVACMode.COOL
            and self._curr_temperature > self._target_temperature + 1
        ):
            self._attr_hvac_action = HVACAction.COOLING
        elif self._curr_hvac_mode == HVACMode.HEAT_COOL:
            if self._curr_temperature > self._target_temperature + 1:
                self._attr_hvac_action = HVACAction.COOLING
            elif self._curr_temperature < self._target_temperature - 1:
                self._attr_hvac_action = HVACAction.HEATING

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set temperature."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._target_temperature = temp
            await self._module.comm.async_set_setpoint(
                self._module.mod_addr, self._controller_idx + 1, int(temp * 10)
            )
            await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set operation mode for both instances."""
        mode_to_val = {
            HVACMode.HEAT: 1,
            HVACMode.COOL: 2,
            HVACMode.HEAT_COOL: 3,
            HVACMode.OFF: 4,
        }
        val = mode_to_val.get(hvac_mode, 4)
        self._module.climate_settings = val

        # This update affects both controllers
        await self._module.comm.async_set_climate_mode(
            self._module.mod_addr, val, self._module.climate_ctl12
        )
        await self.coordinator.async_request_refresh()
