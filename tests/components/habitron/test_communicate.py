"""Tests for the Habitron communicate (HbtnComm) layer (v2 thin transport)."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import HabitronClient, Module, Router

from custom_components.habitron.communicate import HbtnComm


def _make_comm(host: str = "192.168.1.50") -> HbtnComm:
    """Build an HbtnComm with the client + smhub stubbed out."""
    hass = MagicMock()
    hass.data = {"integrations": {"habitron": MagicMock(manifest={"version": "9.9.9"})}}
    hass.async_add_executor_job = AsyncMock()
    config = MagicMock()
    config.data = {"habitron_host": host}
    smhub = MagicMock()
    comm = HbtnComm(hass, config, smhub)
    comm._client = AsyncMock(spec=HabitronClient)
    return comm


# ---------------------------------------------------------------------------
# init / helpers / properties
# ---------------------------------------------------------------------------


def test_init_with_valid_ipv4_uses_host_directly() -> None:
    """A valid IPv4 in config is stored as the active host."""
    comm = _make_comm("10.0.0.5")
    assert comm._host == "10.0.0.5"


def test_init_with_hostname_leaves_host_empty() -> None:
    """A non-IPv4 hostname produces an empty initial host (resolved later)."""
    assert _make_comm("my-hub.local")._host == ""


def test_is_valid_ipv4() -> None:
    """``is_valid_ipv4`` accepts valid IPv4 only."""
    comm = _make_comm()
    assert comm.is_valid_ipv4("192.168.1.1") is True
    assert comm.is_valid_ipv4("not-an-ip") is False


def test_convert_mod_id_subtracts_hundred() -> None:
    """_convert_mod_id maps the bus address back to a raw module address."""
    comm = _make_comm()
    assert comm._convert_mod_id(105) == 5
    assert comm._convert_mod_id(100) == 0


def test_property_accessors() -> None:
    """Public properties expose the cached fields."""
    comm = _make_comm("10.0.0.5")
    comm._mac = "AA:BB"
    comm._version = "1.2.3"
    assert comm.com_ip == "10.0.0.5"
    assert comm.com_mac == "AA:BB"
    assert comm.com_version == "1.2.3"
    assert comm.hbtn_version == "9.9.9"


def test_router_property_falls_back_to_smhub_router() -> None:
    """``router`` returns smhub.router until set_router stores one."""
    comm = _make_comm()
    rt = Router(uid="rt_x")
    comm.smhub.router = rt
    assert comm.router is rt
    other = Router(uid="rt_y")
    comm.set_router(other)
    assert comm.router is other


def test_module_by_addr() -> None:
    """_module_by_addr finds a module by its full address."""
    comm = _make_comm()
    router = Router()
    mod = Module(uid="M", addr=105, typ=b"\x0a\x01", name="x")
    router.modules = [mod]
    comm.set_router(router)
    assert comm._module_by_addr(105) is mod
    assert comm._module_by_addr(999) is None


# ---------------------------------------------------------------------------
# command wrappers (transport pass-throughs)
# ---------------------------------------------------------------------------


async def test_set_output_converts_addr() -> None:
    """set_output converts the address and forwards a bool value."""
    comm = _make_comm()
    await comm.async_set_output(105, 2, 1)
    comm._client.set_output.assert_awaited_with(5, 2, True)


async def test_set_dimmval_and_flag() -> None:
    """Dim/flag setters forward converted addresses."""
    comm = _make_comm()
    await comm.async_set_dimmval(105, 1, 50)
    comm._client.set_dimmval.assert_awaited_with(5, 1, 50)
    await comm.async_set_flag(105, 3, 1)
    comm._client.set_flag.assert_awaited_with(5, 3, True)


async def test_set_analog_val_uses_dimm_channel_3() -> None:
    """The analogue output maps to dimm channel 3."""
    comm = _make_comm()
    await comm.async_set_analog_val(105, 1, 42)
    comm._client.set_dimmval.assert_awaited_with(5, 3, 42)


async def test_set_led_outp_offsets_by_output_count() -> None:
    """LED output number is offset by the module's output count."""
    comm = _make_comm()
    router = Router()
    mod = Module(uid="M", addr=105, typ=b"\x01\x02", name="x")
    mod.outputs = [object()] * 16  # 16 outputs
    router.modules = [mod]
    comm.set_router(router)
    await comm.async_set_led_outp(105, 0, 1)
    comm._client.set_output.assert_awaited_with(5, 16, True)


async def test_set_group_mode_and_climate() -> None:
    """Group-mode + climate setters pass through to the client."""
    comm = _make_comm()
    await comm.async_set_group_mode(2, 32)
    comm._client.set_group_mode.assert_awaited_with(2, 32)
    await comm.async_set_climate_mode(105, 1, 2)
    comm._client.set_climate_mode.assert_awaited_with(5, 1, 2)


