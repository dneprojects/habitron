"""Tests for the Habitron router class."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.habitron.const import (
    FALSE_VAL,
    TRUE_VAL,
    ModuleDescriptor,
    MStatIdx,
    RoutIdx,
)
from custom_components.habitron.router import (
    AlarmMode,
    DaytimeMode,
    GroupMode,
    HbtnRouter,
)


def _make_router(uid: str = "ROUTER-1") -> HbtnRouter:
    """Build an HbtnRouter with stubbed comm + smhub.

    HbtnCoordinator is patched out so the constructor does not try to
    parse the (mock) config-entry update_interval into a timedelta.
    """
    smhub = MagicMock()
    smhub.uid = uid
    smhub.base_url = "http://10.0.0.1:7780"
    smhub.update = AsyncMock()
    smhub.comm = MagicMock()
    smhub.comm.send_devregid = AsyncMock()
    smhub.comm.set_router = MagicMock()
    smhub.comm.async_get_router_status = AsyncMock(return_value=b"")
    smhub.comm.async_get_router_modules = AsyncMock(return_value=b"")
    smhub.comm.async_get_error_status = AsyncMock(return_value=b"\x00\x00")
    smhub.comm.async_system_update = AsyncMock()
    smhub.comm.async_start_mirror = AsyncMock()
    smhub.comm.module_restart = AsyncMock()
    smhub.comm.restart_fwd_tbl = AsyncMock()
    smhub.comm.get_smr = AsyncMock(return_value=b"")
    smhub.comm.get_global_descriptions = AsyncMock(return_value=b"\x00\x00\x00\x00")
    smhub.comm.grp_modes = {}
    config = MagicMock()
    config.entry_id = "entry-1"
    hass = MagicMock()
    with patch("custom_components.habitron.router.HbtnCoordinator"):
        return HbtnRouter(hass, config, smhub)


def test_daytime_alarm_group_enum_values() -> None:
    """Router-side enums expose the documented int values."""
    assert DaytimeMode.day.value == 1
    assert AlarmMode.on.value == 4
    assert GroupMode.absent.value == 16
    assert GroupMode.user1.value == 80


def test_router_init_seeds_uid_and_descriptor_lists() -> None:
    """HbtnRouter.__init__ wires the per-router defaults and descriptors."""
    rt = _make_router()
    assert rt.uid == "rt_ROUTER-1"
    assert rt.id == 100
    assert len(rt.chan_timeouts) == 4
    assert len(rt.chan_currents) == 8
    assert len(rt.voltages) == 2
    assert rt.voltages[0].name == "Voltage 5V"
    assert rt.voltages[1].name == "Voltage 24V"
    assert len(rt.states) == 2
    assert rt.states[0].name == "System OK"


def test_system_ok_and_number_modules_defaults() -> None:
    """``system_ok`` defaults True and ``number_modules`` mirrors len(modules)."""
    rt = _make_router()
    assert rt.system_ok() is True
    assert rt.number_modules() == 0
    rt.modules.append(MagicMock())
    assert rt.number_modules() == 1


def test_get_module_by_addr_and_uid_and_stream() -> None:
    """The three lookup helpers walk the modules list correctly."""
    rt = _make_router()
    mod = MagicMock()
    mod.raddr = 5
    mod.uid = "MOD-A"
    mod.type = "Smart Controller Touch"
    mod.stream_name = "touch_1"
    rt.modules.append(mod)
    assert rt.get_module(5) is mod
    assert rt.get_module(99) is None
    assert rt.get_module_by_uid("MOD-A") is mod
    assert rt.get_module_by_uid("nope") is None
    assert rt.get_module_by_stream("touch_1") is mod
    assert rt.get_module_by_stream("missing") is None


def test_get_area_id_matches_by_slug() -> None:
    """get_area_id returns the area key whose slugified name matches."""
    from custom_components.habitron.interfaces import AreaDescriptor  # noqa: PLC0415

    rt = _make_router()
    rt.areas[3] = AreaDescriptor("Living Room", 3)
    assert rt.get_area_id("living_room") == 3
    assert rt.get_area_id("kitchen") == 0


def test_unit_not_exists_walks_descriptor_list() -> None:
    """unit_not_exists is True only when no matching name exists."""
    from custom_components.habitron.interfaces import IfDescriptor  # noqa: PLC0415

    rt = _make_router()
    units = [IfDescriptor("A", 0, 1, 0), IfDescriptor("B", 1, 1, 0)]
    assert rt.unit_not_exists(units, "C") is True
    assert rt.unit_not_exists(units, "A") is False


async def test_async_reset_calls_module_restart_zero() -> None:
    """async_reset on the router restarts itself (mod 0)."""
    rt = _make_router()
    await rt.async_reset()
    rt.comm.module_restart.assert_awaited_with(0)


async def test_async_restart_fwd_tbl_forwards() -> None:
    """async_restart_fwd_tbl forwards to comm.restart_fwd_tbl."""
    rt = _make_router()
    await rt.async_restart_fwd_tbl()
    rt.comm.restart_fwd_tbl.assert_awaited()


async def test_async_reset_all_modules_uses_0xff() -> None:
    """async_reset_all_modules calls module_restart(0xFF)."""
    rt = _make_router()
    await rt.async_reset_all_modules()
    rt.comm.module_restart.assert_awaited_with(0xFF)


async def test_send_devregid_forwards_to_comm() -> None:
    """send_devregid forwards (0, devreg_id) to comm.send_devregid."""
    rt = _make_router()
    rt.devreg_id = "dev-1"
    await rt.send_devregid()
    rt.comm.send_devregid.assert_awaited_with(0, "dev-1")


async def test_get_comm_errors_returns_empty_when_no_errors_reported() -> None:
    """A response with err_cnt == 0 produces an empty error byte string."""
    rt = _make_router()
    rt.comm.async_get_error_status = AsyncMock(return_value=bytes([0]))
    out = await rt.get_comm_errors()
    assert out == b""


# ---------- _pad_sys_status static helper ----------


def test_pad_sys_status_empty_passes_through() -> None:
    """An empty buffer is passed through unchanged."""
    assert HbtnRouter._pad_sys_status(b"") == b""


def test_pad_sys_status_zero_byte_count_returns_input() -> None:
    """A block whose BYTE_COUNT is zero is passed through (unknown layout)."""
    bad = b"\x00" * 50
    assert HbtnRouter._pad_sys_status(bad) == bad


def test_pad_sys_status_uneven_length_returns_input() -> None:
    """A buffer that doesn't divide evenly into blk_len is passed through."""
    # blk_len 50 but buffer is 75 bytes → 75 % 50 != 0
    buf = bytes([50]) + b"\x00" * 74
    assert HbtnRouter._pad_sys_status(buf) == buf


