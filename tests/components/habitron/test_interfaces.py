"""Tests for the Habitron interfaces descriptor helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from custom_components.habitron.interfaces import (
    TYPE_DIAG,
    AreaDescriptor,
    CLedDescriptor,
    CmdDescriptor,
    CovDescriptor,
    IfDescriptor,
    LgcDescriptor,
    StateDescriptor,
)


def test_type_diag_constant_value() -> None:
    """TYPE_DIAG keeps its documented sentinel value."""
    assert TYPE_DIAG == 10


def test_if_descriptor_stores_scalar_value() -> None:
    """A scalar value is stored directly on the descriptor."""
    desc = IfDescriptor("Sensor", 3, 1, 42, iarea=5)
    assert desc.name == "Sensor"
    assert desc.nmbr == 3
    assert desc.type == 1
    assert desc.value == 42
    assert desc.area == 5


def test_if_descriptor_skips_value_for_list_ivalue() -> None:
    """A list ``ivalue`` is *not* assigned to ``value`` on the base class."""
    desc = IfDescriptor("LedList", 0, 1, [1, 2, 3])
    # Base class skips the assignment; ``value`` should never have been set.
    assert not hasattr(desc, "value")


def test_if_descriptor_register_and_remove_callback() -> None:
    """register/remove_callback toggles the internal callback set."""
    desc = IfDescriptor("X", 0, 1, 0)
    cb = MagicMock()
    desc.register_callback(cb)
    assert cb in desc._callbacks
    desc.remove_callback(cb)
    assert cb not in desc._callbacks


def test_if_descriptor_remove_unregistered_callback_is_silent() -> None:
    """remove_callback on a never-registered callback does not raise."""
    desc = IfDescriptor("X", 0, 1, 0)
    desc.remove_callback(lambda: None)  # no-op


def test_if_descriptor_set_name_updates_name() -> None:
    """set_name overwrites the cached name."""
    desc = IfDescriptor("Old", 0, 1, 0)
    desc.set_name("New")
    assert desc.name == "New"


async def test_handle_upd_event_zero_args_dispatches_callbacks() -> None:
    """A zero-arg event calls every registered callback without arguments."""
    desc = IfDescriptor("X", 0, 1, 0)
    cb1 = MagicMock()
    cb2 = MagicMock()
    desc.register_callback(cb1)
    desc.register_callback(cb2)
    await desc.handle_upd_event()
    cb1.assert_called_once_with()
    cb2.assert_called_once_with()


async def test_handle_upd_event_one_arg_dispatches_single_value() -> None:
    """A 1-arg event forwards the value to every callback."""
    desc = IfDescriptor("X", 0, 1, 0)
    cb = MagicMock()
    desc.register_callback(cb)
    await desc.handle_upd_event(7)
    cb.assert_called_once_with(7)


async def test_handle_upd_event_two_args_dispatches_pair() -> None:
    """A 2-arg event forwards the pair to every callback."""
    desc = IfDescriptor("X", 0, 1, 0)
    cb = MagicMock()
    desc.register_callback(cb)
    await desc.handle_upd_event("a", "b")
    cb.assert_called_once_with("a", "b")


async def test_handle_upd_event_three_or_more_args_uses_first_three() -> None:
    """Three-plus arguments dispatch only the first three positional values."""
    desc = IfDescriptor("X", 0, 1, 0)
    cb = MagicMock()
    desc.register_callback(cb)
    await desc.handle_upd_event(1, 2, 3, 4, 5)
    cb.assert_called_once_with(1, 2, 3)


def test_cled_descriptor_stores_list_value() -> None:
    """CLedDescriptor exposes the full RGB(A) value list."""
    cled = CLedDescriptor("Color 1", 1, 0, [1, 200, 100, 50])
    assert cled.value == [1, 200, 100, 50]
    assert cled.name == "Color 1"
    assert cled.nmbr == 1


def test_cov_descriptor_stores_tilt() -> None:
    """CovDescriptor adds the tilt position to a base descriptor."""
    cov = CovDescriptor("Sh 1", 0, 1, 50, 25, iarea=3)
    assert cov.value == 50
    assert cov.tilt == 25
    assert cov.area == 3


def test_cmd_descriptor_zero_defaults() -> None:
    """CmdDescriptor is a name+number pair with zero type/value/area."""
    cmd = CmdDescriptor("All off", 7)
    assert cmd.name == "All off"
    assert cmd.nmbr == 7
    assert cmd.type == 0
    assert cmd.value == 0
    assert cmd.area == 0


def test_area_descriptor_get_name_and_id() -> None:
    """AreaDescriptor exposes the area name and a slugified id."""
    area = AreaDescriptor("Living Room", 4)
    assert area.get_name() == "Living Room"
    assert area.get_name_id() == "living_room"


def test_lgc_descriptor_carries_separate_idx() -> None:
    """LgcDescriptor keeps a distinct ``idx`` next to the sequence number."""
    lgc = LgcDescriptor("Counter", 2, 5, 1, 12)
    assert lgc.idx == 2
    assert lgc.nmbr == 5
    assert lgc.name == "Counter"
    assert lgc.type == 1
    assert lgc.value == 12


def test_state_descriptor_carries_separate_idx() -> None:
    """StateDescriptor keeps a distinct ``idx`` for the mode/flag."""
    state = StateDescriptor("Flag 1", 1, 3, 1, 0)
    assert state.idx == 1
    assert state.nmbr == 3
    assert state.value == 0


def test_callback_set_dedupes_repeated_registers() -> None:
    """register_callback dedupes — the same callback is only stored once."""
    desc = IfDescriptor("X", 0, 1, 0)
    cb = MagicMock()
    desc.register_callback(cb)
    desc.register_callback(cb)
    assert len(desc._callbacks) == 1


def test_handle_upd_event_dispatches_synchronously() -> None:
    """``handle_upd_event`` is awaitable but dispatches synchronously."""
    desc = IfDescriptor("X", 0, 1, 0)
    cb = MagicMock()
    desc.register_callback(cb)
    # Using asyncio.run() avoids the pytest-asyncio fixture for parity with
    # how event-bus callbacks fire — synchronous dispatch wrapped in a
    # coroutine.
    asyncio.run(desc.handle_upd_event(1))
    cb.assert_called_once_with(1)
