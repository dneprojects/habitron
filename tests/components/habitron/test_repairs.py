"""Tests for the Habitron module-fault repair flow (repairs.py)."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Module, Router

from custom_components.habitron import repairs
from custom_components.habitron.repairs import ModuleFaultRepairFlow, _channel_and_peers
from homeassistant.core import HomeAssistant


def _module(uid: str = "MOD-1", name: str = "Mod", addr: int = 105) -> Module:
    """Build a v2 model module (mod_id = addr - router.id)."""
    return Module(uid=uid, addr=addr, typ=b"\x01\x02", name=name)


def _flow(hass: HomeAssistant) -> ModuleFaultRepairFlow:
    """Build a flow wired to a hass, with stub issue data."""
    flow = ModuleFaultRepairFlow(
        "module_fault_MOD-1", {"entry_id": "e", "module_uid": "MOD-1"}
    )
    flow.hass = hass
    return flow


# ---------------------------------------------------------------------------
# _channel_and_peers
# ---------------------------------------------------------------------------


def test_channel_and_peers_maps_module_to_channel() -> None:
    """The module's channel and the other modules on it are returned."""
    router = Router(uid="R", id=100)
    target = _module(uid="A", name="A", addr=105)  # mod_id 5
    peer = _module(uid="B", name="B", addr=107)  # mod_id 7, same channel
    router.modules = [target, peer]
    router.chan_list = [[5, 7], [], [], []]
    channel, peers = _channel_and_peers(router, target)
    assert channel == 1
    assert peers == ["B"]


def test_channel_and_peers_unknown_channel() -> None:
    """A module not present in any channel yields (None, [])."""
    router = Router(uid="R", id=100)
    target = _module(addr=105)
    router.modules = [target]
    router.chan_list = [[], [], [], []]
    assert _channel_and_peers(router, target) == (None, [])


# ---------------------------------------------------------------------------
# ModuleFaultRepairFlow
# ---------------------------------------------------------------------------


async def test_non_comm_fault_offers_and_runs_restart(hass: HomeAssistant) -> None:
    """A reachable fault routes to the restart step and restarts the module."""
    module = _module()
    module.health.value = 0x10  # F16 only -> module reachable
    smhub = MagicMock()
    smhub.comm.module_restart = AsyncMock()
    flow = _flow(hass)
    with patch.object(repairs, "_resolve_module", return_value=(smhub, module)):
        form = await flow.async_step_init()
        assert form["step_id"] == "confirm_restart"
        assert "F16: Fehler Leistungsteil" in form["description_placeholders"]["faults"]
        result = await flow.async_step_confirm_restart({})
    smhub.comm.module_restart.assert_awaited_once_with(module.addr)
    assert result["type"] == "create_entry"


async def test_comm_timeout_offers_and_runs_power_cycle(hass: HomeAssistant) -> None:
    """F1 routes to the power-cycle step, warns about peers, cycles the channel."""
    module = _module(addr=105)  # mod_id 5
    module.health.value = 0x01 | 0x10  # F1 dominates even with F16 present
    peer = _module(uid="MOD-2", name="Neighbor", addr=106)  # mod_id 6
    router = Router(uid="R", id=100)
    router.modules = [module, peer]
    router.chan_list = [[5, 6], [], [], []]
    smhub = MagicMock()
    smhub.router = router
    smhub.comm.async_power_cycle_channel = AsyncMock()
    flow = _flow(hass)
    with patch.object(repairs, "_resolve_module", return_value=(smhub, module)):
        form = await flow.async_step_init()
        assert form["step_id"] == "confirm_power_cycle"
        assert form["description_placeholders"]["channel"] == "1"
        assert "Neighbor" in form["description_placeholders"]["others"]
        result = await flow.async_step_confirm_power_cycle({})
    smhub.comm.async_power_cycle_channel.assert_awaited_once_with(1)
    assert result["type"] == "create_entry"


async def test_cleared_fault_completes_flow(hass: HomeAssistant) -> None:
    """If the fault already cleared, the flow completes so HA drops the issue."""
    module = _module()
    module.health.value = 0
    flow = _flow(hass)
    with patch.object(repairs, "_resolve_module", return_value=(MagicMock(), module)):
        result = await flow.async_step_init()
    assert result["type"] == "create_entry"


async def test_missing_module_aborts(hass: HomeAssistant) -> None:
    """An unresolvable module (hub unloaded / removed) aborts the flow."""
    flow = _flow(hass)
    with patch.object(repairs, "_resolve_module", return_value=None):
        result = await flow.async_step_init()
    assert result["type"] == "abort"
    assert result["reason"] == "module_unavailable"


async def test_power_cycle_unknown_channel_aborts(hass: HomeAssistant) -> None:
    """F1 on a module without a mapped channel aborts instead of guessing."""
    module = _module(addr=105)
    module.health.value = 0x01
    router = Router(uid="R", id=100)
    router.modules = [module]
    router.chan_list = [[], [], [], []]
    smhub = MagicMock()
    smhub.router = router
    flow = _flow(hass)
    with patch.object(repairs, "_resolve_module", return_value=(smhub, module)):
        result = await flow.async_step_init()
    assert result["type"] == "abort"
    assert result["reason"] == "channel_unknown"