def test_pad_sys_status_already_at_target_passes_through() -> None:
    """A block already at MStatIdx.END is left untouched."""
    blk_len = MStatIdx.END
    buf = bytes([blk_len]) + b"\x01" * (blk_len - 1) + bytes([blk_len]) + b"\x02" * (
        blk_len - 1
    )
    assert HbtnRouter._pad_sys_status(buf) == buf


def test_pad_sys_status_pads_short_block_up_to_target() -> None:
    """A legacy 92-byte block gets zero-padded up to MStatIdx.END."""
    blk_len = 92
    # Build 2 blocks of 92 bytes each
    block_a = bytes([blk_len]) + b"\x01" * (blk_len - 1)
    block_b = bytes([blk_len]) + b"\x02" * (blk_len - 1)
    out = HbtnRouter._pad_sys_status(block_a + block_b)
    assert len(out) == 2 * MStatIdx.END
    # First block keeps its prefix
    assert out[:blk_len] == block_a
    # Padded region is zeroed
    assert out[blk_len : MStatIdx.END] == b"\x00" * (MStatIdx.END - blk_len)


# ---------- get_descriptions parser ----------


def _build_desc_line(content_code: int, entry_no: int, entry_name: bytes) -> bytes:
    """Build a global description line (event-style record).

    Layout (from production code):
        byte 0    = sub_code (unused for matching)
        bytes 1,2 = content_code (little-endian)
        byte 3    = entry_no
        bytes 4-7 = filler (unused)
        byte 8    = entry_name length (line_len = byte 8 + 9)
        bytes 9.. = entry_name (decoded as iso8859-1)
    """
    header = bytearray(9)
    header[1] = content_code & 0xFF
    header[2] = (content_code >> 8) & 0xFF
    header[3] = entry_no
    header[8] = len(entry_name)
    return bytes(header) + entry_name


