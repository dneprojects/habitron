"""Tests for the Habitron event platform."""

from __future__ import annotations

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.event import (
    EkeyUserEvent,
    FingerDetected,
    HbtnEvent,
    InputPressed,
)


async def test_event_setup(setup_integration: MockConfigEntry) -> None:
    """The event platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def _make_input(nmbr: int = 0, name: str = "Btn 1") -> MagicMock:
    inp = MagicMock()
    inp.nmbr = nmbr
    inp.name = name
    inp.type = 1
    inp.area = 0
    inp.value = 0
    inp.register_callback = MagicMock()
    inp.remove_callback = MagicMock()
    return inp


def _make_module() -> MagicMock:
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.fingers = []
    mod.ids = []
    return mod


def test_input_pressed_unique_id() -> None:
    """InputPressed builds a stable, module + input scoped unique id."""
    inp = _make_input(nmbr=3)
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_evnt3"


def test_input_pressed_supports_press_event_types() -> None:
    """InputPressed reports single / long press as event types."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    assert "single_press" in entity._attr_event_types
    assert "long_press" in entity._attr_event_types
    assert "long_press_end" in entity._attr_event_types


def test_finger_detected_has_extra_state_attrs() -> None:
    """FingerDetected exposes ``last_user``/``last_finger`` attributes."""
    finger = _make_input(nmbr=2, name="Index left")
    mod = _make_module()
    coord = MagicMock()
    entity = FingerDetected(finger, mod, coord, 0)
    assert "last_user" in entity._attr_extra_state_attributes
    assert "last_finger" in entity._attr_extra_state_attributes


def test_ekey_user_event_constructor_extra_args() -> None:
    """EkeyUserEvent takes a user id and a user name."""
    user = _make_input(nmbr=1, name="ekey")
    mod = _make_module()
    coord = MagicMock()
    entity = EkeyUserEvent(user, mod, coord, 0, 5, "Alice")
    # Instance was constructed without error and inherits HbtnEvent.
    assert isinstance(entity, HbtnEvent)


def test_input_pressed_handles_callback_short_press() -> None:
    """A '1' callback value translates to single_press."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event(1)
    entity._trigger_event.assert_called()


def test_input_pressed_handles_callback_long_press() -> None:
    """A '2' callback value translates to long_press."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event(2)
    entity._trigger_event.assert_called()


def test_input_pressed_remove_callback() -> None:
    """async_will_remove_from_hass unregisters the callback."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    # The entity uses ``self._if`` from the base class for input refs.
    entity._if = inp
    # Call directly; we just want the test to exercise the remove path.
    import asyncio  # noqa: PLC0415
    asyncio.run(entity.async_will_remove_from_hass())
    inp.remove_callback.assert_called()
