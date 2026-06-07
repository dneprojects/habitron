"""Tests for the Habitron communicate (HbtnComm) layer."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.habitron.const import HaEvents


def _make_comm(host: str = "192.168.1.50") -> object:
    """Build an HbtnComm with all heavyweight dependencies stubbed out."""
    from custom_components.habitron.communicate import HbtnComm  # noqa: PLC0415

    hass = MagicMock()
    hass.data = {"integrations": {"habitron": MagicMock(manifest={"version": "9.9.9"})}}
    hass.async_add_executor_job = AsyncMock()
    config = MagicMock()
    config.data = {"habitron_host": host, "update_interval": 5}
    smhub = MagicMock()
    with patch("custom_components.habitron.communicate.HabitronClient"):
        comm = HbtnComm(hass, config, smhub)
    return comm


def test_init_with_valid_ipv4_uses_host_directly() -> None:
    """A valid IPv4 in config is stored as the active host."""
    comm = _make_comm("10.0.0.5")
    assert comm._host == "10.0.0.5"
    assert comm._hostip == "10.0.0.5"


def test_init_with_hostname_leaves_host_empty() -> None:
    """A non-IPv4 hostname produces an empty initial host (resolved later)."""
    comm = _make_comm("my-hub.local")
    assert comm._host == ""


def test_is_valid_ipv4_accepts_valid_and_rejects_invalid() -> None:
    """``is_valid_ipv4`` returns True for valid IPv4 strings only."""
    comm = _make_comm()
    assert comm.is_valid_ipv4("192.168.1.1") is True
    assert comm.is_valid_ipv4("not-an-ip") is False
    assert comm.is_valid_ipv4("256.300.0.0") is False


def test_convert_mod_id_subtracts_hundred() -> None:
    """_convert_mod_id maps the bus address back to a 0-based module index."""
    comm = _make_comm()
    assert comm._convert_mod_id(105) == 5
    assert comm._convert_mod_id(100) == 0


def test_property_accessors_expose_internal_fields() -> None:
    """Public properties expose host / port / mac / version / hwtype / hostname."""
    comm = _make_comm("10.0.0.5")
    comm._port = 7777
    comm._mac = "AA:BB"
    comm._version = "1.2.3"
    comm._hwtype = "RPi 4"
    comm._hostname = "smarthub"
    assert comm.com_ip == "10.0.0.5"
    assert comm.com_port == 7777
    assert comm.com_mac == "AA:BB"
    assert comm.com_version == "1.2.3"
    assert comm.com_hwtype == "RPi 4"
    assert comm.hostname == "smarthub"
    assert comm.hbtn_version == "9.9.9"


def test_router_property_falls_back_to_smhub_router() -> None:
    """``router`` returns smhub.router when no _rtr has been set."""
    comm = _make_comm()
    rt = MagicMock()
    comm.smhub.router = rt
    assert comm.router is rt
    other = MagicMock()
    comm.set_router(other)
    assert comm.router is other


async def test_async_exec_runs_inside_api_lock() -> None:
    """_async_exec offloads the call to hass.async_add_executor_job."""
    comm = _make_comm()
    fn = MagicMock(return_value="ok")
    comm._hass.async_add_executor_job = AsyncMock(return_value="ok")
    result = await comm._async_exec(fn, 1, 2)
    assert result == "ok"
    comm._hass.async_add_executor_job.assert_awaited_with(fn, 1, 2)


# ---------- async_setup() host resolution ----------


async def test_async_setup_resolves_local_via_own_ip() -> None:
    """When host_conf is "local", async_setup uses get_own_ip()."""
    comm = _make_comm("local")
    comm._hass.async_add_executor_job = AsyncMock(return_value="192.0.2.1")
    with patch(
        "custom_components.habitron.communicate.network.async_get_source_ip",
        new=AsyncMock(return_value="192.0.2.42"),
    ):
        await comm.async_setup()
    assert comm._host == "192.0.2.1"
    assert comm.client.host == "192.0.2.1"
    assert comm._network_ip == "192.0.2.42"


async def test_async_setup_resolves_hostname_via_get_host_ip() -> None:
    """A hostname is resolved to an IP via get_host_ip()."""
    comm = _make_comm("hub.local")
    comm._hass.async_add_executor_job = AsyncMock(return_value="10.0.0.99")
    with patch(
        "custom_components.habitron.communicate.network.async_get_source_ip",
        new=AsyncMock(return_value="10.0.0.42"),
    ):
        await comm.async_setup()
    assert comm._host == "10.0.0.99"


async def test_async_setup_skips_dns_when_host_already_set() -> None:
    """If the IP is already set, async_setup only resolves the network IP."""
    comm = _make_comm("10.0.0.1")  # IPv4 → _host already set
    comm._hass.async_add_executor_job = AsyncMock()
    with patch(
        "custom_components.habitron.communicate.network.async_get_source_ip",
        new=AsyncMock(return_value="10.0.0.42"),
    ):
        await comm.async_setup()
    # async_add_executor_job is NOT called for host resolution
    comm._hass.async_add_executor_job.assert_not_called()


# ---------- set_host ----------


async def test_set_host_no_op_when_host_unchanged() -> None:
    """A set_host call with the same host short-circuits after the update_entry call."""
    comm = _make_comm("192.168.1.50")
    comm._hass.config_entries.async_update_entry = MagicMock()
    comm._hass.config_entries.async_reload = AsyncMock()
    await comm.set_host("192.168.1.50")
    comm._hass.config_entries.async_update_entry.assert_called()
    comm._hass.config_entries.async_reload.assert_not_called()


async def test_set_host_with_new_host_triggers_reload() -> None:
    """A different host string triggers a reload of the config entry."""
    comm = _make_comm("192.168.1.50")
    comm._hass.config_entries.async_update_entry = MagicMock()
    comm._hass.config_entries.async_reload = AsyncMock()
    comm._hass.async_add_executor_job = AsyncMock(return_value="10.0.0.99")
    await comm.set_host("new-host")
    assert comm._host_conf == "new-host"
    assert comm._host == "10.0.0.99"
    comm._hass.config_entries.async_reload.assert_awaited()


# ---------- get_smhub_info success + error paths ----------


def test_get_smhub_info_populates_fields_from_client_payload() -> None:
    """get_smhub_info maps the client response into the comm's cached fields."""
    comm = _make_comm()
    payload = {
        "software": {"version": "1.0.0", "slug": "habitron_addon"},
        "hardware": {
            "platform": {"type": "Raspberry Pi"},
            "network": {
                "ip": "10.0.0.99",
                "host": "smarthub",
                "lan mac": "AA:BB:CC:DD:EE:FF",
            },
        },
    }
    comm.client.get_smhub_info = MagicMock(return_value=payload)
    with patch.dict("os.environ", {"SUPERVISOR_TOKEN": "tok"}):
        out = comm.get_smhub_info()
    assert out is payload
    assert comm._version == "1.0.0"
    assert comm._hwtype == "Raspberry Pi"
    assert comm._mac == "AA:BB:CC:DD:EE:FF"
    assert comm._hostname == "smarthub"
    assert comm._hostip == "10.0.0.99"
    assert comm.is_addon is True
    assert comm.slugname == "habitron_addon"


