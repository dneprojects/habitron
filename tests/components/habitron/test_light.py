"""Tests for the Habitron light platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.light import ColorMode
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.light import (
    ColorLed,
    DimmedOutput,
    DimmedOutputPush,
    SwitchedLight,
    SwitchedLightPush,
    async_setup_entry,
)

from .conftest import class_attr


async def test_light_setup(setup_integration: MockConfigEntry) -> None:
    """The light platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_color_modes_class_level() -> None:
    """All light classes advertise both _attr_color_mode and supported_color_modes."""
    # SwitchedLight: ONOFF
    assert class_attr(SwitchedLight, "_attr_color_mode") is ColorMode.ONOFF
    assert class_attr(SwitchedLight, "_attr_supported_color_modes") == {ColorMode.ONOFF}
    # DimmedOutput / DimmedOutputPush: BRIGHTNESS
    assert class_attr(DimmedOutput, "_attr_color_mode") is ColorMode.BRIGHTNESS
    assert class_attr(DimmedOutput, "_attr_supported_color_modes") == {
        ColorMode.BRIGHTNESS
    }
    assert class_attr(DimmedOutputPush, "_attr_color_mode") is ColorMode.BRIGHTNESS
    assert class_attr(DimmedOutputPush, "_attr_supported_color_modes") == {
        ColorMode.BRIGHTNESS
    }
    # ColorLed: RGB
    assert class_attr(ColorLed, "_attr_color_mode") is ColorMode.RGB
    assert class_attr(ColorLed, "_attr_supported_color_modes") == {ColorMode.RGB}


def test_dimmed_output_translation_key() -> None:
    """DimmedOutput uses the icon-translation key."""
    assert class_attr(DimmedOutput, "_attr_translation_key") == "dimmed_output"


def _make_output(name: str = "Lamp", nmbr: int = 0, type_: int = 1) -> MagicMock:
    """Build a stub IfDescriptor for light outputs."""
    out = MagicMock()
    out.nmbr = nmbr
    out.name = name
    out.type = type_
    out.area = 0
    out.value = 0
    return out


def _make_module() -> MagicMock:
    """Build a stub HbtnModule for a light entity."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.typ = b"\x01\x03"
    mod.comm.async_set_output = AsyncMock()
    mod.comm.async_set_rgbval = AsyncMock()
    mod.comm.async_set_rgb_output = AsyncMock()
    return mod


async def test_switched_light_turn_on() -> None:
    """SwitchedLight.async_turn_on forwards 1 to the bus."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    light = SwitchedLight(out, mod, coord, 0)
    await light.async_turn_on()
    mod.comm.async_set_output.assert_awaited_with(105, 1, 1)


async def test_switched_light_turn_off() -> None:
    """SwitchedLight.async_turn_off forwards 0 to the bus."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    light = SwitchedLight(out, mod, coord, 0)
    await light.async_turn_off()
    mod.comm.async_set_output.assert_awaited_with(105, 1, 0)


def test_switched_light_unique_id() -> None:
    """SwitchedLight has a stable, module-scoped unique id."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    light = SwitchedLight(out, mod, coord, 0)
    assert light.unique_id == "Mod_MOD-1_out0"


def test_switched_light_handles_coordinator_update() -> None:
    """_handle_coordinator_update mirrors the output value into is_on."""
    out = _make_output()
    out.value = 1
    mod = _make_module()
    coord = MagicMock()
    light = SwitchedLight(out, mod, coord, 0)
    light.async_write_ha_state = MagicMock()
    light._handle_coordinator_update()
    assert light._attr_is_on is True


def _make_dimmer_module() -> MagicMock:
    """Build a module stub for DimmedOutput tests (typ=Smart Out)."""
    mod = _make_module()
    mod.typ = b"\x01\x03"
    dim = MagicMock()
    dim.value = 50  # ~50%
    mod.dimmers = [dim]
    mod.comm.async_set_dimmval = AsyncMock()
    return mod