def _wrap_descriptions(lines: list[bytes]) -> bytes:
    """Wrap a list of lines into the get_descriptions response framing."""
    header = bytes([len(lines) & 0xFF, (len(lines) >> 8) & 0xFF, 0, 0])
    return header + b"".join(lines)


async def test_get_descriptions_parses_flags_commands_and_areas() -> None:
    """A crafted reply walks each branch of the get_descriptions loop."""
    rt = _make_router()
    lines = [
        # 767 = FF 02 → global flag
        _build_desc_line(767, 1, b"flag-1"),
        # 1023 = FF 03 → collective command
        _build_desc_line(1023, 4, b"All off"),
        # 2815 = FF 0A → area definition
        _build_desc_line(2815, 2, b"Kitchen"),
        # 3071 = FF 0B → cover_autostop_del
        _build_desc_line(3071, 7, b"unused"),
    ]
    payload = _wrap_descriptions(lines)
    rt.comm.get_global_descriptions = AsyncMock(return_value=payload)

    await rt.get_descriptions()
    assert any(f.name == "flag-1" for f in rt.flags)
    assert any(c.name == "All off" for c in rt.coll_commands)
    assert 2 in rt.areas
    assert rt.cover_autostop_del == 7


async def test_get_descriptions_unknown_code_logs_warning(caplog) -> None:
    """An unknown content code logs a warning but does not raise."""
    rt = _make_router()
    # Use a code that's outside the listed branches AND has byte[2] != 7
    # (so it doesn't fall into the silent "group name" path).
    lines = [_build_desc_line(9999, 0, b"???")]
    payload = _wrap_descriptions(lines)
    rt.comm.get_global_descriptions = AsyncMock(return_value=payload)
    rt.logger = MagicMock()
    await rt.get_descriptions()
    rt.logger.warning.assert_called()


async def test_get_descriptions_group_name_branch_is_silent() -> None:
    """A content with line[2] == 7 (group name) is a silent no-op."""
    rt = _make_router()
    # content_code with byte[2] == 7 (0x07XX, e.g. 0x0701 = 1793)
    lines = [_build_desc_line(0x0701, 0, b"grp")]
    payload = _wrap_descriptions(lines)
    rt.comm.get_global_descriptions = AsyncMock(return_value=payload)
    rt.logger = MagicMock()
    await rt.get_descriptions()
    rt.logger.warning.assert_not_called()


async def test_get_descriptions_alarm_branch_is_silent() -> None:
    """A 2303 (alarm command) entry is a silent no-op."""
    rt = _make_router()
    lines = [_build_desc_line(2303, 0, b"alarm")]
    payload = _wrap_descriptions(lines)
    rt.comm.get_global_descriptions = AsyncMock(return_value=payload)
    rt.logger = MagicMock()
    await rt.get_descriptions()
    rt.logger.warning.assert_not_called()


# ---------- get_definitions parser ----------


