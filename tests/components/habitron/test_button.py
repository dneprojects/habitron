"""Tests for the Habitron button platform.

Smoke test + per-class translation_key check; extend with button-press
service tests using ``hass.services.async_call("button", "press", ...)``.
"""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.button import (
    CountDownButton,
    CountUpButton,
    RebootHubButton,
    ResetChannelPowerButton,
    RestartAllButton,
    RestartButton,
    RestartFwdTableButton,
    RestartHubButton,
    SpeechButton,
)

from .conftest import class_attr


async def test_button_setup(setup_integration: MockConfigEntry) -> None:
    """The platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_keys_set() -> None:
    """Every button class exposes the icon translation key."""
    assert class_attr(RestartButton, "_attr_translation_key") == "module_reset"
    assert class_attr(RestartFwdTableButton, "_attr_translation_key") == "restart_fwd_table"
    assert class_attr(RestartAllButton, "_attr_translation_key") == "router_reset_all"
    assert class_attr(RestartHubButton, "_attr_translation_key") == "hub_restart"
    assert class_attr(RebootHubButton, "_attr_translation_key") == "hub_reboot"
    assert class_attr(CountUpButton, "_attr_translation_key") == "count_up"
    assert class_attr(CountDownButton, "_attr_translation_key") == "count_down"
    assert class_attr(ResetChannelPowerButton, "_attr_translation_key") == "power_cycle"
    assert class_attr(SpeechButton, "_attr_translation_key") == "voice_input"
