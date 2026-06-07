"""Tests for the Habitron text platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.text import EKeySensorFngr, EKeySensorUsr

from .conftest import class_attr


async def test_text_setup(setup_integration: MockConfigEntry) -> None:
    """The text platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_keys_set() -> None:
    """eKey entities expose translation keys for icons."""
    assert class_attr(EKeySensorUsr, "_attr_translation_key") == "ekey_user"
    assert class_attr(EKeySensorFngr, "_attr_translation_key") == "ekey_finger"
