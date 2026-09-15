"""Tests for the Habitron coordinator."""

from unittest.mock import AsyncMock, MagicMock

from habitron_client import (
    HabitronConnectionError,
    HabitronTimeoutError,
    Module,
    Router,
)
import pytest

from custom_components.habitron.const import SCAN_INTERVAL
from custom_components.habitron.coordinator import (
    FW_POLL_INTERVAL,
    HbtnCoordinator,
    HbtnFirmwareCoordinator,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed


def _make_coord(hass: HomeAssistant) -> HbtnCoordinator:
    """Build a coordinator with the bus refresh and host readings stubbed.

    The coordinator owns the connection now, so there is no transport to swap;
    only the two calls a tick makes are replaced. ``hass.data`` carries the
    manifest the constructor reads for the version it reports to the hub.
    """
    entry = MagicMock()
    entry.data = {"host": "192.168.1.50"}
    hass.data.setdefault("integrations", {})["habitron"] = MagicMock(
        manifest={"version": "3.4.3"}
    )
    coord = HbtnCoordinator(hass, entry)
    coord._client = AsyncMock()
    coord.async_system_update = AsyncMock(return_value=4711)  # type: ignore[method-assign]
    coord.update = AsyncMock()  # type: ignore[method-assign]
    return coord


async def test_coordinator_normal_update(hass: HomeAssistant) -> None:
    """``_async_update_data`` returns the compact status and forwards to the library."""
    coord = _make_coord(hass)
    result = await coord._async_update_data()
    assert result == 4711
    coord.async_system_update.assert_awaited_once()


async def test_coordinator_timeout_raises_update_failed(
    hass: HomeAssistant,
) -> None:
    """A timeout in ``async_system_update`` is wrapped in ``UpdateFailed``."""
    coord = _make_coord(hass)
    coord.async_system_update.side_effect = TimeoutError("hub silent")
    with pytest.raises(UpdateFailed) as exc_info:
        await coord._async_update_data()
    assert exc_info.value.translation_key == "update_timeout"


async def test_coordinator_change_detection(hass: HomeAssistant) -> None:
    """``always_update`` is False so the heartbeat only fans out on changes."""
    coord = _make_coord(hass)
    assert coord.always_update is False


async def test_coordinator_uses_fixed_scan_interval(hass: HomeAssistant) -> None:
    """The coordinator's interval is the integration's hard-coded SCAN_INTERVAL."""
    coord = _make_coord(hass)
    assert coord.update_interval == SCAN_INTERVAL


async def test_async_setup_runs_first_refresh(hass: HomeAssistant) -> None:
    """``_async_setup`` delegates to ``_async_update_data``."""
    coord = _make_coord(hass)
    await coord._async_setup()
    coord.async_system_update.assert_awaited()


async def test_coordinator_network_error_raises_update_failed(
    hass: HomeAssistant,
) -> None:
    """An OSError in ``async_system_update`` is wrapped in ``UpdateFailed``."""
    coord = _make_coord(hass)
    coord.async_system_update.side_effect = OSError("dns down")
    with pytest.raises(UpdateFailed) as exc_info:
        await coord._async_update_data()
    assert exc_info.value.translation_key == "update_network_error"


async def test_coordinator_library_timeout_raises_update_failed(
    hass: HomeAssistant,
) -> None:
    """A HabitronTimeoutError from the client maps to ``update_timeout``."""
    coord = _make_coord(hass)
    coord.async_system_update.side_effect = HabitronTimeoutError("no response")
    with pytest.raises(UpdateFailed) as exc_info:
        await coord._async_update_data()
    assert exc_info.value.translation_key == "update_timeout"


async def test_coordinator_library_error_raises_update_failed(
    hass: HomeAssistant,
) -> None:
    """Any other HabitronError maps to ``update_network_error``."""
    coord = _make_coord(hass)
    coord.async_system_update.side_effect = HabitronConnectionError("bus down")
    with pytest.raises(UpdateFailed) as exc_info:
        await coord._async_update_data()
    assert exc_info.value.translation_key == "update_network_error"


# ---------- HbtnFirmwareCoordinator ----------


def _make_fw_status(resp: bytes = b"1.0.0\n2.0.0") -> MagicMock:
    """Stub status parent with a router + one module, both read via handle_firmware."""
    status = MagicMock()
    router = Router(uid="ROUTER-1", name="Router")
    router.modules = [Module(uid="MOD-1", addr=5, typ=b"\x01\x02", name="Mod 1")]
    status.router = router
    status.handle_firmware = AsyncMock(return_value=resp)
    return status


async def test_fw_coordinator_uses_slow_interval(hass: HomeAssistant) -> None:
    """The firmware coordinator runs on the dedicated FW_POLL_INTERVAL."""
    coord = HbtnFirmwareCoordinator(hass, MagicMock(), _make_fw_status())
    assert coord.update_interval == FW_POLL_INTERVAL


async def test_fw_coordinator_reads_one_target_per_cycle(hass: HomeAssistant) -> None:
    """Each refresh reads a single target and records its versions."""
    status = _make_fw_status()
    coord = HbtnFirmwareCoordinator(hass, MagicMock(), status)
    data = await coord._async_update_data()
    assert data == {"ROUTER-1": ("1.0.0", "2.0.0")}
    status.handle_firmware.assert_awaited_once_with(0)


async def test_fw_coordinator_round_robin_wraps(hass: HomeAssistant) -> None:
    """Successive refreshes rotate router -> module -> router."""
    status = _make_fw_status()
    coord = HbtnFirmwareCoordinator(hass, MagicMock(), status)
    await coord._async_update_data()
    await coord._async_update_data()
    await coord._async_update_data()
    assert [c.args[0] for c in status.handle_firmware.await_args_list] == [0, 5, 0]
    assert coord.data["MOD-1"] == ("1.0.0", "2.0.0")


async def test_fw_coordinator_empty_response_keeps_data(hass: HomeAssistant) -> None:
    """An empty (crc-unchanged) response records nothing for that target."""
    coord = HbtnFirmwareCoordinator(hass, MagicMock(), _make_fw_status(resp=b""))
    assert await coord._async_update_data() == {}


async def test_fw_coordinator_read_error_is_swallowed(hass: HomeAssistant) -> None:
    """A bus error during a firmware read does not fail the refresh."""
    status = _make_fw_status()
    status.handle_firmware = AsyncMock(side_effect=OSError("bus"))
    coord = HbtnFirmwareCoordinator(hass, MagicMock(), status)
    assert await coord._async_update_data() == {}  # no raise


async def test_fw_coordinator_library_error_is_swallowed(hass: HomeAssistant) -> None:
    """A client timeout during a firmware read does not fail the refresh."""
    status = _make_fw_status()
    status.handle_firmware = AsyncMock(side_effect=HabitronTimeoutError("no response"))
    coord = HbtnFirmwareCoordinator(hass, MagicMock(), status)
    assert await coord._async_update_data() == {}  # no raise
