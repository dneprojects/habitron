"""Platform for number integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.number import NumberDeviceClass, NumberEntity
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
    """Add input_number for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_comm = hbtn_rt.comm
    hbtn_cord = HbtnCoordinator(hass, hbtn_comm)

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        if hbt_module.has_setvals:
            for set_val in hbt_module.setvalues:
                new_devices.append(
                    HbtnNumber(set_val, hbt_module, hbtn_cord, len(new_devices))
                )

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


class HbtnNumber(CoordinatorEntity, NumberEntity):
    """Representation of a input number."""

    device_class = NumberDeviceClass.TEMPERATURE
    native_max_value = 25.5
    native_step = 0.5

    def __init__(self, setval, module, coord, idx) -> None:
        """Initialize a Habitron set value, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._setval = setval
        self._module = module
        self._name = setval.name
        self._nmbr = setval.nmbr
        self._value = setval.value
        self._moving = 0
        self._attr_unique_id = f"{self._module.id}_number_{48+setval.nmbr}"
        self._attr_name = f"{self._module.id} {self._name}"

    @property
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.mod_id)}}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_value = self._setval.value
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set the new value."""
        self._value = value
        cmd_str = SMARTIP_COMMAND_STRINGS["SET_SETPOINT_VALUE"]
        int_val = int(self._value * 10)
        hi_val = max(int_val - 255, 0)
        lo_val = int_val - 256 * hi_val
        cmd_str = cmd_str.replace("\xfc", chr(hi_val))
        cmd_str = cmd_str.replace("\xfd", chr(lo_val))
        await self.async_send_command(cmd_str)
        # Update the data
        await self.coordinator.async_request_refresh()

    async def async_send_command(self, cmd_str) -> None:
        """Send command patches module and output numbers"""
        cmd_str = cmd_str.replace("\xff", chr(self._module.mod_addr))
        cmd_str = cmd_str.replace("\xfe", chr(self._setval.nmbr + 1))
        await self._module.comm.async_send_command(cmd_str)
