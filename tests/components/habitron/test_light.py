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
