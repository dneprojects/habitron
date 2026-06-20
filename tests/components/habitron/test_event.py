"""Tests for the Habitron event platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Finger, HbtnCommand, Input, Module, Router

from custom_components.habitron.event import (
    EkeyUserEvent,
    FingerDetected,
    InputPressed,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant


def _module(uid: str = "MOD-1", **kwargs) -> Module:
    return Module(uid=uid, addr=105, typ=b"\x01\x02", name="Mod", **kwargs)


# ---------------------------------------------------------------------------
# InputPressed
# ---------------------------------------------------------------------------


def test_input_pressed_fires_for_press_code() -> None:
    """A press code maps to the matching button event; the reset is ignored."""
    inp = Input(name="Btn", nmbr=0, type=1, value=0)
    entity = InputPressed(inp, _module(), 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()

    inp.value = 1  # single_press
    entity._handle_member_update()
    entity._trigger_event.assert_called_with("single_press")

    entity._trigger_event.reset_mock()
    inp.value = 0  # inactive reset -> ignored
    entity._handle_member_update()
    entity._trigger_event.assert_not_called()


async def test_input_pressed_listener_lifecycle() -> None:
    """The event entity subscribes/unsubscribes the input listener."""
    inp = Input(name="Btn", nmbr=0, type=1, value=0)
    entity = InputPressed(inp, _module(), 0)
    with patch(
        "homeassistant.components.event.EventEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    assert len(inp._listeners) == 1
    await entity.async_will_remove_from_hass()
    assert len(inp._listeners) == 0


# ---------------------------------------------------------------------------
# Fanekey finger events
# ---------------------------------------------------------------------------


def test_finger_detected_fires_with_user_and_finger() -> None:
    """FingerDetected fires the finger event with the raw user/finger."""
    finger = Finger(name="Finger", nmbr=0, type=2)
    entity = FingerDetected(finger, _module(), 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()

    finger.user = 5
    finger.value = 3
    entity._handle_member_update()
    entity._trigger_event.assert_called_with("finger", {"user": "5", "finger": "3"})
    assert entity.extra_state_attributes == {"last_user": 5, "last_finger": 3}


def test_finger_detected_disabled_user() -> None:
    """A finger value > 10 marks the user disabled (negated + offset)."""
    finger = Finger(name="Finger", nmbr=0, type=2)
    entity = FingerDetected(finger, _module(), 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()

    finger.user = 5
    finger.value = 131  # 131 - 128 = finger 3, user disabled
    entity._handle_member_update()
    entity._trigger_event.assert_called_with("finger", {"user": "-5", "finger": "3"})


def test_ekey_user_event_matches_user() -> None:
    """EkeyUserEvent fires a finger-named event for its own user only."""
    finger = Finger(name="Finger", nmbr=0, type=2)
    entity = EkeyUserEvent(finger, _module(), 0, 5, "Alice")
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    assert entity.unique_id == "Mod_MOD-1_u5"

    finger.user = 5
    finger.value = 3
    entity._handle_member_update()
    entity._trigger_event.assert_called_with("left_middle", {"finger_id": 3})

    entity._trigger_event.reset_mock()
    finger.user = 6  # different user -> no event
    entity._handle_member_update()
    entity._trigger_event.assert_not_called()


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_async_setup_entry_emits_events(hass: HomeAssistant) -> None:
    """Setup emits input-press events and ekey finger/user events."""
    btn_module = _module(uid="MOD-1")
    btn_module.inputs = [Input(name="Btn", nmbr=0, type=1, value=0)]
    ekey = Module(
        uid="MOD-EK", addr=106, typ=b"\x1e\x01", name="eKey", mod_type="Fanekey"
    )
    ekey.fingers = [Finger(name="Finger", nmbr=0, type=2)]
    ekey.ids = [HbtnCommand(name="Alice", nmbr=5)]
    router = Router(uid="ROUTER-1")
    router.modules = [btn_module, ekey]
    router.areas = []
    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    with patch("custom_components.habitron.event.er.async_get") as mock_get:
        mock_get.return_value.async_get_entity_id = MagicMock(return_value=None)
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, InputPressed) for e in added)
    assert any(isinstance(e, FingerDetected) for e in added)
    assert any(isinstance(e, EkeyUserEvent) for e in added)
