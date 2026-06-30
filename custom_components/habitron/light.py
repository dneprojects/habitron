"""Platform for light integration."""

from typing import Any

from habitron_client import ColorLed, Module, Output

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._helpers import async_assign_entity_area, hbtn_device_info
from .coordinator import HabitronConfigEntry, HbtnCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add lights for passed config_entry in HA."""
    smhub = entry.runtime_data
    hbtn_rt = smhub.router
    hbtn_cord = smhub.coordinator

    new_devices: list[LightEntity] = []
    for hbt_module in hbtn_rt.modules:
        for mod_output in hbt_module.outputs:
            # type == 1 (standard output) is a switch entity; type == 2 dims.
            if mod_output.type == 2:
                new_devices.append(
                    DimmedOutputPush(
                        mod_output, hbt_module, hbtn_cord, len(new_devices)
                    )
                )

        if hbt_module.typ in [b"\x01\x04", b"\x32\x01"]:
            for cled in hbt_module.color_leds:
                if cled.nmbr == 0:
                    led_name = "Color Ambient"
                else:
                    led_name = f"Color Corner {cled.nmbr}"
                cled.name = (
                    led_name if cled.name.strip() == "" else f"{led_name}: {cled.name}"
                )
                new_devices.append(
                    HbtnColorLight(cled, hbt_module, hbtn_cord, len(new_devices))
                )
    if new_devices:
        async_add_entities(new_devices)

    registry: er.EntityRegistry = er.async_get(hass)
    area_reg = ar.async_get(hass)
    area_ids = {
        area.nmbr: area_reg.async_get_or_create(area.name).id for area in hbtn_rt.areas
    }

    for hbt_module in hbtn_rt.modules:
        for mod_output in hbt_module.outputs:
            if mod_output.type == 2:  # dimmer
                async_assign_entity_area(
                    registry,
                    domain="light",
                    unique_id=f"Mod_{hbt_module.uid}_out{mod_output.nmbr}",
                    area_index=mod_output.area,
                    area_member=hbt_module.area,
                    area_ids=area_ids,
                )


class SwitchedLight(CoordinatorEntity[HbtnCoordinator], LightEntity):
    """Representation of a Habitron output as an on/off light."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self, output: Output, module: Module, coord: HbtnCoordinator, idx: int
    ) -> None:
        """Initialize an HbtnLight, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._output = output
        self._module = module
        if output.name.strip() == "":
            self._attr_name = f"Out {output.nmbr + 1}"
            self._attr_entity_registry_enabled_default = False
        else:
            self._attr_name = output.name
        self._nmbr: int = output.nmbr
        self._brightness: int = 255
        self._out_offs = 0  # Dimm 1 = Out 1 + offs
        self._attr_unique_id: str | None = f"Mod_{module.uid}_out{output.nmbr}"
        self._attr_device_info = hbtn_device_info(module.uid)

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._output.is_on

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._output.is_on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        await self.coordinator.comm.async_set_output(
            self._module.addr, self._nmbr + 1, 1
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self.coordinator.comm.async_set_output(
            self._module.addr, self._nmbr + 1, 0
        )


class DimmedOutput(SwitchedLight):
    """Representation of a Habitron dimmable output."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_translation_key = "dimmed_output"

    def __init__(
        self, output: Output, module: Module, coord: HbtnCoordinator, idx: int
    ) -> None:
        """Initialize a dimmable Habitron Light."""
        super().__init__(output, module, coord, idx)
        if module.typ[0] == 1:
            self._out_offs = 10  # Dimm 1 = Out 11

    @property
    def brightness(self) -> int | None:
        """Return the brightness of the light."""
        return self._brightness

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._output.is_on
        self._brightness = round(
            self._module.dimmers[self._nmbr - self._out_offs].brightness * 2.55
        )
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on (with optional brightness)."""
        self._brightness = kwargs.get(ATTR_BRIGHTNESS, self._brightness)
        await self.coordinator.comm.async_set_dimmval(
            self._module.addr,
            self._nmbr - self._out_offs + 1,
            round(self._brightness * 100.0 / 255),
        )


class SwitchedLightPush(SwitchedLight):
    """Version for push update."""

    async def async_added_to_hass(self) -> None:
        """Subscribe to the output's change notifications."""
        await super().async_added_to_hass()
        self._output.add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe the output listener."""
        self._output.remove_listener(self.async_write_ha_state)
        await super().async_will_remove_from_hass()


class DimmedOutputPush(DimmedOutput):
    """Representation of a Habitron dimmable output with push updates."""

    async def async_added_to_hass(self) -> None:
        """Subscribe to the output's change notifications."""
        await super().async_added_to_hass()
        self._output.add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe the output listener."""
        self._output.remove_listener(self.async_write_ha_state)
        await super().async_will_remove_from_hass()


class HbtnColorLight(CoordinatorEntity[HbtnCoordinator], LightEntity):
    """Representation of a Habitron RGB colour LED."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(
        self, led: ColorLed, module: Module, coord: HbtnCoordinator, idx: int
    ) -> None:
        """Initialize an HbtnLight, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._led = led
        self._module = module
        self._attr_name = led.name if led.name.strip() else f"CLED {led.nmbr}"
        self._nmbr: int = led.nmbr
        self._brightness: int = 255
        self._rgb_color: tuple[int, int, int] = (50, 50, 50)
        self._attr_unique_id: str | None = f"Mod_{module.uid}_rgbled{led.nmbr}"
        self._attr_device_info = hbtn_device_info(module.uid)
        if led.type < 0:
            self._attr_entity_registry_enabled_default = False
        _corner_icons = {
            0: "mdi:square-outline",
            1: "mdi:arrow-top-left-bold-box-outline",
            2: "mdi:arrow-top-right-bold-box-outline",
            3: "mdi:arrow-bottom-left-bold-box-outline",
            4: "mdi:arrow-bottom-right-bold-box-outline",
        }
        if led.nmbr in _corner_icons:
            self._attr_icon = _corner_icons[led.nmbr]

    async def async_added_to_hass(self) -> None:
        """Subscribe to the colour-LED's change notifications."""
        await super().async_added_to_hass()
        self._led.add_listener(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe the colour-LED listener."""
        self._led.remove_listener(self._handle_coordinator_update)
        await super().async_will_remove_from_hass()

    @property
    def is_on(self) -> bool | None:
        """Return status of output."""
        return self._led.is_on

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the colour of the light."""
        return self._rgb_color

    @property
    def brightness(self) -> int:
        """Return the brightness of the light."""
        return self._brightness

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._led.is_on
        r_dimmed, g_dimmed, b_dimmed = (
            self._led.rgb[0],
            self._led.rgb[1],
            self._led.rgb[2],
        )
        max_channel = max(r_dimmed, g_dimmed, b_dimmed)
        if max_channel > 0:
            # Brightness from the highest channel; rescale to the 100% colour.
            self._brightness = max_channel
            self._rgb_color = (
                min(round((r_dimmed / max_channel) * 255), 255),
                min(round((g_dimmed / max_channel) * 255), 255),
                min(round((b_dimmed / max_channel) * 255), 255),
            )
        else:
            # All channels off — keep the last colour, drop brightness to 0.
            self._brightness = 0
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        if ATTR_RGB_COLOR in kwargs:
            rgb = kwargs[ATTR_RGB_COLOR]
            max_channel = max(rgb)
            if ATTR_BRIGHTNESS not in kwargs and max_channel > 0:
                # Derive brightness from the highest channel and rescale the
                # colour to 100 %, mirroring _handle_coordinator_update so the
                # write/read round-trip stays consistent.
                self._brightness = max_channel
                self._rgb_color = tuple(
                    min(round(c / max_channel * 255), 255) for c in rgb
                )
            else:
                self._rgb_color = rgb
        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = kwargs[ATTR_BRIGHTNESS]

        bright_factor = self._brightness / 255.0
        dimmed_col = (
            max(round(self._rgb_color[0] * bright_factor), 1),
            max(round(self._rgb_color[1] * bright_factor), 1),
            max(round(self._rgb_color[2] * bright_factor), 1),
        )
        self._led.is_on = True
        self._led.rgb = [dimmed_col[0], dimmed_col[1], dimmed_col[2], 0]
        await self.coordinator.comm.async_set_rgbval(
            self._module.addr, self._nmbr, list(dimmed_col)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        self._led.is_on = False
        await self.coordinator.comm.async_set_rgb_output(
            self._module.addr, self._nmbr, 0
        )