def test_get_smhub_info_non_addon_clears_slugname() -> None:
    """Without SUPERVISOR_TOKEN, ``is_addon`` is False and slugname is blank."""
    import os  # noqa: PLC0415

    comm = _make_comm()
    payload = {
        "software": {"version": "1.0.0", "slug": "habitron_addon"},
        "hardware": {
            "platform": {"type": "RPi"},
            "network": {"ip": "1.1.1.1", "host": "h", "lan mac": "ff"},
        },
    }
    comm.client.get_smhub_info = MagicMock(return_value=payload)
    os.environ.pop("SUPERVISOR_TOKEN", None)
    comm.get_smhub_info()
    assert comm.is_addon is False
    assert comm.slugname == ""


def test_get_smhub_info_timeout_reraises() -> None:
    """A TimeoutException is re-raised so the caller knows the hub is silent."""
    from habitron_client import TimeoutException  # noqa: PLC0415

    comm = _make_comm()
    comm.client.get_smhub_info = MagicMock(side_effect=TimeoutException("silent"))
    with pytest.raises(TimeoutException):
        comm.get_smhub_info()


def test_get_smhub_info_generic_exception_reraises() -> None:
    """A non-timeout exception also propagates after being logged."""
    comm = _make_comm()
    comm.client.get_smhub_info = MagicMock(side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        comm.get_smhub_info()


def test_get_smhub_update_forwards_to_client() -> None:
    """get_smhub_update delegates to the client."""
    comm = _make_comm()
    comm.client.get_smhub_update = MagicMock(return_value={"ok": True})
    out = comm.get_smhub_update()
    assert out == {"ok": True}
    comm.client.get_smhub_update.assert_called_with(comm._hbtn_version)


# ---------- async_setup-suite of bus wrappers (delegate to _async_exec) ----------


@pytest.fixture
def comm_with_mock_exec() -> object:
    """An HbtnComm with ``_async_exec`` patched to a recording AsyncMock."""
    comm = _make_comm("10.0.0.1")
    comm._async_exec = AsyncMock(return_value=b"resp")
    return comm


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("get_smhub_version", ()),
        ("get_smr", ()),
        ("async_get_router_status", ()),
        ("async_get_router_modules", ()),
        ("get_global_descriptions", ()),
        ("async_get_error_status", ()),
        ("async_start_mirror", ()),
        ("async_stop_mirror", ()),
        ("async_set_group_mode", (1, 7)),
        ("async_set_alarm_mode", (1, True)),
        ("async_set_log_level", (0, 3)),
        ("async_set_output", (105, 2, True)),
        ("async_set_dimmval", (105, 1, 80)),
        ("async_set_rgb_output", (105, 0, False)),
        ("async_set_rgbval", (105, 0, [255, 0, 0])),
        ("async_set_shutterpos", (105, 1, 50)),
        ("async_set_blindtilt", (105, 1, 30)),
        ("async_set_flag", (105, 0, True)),
        ("async_inc_dec_counter", (105, 1, 1)),
        ("async_set_setpoint", (105, 1, 220)),
        ("async_set_climate_mode", (105, 1, 1)),
        ("async_call_dir_command", (105, 1)),
        ("async_call_vis_command", (105, 1)),
        ("async_call_coll_command", (1,)),
        ("async_get_module_definitions", (105,)),
        ("async_get_module_settings", (105,)),
        ("send_message", (105, 1)),
        ("send_sms", (105, 1, 1)),
        ("hub_restart", ()),
        ("hub_reboot", ()),
        ("module_restart", (5,)),
        ("restart_fwd_tbl", ()),
        ("send_devregid", (5, "dev-1")),
        ("async_set_analog_val", (105, 1, 50)),
        ("send_network_info", ("tok",)),
        ("reinit_hub", (0,)),
    ],
)
async def test_comm_bus_wrappers_delegate_to_async_exec(
    comm_with_mock_exec: object,
    method: str,
    args: tuple,
) -> None:
    """Each bus-wrapper method delegates the call to ``_async_exec``."""
    await getattr(comm_with_mock_exec, method)(*args)
    comm_with_mock_exec._async_exec.assert_awaited()