async def test_get_definitions_with_modules_records_max_mod_no_and_groups() -> None:
    """A SMR with non-zero channel counts walks the module_grp + max_mod_no path."""
    rt = _make_router()
    smr = bytearray(b"\x00" * 256)
    # Channel 0: count=2, addrs [5, 6] → max_mod_no = 6
    smr[1] = 2
    smr[2] = 5
    smr[3] = 6
    # Channel 1..3: count=0
    # ptr advances: 1 + (1+2) + (1+0)*3 = 7
    # ptr += 2 → 9; grp_cnt at smr[8] = 2; groups at 9..10 = [3, 4]
    smr[8] = 2  # grp_cnt
    smr[9] = 3
    smr[10] = 4
    # For 6 modules (max_mod_no=6), grp_no walked from ptr=9..14
    smr[11] = 1
    smr[12] = 2
    smr[13] = 1
    smr[14] = 2
    # ptr += 2*2 + 1 = 5 → 14; router name at smr[14]
    # Wait — production code: ptr += 2 * grp_cnt + 1 = 5, after that ptr=14
    # Actually need to recompute. After ptr=9 and after the for-mod_i loop,
    # ptr += 2*grp_cnt + 1 → ptr = 9 + 5 = 14
    # smr[14] = router name length
    smr[14] = 4
    smr[15:19] = b"R-Hb"
    # ptr after name = 19; user1 length
    smr[19] = 3
    smr[20:23] = b"Bob"
    # ptr after user1 = 23
    smr[23] = 3
    smr[24:27] = b"Sue"
    # ptr after user2 = 27
    smr[27] = 5
    smr[28:33] = b"S/N-1"
    smr[-22:] = b"v1.0                  "

    rt.comm.async_get_router_status = AsyncMock(return_value=b"\x00" * 50)
    rt.comm.get_smr = AsyncMock(return_value=bytes(smr))
    await rt.get_definitions()
    # 6 modules walked → 6 group entries
    assert len(rt.module_grp) == 6
    assert rt.name == "R-Hb"


async def test_get_descriptions_breaks_on_overlong_header() -> None:
    """A header that claims more lines than the body delivers stops at empty resp."""
    rt = _make_router()
    # no_lines=2 but only one line follows
    header = bytes([2, 0, 0, 0])
    lines = [_build_desc_line(767, 1, b"flag-1")]
    payload = header + b"".join(lines)
    rt.comm.get_global_descriptions = AsyncMock(return_value=payload)
    await rt.get_descriptions()  # no exception — the for-loop hits break


async def test_update_system_status_writes_flag_values() -> None:
    """When the router has flags, the FLAG_GLOB byte drives flag.value updates."""
    from custom_components.habitron.interfaces import StateDescriptor  # noqa: PLC0415

    rt = _make_router()
    rt.flags = [StateDescriptor("flg", 0, 1, 1, False)]
    rt_status = bytearray(b"\x00" * 60)
    rt_status[RoutIdx.FLAG_GLOB] = 0x01
    rt_status[RoutIdx.ERR_SYSTEM] = FALSE_VAL
    rt_status[RoutIdx.MIRROR_STARTED] = TRUE_VAL
    rt.comm.async_get_router_status = AsyncMock(return_value=bytes(rt_status))

    with (
        patch("custom_components.habitron.router.ir.async_create_issue"),
        patch("custom_components.habitron.router.ir.async_delete_issue"),
    ):
        await rt.update_system_status(b"")
    assert rt.flags[0].value == 1


async def test_get_comm_errors_concatenates_error_pairs() -> None:
    """A response with err_cnt > 0 yields the concatenated 2-byte error pairs."""
    rt = _make_router()
    # err_cnt=2, error pairs (0xAA,0xBB) and (0xCC,0xDD)
    payload = bytes([2, 0xAA, 0xBB, 0xCC, 0xDD])
    rt.comm.async_get_error_status = AsyncMock(return_value=payload)
    out = await rt.get_comm_errors()
    assert out == b"\xaa\xbb\xcc\xdd"


