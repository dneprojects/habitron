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


from unittest.mock import AsyncMock, MagicMock  # noqa: E402


def _make_module_for_button() -> MagicMock:
    """Build a stub HbtnModule with async hooks used by Habitron buttons."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.b_uid = "HUB-1"
    mod.mod_addr = 105
    mod.async_reset = AsyncMock()
    mod.async_restart_fwd_tbl = AsyncMock()
    mod.comm.async_inc_dec_counter = AsyncMock()
    return mod


def _make_router() -> MagicMock:
    """Build a stub HbtnRouter with the methods buttons call into."""
    rt = MagicMock()
    rt.uid = "RT-1"
    rt.b_uid = "HUB-1"
    rt.id = 1
    rt.async_reset_all_modules = AsyncMock()
    rt.smhub.restart = AsyncMock()
    rt.smhub.reboot = AsyncMock()
    rt.comm.async_power_cycle_channel = AsyncMock()
    return rt


async def test_restart_button_press_calls_module_reset() -> None:
    """RestartButton.async_press forwards to module.async_reset."""
    mod = _make_module_for_button()
    btn = RestartButton(mod)
    await btn.async_press()
    mod.async_reset.assert_awaited()


async def test_restart_fwd_table_button_press() -> None:
    """RestartFwdTableButton.async_press forwards to module.async_restart_fwd_tbl."""
    mod = _make_module_for_button()
    btn = RestartFwdTableButton(mod)
    await btn.async_press()
    mod.async_restart_fwd_tbl.assert_awaited()


async def test_restart_all_button_press() -> None:
    """RestartAllButton.async_press triggers router.async_reset_all_modules."""
    rt = _make_router()
    btn = RestartAllButton(rt)
    await btn.async_press()
    rt.async_reset_all_modules.assert_awaited()


async def test_restart_hub_button_press_routes_through_smhub() -> None:
    """RestartHubButton.async_press calls smhub.restart with the router id."""
    rt = _make_router()
    btn = RestartHubButton(rt)
    await btn.async_press()
    rt.smhub.restart.assert_awaited_with(rt.id)


async def test_reboot_hub_button_press_calls_smhub_reboot() -> None:
    """RebootHubButton.async_press calls smhub.reboot."""
    rt = _make_router()
    btn = RebootHubButton(rt)
    await btn.async_press()
    rt.smhub.reboot.assert_awaited()


async def test_count_up_button_press_forwards_arguments() -> None:
    """CountUpButton.async_press calls async_inc_dec_counter with op=1."""
    mod = _make_module_for_button()
    counter = MagicMock()
    counter.nmbr = 2
    counter.name = "Visitors"
    btn = CountUpButton(counter, mod)
    await btn.async_press()
    mod.comm.async_inc_dec_counter.assert_awaited_with(105, 3, 1)


async def test_count_down_button_press_forwards_arguments() -> None:
    """CountDownButton.async_press calls async_inc_dec_counter with op=2."""
    mod = _make_module_for_button()
    counter = MagicMock()
    counter.nmbr = 1
    counter.name = "Visitors"
    btn = CountDownButton(counter, mod)
    await btn.async_press()
    mod.comm.async_inc_dec_counter.assert_awaited_with(105, 2, 2)


async def test_reset_channel_power_button_press_forwards_channel() -> None:
    """ResetChannelPowerButton calls async_power_cycle_channel with channel."""
    rt = _make_router()
    btn = ResetChannelPowerButton(rt, 3)
    await btn.async_press()
    rt.comm.async_power_cycle_channel.assert_awaited_with(rt.id, 3)


def test_restart_hub_button_unique_id_contains_hub_uid() -> None:
    """The unique id is namespaced by the hub's b_uid."""
    rt = _make_router()
    btn = RestartHubButton(rt)
    assert btn.unique_id == "Hub_HUB-1_restart"


def test_reboot_hub_button_unique_id_contains_hub_uid() -> None:
    """The reboot button is namespaced by the hub's b_uid."""
    rt = _make_router()
    btn = RebootHubButton(rt)
    assert btn.unique_id == "Hub_HUB-1_reboot"
