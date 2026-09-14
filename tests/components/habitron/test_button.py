"""Tests for the Habitron button platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock

from habitron_client import HbtnCommand, Logic, Module, Router, SmartController

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
from homeassistant.core import HomeAssistant


def _hub_coord() -> MagicMock:
    coordinator = MagicMock()
    coordinator.uid = "HUB-1"
    coordinator.comm = MagicMock()
    for method in (
        "async_call_coll_command",
        "async_call_dir_command",
        "async_call_vis_command",
        "module_restart",
        "restart_fwd_tbl",
        "async_inc_dec_counter",
        "async_power_cycle_channel",
    ):
        setattr(coordinator.comm, method, AsyncMock())
    coordinator.restart = AsyncMock()
    coordinator.reboot = AsyncMock()
    coordinator.router = Router(uid="ROUTER-1")  # id defaults to 100
    coordinator.ws_provider = None
    return coordinator


def _module() -> Module:
    return Module(uid="MOD-1", addr=105, typ=b"\x01\x02", name="SC")


async def test_coll_cmd_button() -> None:
    """A collective command button calls the router collective command."""
    coordinator = _hub_coord()
    entity = CollCmdButton(HbtnCommand(name="All off", nmbr=5), coordinator)
    assert entity.unique_id == "HUB-1_collective_command_5"
    await entity.async_press()
    coordinator.comm.async_call_coll_command.assert_awaited_with(5)


async def test_dir_cmd_button() -> None:
    """A direct command button targets the module address."""
    coordinator = _hub_coord()
    entity = DirCmdButton(HbtnCommand(name="Scene", nmbr=2), _module(), coordinator)
    assert entity.unique_id == "MOD-1_direct_command_2"
    await entity.async_press()
    coordinator.comm.async_call_dir_command.assert_awaited_with(105, 2)


async def test_vis_cmd_button() -> None:
    """A visualization command button decodes hi/lo and targets the module."""
    coordinator = _hub_coord()
    entity = VisCmdButton(HbtnCommand(name="Vis", nmbr=258), _module(), coordinator)
    assert entity._attr_name == "VisCmd 1/2: Vis"
    await entity.async_press()
    coordinator.comm.async_call_vis_command.assert_awaited_with(105, 258)


async def test_restart_button_module_and_router() -> None:
    """Restart targets the module (raddr) or the router (0)."""
    coordinator = _hub_coord()
    mod_btn = RestartButton(_module(), coordinator)
    await mod_btn.async_press()
    coordinator.comm.module_restart.assert_awaited_with(5)  # 105 - 100
    rt_btn = RestartButton(coordinator.router, coordinator)
    await rt_btn.async_press()
    coordinator.comm.module_restart.assert_awaited_with(0)


async def test_count_up_down_buttons() -> None:
    """Counter buttons increment (1) / decrement (2) the counter."""
    coordinator = _hub_coord()
    logic = Logic(name="Cnt", nmbr=0, idx=0, type=5)
    up = CountUpButton(logic, _module(), coordinator)
    await up.async_press()
    coordinator.comm.async_inc_dec_counter.assert_awaited_with(105, 1, 1)
    down = CountDownButton(logic, _module(), coordinator)
    await down.async_press()
    coordinator.comm.async_inc_dec_counter.assert_awaited_with(105, 1, 2)


async def test_router_restart_buttons() -> None:
    """Router/hub maintenance buttons call the right commands."""
    coordinator = _hub_coord()
    await RestartFwdTableButton(coordinator.router, coordinator).async_press()
    coordinator.comm.restart_fwd_tbl.assert_awaited()
    await RestartAllButton(coordinator.router, coordinator).async_press()
    coordinator.comm.module_restart.assert_awaited_with(0xFF)
    await RestartHubButton(coordinator).async_press()
    coordinator.restart.assert_awaited_with(coordinator.router.id)
    await RebootHubButton(coordinator).async_press()
    coordinator.reboot.assert_awaited()


async def test_power_cycle_button() -> None:
    """The power-cycle button cycles the given router channel."""
    coordinator = _hub_coord()
    entity = ResetChannelPowerButton(coordinator.router, coordinator, 3)
    assert entity.unique_id == "ROUTER-1_power_cycle_3"
    await entity.async_press()
    coordinator.comm.async_power_cycle_channel.assert_awaited_with(3)


async def test_speech_button_sends_activate() -> None:
    """The speech button sends a voice-activate request over the websocket."""
    coordinator = _hub_coord()
    ws_connection = MagicMock()
    satellite = MagicMock()
    satellite.recognition_disabled = False
    satellite.entity_id = "assist_satellite.touch"
    provider = MagicMock()
    provider.active_ws_connections = {"touch_1": ws_connection}
    provider.assist_satellites = {"touch_1": satellite}
    coordinator.ws_provider = provider

    module = SmartController(uid="MOD-T", addr=104, typ=b"\x01\x04", name="Touch")
    module.stream_name = "touch_1"
    entity = SpeechButton(module, coordinator)
    await entity.async_press()
    ws_connection.send_message.assert_called_with(
        {
            "type": "habitron/voice_activate_request",
            "payload": {"entity_id": "assist_satellite.touch"},
        }
    )


async def test_async_setup_entry_emits_buttons(hass: HomeAssistant) -> None:
    """Setup emits module + router + hub maintenance buttons."""
    module = _module()
    module.dir_commands = [HbtnCommand(name="Scene", nmbr=1)]
    module.vis_commands = [HbtnCommand(name="Vis", nmbr=2)]
    module.logic = [Logic(name="Cnt", nmbr=0, idx=0, type=5)]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    router.coll_commands = [HbtnCommand(name="All off", nmbr=5)]
    coordinator = _hub_coord()
    coordinator.router = router
    entry = MagicMock()
    entry.runtime_data = coordinator

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, DirCmdButton) for e in added)
    assert any(isinstance(e, VisCmdButton) for e in added)
    assert any(isinstance(e, CountUpButton) for e in added)
    assert any(isinstance(e, CollCmdButton) for e in added)
    assert any(isinstance(e, RestartHubButton) for e in added)
    assert any(isinstance(e, ResetChannelPowerButton) for e in added)
