"""Tests for the Habitron binary_sensor platform.

Skeleton with smoke-level setup test and translation_key sanity checks.
Extend with per-entity state-transition tests and snapshot-based UI tests.
"""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from unittest.mock import MagicMock

from custom_components.habitron.binary_sensor import (
    HbtnBinSensor,
    HbtnState,
    InputSwitch,
    InputSwitchPush,
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


def _make_input(name: str = "Sw 1", nmbr: int = 0, type_: int = 2) -> MagicMock:
    """Build a stub IfDescriptor for input-switch entities."""
    inp = MagicMock()
    inp.nmbr = nmbr
    inp.name = name
    inp.type = type_
    inp.area = 0
    return inp


def _make_module() -> MagicMock:
    """Build a stub HbtnModule with input list."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.inputs = [MagicMock(value=0, nmbr=0)]
    mod.sensors = [MagicMock(value=0, nmbr=0)]
    return mod


def test_input_switch_initial_state_off() -> None:
    """An InputSwitch starts as off when the underlying input value is 0."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputSwitch(inp, mod, coord, 0)
    assert entity.is_on is False
    assert entity.unique_id == "Mod_MOD-1_in0"


def test_motion_sensor_unique_id() -> None:
    """MotionSensor has a stable, module-scoped unique id."""
    inp = _make_input(name="Motion")
    mod = _make_module()
    coord = MagicMock()
    entity = MotionSensor(inp, mod, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_motion"


def test_rain_sensor_initial_state_off() -> None:
    """RainSensor starts off when the underlying sensor value is 0."""
    inp = _make_input(name="Rain")
    mod = _make_module()
    coord = MagicMock()
    entity = RainSensor(inp, mod, coord, 0)
    assert entity.is_on is False
    assert entity.unique_id == "Mod_MOD-1_rain"


def test_input_switch_push_inherits_translation_key() -> None:
    """The push subclass keeps the input_switch translation key."""
    assert class_attr(InputSwitchPush, "_attr_translation_key") == "input_switch"
    # Verify it inherits from HbtnBinSensor through InputSwitch
    assert issubclass(InputSwitchPush, HbtnBinSensor)
