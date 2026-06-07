"""Tests for the Habitron media_player platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.media_player import HbtnMediaPlayer

from .conftest import class_attr


async def test_media_player_setup(setup_integration: MockConfigEntry) -> None:
    """The media_player platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_key() -> None:
    """HbtnMediaPlayer uses the icon-translation key."""
    assert class_attr(HbtnMediaPlayer, "_attr_translation_key") == "habitron_speaker"
