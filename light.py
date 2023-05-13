"""Platform for light integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .module import IfDescriptor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add lights for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for mod_output in hbt_module.outputs:
            # other type numbers disable output
            if abs(mod_output.type) == 1:  # standard
                new_devices.append(
                    SwitchedOutput(mod_output, hbt_module, hbtn_cord, len(new_devices))
                )
            if abs(mod_output.type) == 2:  # dimmer
                new_devices.append(
                    DimmedOutput(mod_output, hbt_module, hbtn_cord, len(new_devices))
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


class SwitchedOutput(CoordinatorEntity, LightEntity):
    """Representation of habitron light entities."""

    _attr_has_entity_name = True

    def __init__(self, output, module, coord, idx) -> None:
        """Initialize an HbtnLight, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._output = output
        self._module = module
        self._attr_name = output.name
        self._nmbr = output.nmbr
        self._state = None
        self._brightness = None
        self._attr_unique_id = f"{self._module.id}_{output.name}"
        if output.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this light."""
        return self._attr_name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.outputs[self._nmbr].value == 1
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._nmbr + 1, 1
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._nmbr + 1, 0
        )


class DimmedOutput(SwitchedOutput):
    """Representation of habitron light entities, dimmable."""

    _attr_brightness = True

    def __init__(self, output, module, coord, idx) -> None:
        """Initialize a dimmable Habitron Light."""
        super().__init__(output, module, coord, idx)
        self._brightness = 255
        self._color_mode = ColorMode.BRIGHTNESS
        self._supported_color_modes = ColorMode.BRIGHTNESS
        if module.mod_type == "Smart Controller":
            self._out_offs = 10
        else:
            self._out_offs = 0

    @property
    def brightness(self) -> int:
        """Return the brightness of the light."""
        return self._brightness

    @property
    def color_mode(self) -> ColorMode:
        return ColorMode.BRIGHTNESS

    @property
    def supported_color_modes(self) -> set[ColorMode] | set[str]:
        """Flag supported color modes."""
        color_modes: set[ColorMode | str] = set()
        color_modes.add(ColorMode.BRIGHTNESS)
        return color_modes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.outputs[self._nmbr].value == 1
        self._brightness = int(
            self._module.dimmers[self._nmbr - self._out_offs].value * 2.55
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._nmbr + 1, 1
        )
        self._brightness = kwargs.get(ATTR_BRIGHTNESS, self._brightness)
        await self._module.comm.async_set_dimmval(
            self._module.mod_addr,
            self._nmbr - self._out_offs + 1,
            int(self._brightness * 100.0 / 255),
        )