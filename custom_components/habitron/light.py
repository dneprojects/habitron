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
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


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
                if hbt_module.comm.is_smhub:
                    new_devices.append(
                        SwitchedOutputPush(mod_output, hbt_module, hbtn_cord, len(new_devices))
                    )
                else:
                    new_devices.append(
                        SwitchedOutput(mod_output, hbt_module, hbtn_cord, len(new_devices))
                    )
            if abs(mod_output.type) == 2:  # dimmer
                if hbt_module.comm.is_smhub:
                    new_devices.append(
                        DimmedOutputPush(mod_output, hbt_module, hbtn_cord, len(new_devices))
                    )
                else:
                    new_devices.append(
                        DimmedOutput(mod_output, hbt_module, hbtn_cord, len(new_devices))
                    )
        for mod_led in hbt_module.leds:
            if mod_led.type == 4:
                led_name = "RGB LED"
                led_no = mod_led.nmbr + 1
                if mod_led.name.strip() == "":
                    mod_led.set_name(f"{led_name} {led_no}")
                else:
                    mod_led.set_name(f"{led_name} {led_no}: {mod_led.name}")
                new_devices.append(
                    ColorLed(mod_led, hbt_module, hbtn_cord, len(new_devices))
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
    should_poll = True  # for push updates

    def __init__(self, output, module, coord, idx) -> None:
        """Initialize an HbtnLight, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._output = output
        self._module = module
        if output.name.strip() == "":
            self._attr_name = f"Out {output.nmbr + 1}"
        else:
            self._attr_name = output.name
        self._nmbr = output.nmbr
        self._state = None
        self._brightness = None
        self._attr_unique_id = f"{self._module.uid}_out_{output.nmbr}"
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

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._module.outputs[self._nmbr].value == 1

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
        self._out_offs = 0
        if module.mod_type == "Smart Controller Mini":
            pass
        elif module.mod_type[:16] == "Smart Controller":
            self._out_offs = 10
        else:
            pass

    @property
    def brightness(self) -> int:
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
        self._attr_is_on = self._module.outputs[self._nmbr].value == 1
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


class SwitchedOutputPush(SwitchedOutput):
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


class DimmedOutputPush(SwitchedOutputPush):
    """Representation of habitron light entities, dimmable."""

    _attr_brightness = True

    def __init__(self, output, module, coord, idx) -> None:
        """Initialize a dimmable Habitron Light."""
        super().__init__(output, module, coord, idx)
        self._brightness = 255
        self._color_mode = ColorMode.BRIGHTNESS
        self._supported_color_modes = ColorMode.BRIGHTNESS
        self._out_offs = 0
        if module.mod_type == "Smart Controller Mini":
            pass
        elif module.mod_type[:16] == "Smart Controller":
            self._out_offs = 10
        else:
            pass

    @property
    def brightness(self) -> int:
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
        self._attr_is_on = self._module.outputs[self._nmbr].value == 1
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
    _attr_color_mode = True
    should_poll = True  # for push updates

    def __init__(self, output, module, coord, idx) -> None:
        """Initialize an HbtnLight, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self._color_mode = ColorMode.RGB
        self._supported_color_modes = ColorMode.RGB
        self.idx = idx
        self._output = output
        self._module = module
        if output.name.strip() == "":
            self._attr_name = f"CLED {output.nmbr + 1}"
        else:
            self._attr_name = output.name
        self._nmbr = output.nmbr
        self._out_offs = 0
        self._state = None
        self._brightness = 255
        self._rgb_color = [50, 50, 50]
        self._attr_unique_id = f"{self._module.uid}_rgbled_{output.nmbr}"
        if output.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False
        if output.nmbr == 0:
            self._attr_icon = "mdi:arrow-top-left-bold-box-outline"
        if output.nmbr == 1:
            self._attr_icon = "mdi:arrow-top-right-bold-box-outline"
        if output.nmbr == 2:
            self._attr_icon = "mdi:arrow-bottom-left-bold-box-outline"
        if output.nmbr == 3:
            self._attr_icon = "mdi:arrow-bottom-right-bold-box-outline"
        if output.nmbr == 4:
            self._attr_icon = "mdi:square-outline"

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

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._module.leds[self._nmbr].value[0] == 1

    @property
    def color_mode(self) -> ColorMode:
        """Return colormode."""
        return ColorMode.RGB

    @property
    def supported_color_modes(self) -> set[ColorMode] | set[str]:
        """Flag supported color modes."""
        color_modes: set[ColorMode | str] = set()
        color_modes.add(ColorMode.RGB)
        return color_modes

    @property
    def rgb_color(self) -> int:
        """Return the brightness of the light."""
        return self._rgb_color

    @property
    def brightness(self) -> int:
        """Return the brightness of the light."""
        return self._brightness

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.leds[self._nmbr].value[0] == 1
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        self._rgb_color = kwargs.get(ATTR_RGB_COLOR, self._rgb_color)
        self._output.value = [1, self._rgb_color[0], self._rgb_color[1], self._rgb_color[2]]
        self._brightness = kwargs.get(ATTR_BRIGHTNESS, self._brightness)
        await self._module.comm.async_set_rgbval(
            self._module.mod_addr,
            self._nmbr - self._out_offs + 1,
            self._rgb_color,
        )
        await self._module.comm.async_set_rgb_output(
            self._module.mod_addr, self._nmbr + 1, 1
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        self._output.value[0] = 0
        await self._module.comm.async_set_rgb_output(
            self._module.mod_addr, self._nmbr + 1, 0
        )

