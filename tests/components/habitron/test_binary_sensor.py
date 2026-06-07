"""Tests for the Habitron binary_sensor platform.

Skeleton with smoke-level setup test and translation_key sanity checks.
Extend with per-entity state-transition tests and snapshot-based UI tests.
"""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.binary_sensor import (
    HbtnState,
    InputSwitch,
    ListeningStatusSensor,
    MotionSensor,
    RainSensor,
)

from .conftest import class_attr


async def test_binary_sensor_setup(setup_integration: MockConfigEntry) -> None:
    """The platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_keys_set() -> None:
    """Every state-based binary sensor exposes the icon translation key."""
    assert class_attr(InputSwitch, "_attr_translation_key") == "input_switch"
    assert class_attr(MotionSensor, "_attr_translation_key") == "motion"
    assert class_attr(RainSensor, "_attr_translation_key") == "rain"
    assert class_attr(HbtnState, "_attr_translation_key") == "hub_state"
    assert class_attr(ListeningStatusSensor, "_attr_translation_key") == "listening_status"