async def test_async_set_daytime_mode_day_path(comm_with_mock_exec) -> None:
    """mode 1 maps to 0x42 and dispatches via _async_exec."""
    await comm_with_mock_exec.async_set_daytime_mode(1, 1)
    args, _ = comm_with_mock_exec._async_exec.call_args
    assert args[1] == 1
    assert args[2] == 0x42


async def test_async_set_daytime_mode_night_path(comm_with_mock_exec) -> None:
    """mode 2 maps to 0x43."""
    await comm_with_mock_exec.async_set_daytime_mode(1, 2)
    args, _ = comm_with_mock_exec._async_exec.call_args
    assert args[2] == 0x43


async def test_async_set_daytime_mode_unknown_is_noop(comm_with_mock_exec) -> None:
    """An undefined daytime mode short-circuits without dispatching."""
    await comm_with_mock_exec.async_set_daytime_mode(1, 99)
    comm_with_mock_exec._async_exec.assert_not_awaited()


def test_set_output_delegates_synchronously() -> None:
    """The synchronous ``set_output`` calls into the client directly."""
    comm = _make_comm("10.0.0.1")
    comm.client.set_output = MagicMock()
    comm.set_output(105, 1, True)
    comm.client.set_output.assert_called_with(5, 1, True)


async def test_async_set_led_outp_translates_to_output(
    comm_with_mock_exec,
) -> None:
    """async_set_led_outp shifts the index by len(module.outputs)."""
    module = MagicMock()
    module.outputs = [MagicMock() for _ in range(8)]
    comm_with_mock_exec.smhub.router.get_module = MagicMock(return_value=module)
    await comm_with_mock_exec.async_set_led_outp(105, 1, True)
    # async_set_led_outp → async_set_output → _async_exec
    args, _ = comm_with_mock_exec._async_exec.call_args
    assert args[2] == 1 + 8  # nmbr + len(outputs)


