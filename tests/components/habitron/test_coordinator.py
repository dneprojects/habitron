"""Tests for the Habitron coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.habitron.const import SCAN_INTERVAL
from custom_components.habitron.coordinator import HbtnCoordinator


def _make_comm(hass: HomeAssistant) -> MagicMock:
    """Build a stub for ``HbtnComm`` carrying just what the coordinator reads."""
    comm = MagicMock()
    comm._config = MagicMock()
    comm.update_suspended = False
    comm.async_system_update = AsyncMock(return_value=None)
    return comm


async def test_coordinator_normal_update(hass: HomeAssistant) -> None:
    """``_async_update_data`` returns None and forwards to comm."""
    comm = _make_comm(hass)
    coord = HbtnCoordinator(hass, MagicMock(), comm)
    result = await coord._async_update_data()
    assert result is None
    comm.async_system_update.assert_awaited_once()


async def test_coordinator_timeout_raises_update_failed(
    hass: HomeAssistant,
) -> None:
    """A timeout in ``async_system_update`` is wrapped in ``UpdateFailed``."""
    comm = _make_comm(hass)
    comm.async_system_update.side_effect = TimeoutError("hub silent")
    coord = HbtnCoordinator(hass, MagicMock(), comm)
    with pytest.raises(UpdateFailed, match="Timeout"):
        await coord._async_update_data()


async def test_coordinator_always_update(hass: HomeAssistant) -> None:
    """``always_update`` is True so the heartbeat fans out on every tick."""
    comm = _make_comm(hass)
    coord = HbtnCoordinator(hass, MagicMock(), comm)
    assert coord.always_update is True


async def test_coordinator_uses_fixed_scan_interval(hass: HomeAssistant) -> None:
    """The coordinator's interval is the integration's hard-coded SCAN_INTERVAL."""
    comm = _make_comm(hass)
    coord = HbtnCoordinator(hass, MagicMock(), comm)
    assert coord.update_interval == SCAN_INTERVAL


async def test_async_setup_runs_first_refresh(hass: HomeAssistant) -> None:
    """``_async_setup`` delegates to ``_async_update_data``."""
    comm = _make_comm(hass)
    coord = HbtnCoordinator(hass, MagicMock(), comm)
    await coord._async_setup()
    comm.async_system_update.assert_awaited()


async def test_coordinator_network_error_raises_update_failed(
    hass: HomeAssistant,
) -> None:
    """An OSError in ``async_system_update`` is wrapped in ``UpdateFailed``."""
    comm = _make_comm(hass)
    comm.async_system_update.side_effect = OSError("dns down")
    coord = HbtnCoordinator(hass, MagicMock(), comm)
    with pytest.raises(UpdateFailed, match="Network error"):
        await coord._async_update_data()
