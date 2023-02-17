"""Platform for cover integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityFeature,
    ATTR_POSITION,
    ATTR_TILT_POSITION,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SMARTIP_COMMAND_STRINGS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add covers for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for mod_cover in hbt_module.covers:
            if mod_cover.nmbr >= 0:  # not disabled
                if abs(mod_cover.type) == 1:  # shutter
                    new_devices.append(
                        HbtnShutter(mod_cover, hbt_module, hbtn_cord, len(new_devices))
                    )
                if abs(mod_cover.type) == 2:  # shutter with tilt
                    new_devices.append(
                        HbtnBlind(mod_cover, hbt_module, hbtn_cord, len(new_devices))
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


# This entire class could be written to extend a base class to ensure common attributes
# are kept identical/in sync. It's broken apart here between the Cover and Sensors to
# be explicit about what is returned, and the comments outline where the overlap is.
class HbtnShutter(CoordinatorEntity, CoverEntity):
    """Representation of a shutter cover."""

    supported_features = (
        CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )
    device_class = "shutter"

    def __init__(self, cover, module, coord, idx) -> None:
        """Initialize an HbtnShutter, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._cover = cover
        self._module = module
        self._name = cover.name
        self._nmbr = cover.nmbr
        self._polarity = cover.type > 0
        self._position = 0
        self._moving = 0
        self._attr_unique_id = f"{self._module.id}_cover_{48+cover.nmbr}"

        self._attr_name = "Shutter " + chr(48 + cover.nmbr) + " " + self._name

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.mod_id)}}

    @property
    def current_cover_position(self) -> int:
        """Return the current position of the cover."""
        return self._position

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed, same as position 0."""
        return self._position == 0

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing or not."""
        return self._moving < 0

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening or not."""
        return self._moving > 0

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._position = 100 - self._module.covers[self._nmbr].value
        self._moving = 0
        if self._module.outputs[self._nmbr * 2].value > 0:
            if self._polarity:
                self._moving = 1
            else:
                self._moving = -1
        if self._module.outputs[(self._nmbr * 2) + 1].value > 0:
            if self._polarity:
                self._moving = -1
            else:
                self._moving = 1
        self.async_write_ha_state()

    async def async_send_command(self, cmd_str):
        """Send command patches module and output numbers"""
        cmd_str = cmd_str.replace("\xff", chr(self._module.mod_addr))
        if self._module.has_sensors:  # SmartController counts 2..4
            cmd_str = cmd_str.replace("\xfe", chr(self._nmbr - 1))
        else:
            cmd_str = cmd_str.replace("\xfe", chr(self._nmbr + 1))
        await self._module.comm.async_send_command(cmd_str)

    async def async_send_stop_command(self, cmd_str):
        """Send command patches module and output numbers"""
        cmd_str = cmd_str.replace("\xff", chr(self._module.mod_addr))
        cmd_str1 = cmd_str.replace("\xfe", chr(self._nmbr * 2 + 1))
        cmd_str2 = cmd_str.replace("\xfe", chr(self._nmbr * 2 + 2))
        await self._module.comm.async_send_command(cmd_str1)
        await self._module.comm.async_send_command(cmd_str2)

    async def async_send_up_command(self, cmd_str):
        """Send command patches module and output numbers"""
        cmd_str = cmd_str.replace("\xff", chr(self._module.mod_addr))
        if self._polarity:
            cmd_str = cmd_str.replace("\xfe", chr(self._nmbr * 2 + 1))
        else:
            cmd_str = cmd_str.replace("\xfe", chr(self._nmbr * 2 + 2))
        await self._module.comm.async_send_command(cmd_str)

    async def async_send_down_command(self, cmd_str):
        """Send command patches module and output numbers"""
        cmd_str = cmd_str.replace("\xff", chr(self._module.mod_addr))
        if self._polarity:
            cmd_str = cmd_str.replace("\xfe", chr(self._nmbr * 2 + 2))
        else:
            cmd_str = cmd_str.replace("\xfe", chr(self._nmbr * 2 + 1))
        await self._module.comm.async_send_command(cmd_str)

    # These methods allow HA to tell the actual device what to do. In this case, move
    # the cover to the desired position, or open and close it all the way.
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self.async_send_stop_command(SMARTIP_COMMAND_STRINGS["SET_OUTPUT_OFF"])
        # Update the data
        await self.coordinator.async_request_refresh()

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self.async_send_up_command(SMARTIP_COMMAND_STRINGS["SET_OUTPUT_ON"])
        # Update the data
        await self.coordinator.async_request_refresh()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self.async_send_down_command(SMARTIP_COMMAND_STRINGS["SET_OUTPUT_ON"])
        # Update the data
        await self.coordinator.async_request_refresh()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to position."""
        self._position = kwargs.get(ATTR_POSITION)
        cmd_str = SMARTIP_COMMAND_STRINGS["SET_ROLLER_POSITION"]
        cmd_str = cmd_str[0:-1] + chr(100 - self._position)
        await self.async_send_command(cmd_str)
        # Update the data
        await self.coordinator.async_request_refresh()


class HbtnBlind(HbtnShutter):
    """Representation of a shutter cover with tilt control."""

    supported_features = (
        CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_TILT_POSITION
    )
    device_class = "blind"

    def __init__(self, cover, module, coord, idx) -> None:
        """Initialize an HbtnShutterTilt."""
        super().__init__(cover, module, coord, idx)
        self._tilt_position = 0
        self._attr_name = "Blind " + chr(48 + cover.nmbr) + " " + self._name

    @property
    def current_cover_tilt_position(self) -> int:
        """Return the current tilt position of the cover."""
        return self._tilt_position

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._position = 100 - self._module.covers[self._nmbr].value
        self._tilt_position = self._module.covers[self._nmbr].tilt
        self._moving = 0
        if self._module.outputs[self._nmbr * 2].value > 0:
            if self._polarity:
                self._moving = 1
            else:
                self._moving = -1
        if self._module.outputs[(self._nmbr * 2) + 1].value > 0:
            if self._polarity:
                self._moving = -1
            else:
                self._moving = 1
        self.async_write_ha_state()

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Close the cover."""
        self._tilt_position = kwargs.get(ATTR_TILT_POSITION)
        cmd_str = SMARTIP_COMMAND_STRINGS["SET_ROLLER_TILT_POSITION"]
        cmd_str = cmd_str[0:-1] + chr(self._tilt_position)
        await self.async_send_command(cmd_str)
        # Update the data
        await self.coordinator.async_request_refresh()