# ---------- send_devreg_ids walking the router modules ----------


async def test_send_devreg_ids_walks_and_dispatches_modules() -> None:
    """send_devreg_ids fires per-module send_devregid for non-blank ids."""
    comm = _make_comm()
    mod_a = MagicMock()
    mod_a.devreg_id = "dev-A"
    mod_a.name = "A"
    mod_a.send_devregid = AsyncMock()
    mod_b = MagicMock()
    mod_b.devreg_id = ""  # skipped
    mod_b.send_devregid = AsyncMock()
    comm.smhub.router.modules = [mod_a, mod_b]
    await comm.send_devreg_ids()
    mod_a.send_devregid.assert_awaited()
    mod_b.send_devregid.assert_not_awaited()


# ---------- async_system_update happy + edge paths ----------


async def test_async_system_update_short_circuits_when_suspended() -> None:
    """update_suspended skips the entire update path."""
    comm = _make_comm()
    comm.update_suspended = True
    comm.get_compact_status = AsyncMock()
    await comm.async_system_update()
    comm.get_compact_status.assert_not_called()


async def test_async_system_update_returns_when_empty_status() -> None:
    """An empty compact status (unchanged crc) returns without dispatching."""
    comm = _make_comm()
    comm.get_compact_status = AsyncMock(return_value=b"")
    comm.smhub.router.update_system_status = AsyncMock()
    await comm.async_system_update()
    comm.smhub.router.update_system_status.assert_not_called()


async def test_async_system_update_logs_when_status_too_short() -> None:
    """A status shorter than 10 bytes logs a warning and returns."""
    comm = _make_comm()
    comm.get_compact_status = AsyncMock(return_value=b"\x00\x01")
    comm.smhub.router.update_system_status = AsyncMock()
    comm.logger = MagicMock()
    await comm.async_system_update()
    comm.logger.warning.assert_called()
    comm.smhub.router.update_system_status.assert_not_called()


async def test_async_system_update_distributes_normal_status() -> None:
    """A valid compact status is forwarded to router.update_system_status."""
    comm = _make_comm()
    comm.get_compact_status = AsyncMock(return_value=b"\x00" * 32)
    comm.smhub.router.update_system_status = AsyncMock()
    await comm.async_system_update()
    comm.smhub.router.update_system_status.assert_awaited()


# ---------- get_compact_status / get_module_status crc dedupe ----------


async def test_get_compact_status_returns_empty_on_unchanged_crc() -> None:
    """A response whose crc matches the cached value yields an empty byte string."""
    comm = _make_comm()
    comm._async_exec = AsyncMock(return_value=(b"payload", 42))
    comm.crc = 42
    out = await comm.get_compact_status()
    assert out == b""


async def test_get_compact_status_caches_new_crc_and_returns_bytes() -> None:
    """A new crc updates the cached value and returns the payload."""
    comm = _make_comm()
    comm._async_exec = AsyncMock(return_value=(b"payload", 7))
    comm.crc = 0
    out = await comm.get_compact_status()
    assert out == b"payload"
    assert comm.crc == 7


async def test_get_module_status_caches_new_crc_and_returns_bytes() -> None:
    """get_module_status follows the same crc-dedupe contract as compact status."""
    comm = _make_comm()
    comm._async_exec = AsyncMock(return_value=(b"mod-payload", 9))
    comm.crc = 0
    out = await comm.get_module_status(105)
    assert out == b"mod-payload"
    assert comm.crc == 9


async def test_get_module_status_returns_empty_on_unchanged_crc() -> None:
    """A matching crc yields an empty bytes."""
    comm = _make_comm()
    comm._async_exec = AsyncMock(return_value=(b"mod-payload", 9))
    comm.crc = 9
    out = await comm.get_module_status(105)
    assert out == b""


async def test_handle_firmware_crc_dedupe() -> None:
    """handle_firmware shares the same crc-dedupe contract."""
    comm = _make_comm()
    comm._async_exec = AsyncMock(return_value=(b"fw", 5))
    comm.crc = 0
    out = await comm.handle_firmware(105)
    assert out == b"fw"
    comm.crc = 5
    out = await comm.handle_firmware(105)
    assert out == b""