async def test_dimmed_output_turn_on_with_brightness() -> None:
    """DimmedOutput.async_turn_on forwards the rounded brightness percentage."""
    out = _make_output()
    mod = _make_dimmer_module()
    coord = MagicMock()
    light = DimmedOutput(out, mod, coord, 0)
    await light.async_turn_on(brightness=128)  # 128/255 ≈ 50%
    mod.comm.async_set_dimmval.assert_awaited()
    # ~50 percentage
    args = mod.comm.async_set_dimmval.await_args
    assert args.args[2] == 50


def test_dimmed_output_handles_coordinator_update_reads_dimmer() -> None:
    """DimmedOutput.update reads brightness from module.dimmers[]."""
    # DimmedOutput maps output ``nmbr`` 10..19 to ``dimmers[0..9]`` when
    # the module's ``typ[0] == 1`` (Smart Out family). Use nmbr=10 so
    # dimmers[nmbr - _out_offs] resolves to dimmers[0].
    out = _make_output(nmbr=10)
    mod = _make_dimmer_module()
    mod.dimmers[0].value = 100  # full
    coord = MagicMock()
    light = DimmedOutput(out, mod, coord, 0)
    light.async_write_ha_state = MagicMock()
    light._handle_coordinator_update()
    # 100 * 2.55 = 255.0 → int() truncates to 254 (one-off below 255)
    assert light._brightness == 254


def _make_cled_descriptor(nmbr: int = 0) -> MagicMock:
    """Build a stub CLedDescriptor for ColorLed tests."""
    cled = MagicMock()
    cled.nmbr = nmbr
    cled.name = "Color"
    cled.type = 1
    cled.value = [0, 0, 0, 0]  # off, R, G, B
    return cled


async def test_color_led_turn_on_sets_rgb() -> None:
    """ColorLed.async_turn_on forwards the dimmed RGB tuple to the bus."""
    cled = _make_cled_descriptor()
    mod = _make_module()
    mod.comm.async_set_rgbval = AsyncMock()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    await led.async_turn_on(rgb_color=(255, 128, 0), brightness=255)
    mod.comm.async_set_rgbval.assert_awaited()


async def test_color_led_turn_off_clears_state() -> None:
    """ColorLed.async_turn_off forwards 0 to the bus."""
    cled = _make_cled_descriptor()
    cled.value = [1, 200, 100, 50]
    mod = _make_module()
    mod.comm.async_set_rgb_output = AsyncMock()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    await led.async_turn_off()
    mod.comm.async_set_rgb_output.assert_awaited()


def test_color_led_handles_coordinator_update() -> None:
    """ColorLed.update derives brightness and rgb_color from cled.value."""
    cled = _make_cled_descriptor()
    cled.value = [1, 255, 0, 0]  # on, full red
    mod = _make_module()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    led.async_write_ha_state = MagicMock()
    led._handle_coordinator_update()
    assert led._attr_is_on is True
    assert led.brightness == 255
    assert led.rgb_color == (255, 0, 0)


def test_color_led_off_keeps_color_brightness_zero() -> None:
    """When all channels are 0, brightness is 0 and color falls back to white."""
    cled = _make_cled_descriptor()
    cled.value = [0, 0, 0, 0]
    mod = _make_module()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    led.async_write_ha_state = MagicMock()
    led._handle_coordinator_update()
    assert led._attr_is_on is False
    assert led.brightness == 0


def test_switched_light_empty_name_disabled_by_default() -> None:
    """An empty output name marks the entity disabled by default."""
    out = _make_output(name="  ", nmbr=2)
    mod = _make_module()
    coord = MagicMock()
    light = SwitchedLight(out, mod, coord, 0)
    assert light._attr_entity_registry_enabled_default is False
    assert light._attr_name == "Out 3"


