"""Tests for the Habitron update platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.update import HbtnModuleUpdate, SCTouchAppUpdate

from .conftest import class_attr


async def test_update_setup(setup_integration: MockConfigEntry) -> None:
    """The update platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_module_update_polls_for_firmware() -> None:
    """HbtnModuleUpdate keeps _attr_should_poll=True (firmware not via coord)."""
    assert class_attr(HbtnModuleUpdate, "_attr_should_poll") is True


def test_sc_touch_app_update_polls() -> None:
    """SCTouchAppUpdate polls for new firmware (no Coordinator binding)."""
    assert class_attr(SCTouchAppUpdate, "_attr_should_poll") is True