async def test_update_firmware_crc_dedupe() -> None:
    """update_firmware shares the crc-dedupe contract."""
    comm = _make_comm()
    comm._async_exec = AsyncMock(return_value=(b"fw", 11))
    comm.crc = 0
    out = await comm.update_firmware(105)
    assert out == b"fw"
    comm.crc = 11
    out = await comm.update_firmware(105)
    assert out == b""


async def test_async_power_cycle_channel_down_and_up_with_sleep() -> None:
    """power_cycle_channel runs the down + sleep + up sequence."""
    comm = _make_comm()
    comm._async_exec = AsyncMock()
    with patch("custom_components.habitron.communicate.asyncio.sleep", new=AsyncMock()):
        await comm.async_power_cycle_channel(2)
    assert comm._async_exec.await_count == 2


# ---------- save_* file persisters ----------


async def test_save_router_status_writes_file(tmp_path) -> None:
    """save_router_status writes a Router_1.rstat file via save_config_data."""
    comm = _make_comm()
    comm.async_get_router_status = AsyncMock(return_value=b"\x01\x02")
    comm.save_config_data = AsyncMock()
    await comm.save_router_status()
    comm.save_config_data.assert_awaited()
    assert comm.save_config_data.call_args.args[0] == "Router_1.rstat"


async def test_save_module_status_writes_file() -> None:
    """save_module_status writes a Module_<id>.mstat file."""
    comm = _make_comm()
    comm.get_module_status = AsyncMock(return_value=b"\x01\x02")
    comm.save_config_data = AsyncMock()
    await comm.save_module_status(105)
    comm.save_config_data.assert_awaited()
    assert comm.save_config_data.call_args.args[0] == "Module_105.mstat"


async def test_save_smc_file_walks_byte_layout() -> None:
    """save_smc_file emits a Module_<id>.smc file with the parsed layout."""
    comm = _make_comm()
    # 7-byte header + 7-byte line (line_len = data[5] + 5)
    payload = b"\x00" * 7 + bytes([0, 0, 0, 0, 0, 2, 0, 0, 0])  # line_len = 2+5 = 7
    comm.async_get_module_definitions = AsyncMock(return_value=payload)
    comm.save_config_data = AsyncMock()
    await comm.save_smc_file(105)
    comm.save_config_data.assert_awaited()
    assert comm.save_config_data.call_args.args[0] == "Module_105.smc"


async def test_save_smg_file_writes_byte_separated_string() -> None:
    """save_smg_file serialises each byte as a semicolon-terminated value."""
    comm = _make_comm()
    comm.async_get_module_settings = AsyncMock(return_value=b"\x01\x02\x03")
    comm.save_config_data = AsyncMock()
    await comm.save_smg_file(105)
    comm.save_config_data.assert_awaited()
    args = comm.save_config_data.call_args.args
    assert args[0] == "Module_105.smg"
    assert args[1] == "1;2;3;"


async def test_save_smr_file_writes_byte_separated_string() -> None:
    """save_smr_file serialises each byte to a semicolon-terminated value."""
    comm = _make_comm()
    comm.get_smr = AsyncMock(return_value=b"\x07\x08")
    comm.save_config_data = AsyncMock()
    await comm.save_smr_file()
    args = comm.save_config_data.call_args.args
    assert args[0] == "Router_1.smr"
    assert args[1] == "7;8;"


async def test_save_config_data_writes_to_disk(tmp_path) -> None:
    """save_config_data creates the data directory and writes the payload."""
    comm = _make_comm()

    async def _exec_job(func, *args):
        return func(*args)

    comm._hass.async_add_executor_job = AsyncMock(side_effect=_exec_job)
    with patch(
        "custom_components.habitron.communicate._DATA_DIR", tmp_path / "data"
    ):
        await comm.save_config_data("test.txt", "hello")
    out_file = tmp_path / "data" / "test.txt"
    assert out_file.read_text() == "hello"


# ---------- update_entity dispatcher (event matrix) ----------


