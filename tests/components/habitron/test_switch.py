"""Tests for the Habitron switch platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.switch import (
    ClimateCtlSwitch,
    HbtnFlag,
    MicrophoneSwitch,
)

from .conftest import class_attr


async def test_switch_setup(setup_integration: MockConfigEntry) -> None:
    """The switch platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_keys_set() -> None:
    """State-based switch entities expose translation keys for icons."""
    assert class_attr(HbtnFlag, "_attr_translation_key") == "habitron_flag"
    assert class_attr(MicrophoneSwitch, "_attr_translation_key") == "microphone"
    assert class_attr(ClimateCtlSwitch, "_attr_translation_key") == "climate_ctl"