# ---------------------------------------------------------------------------
# async_system_update -> async_refresh_system
# ---------------------------------------------------------------------------


async def test_async_system_update_suspended_returns_crc() -> None:
    """While suspended no refresh happens and the cached CRC is returned."""
    comm = _make_comm()
    comm.update_suspended = True
    comm.crc = 7
    comm.smhub.update = AsyncMock()
    with patch(
        "custom_components.habitron.communicate.async_refresh_system",
        new=AsyncMock(),
    ) as refresh:
        assert await comm.async_system_update() == 7
        refresh.assert_not_called()
        comm.smhub.update.assert_not_called()


async def test_async_system_update_refreshes_and_returns_new_crc() -> None:
    """A normal tick refreshes hub diagnostics + the bus, returning the new CRC."""
    comm = _make_comm()
    comm.smhub.update = AsyncMock()
    with patch(
        "custom_components.habitron.communicate.async_refresh_system",
        new=AsyncMock(return_value=99),
    ) as refresh:
        assert await comm.async_system_update() == 99
        comm.smhub.update.assert_awaited()
        refresh.assert_awaited()
        assert comm.crc == 99


# ---------------------------------------------------------------------------
# update_entity -> apply_event
# ---------------------------------------------------------------------------


async def test_update_entity_applies_event_when_host_matches() -> None:
    """A matching host forwards the event to ``apply_event``."""
    comm = _make_comm()
    comm._hostip = "1.2.3.4"
    router = Router()
    comm.set_router(router)
    with patch("custom_components.habitron.communicate.apply_event") as apply_evt:
        await comm.update_entity("1.2.3.4", 2, 1, 3, 1)
        apply_evt.assert_called_once_with(router, 2, 1, 3, 1, 0, 0, 0)


async def test_update_entity_ignores_foreign_host() -> None:
    """A non-matching host does not apply the event."""
    comm = _make_comm()
    comm._hostip = "1.2.3.4"
    with patch("custom_components.habitron.communicate.apply_event") as apply_evt:
        await comm.update_entity("9.9.9.9", 2, 1, 3, 1)
        apply_evt.assert_not_called()


# ---------------------------------------------------------------------------
# crc dedupe
# ---------------------------------------------------------------------------


async def test_get_compact_status_dedupes_on_unchanged_crc() -> None:
    """An unchanged CRC returns empty bytes (no work)."""
    comm = _make_comm()
    comm._stream_crc["compact"] = 42
    comm._client.get_compact_status = AsyncMock(return_value=(b"payload", 42))
    assert await comm.get_compact_status() == b""


async def test_get_compact_status_caches_new_crc() -> None:
    """A changed CRC returns the payload and caches the new CRC."""
    comm = _make_comm()
    comm._client.get_compact_status = AsyncMock(return_value=(b"payload", 7))
    assert await comm.get_compact_status() == b"payload"
    assert comm._stream_crc["compact"] == 7


# ---------------------------------------------------------------------------
# get_smhub_info
# ---------------------------------------------------------------------------


async def test_get_smhub_info_populates_fields() -> None:
    """get_smhub_info fills mac/version/host fields from the validated info."""
    comm = _make_comm()
    info = {
        "software": {"version": "1.0", "slug": "habitron"},
        "hardware": {
            "platform": {"type": "Raspberry Pi 4"},
            "network": {"ip": "10.0.0.5", "host": "smarthub", "lan mac": "AA:BB"},
        },
    }
    comm._client.get_smhub_info = AsyncMock(return_value=info)
    with patch("custom_components.habitron.communicate.os.getenv", return_value=None):
        out = await comm.get_smhub_info()
    assert out["software"]["version"] == "1.0"
    assert comm.com_version == "1.0"
    assert comm.com_mac == "AA:BB"
    assert comm.com_ip == "10.0.0.5"


# ---------------------------------------------------------------------------
# async_setup
# ---------------------------------------------------------------------------


async def test_async_setup_resolves_host_and_connects() -> None:
    """async_setup resolves the host and connects a fresh client."""
    comm = _make_comm("my-hub.local")
    comm._client = None
    comm._hass.async_add_executor_job = AsyncMock(return_value="10.0.0.9")
    client = AsyncMock(spec=HabitronClient)
    with (
        patch(
            "custom_components.habitron.communicate.network.async_get_source_ip",
            new=AsyncMock(return_value="10.0.0.1"),
        ),
        patch(
            "custom_components.habitron.communicate.HabitronClient",
            return_value=client,
        ),
    ):
        await comm.async_setup()
    assert comm._host == "10.0.0.9"
    client.connect.assert_awaited()