async def test_get_definitions_parses_smr_payload() -> None:
    """get_definitions walks the channel/group/name layout into attributes."""
    rt = _make_router()
    # Pointer arithmetic per production code (custom_components/habitron/router.py
    # get_definitions). Compact layout we build:
    #   ptr=1, 4 channels each with count=0 → ptr advances to 5
    #   ptr += 2 → ptr=7
    #   smr[6] = grp_cnt (we set 1), smr[7] = a single group value (we set 0)
    #   ptr += 2*1 + 1 = 3 → ptr=10
    #   smr[10] = name_len, name follows
    smr = bytearray(b"\x00" * 256)
    smr[6] = 1  # grp_cnt
    smr[7] = 0  # one group with value 0
    # Router name
    smr[10] = 5
    smr[11:16] = b"R-Hub"
    # user1 name at ptr=16
    smr[16] = 3
    smr[17:20] = b"Bob"
    # user2 name at ptr=20
    smr[20] = 3
    smr[21:24] = b"Sue"
    # serial at ptr=24
    smr[24] = 5
    smr[25:30] = b"S/N-1"
    # version is the last 22 bytes (production reads ``self.smr[-22:]``)
    smr[-22:] = b"v1.2.3                "

    rt.comm.async_get_router_status = AsyncMock(return_value=b"\x00" * 50)
    rt.comm.get_smr = AsyncMock(return_value=bytes(smr))

    await rt.get_definitions()
    assert rt.name == "R-Hub"
    assert rt.user1_name == "Bob"
    assert rt.user2_name == "Sue"
    assert rt.serial == "S/N-1"
    assert rt.version == "v1.2.3"


# ---------- get_modules parser ----------


