"""Platform for light integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .interfaces import CLedDescriptor, IfDescriptor
from .module import HbtnModule
from .router import HbtnRouter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add lights for passed config_entry in HA."""
    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices: list[LightEntity] = []
    for hbt_module in hbtn_rt.modules:
        for mod_output in hbt_module.outputs:
            # other type numbers disable output
            # type == 1, standard output: -> switch entities
            if abs(mod_output.type) == 2:  # dimmer
                new_devices.append(
                    DimmedOutputPush(
                        mod_output, hbt_module, hbtn_cord, len(new_devices)
                    )
                )
        for mod_led in hbt_module.leds:
            if isinstance(mod_led, CLedDescriptor):
                led_name = "RGB LED"
                led_no = mod_led.nmbr
                if mod_led.name.strip() == "":
                    mod_led.set_name(f"{led_name} {led_no}")
                else:
                    mod_led.set_name(f"{led_name} {led_no}: {mod_led.name}")
                new_devices.append(
                    ColorLed(mod_led, hbt_module, hbtn_cord, len(new_devices))
                )
    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        async_add_entities(new_devices)


class SwitchedLight(CoordinatorEntity, LightEntity):
    """Representation of habitron light entities."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_should_poll = True  # for push updates

    def __init__(
        self,
        output: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize an HbtnLight, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._output: IfDescriptor = output
        self._module: HbtnModule = module
        if output.name.strip() == "":
            self._attr_name = f"Out {output.nmbr + 1}"
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False
        else:
            self._attr_name = output.name
        self._nmbr: int = output.nmbr
        self._brightness: int = 255
        self._out_offs = 0  # Dimm 1 = Out 1 + offs
        self._attr_unique_id: str | None = f"Mod_{self._module.uid}_out{output.nmbr}"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def supported_color_modes(self) -> set[ColorMode] | set[str] | None:
        """Flag supported color modes."""
        color_modes: set[ColorMode | str] = set()
        color_modes.add(ColorMode.ONOFF)
        return color_modes

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._output.value == 1

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._output.value == 1
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


class DimmedOutput(SwitchedLight):
    """Representation of habitron light entities, dimmable."""

    _attr_brightness = True

    def __init__(self, output, module, coord, idx) -> None:
        """Initialize a dimmable Habitron Light."""
        super().__init__(output, module, coord, idx)
        if module.mod_type[:18] == "Smart Controller X":
            self._out_offs = 10  # Dimm 1 = Out 11
        self._attr_icon = "mdi:lightbulb-on-60"

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        return self._brightness

    @property
    def color_mode(self) -> ColorMode | str | None:
        """Return colormode."""
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
        self._attr_is_on = self._output.value == 1
        self._brightness = int(
            self._module.dimmers[self._nmbr - self._out_offs].value * 2.55
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        # await self._module.comm.async_set_output(
        #     self._module.mod_addr, self._nmbr + 1, 1
        # )
        self._brightness = kwargs.get(ATTR_BRIGHTNESS, self._brightness)
        await self._module.comm.async_set_dimmval(
            self._module.mod_addr,
            self._nmbr - self._out_offs + 1,
            round(self._brightness * 100.0 / 255),
        )


class SwitchedLightPush(SwitchedLight):
    """Version for push update."""

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._output.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._output.remove_callback(self.async_write_ha_state)


class DimmedOutputPush(SwitchedLightPush):
    """Representation of habitron light entities, dimmable."""

    _attr_brightness = True

    def __init__(self, output, module, coord, idx) -> None:
        """Initialize a dimmable Habitron Light."""
        super().__init__(output, module, coord, idx)
        if module.mod_type[:18] == "Smart Controller X":
            self._out_offs = 10  # Dimm 1 = Out 11

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        return self._brightness

    @property
    def color_mode(self) -> ColorMode:
        """Return colormode."""
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
        self._attr_is_on = self._output.value == 1
        self._brightness = int(
            self._module.dimmers[self._nmbr - self._out_offs].value * 2.55
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        # await self._module.comm.async_set_output(
        #     self._module.mod_addr, self._nmbr + 1, 1
        # )
        self._brightness = kwargs.get(ATTR_BRIGHTNESS, self._brightness)
        await self._module.comm.async_set_dimmval(
            self._module.mod_addr,
            self._nmbr - self._out_offs + 1,
            int(self._brightness * 100.0 / 255),
        )


class ColorLed(CoordinatorEntity, LightEntity):
    """Representation of habitron light entities."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.RGB
    _attr_should_poll = True  # for push updates

    def __init__(
        self,
        led: CLedDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize an HbtnLight, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._led: CLedDescriptor = led
        self._module: HbtnModule = module
        if led.name.strip() == "":
            self._attr_name = f"CLED {led.nmbr}"
        else:
            self._attr_name = led.name
        self._nmbr: int = led.nmbr
        self._out_offs: int = 0
        self._brightness: int = 255
        self._rgb_color: tuple[int, int, int] = (50, 50, 50)
        self._attr_unique_id: str | None = f"Mod_{self._module.uid}_rgbled{led.nmbr}"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}
        if led.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False
        if led.nmbr == 0:
            self._attr_icon = "mdi:square-outline"
        if led.nmbr == 1:
            self._attr_icon = "mdi:arrow-top-left-bold-box-outline"
        if led.nmbr == 2:
            self._attr_icon = "mdi:arrow-top-right-bold-box-outline"
        if led.nmbr == 3:
            self._attr_icon = "mdi:arrow-bottom-left-bold-box-outline"
        if led.nmbr == 4:
            self._attr_icon = "mdi:arrow-bottom-right-bold-box-outline"

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._led.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._led.remove_callback(self._handle_coordinator_update)

    @property
    def is_on(self) -> bool | None:
        """Return status of output."""
        return self._led.value[0] == 1

    @property
    def supported_color_modes(self) -> set[ColorMode] | set[str]:
        """Flag supported color modes."""
        color_modes: set[ColorMode | str] = set()
        color_modes.add(ColorMode.RGB)
        return color_modes

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the brightness of the light."""
        return self._rgb_color

    @property
    def brightness(self) -> int:
        """Return the brightness of the light."""
        return self._brightness

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._led.value[0] == 1
        self._rgb_color = self._led.value[1], self._led.value[2], self._led.value[3]
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        self._rgb_color = kwargs.get(ATTR_RGB_COLOR, self._rgb_color)
        self._led.value = [
            1,
            self._rgb_color[0],
            self._rgb_color[1],
            self._rgb_color[2],
        ]
        self._brightness = kwargs.get(ATTR_BRIGHTNESS, self._brightness)
        dimmed_col = self._rgb_color
        dimmed_col = (
            round(dimmed_col[0] * self._brightness / 256),
            round(dimmed_col[1] * self._brightness / 256),
            round(dimmed_col[2] * self._brightness / 256),
        )
        await self._module.comm.async_set_rgbval(
            self._module.mod_addr,
            self._nmbr,
            dimmed_col,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        self._led.value[0] = 0
        await self._module.comm.async_set_rgb_output(
            self._module.mod_addr, self._nmbr, 0
        )
