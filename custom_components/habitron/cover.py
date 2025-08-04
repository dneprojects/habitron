"""Platform for cover integration."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .interfaces import CovDescriptor
from .module import HbtnModule
from .router import HbtnRouter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add covers for passed config_entry in HA."""
    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord: DataUpdateCoordinator = hbtn_rt.coord

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

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices  # type: ignore  # noqa: PGH003
        async_add_entities(new_devices)


# This entire class could be written to extend a base class to ensure common attributes
# are kept identical/in sync. It's broken apart here between the Cover and Sensors to
# be explicit about what is returned, and the comments outline where the overlap is.
class HbtnShutter(CoordinatorEntity, CoverEntity):
    """Representation of a shutter cover."""

    _attr_has_entity_name = True
    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_should_poll = True  # for push updates

    _attr_supported_features = (
        CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        cover: CovDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize an HbtnShutter, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._cover: CovDescriptor = cover
        self._module: HbtnModule = module
        if cover.name.strip() == "":
            self._attr_name = f"Out {cover.nmbr + 1}"
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False
        else:
            self._attr_name = cover.name
        self._nmbr: int = cover.nmbr
        self._polarity: bool = cover.type > 0
        if self._polarity:
            self._out_up = self._nmbr * 2
            self._out_down = self._nmbr * 2 + 1
        else:
            self._out_up = self._nmbr * 2 + 1
            self._out_down = self._nmbr * 2
        self._position: int = 0
        self._moving: int = 0
        self.stop_delay: int = module.comm.router.cover_autostop_del
        self._attr_unique_id: str | None = f"Mod_{self._module.uid}_cover{cover.nmbr}"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._cover.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._cover.remove_callback(self._handle_coordinator_update)

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position of the cover."""
        return self._position

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed, same as position 0."""
        return (self._position == 0) & (self._moving == 0)

    @property
    def is_open(self) -> bool | None:
        """Return if the cover is closed, same as position 0."""
        return (self._position == 100) & (self._moving == 0)

    @property
    def is_closing(self) -> bool | None:
        """Return if the cover is closing or not."""
        return self._moving < 0

    @property
    def is_opening(self) -> bool | None:
        """Return if the cover is opening or not."""
        return self._moving > 0

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._position = 100 - int(self._cover.value)
        self.stop_delay = self._module.comm.router.cover_autostop_del
        if self._module.outputs[self._out_up].value > 0:
            self._moving = 1
        elif self._module.outputs[self._out_down].value > 0:
            self._moving = -1
        else:
            self._moving = 0
        if self._moving == 1:
            if (self._position == 100) and (self.stop_delay >= 0):
                self.hass.create_task(self._stop_cover_after_delay(self.stop_delay))
        elif self._moving == -1:
            if (self._position == 0) and (self.stop_delay >= 0):
                self.hass.create_task(self._stop_cover_after_delay(self.stop_delay))
        self.async_write_ha_state()

    async def _stop_cover_after_delay(self, delay_time: int) -> None:
        await asyncio.sleep(delay_time)
        if self._moving == 1:
            await self._module.comm.async_set_output(
                self._module.mod_addr, self._out_up + 1, 0
            )
        else:
            await self._module.comm.async_set_output(
                self._module.mod_addr, self._out_down + 1, 0
            )
        self._moving = 0

    # These methods allow HA to tell the actual device what to do. In this case, move
    # the cover to the desired position, or open and close it all the way.
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._out_up + 1, 0
        )
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._out_down + 1, 0
        )
        self._moving = 0
        self._position = 100 - int(self._cover.value)

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        self._position = 100 - int(self._cover.value)
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._out_up + 1, 1
        )
        self._moving = 1

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        self._position = 100 - int(self._cover.value)
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._out_down + 1, 1
        )
        self._moving = -1

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to position."""
        tmp_position = int(kwargs.get(ATTR_POSITION))  # type: ignore  # noqa: PGH003
        self._position = 100 - int(self._cover.value)
        sh_nmbr = self._nmbr + 1
        if self._module.mod_type[:16] == "Smart Controller":
            sh_nmbr -= 2  # map #3..5 to 1..3
            if sh_nmbr < 1:
                sh_nmbr += 5  # ...and 1..2 to 4..5
        if self._position == tmp_position:
            return
        if self._position < tmp_position:
            self._moving = 1
        if self._position > tmp_position:
            self._moving = -1
        await self._module.comm.async_set_shutterpos(
            self._module.mod_addr,
            sh_nmbr,
            100 - tmp_position,
        )


class HbtnBlind(HbtnShutter):
    """Representation of a shutter cover with tilt control."""

    _attr_supported_features = (
        CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_TILT_POSITION
        | CoverEntityFeature.OPEN_TILT
        | CoverEntityFeature.CLOSE_TILT
    )
    _attr_device_class = CoverDeviceClass.BLIND

    def __init__(self, cover, module, coord, idx) -> None:
        """Initialize an HbtnShutterTilt."""
        super().__init__(cover, module, coord, idx)
        self._tilt_position = 0

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return the current tilt position of the cover."""
        return self._tilt_position

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._position = 100 - int(self._module.covers[self._nmbr].value)
        self._tilt_position = 100 - self._module.covers[self._nmbr].tilt
        self.stop_delay = self._module.comm.router.cover_autostop_del
        if self._module.outputs[self._out_up].value > 0:
            self._moving = 1
        elif self._module.outputs[self._out_down].value > 0:
            self._moving = -1
        else:
            self._moving = 0
        self._position = 100 - int(self._cover.value)
        if self._moving == 1:
            if (self._position == 100) and (self.stop_delay >= 0):
                self.hass.create_task(self._stop_cover_after_delay(self.stop_delay))
        elif self._moving == -1:
            if (self._position == 0) and (self.stop_delay >= 0):
                self.hass.create_task(self._stop_cover_after_delay(self.stop_delay))
        self.async_write_ha_state()

    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Set the tilt angle."""
        tmp_tilt_position = int(kwargs.get(ATTR_TILT_POSITION))  # type: ignore  # noqa: PGH003
        self._tilt_position = 100 - self._module.covers[self._nmbr].tilt
        sh_nmbr = self._nmbr + 1
        if self._module.mod_type[:16] == "Smart Controller":
            sh_nmbr -= 2  # map #3..5 to 1..3
            if sh_nmbr < 1:
                sh_nmbr += 5  # ...and 1..2 to 4..5
        await self._module.comm.async_set_blindtilt(
            self._module.mod_addr,
            sh_nmbr,
            100 - tmp_tilt_position,
        )

    async def async_open_cover_tilt(self, **kwargs) -> None:
        """Set the tilt angle."""
        sh_nmbr = self._nmbr + 1
        self._tilt_position = 100 - self._module.covers[self._nmbr].tilt
        if self._module.mod_type[:16] == "Smart Controller":
            sh_nmbr -= 2  # map #3..5 to 1..3
            if sh_nmbr < 1:
                sh_nmbr += 5  # ...and 1..2 to 4..5
        await self._module.comm.async_set_blindtilt(
            self._module.mod_addr,
            sh_nmbr,
            0,
        )

    async def async_close_cover_tilt(self, **kwargs) -> None:
        """Set the tilt angle."""
        sh_nmbr = self._nmbr + 1
        self._tilt_position = 100 - self._module.covers[self._nmbr].tilt
        if self._module.mod_type[:16] == "Smart Controller":
            sh_nmbr -= 2  # map #3..5 to 1..3
            if sh_nmbr < 1:
                sh_nmbr += 5  # ...and 1..2 to 4..5
        await self._module.comm.async_set_blindtilt(
            self._module.mod_addr,
            sh_nmbr,
            100,
        )
