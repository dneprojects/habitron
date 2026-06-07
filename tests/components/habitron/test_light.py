"""Tests for the Habitron light platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.light import ColorMode

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
