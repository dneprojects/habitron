"""Tests for the Habitron text platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from unittest.mock import MagicMock

from custom_components.habitron.text import EKeySensorFngr, EKeySensorUsr

from .conftest import class_attr


async def test_text_setup(setup_integration: MockConfigEntry) -> None:
    """The text platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_keys_set() -> None:
    """eKey entities expose translation keys for icons."""
    assert class_attr(EKeySensorUsr, "_attr_translation_key") == "ekey_user"
    assert class_attr(EKeySensorFngr, "_attr_translation_key") == "ekey_finger"


def _make_text_module() -> MagicMock:
    """Build a stub module with sensors + ids for the text-platform entities."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    sensor = MagicMock()
    sensor.value = 0
    mod.sensors = {0: sensor}
    mod.ids = [MagicMock(name="user0"), MagicMock(name="user1")]
    mod.ids[0].name = "Alice"
    mod.ids[1].name = "Bob"
    return mod


def test_ekey_user_unique_id_and_initial_state() -> None:
    """EKeySensorUsr has a stable unique id and starts at 'None'."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorUsr(mod, 0, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_ekey_ident"
    assert entity._attr_name == "Identifier Name"
    assert entity._attr_native_value == "None"


def test_ekey_user_resolves_id_to_user_name() -> None:
    """A positive in-range identifier value maps to its user name."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorUsr(mod, 0, coord, 0)
    entity.async_write_ha_state = MagicMock()
    mod.sensors[0].value = 1
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "Alice"


def test_ekey_user_zero_is_none() -> None:
    """Identifier 0 reports as the literal string 'None'."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorUsr(mod, 0, coord, 0)
    entity.async_write_ha_state = MagicMock()
    mod.sensors[0].value = 0
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "None"


def test_ekey_user_255_is_error() -> None:
    """Identifier sentinel 255 reports as 'Error'."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorUsr(mod, 0, coord, 0)
    entity.async_write_ha_state = MagicMock()
    mod.sensors[0].value = 255
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "Error"


def test_ekey_user_disabled_user_shown_with_suffix() -> None:
    """A negative identifier reports as user name + '-disabled' suffix."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorUsr(mod, 0, coord, 0)
    entity.async_write_ha_state = MagicMock()
    mod.sensors[0].value = -1
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "Alice-disabled"


def test_ekey_user_out_of_range_is_unknown() -> None:
    """An identifier outside the ids list reports as 'Unknown'."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorUsr(mod, 0, coord, 0)
    entity.async_write_ha_state = MagicMock()
    mod.sensors[0].value = 99
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "Unknown"


def test_ekey_fngr_unique_id_and_initial_state() -> None:
    """EKeySensorFngr has the fngr-prefixed unique id and starts at 'None'."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorFngr(mod, 0, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_ekey_fngr_ident"
    assert entity._attr_name == "Finger Name"
    assert entity._attr_native_value == "None"


def test_ekey_fngr_decodes_german_finger_names() -> None:
    """The finger value maps to a German finger name."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorFngr(mod, 0, coord, 0)
    entity.async_write_ha_state = MagicMock()
    mod.sensors[0].value = 1
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "Kleiner Finger links"
    mod.sensors[0].value = 5
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "Daumen links"
    mod.sensors[0].value = 10
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "Kleiner Finger rechts"


def test_ekey_fngr_zero_is_none() -> None:
    """Finger sentinel 0 reports as 'None'."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorFngr(mod, 0, coord, 0)
    entity.async_write_ha_state = MagicMock()
    mod.sensors[0].value = 0
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "None"


def test_ekey_fngr_255_is_error() -> None:
    """Finger sentinel 255 reports as 'Error'."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorFngr(mod, 0, coord, 0)
    entity.async_write_ha_state = MagicMock()
    mod.sensors[0].value = 255
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "Error"


def test_ekey_fngr_unknown_for_out_of_range() -> None:
    """Finger values outside 1–10 report as 'Unknown'."""
    mod = _make_text_module()
    coord = MagicMock()
    entity = EKeySensorFngr(mod, 0, coord, 0)
    entity.async_write_ha_state = MagicMock()
    mod.sensors[0].value = 99
    entity._handle_coordinator_update()
    assert entity._attr_native_value == "Unknown"
