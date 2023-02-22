"""Platform for select integration."""
from __future__ import annotations
from enum import Enum

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .router import DaytimeMode, AlarmMode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add input_select for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        if hbt_module.mod_type == "Smart Controller":
            # Mode setting is per group, entities linked to smart controllers only
            new_devices.append(
                HbtnSelectDaytimeMode(hbt_module, hbtn_rt, hbtn_cord, len(new_devices))
            )
            new_devices.append(
                HbtnSelectAlarmMode(hbt_module, hbtn_rt, hbtn_cord, len(new_devices))
            )
            new_devices.append(
                HbtnSelectGroupMode(hbt_module, hbtn_rt, hbtn_cord, len(new_devices))
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


class HbtnMode(CoordinatorEntity, SelectEntity):
    """Representation of a input select for Habitron modes."""

    def __init__(self, module, hbtnr, coord, idx) -> None:
        """Initialize a Habitron mode, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._mode = module.mode
        self._module = module
        self._mask = 0x03
        self._value = self._mode & self._mask
        self._current_option = ""
        self._enum = DaytimeMode
        self.hbtnr = hbtnr

    @property
    def should_poll(self) -> bool:
        return True

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will reflect this.
    @property
    def available(self) -> bool:
        return True

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.mod_id)}}

    @property
    def options(self) -> list[str]:
        """Return all mode names of enumeration type"""
        all_modes = []
        for mode in self._enum:
            all_modes.append(mode.name)
        return all_modes

    @property
    def current_option(self) -> str:
        """Return the current mode name"""
        return self._current_option

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator, get current module mode"""
        self._mode = self._module.mode
        self._value = self._mode & self._mask
        if self._value == 0:
            self._value = self.hbtnr.mode0 & self._mask
        self._current_option = self._enum(self._value).name
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        mode_val = self._enum[option].value
        self._mode = (self._module.mode & (0xFF - self._mask)) + mode_val
        self._module.mode = self._mode
        await self._module.comm.async_set_group_mode(
            self._module.mod_addr, self._module.group, self._mode
        )


class HbtnSelectDaytimeMode(HbtnMode):
    """Daytime mode object"""

    def __init__(self, module, hbtnr, coord, idx) -> None:
        """Initialize daytime mode selector."""
        super().__init__(module, hbtnr, coord, idx)
        self._mask = 0x03
        self._value = self._mode & self._mask
        if self._value == 0:
            self._value = self.hbtnr.mode0 & self._mask
        self._enum = DaytimeMode
        self._current_option = self._enum(self._value).name
        self._attr_name = f"Group {self._module.group} daytime: "
        self._attr_unique_id = f"{self._module.id}_daytime_mode"


class HbtnSelectAlarmMode(HbtnMode):
    """Daytime mode object"""

    def __init__(self, module, hbtnr, coord, idx) -> None:
        """Initialize alarm mode selector."""
        super().__init__(module, hbtnr, coord, idx)
        self._mask = 0x04
        self._value = self._mode & self._mask
        if self._value == 0:
            self._value = self.hbtnr.mode0 & self._mask
        self._enum = AlarmMode
        self._current_option = self._enum(self._value).name
        self._attr_name = f"Group {self._module.group} alarm: "
        self._attr_unique_id = f"{self._module.id}_alarm_mode"


class HbtnSelectGroupMode(HbtnMode):
    """Daytime mode object"""

    def __init__(self, module, hbtnr, coord, idx) -> None:
        """Initialize group mode selector."""
        super().__init__(module, hbtnr, coord, idx)
        self._mask = 0xF0
        self._value = self._mode & self._mask
        if self._value == 0:
            self._value = self.hbtnr.mode0 & self._mask

        group_enum = Enum(
            value="group_enum",
            names=[
                ("Absent", 16),
                ("Present", 32),
                ("Sleeping", 48),
                ("Vacation", 80),
                (self.hbtnr.user1_name, 96),
                (self.hbtnr.user2_name, 112),
            ],
        )
        self._enum = group_enum
        self._current_option = self._enum(self._value).name
        self._attr_name = f"Group {self._module.group} mode: "
        self._attr_unique_id = f"{self._module.id}_group_mode"
