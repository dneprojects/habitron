"""Platform for climate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
    ATTR_TEMPERATURE,
    TEMP_CELSIUS,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HbtnCoordinator
from .const import DOMAIN, SMARTIP_COMMAND_STRINGS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add climate units for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_comm = hbtn_rt.comm
    hbtn_cord = HbtnCoordinator(hass, hbtn_comm)

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

    supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    device_class = "shutter"

    def __init__(self, module, coord, idx) -> None:
        """Initialize an HbtnLight, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._module = module
        self._name = f"{self._module.id} climate"
        self._state = None
        self._curr_temperature = module.sensors[1].value
        self._target_temperature = module.setvalues[0].value
        self._attr_unique_id = f"{self._module.id}_{self._name}"
        self._attr_hvac_modes = HVACMode.HEAT
        self._attr_temperature_unit = TEMP_CELSIUS
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
        return self._name

    # @property
    # def target_temperature(self) -> float:
    #     return self._target_temperature

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_current_temperature = self._module.sensors[1].value
        self._attr_current_humidity = self._module.sensors[2].value
        self._attr_target_temperature = self._module.setvalues[0].value
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        self._target_temperature = kwargs.get(ATTR_TEMPERATURE)
        cmd_str = SMARTIP_COMMAND_STRINGS["SET_SETPOINT_VALUE"]
        int_val = int(self._target_temperature * 10)
        hi_val = max(int_val - 255, 0)
        lo_val = int_val - 256 * hi_val
        cmd_str = cmd_str.replace("\xfc", chr(hi_val))
        cmd_str = cmd_str.replace("\xfd", chr(lo_val))
        cmd_str = cmd_str.replace("\xff", chr(self._module.mod_addr))
        cmd_str = cmd_str.replace("\xfe", chr(1))
        await self._module.comm.async_send_command(cmd_str)
        # Update the data
        await self.coordinator.async_request_refresh()
