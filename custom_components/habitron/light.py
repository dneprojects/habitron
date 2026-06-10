"""Platform for light integration."""

from typing import Any

from homeassistant.components.light import (  # type: ignore[attr-defined]
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .coordinator import HabitronConfigEntry
from .interfaces import AreaDescriptor, CLedDescriptor, IfDescriptor
from .module import HbtnModule
from .router import HbtnRouter

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add lights for passed config_entry in HA."""
    hbtn_rt: HbtnRouter = entry.runtime_data.router
    hbtn_cord = hbtn_rt.coord

    new_devices: list[LightEntity] = []
    for hbt_module in hbtn_rt.modules:
        for mod_output in hbt_module.outputs:
            # other type numbers disable output
            # type == 1, standard output: -> switch entities
            if mod_output.type == 2:  # dimmer
                new_devices.append(
                    DimmedOutputPush(
                        mod_output, hbt_module, hbtn_cord, len(new_devices)
                    )
                )

        if hbt_module.typ in [b"\x01\x04", b"\x32\x01"]:
            for cled in hbt_module.cleds:
                led_name = "Color Corner"
                if cled.nmbr == 0:
                    led_name = "Color Ambient"
                else:
                    led_name = f"Color Corner {cled.nmbr}"
                if cled.name.strip() == "":
                    cled.set_name(f"{led_name}")
                else:
                    cled.set_name(f"{led_name}: {cled.name}")
                new_devices.append(
                    ColorLed(cled, hbt_module, hbtn_cord, len(new_devices))
                )
    if new_devices:
        async_add_entities(new_devices)

    registry: er.EntityRegistry = er.async_get(hass)
    area_names: dict[int, AreaDescriptor] = hbtn_rt.areas

    for hbt_module in hbtn_rt.modules:
        for mod_output in hbt_module.outputs:
            if mod_output.type == 2:  # dimmer
                entity_entry = registry.async_get_entity_id(
                    "light", DOMAIN, f"Mod_{hbt_module.uid}_out{mod_output.nmbr}"
                )
                if entity_entry:
                    area_index = mod_output.area
                    if area_index > len(area_names) - 1:
                        area_index = 0
                    if area_index in [0, hbt_module.area_member]:
                        registry.async_update_entity(
                            entity_entry, area_id=None
                        )  # default
                    else:
                        registry.async_update_entity(
                            entity_entry, area_id=area_names[area_index].get_name_id()
                        )


class SwitchedLight(CoordinatorEntity[DataUpdateCoordinator[None]], LightEntity):
    """Representation of habitron light entities."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        output: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator[None],
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
    def is_on(self) -> bool:
        """Return status of output."""
        return bool(self._output.value == 1)

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
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_translation_key = "dimmed_output"

    def __init__(
        self,
        output: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator[None],
        idx: int,
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
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(
        self,
        output: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator[None],
        idx: int,
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
        self._attr_is_on = self._output.value == 1
        self._brightness = round(
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


class ColorLed(CoordinatorEntity[DataUpdateCoordinator[None]], LightEntity):
    """Representation of habitron light entities."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    def __init__(
        self,
        led: CLedDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator[None],
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
        self._org_color: tuple[int, int, int] = (50, 50, 50)
        self._hs_color: tuple[float, float] = (0.0, 0.0)
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
        r_dimmed = self._led.value[1]
        g_dimmed = self._led.value[2]
        b_dimmed = self._led.value[3]
        max_channel = max(r_dimmed, g_dimmed, b_dimmed)
        if max_channel > 0:
            # 1. Calculate brightness (0..255) based on the highest channel
            self._brightness = max_channel
            # 2. Re-calculate the original 100% color for the HA color picker
            self._rgb_color = (
                min(round((r_dimmed / max_channel) * 255), 255),
                min(round((g_dimmed / max_channel) * 255), 255),
                min(round((b_dimmed / max_channel) * 255), 255),
            )
        else:
            # All channels off — keep the last-known colour, drop brightness to 0.
            self._brightness = 0
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""

        # __init__ seeds both ``_rgb_color`` and ``_brightness`` so we can read
        # them directly when the user didn't supply new values via the
        # frontend's color picker / brightness slider.
        if ATTR_RGB_COLOR in kwargs:
            self._rgb_color = kwargs[ATTR_RGB_COLOR]
        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = kwargs[ATTR_BRIGHTNESS]

        # Calculate the dimmed color for your hardware based on current brightness
        # We use a float factor to avoid early truncation during calculation
        bright_factor = self._brightness / 255.0

        dimmed_col = (
            max(round(self._rgb_color[0] * bright_factor), 1),
            max(round(self._rgb_color[1] * bright_factor), 1),
            max(round(self._rgb_color[2] * bright_factor), 1),
        )
        # Update the LED indicator value with the 100% color
        self._led.value = [
            1,
            dimmed_col[0],
            dimmed_col[1],
            dimmed_col[2],
        ]

        await self._module.comm.async_set_rgbval(
            self._module.mod_addr,
            self._nmbr,
            list(dimmed_col),
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        self._led.value[0] = 0
        await self._module.comm.async_set_rgb_output(
            self._module.mod_addr, self._nmbr, 0
        )
