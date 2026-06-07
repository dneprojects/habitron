"""Tests for the Habitron number platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.number import HbtnAnalogOutput

from .conftest import class_attr


async def test_number_setup(setup_integration: MockConfigEntry) -> None:
    """The number platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_key() -> None:
    """HbtnAnalogOutput uses the icon-translation key."""
    assert class_attr(HbtnAnalogOutput, "_attr_translation_key") == "analog_output"