def _make_module_for_update_entity() -> MagicMock:
    """Build a module stub rich enough to drive every update_entity branch."""
    module = MagicMock()
    # inputs, outputs, dimmers, covers, sensors, leds, flags, logic, cleds, fingers
    descriptors = lambda n: [  # noqa: E731
        type(
            "Desc",
            (),
            {
                "value": 0,
                "tilt": 0,
                "nmbr": i,
                "handle_upd_event": AsyncMock(),
            },
        )()
        for i in range(n)
    ]
    module.inputs = descriptors(8)
    module.outputs = descriptors(16)
    module.dimmers = descriptors(4)
    module.covers = descriptors(4)
    module.sensors = descriptors(4)
    module.leds = descriptors(4)
    # cleds need ``.value`` to be a list
    cled = MagicMock()
    cled.value = [0, 0, 0, 0]
    cled.handle_upd_event = AsyncMock()
    module.cleds = [cled, cled, cled]
    # logic, fingers
    module.logic = descriptors(4)
    module.fingers = descriptors(1)
    flag = MagicMock()
    flag.nmbr = 1
    flag.handle_upd_event = AsyncMock()
    module.flags = [flag]
    module.get_cover_index = MagicMock(return_value=-1)
    module.typ = b"\x01\x03"
    return module


async def test_update_entity_short_circuits_on_wrong_hub_id() -> None:
    """A mismatched hub id short-circuits the dispatcher."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    comm.router.flags = []
    await comm.update_entity("other-host", 0, HaEvents.FLAG, 0, 0)
    # Nothing to assert other than: no exception was raised.


async def test_update_entity_router_flag_branch() -> None:
    """A router FLAG event updates the matching router flag and fires its event."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    flag = MagicMock()
    flag.nmbr = 2
    flag.handle_upd_event = AsyncMock()
    comm.smhub.router.flags = [flag]
    await comm.update_entity("10.0.0.1", 0, HaEvents.FLAG, 2, 1)
    flag.handle_upd_event.assert_awaited()
    assert flag.value == 1


async def test_update_entity_mode_router_branch() -> None:
    """A MODE event with arg1 == 0 updates the router mode."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    comm.smhub.router.mode = MagicMock()
    comm.smhub.router.mode.handle_upd_event = AsyncMock()
    await comm.update_entity("10.0.0.1", 5, HaEvents.MODE, 0, 0x42)
    assert comm.smhub.router.mode.value == 0x42
    comm.smhub.router.mode.handle_upd_event.assert_awaited()
    assert comm.grp_modes[0] == 0x42


async def test_update_entity_mode_module_branch() -> None:
    """A MODE event with arg1 != 0 updates the matching module mode."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    mod = MagicMock()
    mod.mode.handle_upd_event = AsyncMock()
    comm.smhub.router.modules = [mod]
    comm.smhub.router.module_grp = [3]
    await comm.update_entity("10.0.0.1", 5, HaEvents.MODE, 3, 0x42)
    assert mod.mode.value == 0x42
    mod.mode.handle_upd_event.assert_awaited()


async def test_update_entity_no_module_logs_error() -> None:
    """A mod_id without a matching module logs an error and returns."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    comm.smhub.router.get_module = MagicMock(return_value=None)
    comm.logger = MagicMock()
    await comm.update_entity("10.0.0.1", 5, HaEvents.BUTTON, 1, 1)
    comm.logger.error.assert_called()


async def test_update_entity_get_module_exception_warns() -> None:
    """An exception in router.get_module is caught and logged as a warning."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    comm.smhub.router.get_module = MagicMock(side_effect=RuntimeError("oops"))
    comm.logger = MagicMock()
    await comm.update_entity("10.0.0.1", 5, HaEvents.BUTTON, 1, 1)
    comm.logger.warning.assert_called()


async def test_update_entity_button_dispatches_input_event() -> None:
    """A BUTTON event with arg2 == 1 dispatches a single_press + inactive reset."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.BUTTON, 1, 1)
    # Two upd_event calls: single_press + inactive reset
    assert module.inputs[0].handle_upd_event.await_count == 2


async def test_update_entity_switch_writes_value() -> None:
    """A SWITCH event writes arg2 into the input's value and fires the event."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.SWITCH, 1, 1)
    assert module.inputs[0].value == 1
    module.inputs[0].handle_upd_event.assert_awaited()


async def test_update_entity_output_low_writes_output_and_fires() -> None:
    """An OUTPUT event with arg1 <= 15 writes the output value."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.OUTPUT, 1, 1)
    assert module.outputs[0].value == 1
    module.outputs[0].handle_upd_event.assert_awaited()


async def test_update_entity_output_led_branch_with_list_value() -> None:
    """An OUTPUT event with arg1 > 15 routes to the LED list (RGB value list)."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    # First LED has a list value (RGB-style)
    module.leds[0].value = [0, 0, 0, 0]
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.OUTPUT, 16, 1)
    assert module.leds[0].value[0] == 1
    module.leds[0].handle_upd_event.assert_awaited()