def test_switched_light_is_on_property() -> None:
    """is_on returns True iff output.value == 1."""
    out = _make_output()
    out.value = 1
    mod = _make_module()
    coord = MagicMock()
    light = SwitchedLight(out, mod, coord, 0)
    assert light.is_on is True


async def test_switched_light_push_register_callback() -> None:
    """SwitchedLightPush.async_added_to_hass registers the callback."""
    out = _make_output()
    out.register_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    light = SwitchedLightPush(out, mod, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await light.async_added_to_hass()
    out.register_callback.assert_called()


async def test_switched_light_push_remove_callback() -> None:
    """SwitchedLightPush.async_will_remove_from_hass removes the callback."""
    out = _make_output()
    out.remove_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    light = SwitchedLightPush(out, mod, coord, 0)
    await light.async_will_remove_from_hass()
    out.remove_callback.assert_called()


def test_dimmed_output_brightness_property() -> None:
    """brightness returns the cached _brightness value."""
    out = _make_output(nmbr=10)
    mod = _make_dimmer_module()
    coord = MagicMock()
    light = DimmedOutput(out, mod, coord, 0)
    assert light.brightness == 255


def test_dimmed_output_push_brightness_property() -> None:
    """DimmedOutputPush.brightness returns the cached value."""
    out = _make_output(nmbr=10)
    mod = _make_dimmer_module()
    coord = MagicMock()
    light = DimmedOutputPush(out, mod, coord, 0)
    assert light.brightness == 255


def test_dimmed_output_push_handle_coordinator_update_reads_dimmer() -> None:
    """DimmedOutputPush._handle_coordinator_update reads brightness via round()."""
    out = _make_output(nmbr=10)
    mod = _make_dimmer_module()
    mod.dimmers[0].value = 100
    coord = MagicMock()
    light = DimmedOutputPush(out, mod, coord, 0)
    light.async_write_ha_state = MagicMock()
    light._handle_coordinator_update()
    # round(100*2.55) == 255
    assert light._brightness == 255


async def test_dimmed_output_push_turn_on_uses_round() -> None:
    """DimmedOutputPush.async_turn_on uses round() before sending."""
    out = _make_output(nmbr=10)
    mod = _make_dimmer_module()
    coord = MagicMock()
    light = DimmedOutputPush(out, mod, coord, 0)
    await light.async_turn_on(brightness=128)
    mod.comm.async_set_dimmval.assert_awaited()
    args = mod.comm.async_set_dimmval.await_args
    # round(128*100/255) == 50
    assert args.args[2] == 50


def test_color_led_empty_name_falls_back_to_default() -> None:
    """An empty CLED name yields a generated name."""
    cled = _make_cled_descriptor(nmbr=3)
    cled.name = " "
    mod = _make_module()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    assert led._attr_name == "CLED 3"


def test_color_led_negative_type_disabled_by_default() -> None:
    """A negative CLED type marks the entity disabled by default."""
    cled = _make_cled_descriptor()
    cled.type = -1
    mod = _make_module()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    assert led._attr_entity_registry_enabled_default is False


def test_color_led_icons_for_corner_numbers() -> None:
    """Each LED number gets its corner-specific MDI icon."""
    for nmbr, expected in [
        (0, "mdi:square-outline"),
        (1, "mdi:arrow-top-left-bold-box-outline"),
        (2, "mdi:arrow-top-right-bold-box-outline"),
        (3, "mdi:arrow-bottom-left-bold-box-outline"),
        (4, "mdi:arrow-bottom-right-bold-box-outline"),
    ]:
        cled = _make_cled_descriptor(nmbr=nmbr)
        mod = _make_module()
        coord = MagicMock()
        led = ColorLed(cled, mod, coord, 0)
        assert led._attr_icon == expected


def test_color_led_is_on_property() -> None:
    """is_on returns True iff led.value[0] == 1."""
    cled = _make_cled_descriptor()
    cled.value = [1, 0, 0, 0]
    mod = _make_module()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    assert led.is_on is True


def test_color_led_handle_coordinator_update_partial_channels() -> None:
    """Partial RGB values are normalised back to a 100% reference colour."""
    cled = _make_cled_descriptor()
    cled.value = [1, 128, 64, 0]  # half-red, quarter-green, no blue
    mod = _make_module()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    led.async_write_ha_state = MagicMock()
    led._handle_coordinator_update()
    # max_channel = 128 → brightness = 128
    assert led._brightness == 128
    # rgb_color normalised: 255, round(64/128*255)=128, 0
    assert led._rgb_color == (255, 128, 0)


async def test_color_led_async_added_to_hass_registers() -> None:
    """ColorLed.async_added_to_hass registers the LED callback."""
    cled = _make_cled_descriptor()
    cled.register_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await led.async_added_to_hass()
    cled.register_callback.assert_called()


async def test_color_led_async_will_remove_unregisters() -> None:
    """ColorLed.async_will_remove_from_hass removes the LED callback."""
    cled = _make_cled_descriptor()
    cled.remove_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    await led.async_will_remove_from_hass()
    cled.remove_callback.assert_called()


async def test_color_led_turn_on_without_kwargs_uses_defaults() -> None:
    """Without rgb_color/brightness kwargs, ColorLed.turn_on uses cached values."""
    cled = _make_cled_descriptor()
    mod = _make_module()
    coord = MagicMock()
    led = ColorLed(cled, mod, coord, 0)
    led._rgb_color = (200, 100, 0)
    led._brightness = 255
    await led.async_turn_on()
    mod.comm.async_set_rgbval.assert_awaited()


async def test_async_setup_entry_emits_dimmed_output_and_color_led(hass) -> None:
    """async_setup_entry creates DimmedOutputPush + ColorLed for relevant modules."""
    dim_out = _make_output(type_=2, nmbr=10)
    dim_out.area = 0
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.typ = b"\x01\x04"  # RGB-capable
    mod.area_member = 0
    mod.outputs = [dim_out]
    mod.dimmers = [MagicMock(value=50)]
    cled = _make_cled_descriptor()
    cled.name = "Color"
    cled.set_name = MagicMock()
    cled_alt = _make_cled_descriptor(nmbr=1)
    cled_alt.name = ""
    cled_alt.set_name = MagicMock()
    mod.cleds = [cled, cled_alt]

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    with patch("custom_components.habitron.light.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="light.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: added.extend(es))

    assert any(isinstance(e, DimmedOutputPush) for e in added)
    assert any(isinstance(e, ColorLed) for e in added)


async def test_async_setup_entry_assigns_external_area(hass) -> None:
    """When dimmer area > module area_member the area_id is set."""
    dim_out = _make_output(type_=2, nmbr=10)
    dim_out.area = 5
    mod = MagicMock()
    mod.uid = "MOD-A"
    mod.mod_addr = 105
    mod.typ = b"\x01\x03"
    mod.area_member = 0
    mod.outputs = [dim_out]
    mod.dimmers = [MagicMock(value=50)]

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    area = MagicMock()
    area.get_name_id = MagicMock(return_value="area_5_id")
    router.areas = dict.fromkeys(range(6), area)

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch("custom_components.habitron.light.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="light.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)

    registry.async_update_entity.assert_called_with("light.fake", area_id="area_5_id")


async def test_async_setup_entry_area_overflow_falls_back_to_zero(hass) -> None:
    """An out-of-range dimmer area is clamped to zero."""
    dim_out = _make_output(type_=2, nmbr=10)
    dim_out.area = 99
    mod = MagicMock()
    mod.uid = "MOD-OV"
    mod.mod_addr = 105
    mod.typ = b"\x01\x03"
    mod.area_member = 0
    mod.outputs = [dim_out]
    mod.dimmers = [MagicMock(value=50)]

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch("custom_components.habitron.light.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="light.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)

    registry.async_update_entity.assert_called_with("light.fake", area_id=None)
