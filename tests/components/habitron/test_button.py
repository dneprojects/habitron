"""Tests for the Habitron button platform.

Smoke test + per-class translation_key check; extend with button-press
service tests using ``hass.services.async_call("button", "press", ...)``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.button import (
    CollCmdButton,
    CountDownButton,
    CountUpButton,
    DirCmdButton,
    RebootHubButton,
    ResetChannelPowerButton,
    RestartAllButton,
    RestartButton,
    RestartFwdTableButton,
    RestartHubButton,
    SpeechButton,
    VisCmdButton,
    async_setup_entry,
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


def test_coll_cmd_button_device_info_and_name_and_unique_id() -> None:
    """CollCmdButton wires up device_info, name and unique id."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.b_uid = "HUB-1"
    mod.id = 7
    mod.comm = MagicMock()
    mod.comm.async_call_coll_command = AsyncMock()
    coll = MagicMock()
    coll.nmbr = 4
    coll.name = "All off"
    btn = CollCmdButton(coll, mod)
    assert "All off" in btn.name
    assert btn.unique_id == "Mod_HUB-1_ccmd4"
    assert ("habitron", "MOD-1") in btn.device_info["identifiers"]


async def test_coll_cmd_button_press_forwards() -> None:
    """CollCmdButton.async_press calls async_call_coll_command."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.b_uid = "HUB-1"
    mod.id = 7
    mod.comm = MagicMock()
    mod.comm.async_call_coll_command = AsyncMock()
    coll = MagicMock()
    coll.nmbr = 1
    coll.name = "All off"
    btn = CollCmdButton(coll, mod)
    await btn.async_press()
    mod.comm.async_call_coll_command.assert_awaited_with(7, 1)


def test_dir_cmd_button_device_info_and_name() -> None:
    """DirCmdButton wires up device_info and name."""
    mod = _make_module_for_button()
    mod.comm.async_call_dir_command = AsyncMock()
    dir_cmd = MagicMock()
    dir_cmd.nmbr = 3
    dir_cmd.name = "Open garage"
    btn = DirCmdButton(dir_cmd, mod)
    assert "Open garage" in btn.name
    assert btn.unique_id == "Mod_MOD-1_dcmd3"
    assert ("habitron", "MOD-1") in btn.device_info["identifiers"]


async def test_dir_cmd_button_press_forwards() -> None:
    """DirCmdButton.async_press calls async_call_dir_command with mod_addr + nmbr."""
    mod = _make_module_for_button()
    mod.comm.async_call_dir_command = AsyncMock()
    dir_cmd = MagicMock()
    dir_cmd.nmbr = 5
    dir_cmd.name = "Open garage"
    btn = DirCmdButton(dir_cmd, mod)
    await btn.async_press()
    mod.comm.async_call_dir_command.assert_awaited_with(105, 5)


def test_vis_cmd_button_decodes_hi_lo_in_name() -> None:
    """VisCmdButton name encodes the high/low byte of vis_cmd.nmbr."""
    mod = _make_module_for_button()
    mod.comm.async_call_vis_command = AsyncMock()
    vis_cmd = MagicMock()
    vis_cmd.nmbr = 512 + 7  # high 2, low 7
    vis_cmd.name = "Page 2/7"
    btn = VisCmdButton(vis_cmd, mod)
    assert "2/7" in btn.name
    assert btn.unique_id == "Mod_MOD-1_vcmd519"
    assert ("habitron", "MOD-1") in btn.device_info["identifiers"]


async def test_vis_cmd_button_press_forwards() -> None:
    """VisCmdButton.async_press calls async_call_vis_command with the encoded nmbr."""
    mod = _make_module_for_button()
    mod.comm.async_call_vis_command = AsyncMock()
    vis_cmd = MagicMock()
    vis_cmd.nmbr = 8
    vis_cmd.name = "P 0/8"
    btn = VisCmdButton(vis_cmd, mod)
    await btn.async_press()
    mod.comm.async_call_vis_command.assert_awaited_with(105, 8)


def test_count_up_button_device_info_and_name() -> None:
    """CountUpButton wires up device_info and the cached name."""
    mod = _make_module_for_button()
    counter = MagicMock()
    counter.nmbr = 0
    counter.name = "Cars"
    btn = CountUpButton(counter, mod)
    assert btn.name == "Count up 1: Cars"
    assert ("habitron", "MOD-1") in btn.device_info["identifiers"]


def test_count_down_button_device_info_and_name() -> None:
    """CountDownButton wires up device_info and the cached name."""
    mod = _make_module_for_button()
    counter = MagicMock()
    counter.nmbr = 0
    counter.name = "Cars"
    btn = CountDownButton(counter, mod)
    assert btn.name == "Count down 1: Cars"
    assert ("habitron", "MOD-1") in btn.device_info["identifiers"]


def test_restart_button_device_info_links_module() -> None:
    """RestartButton.device_info points at the module uid."""
    mod = _make_module_for_button()
    btn = RestartButton(mod)
    assert ("habitron", "MOD-1") in btn.device_info["identifiers"]


def test_restart_fwd_table_button_device_info_links_module() -> None:
    """RestartFwdTableButton.device_info points at the module uid."""
    mod = _make_module_for_button()
    btn = RestartFwdTableButton(mod)
    assert ("habitron", "MOD-1") in btn.device_info["identifiers"]


def test_restart_all_button_device_info_links_router() -> None:
    """RestartAllButton.device_info points at the router uid."""
    rt = _make_router()
    btn = RestartAllButton(rt)
    assert ("habitron", "RT-1") in btn.device_info["identifiers"]


def test_restart_hub_button_device_info_links_hub() -> None:
    """RestartHubButton.device_info points at the hub b_uid."""
    rt = _make_router()
    btn = RestartHubButton(rt)
    assert ("habitron", "HUB-1") in btn.device_info["identifiers"]


def test_reboot_hub_button_device_info_links_hub() -> None:
    """RebootHubButton.device_info points at the hub b_uid."""
    rt = _make_router()
    btn = RebootHubButton(rt)
    assert ("habitron", "HUB-1") in btn.device_info["identifiers"]


def test_reset_channel_power_button_device_info_and_name() -> None:
    """ResetChannelPowerButton exposes name and device_info."""
    rt = _make_router()
    btn = ResetChannelPowerButton(rt, 2)
    assert "channel 2" in btn.name
    assert ("habitron", "RT-1") in btn.device_info["identifiers"]


def _make_speech_module(stream_name: str = "touch_1") -> MagicMock:
    mod = MagicMock()
    mod.uid = "MOD-SP"
    mod.stream_name = stream_name
    mod.assist_entity_id = "assist_satellite.touch_1"
    provider = MagicMock()
    provider.active_ws_connections = {stream_name: MagicMock()}
    assist = MagicMock()
    assist.recognition_disabled = False
    provider.assist_satellites = {stream_name: assist}
    mod.comm.router.smhub.ws_provider = provider
    return mod


def test_speech_button_device_info_links_module() -> None:
    """SpeechButton.device_info points at the module uid."""
    mod = _make_speech_module()
    btn = SpeechButton(mod)
    assert ("habitron", "MOD-SP") in btn.device_info["identifiers"]


async def test_speech_button_press_sends_voice_activate_request() -> None:
    """SpeechButton.async_press sends a habitron/voice_activate_request message."""
    mod = _make_speech_module()
    ws_connection = mod.comm.router.smhub.ws_provider.active_ws_connections["touch_1"]
    btn = SpeechButton(mod)
    await btn.async_press()
    ws_connection.send_message.assert_called()
    call = ws_connection.send_message.call_args.args[0]
    assert call["type"] == "habitron/voice_activate_request"


async def test_speech_button_press_skips_when_recognition_disabled() -> None:
    """SpeechButton.async_press logs and skips when recognition is disabled."""
    mod = _make_speech_module()
    assist = mod.comm.router.smhub.ws_provider.assist_satellites["touch_1"]
    assist.recognition_disabled = True
    ws_connection = mod.comm.router.smhub.ws_provider.active_ws_connections["touch_1"]
    btn = SpeechButton(mod)
    await btn.async_press()
    ws_connection.send_message.assert_not_called()


async def test_speech_button_press_skips_when_no_active_ws() -> None:
    """SpeechButton.async_press logs and skips when no ws connection is active."""
    mod = _make_speech_module()
    mod.comm.router.smhub.ws_provider.active_ws_connections = {}
    btn = SpeechButton(mod)
    await btn.async_press()  # should log without raising


async def test_async_setup_entry_emits_button_set(hass) -> None:
    """async_setup_entry adds dir, vis, counter, speech, restart and hub buttons."""
    dir_cmd = MagicMock()
    dir_cmd.nmbr = 1
    dir_cmd.name = "DirCmd 1"
    vis_cmd = MagicMock()
    vis_cmd.nmbr = 2
    vis_cmd.name = "VisCmd 2"
    counter = MagicMock()
    counter.type = 5
    counter.nmbr = 0
    counter.name = "Cnt"

    from custom_components.habitron.module import SmartController  # noqa: PLC0415

    mod = MagicMock()
    mod.__class__ = SmartController  # so isinstance() narrows correctly
    mod.uid = "MOD-1"
    mod.b_uid = "HUB-1"
    mod.mod_addr = 105
    mod.id = 7
    mod.stream_name = "touch_1"
    mod.assist_entity_id = "assist_satellite.touch_1"
    mod.mod_type = "Smart Controller Touch"
    mod.dir_commands = [dir_cmd]
    mod.vis_commands = [vis_cmd]
    mod.logic = [counter]
    provider = MagicMock()
    provider.active_ws_connections = {"touch_1": MagicMock()}
    assist = MagicMock()
    assist.recognition_disabled = False
    provider.assist_satellites = {"touch_1": assist}
    mod.comm.router.smhub.ws_provider = provider

    coll_cmd = MagicMock()
    coll_cmd.nmbr = 1
    coll_cmd.name = "All"
    router = MagicMock()
    router.uid = "RT-1"
    router.b_uid = "HUB-1"
    router.modules = [mod]
    router.coll_commands = [coll_cmd]
    router.id = 1

    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    await async_setup_entry(hass, entry, lambda es: added.extend(es))
    assert any(isinstance(e, DirCmdButton) for e in added)
    assert any(isinstance(e, VisCmdButton) for e in added)
    assert any(isinstance(e, CountUpButton) for e in added)
    assert any(isinstance(e, CountDownButton) for e in added)
    assert any(isinstance(e, SpeechButton) for e in added)
    assert any(isinstance(e, RestartButton) for e in added)
    assert any(isinstance(e, CollCmdButton) for e in added)
    assert any(isinstance(e, RestartAllButton) for e in added)
    assert any(isinstance(e, RestartFwdTableButton) for e in added)
    assert any(isinstance(e, RestartHubButton) for e in added)
    assert any(isinstance(e, RebootHubButton) for e in added)
    assert any(isinstance(e, ResetChannelPowerButton) for e in added)