async def test_get_modules_decodes_descriptor_blocks() -> None:
    """get_modules walks a multi-block bus reply into ModuleDescriptors."""
    rt = _make_router()
    # block: [addr_byte, type[0], type[1], name_len, name...]
    name_a = b"Living"
    name_b = b"Kitchen"
    payload = (
        bytes([5]) + b"\x01\x03" + bytes([len(name_a)]) + name_a
        + bytes([6]) + b"\x0a\x01" + bytes([len(name_b)]) + name_b
    )
    rt.comm.async_get_router_modules = AsyncMock(return_value=payload)
    descs = await rt.get_modules([0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    assert len(descs) == 2
    assert descs[0].name.startswith("Living")
    assert descs[0].mtype == b"\x01\x03"
    assert descs[0].addr == 5 + rt.id
    assert descs[1].name.startswith("Kitchen")


# ---------- update_system_status full happy-path ----------


async def test_update_system_status_short_router_status_returns_early() -> None:
    """A too-short router status block logs a warning and returns."""
    rt = _make_router()
    rt.comm.async_get_router_status = AsyncMock(return_value=b"\x00" * 5)
    rt.logger = MagicMock()
    await rt.update_system_status(b"")
    rt.logger.warning.assert_called()
    rt.smhub.update.assert_awaited()


async def test_update_system_status_writes_router_values() -> None:
    """A full-length router status fills the descriptor lists with parsed values."""
    rt = _make_router()
    # Build a router status long enough to carry every parsed field.
    rt_status = bytearray(b"\x00" * 60)
    rt_status[RoutIdx.MODE0] = 0x42
    rt_status[RoutIdx.FLAG_GLOB] = 0x01
    rt_status[RoutIdx.TIME_OUT + 0] = 7
    rt_status[RoutIdx.CURRENTS + 0] = 100
    rt_status[RoutIdx.CURRENTS + 1] = 0
    rt_status[RoutIdx.VOLTAGE_5 + 0] = 50
    rt_status[RoutIdx.VOLTAGE_5 + 1] = 0
    rt_status[RoutIdx.VOLTAGE_24 + 0] = 240
    rt_status[RoutIdx.VOLTAGE_24 + 1] = 0
    rt_status[RoutIdx.ERR_SYSTEM] = FALSE_VAL
    rt_status[RoutIdx.MIRROR_STARTED] = TRUE_VAL

    rt.comm.async_get_router_status = AsyncMock(return_value=bytes(rt_status))

    with (
        patch("custom_components.habitron.router.ir.async_create_issue"),
        patch("custom_components.habitron.router.ir.async_delete_issue") as mock_del,
    ):
        await rt.update_system_status(b"")

    assert rt.mode.value == 0x42
    assert rt.chan_timeouts[0].value == 7
    assert rt.chan_currents[0].value == 0.1  # 100 / 1000
    assert rt.voltages[0].value == 5.0
    assert rt.voltages[1].value == 24.0
    assert rt._sys_ok is True
    assert rt._mirror_started is True
    mock_del.assert_called()  # issue cleared because sys_ok


async def test_update_system_status_creates_issue_when_not_ok() -> None:
    """When ERR_SYSTEM is set, an issue is created via ir.async_create_issue."""
    rt = _make_router()
    rt_status = bytearray(b"\x00" * 60)
    rt_status[RoutIdx.ERR_SYSTEM] = TRUE_VAL  # not ok
    rt_status[RoutIdx.MIRROR_STARTED] = TRUE_VAL
    rt.comm.async_get_router_status = AsyncMock(return_value=bytes(rt_status))

    with (
        patch(
            "custom_components.habitron.router.ir.async_create_issue"
        ) as mock_create,
        patch("custom_components.habitron.router.ir.async_delete_issue"),
    ):
        await rt.update_system_status(b"")

    assert rt._sys_ok is False
    mock_create.assert_called()


async def test_update_system_status_restarts_mirror_when_not_started() -> None:
    """A not-yet-started mirror triggers ``comm.async_start_mirror``."""
    rt = _make_router()
    rt_status = bytearray(b"\x00" * 60)
    rt_status[RoutIdx.ERR_SYSTEM] = FALSE_VAL
    rt_status[RoutIdx.MIRROR_STARTED] = FALSE_VAL
    rt.comm.async_get_router_status = AsyncMock(return_value=bytes(rt_status))

    with (
        patch("custom_components.habitron.router.ir.async_create_issue"),
        patch("custom_components.habitron.router.ir.async_delete_issue"),
    ):
        await rt.update_system_status(b"")
    rt.comm.async_start_mirror.assert_awaited()


async def test_update_system_status_distributes_to_modules() -> None:
    """Each per-module status block is dispatched via mod_reg lookup."""
    rt = _make_router()
    # One module with addr=5 and raddr=5
    module = MagicMock()
    module.send_devregid = AsyncMock()
    module.update = MagicMock()
    rt.modules.append(module)
    rt.mod_reg = {5 + rt.id: 0}
    # A status with one MStatIdx.END-sized block, ADDR=5
    mod_blk = bytearray(MStatIdx.END)
    mod_blk[MStatIdx.BYTE_COUNT] = MStatIdx.END
    mod_blk[MStatIdx.ADDR] = 5
    sys_status = bytes(mod_blk)

    rt_status = bytearray(b"\x00" * 60)
    rt_status[RoutIdx.ERR_SYSTEM] = FALSE_VAL
    rt_status[RoutIdx.MIRROR_STARTED] = TRUE_VAL
    rt.comm.async_get_router_status = AsyncMock(return_value=bytes(rt_status))

    with (
        patch("custom_components.habitron.router.ir.async_create_issue"),
        patch("custom_components.habitron.router.ir.async_delete_issue"),
    ):
        await rt.update_system_status(sys_status)

    module.update.assert_called()
    module.send_devregid.assert_awaited()


# ---------- initialize() full flow with all module type branches ----------


async def test_initialize_registers_device_and_seeds_module_instances() -> None:
    """``initialize`` walks the full registration flow and creates HbtnModule subclasses."""
    rt = _make_router()
    # Pre-seed module_grp so get_modules can index it.
    rt.module_grp = [0] * 16

    # 11 descriptors, one per module-type branch in initialize().
    descs = [
        # m0=10, m1=1 → hbtoutm (SmartOutput)
        ModuleDescriptor("uid-1", 101, b"\x0a\x01", "Out", 0),
        # m0=10, m1=20 → hbtdimm
        ModuleDescriptor("uid-2", 102, b"\x0a\x14", "Dimm", 0),
        # m0=10, m1=30 → hbtio2
        ModuleDescriptor("uid-3", 103, b"\x0a\x1e", "IO2", 0),
        # m0=11 → hbtinm
        ModuleDescriptor("uid-4", 104, b"\x0b\x1e", "In", 0),
        # m0=80 → hbtsdm
        ModuleDescriptor("uid-5", 105, b"\x50\x64", "Detect", 0),
        # m0=20 → hbtsnm (SmartNature)
        ModuleDescriptor("uid-6", 106, b"\x14\x01", "Nature", 0),
        # m0=50, m1=1 → hbtscmm (SmartControllerMini)
        ModuleDescriptor("uid-7", 107, b"\x32\x01", "Mini", 0),
        # m0=50, m1=40 → hbtsens (SmartSensor)
        ModuleDescriptor("uid-8", 108, b"\x32\x28", "Sensor", 0),
        # m0=1 → hbtscm (SmartController)
        ModuleDescriptor("uid-9", 109, b"\x01\x03", "SC", 0),
        # m0=30, m1=1 → hbtkey (SmartEKey)
        ModuleDescriptor("uid-10", 110, b"\x1e\x01", "eKey", 0),
        # m0=30, m1=3 → hbtgsm
        ModuleDescriptor("uid-11", 111, b"\x1e\x03", "GSM", 0),
    ]

    async def _no_op_get_definitions():
        return None

    async def _no_op_get_descriptions():
        return None

    async def _return_descs(_):
        return descs

    rt.get_definitions = _no_op_get_definitions
    rt.get_descriptions = _no_op_get_descriptions
    rt.get_modules = _return_descs

    # Stub HbtnModule.initialize so we don't dive into each subclass —
    # SmartDetect and SmartNature override ``initialize`` so we patch
    # those independently too.
    with (
        patch("custom_components.habitron.router.dr.async_get") as mock_dr,
        patch(
            "custom_components.habitron.module.HbtnModule.initialize",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.habitron.module.SmartDetect.initialize",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.habitron.module.SmartNature.initialize",
            new=AsyncMock(),
        ),
    ):
        dev = MagicMock(); dev.id = "dev-rt"
        mock_dr.return_value.async_get_or_create.return_value = dev
        mock_dr.return_value.async_get_device.return_value = dev
        result = await rt.initialize()

    assert result is True
    assert rt.devreg_id == "dev-rt"
    # 11 module instances created
    assert len(rt.modules) == 11
    # The right subclasses ended up in the list (sample check)
    from custom_components.habitron.module import (  # noqa: PLC0415
        SmartController,
        SmartControllerMini,
        SmartDetect,
        SmartDimm,
        SmartEKey,
        SmartGSM,
        SmartInput,
        SmartIO2,
        SmartNature,
        SmartOutput,
        SmartSensor,
    )

    types = {type(m) for m in rt.modules}
    assert SmartOutput in types
    assert SmartDimm in types
    assert SmartIO2 in types
    assert SmartInput in types
    assert SmartDetect in types
    assert SmartNature in types
    assert SmartControllerMini in types
    assert SmartSensor in types
    assert SmartController in types
    assert SmartEKey in types
    assert SmartGSM in types


@pytest.mark.parametrize(
    "mtype",
    [
        b"\x0a\x02",  # m0=10, m1=2 also routes to SmartOutput
        b"\x0a\x32",  # m0=10, m1=50 also routes to SmartOutput
        b"\x0a\x15",  # m0=10, m1=21 also routes to SmartDimm
        b"\x0a\x16",  # m0=10, m1=22 also routes to SmartDimm
    ],
)
async def test_initialize_groups_alternate_outputs_and_dimmers(mtype: bytes) -> None:
    """The m0=10 / m1=N family of types routes to SmartOutput or SmartDimm."""
    rt = _make_router()
    rt.module_grp = [0]
    descs = [ModuleDescriptor("uid", 105, mtype, "Mod", 0)]

    async def _no_op():
        return None

    async def _return(_):
        return descs

    rt.get_definitions = _no_op
    rt.get_descriptions = _no_op
    rt.get_modules = _return

    with (
        patch("custom_components.habitron.router.dr.async_get"),
        patch(
            "custom_components.habitron.module.HbtnModule.initialize",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.habitron.module.SmartDetect.initialize",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.habitron.module.SmartNature.initialize",
            new=AsyncMock(),
        ),
    ):
        await rt.initialize()

    assert len(rt.modules) == 1
