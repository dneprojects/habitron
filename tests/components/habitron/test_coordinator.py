"""Tests for the Habitron coordinator."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.habitron.coordinator import HbtnCoordinator


def _make_comm(hass: HomeAssistant, interval: int = 5) -> MagicMock:
    """Build a stub for ``HbtnComm`` carrying just what the coordinator reads."""
    comm = MagicMock()
    comm._config = MagicMock()
    comm._config.data = {"update_interval": interval}
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


async def test_set_update_interval(hass: HomeAssistant) -> None:
    """``set_update_interval`` updates both the coordinator and the comm flag."""
    comm = _make_comm(hass, interval=5)
    coord = HbtnCoordinator(hass, MagicMock(), comm)
    coord.set_update_interval(12, updates=False)
    assert coord.update_interval == timedelta(seconds=12)
    assert comm.update_suspended is True


async def test_coordinator_always_update(hass: HomeAssistant) -> None:
    """``always_update`` is True so the heartbeat fans out on every tick."""
    comm = _make_comm(hass)
    coord = HbtnCoordinator(hass, MagicMock(), comm)
    assert coord.always_update is True


async def test_coordinator_uses_configured_interval(hass: HomeAssistant) -> None:
    """The constructor picks up the configured update interval."""
    comm = _make_comm(hass, interval=7)
    coord = HbtnCoordinator(hass, MagicMock(), comm)
    assert coord.update_interval == timedelta(seconds=7)
