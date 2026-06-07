"""Tests for the Habitron light platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.light import ColorMode

from unittest.mock import AsyncMock, MagicMock

from custom_components.habitron.light import (
    ColorLed,
    DimmedOutput,
    DimmedOutputPush,
    SwitchedLight,
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
    assert class_attr(DimmedOutput, "_attr_supported_color_modes") == {ColorMode.BRIGHTNESS}
    assert class_attr(DimmedOutputPush, "_attr_color_mode") is ColorMode.BRIGHTNESS
    assert class_attr(DimmedOutputPush, "_attr_supported_color_modes") == {ColorMode.BRIGHTNESS}
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