async def test_update_entity_output_led_branch_with_scalar_value() -> None:
    """An OUTPUT event with arg1 > 15 also handles scalar LED values."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    module.leds[0].value = 0  # scalar
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.OUTPUT, 16, 1)
    assert module.leds[0].value == 1


async def test_update_entity_output_mini_controller_led_path() -> None:
    """A typ[0] == 50 module with arg1 > 2 fires the matching LED event."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    module.typ = b"\x32\x01"
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.OUTPUT, 3, 1)
    module.leds[0].handle_upd_event.assert_awaited()


async def test_update_entity_output_triggers_cover_event_when_paired() -> None:
    """A paired output triggers the corresponding cover event via get_cover_index."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    module.get_cover_index = MagicMock(return_value=0)
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.OUTPUT, 1, 1)
    module.covers[0].handle_upd_event.assert_awaited()


async def test_update_entity_rgb_value_change() -> None:
    """RGB with arg2 == 2 writes the R/G/B triple into the cled.value list."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.RGB, 0, 2, 200, 100, 50)
    cled = module.cleds[0]
    assert cled.value[0] == 1
    assert cled.value[1] == 200
    assert cled.value[2] == 100
    assert cled.value[3] == 50


async def test_update_entity_rgb_on_off_change() -> None:
    """RGB with arg2 != 2 toggles cled.value[0] only."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.RGB, 0, 1)
    cled = module.cleds[0]
    assert cled.value[0] == 1


async def test_update_entity_finger_normal_branch() -> None:
    """Finger value ≤ 10 stores the user id positively."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    with patch(
        "custom_components.habitron.communicate.asyncio.sleep",
        new=AsyncMock(),
    ):
        await comm.update_entity("10.0.0.1", 5, HaEvents.FINGER, 7, 4)
    assert module.sensors[0].value == 7


async def test_update_entity_finger_disabled_user_branch() -> None:
    """Finger value > 10 stores the user id negatively (disabled marker)."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    with patch(
        "custom_components.habitron.communicate.asyncio.sleep",
        new=AsyncMock(),
    ):
        await comm.update_entity("10.0.0.1", 5, HaEvents.FINGER, 7, 140)
    assert module.sensors[0].value == -7


async def test_update_entity_dimm_val_writes_dimmer_and_fires() -> None:
    """DIM_VAL writes arg2 into dimmers[arg1].value."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.DIM_VAL, 0, 75)
    assert module.dimmers[0].value == 75


async def test_update_entity_cov_val_writes_cover_value() -> None:
    """COV_VAL writes arg2 into covers[arg1].value."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.COV_VAL, 0, 50)
    assert module.covers[0].value == 50


async def test_update_entity_bld_val_writes_cover_tilt() -> None:
    """BLD_VAL writes arg2 into covers[arg1].tilt."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.BLD_VAL, 0, 25)
    assert module.covers[0].tilt == 25


async def test_update_entity_move_writes_sensor_value() -> None:
    """MOVE writes a binary movement flag into sensors[arg1].value."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.MOVE, 0, 7)
    assert module.sensors[0].value == 1


async def test_update_entity_flag_writes_matching_flag() -> None:
    """A module FLAG event writes the matching flag's value."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.FLAG, 1, 1)
    assert module.flags[0].value == 1


async def test_update_entity_cnt_val_writes_counter() -> None:
    """CNT_VAL writes arg2 into logic[arg1].value."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    comm.smhub.router.get_module = MagicMock(return_value=module)
    await comm.update_entity("10.0.0.1", 5, HaEvents.CNT_VAL, 1, 9)
    assert module.logic[1].value == 9


async def test_update_entity_handler_exception_is_logged() -> None:
    """An exception during dispatch is caught and reported via the logger."""
    comm = _make_comm()
    comm._hostip = "10.0.0.1"
    module = _make_module_for_update_entity()
    # Break the inputs lookup so DIM_VAL etc. raise IndexError.
    module.dimmers = []
    comm.smhub.router.get_module = MagicMock(return_value=module)
    comm.logger = MagicMock()
    await comm.update_entity("10.0.0.1", 5, HaEvents.DIM_VAL, 99, 1)
    comm.logger.warning.assert_called()
