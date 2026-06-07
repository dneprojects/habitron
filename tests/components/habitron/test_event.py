"""Tests for the Habitron event platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_event_setup(setup_integration: MockConfigEntry) -> None:
    """The event platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None
