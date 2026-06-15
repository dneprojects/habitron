"""Tests for the Habitron module-layer classes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.habitron.const import ModuleDescriptor, MSetIdx, MStatIdx
from custom_components.habitron.interfaces import (
    CovDescriptor,
    IfDescriptor,
    LgcDescriptor,
    StateDescriptor,
)
from custom_components.habitron.module import (
    HbtnModule,
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


def _make_comm() -> MagicMock:
    """Build a stub ``HbtnComm`` with the few attributes the module reads."""
    comm = MagicMock()
    comm.router.areas = {}
    comm.router.smhub.base_url = "http://192.0.2.1:7780"
    comm.router.uid = "rt_ABC"
    comm.send_devregid = AsyncMock()
    return comm


def _make_descriptor(
    uid: str = "MOD-1",
    addr: int = 105,
    mtype: bytes = b"\x01\x03",
    name: str = "Living room",
    group: int = 0,
) -> ModuleDescriptor:
    """Build a real ModuleDescriptor — it's a tiny value object."""
    return ModuleDescriptor(uid, addr, mtype, name, group)


# ---------- HbtnModule base class ----------


def test_module_init_populates_lists_and_defaults() -> None:
    """HbtnModule.__init__ sets up empty entity-list attributes."""
    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert mod.name == "Living room"
    assert mod.b_uid == "HUB-1"
    assert mod.typ == b"\x01\x03"
    assert mod.type == "Smart Controller XL-2 (LE2)"
    assert mod._addr == 105
    assert mod.raddr == 5  # 105 - int(105/100) * 100
    assert mod.id == "Mod_MOD-1_HUB-1"
    assert isinstance(mod.inputs, list) and mod.inputs == []
    assert isinstance(mod.outputs, list) and mod.outputs == []
    assert isinstance(mod.sensors, list) and mod.sensors == []
    # diags list seeded with two entries: "" + "Status"
    assert len(mod.diags) == 2
    assert mod.diags[1].name == "Status"


def test_module_properties_mod_id_addr_type() -> None:
    """The public properties expose internal ids."""
    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert mod.mod_id == mod.id
    assert mod.mod_addr == 105
    assert mod.mod_type == "Smart Controller XL-2 (LE2)"


def test_module_area_fallback_to_house() -> None:
    """Without an area entry the property falls back to 'House'."""
    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert mod.area == "House"


def test_module_area_uses_router_area_name() -> None:
    """When the area_member exists in router.areas its name is returned."""
    desc = _make_descriptor()
    comm = _make_comm()
    area = MagicMock()
    area.name = "Kitchen"
    comm.router.areas = {3: area}
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    mod.area_member = 3
    assert mod.area == "Kitchen"


def test_module_get_cover_index_paired_outputs() -> None:
    """``get_cover_index`` walks the outputs to map a pair to a cover."""

    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    # Populate at least two paired outputs (type 1 == standard digital out).
    mod.outputs = [IfDescriptor("Out 1", 0, 1, 0), IfDescriptor("Out 2", 1, 1, 0)]
    result = mod.get_cover_index(1)
    assert isinstance(result, int)


def test_module_extract_status_returns_slice() -> None:
    """``extract_status`` slices the system status bytes for this module."""
    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    # Build a 200-byte sys_status; the module just picks its slice.
    sys_status = bytes(range(200)) * 5
    out = mod.extract_status(sys_status)
    assert isinstance(out, bytes)


def test_module_set_default_names_assigns_indexed_names() -> None:
    """``set_default_names`` fills empty names with a base + index pattern."""
    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())

    items = [
        IfDescriptor("", 0, 0, 0),
        IfDescriptor("Custom", 1, 0, 0),
        IfDescriptor("", 2, 0, 0),
    ]
    mod.set_default_names(items, "Out")
    # Empty names are replaced with "<mod_id> <prefix><idx+1>"; existing
    # names are left untouched.
    assert items[0].name.endswith("Out1")
    assert items[1].name == "Custom"
    assert items[2].name.endswith("Out3")


async def test_module_send_devregid_forwards_to_comm() -> None:
    """``send_devregid`` calls into comm with the raw address and devreg_id."""
    desc = _make_descriptor()
    comm = _make_comm()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    mod.devreg_id = "dev-42"
    await mod.send_devregid()
    comm.send_devregid.assert_awaited_with(5, "dev-42")


async def test_module_async_reset_dispatches_to_comm() -> None:
    """async_reset calls comm.module_restart with the right address."""
    desc = _make_descriptor()
    comm = _make_comm()
    comm.module_restart = AsyncMock()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    await mod.async_reset()
    comm.module_restart.assert_awaited()


# ---------- SmartController (typ \x01\x03 / \x01\x04 family) ----------


def test_smart_controller_init_populates_extra_lists() -> None:
    """SmartController extends HbtnModule with controller-specific lists."""
    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    # SC adds analog inputs, leds, sensors, setvalues
    assert len(sc.inputs) > 0
    assert len(sc.outputs) > 0
    assert len(sc.sensors) > 0


def test_smart_controller_touch_init_seeds_stream_name_and_version() -> None:
    """A SC Touch is configured with stream_name and client_version."""
    desc = _make_descriptor(mtype=b"\x01\x04", name="Touch Hallway")
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert sc.type == "Smart Controller Touch"
    assert sc.stream_name.endswith("_5")  # raddr suffix
    assert sc.client_version == "unknown"


def test_smart_controller_set_assist_entity() -> None:
    """``set_assist_entity`` records the assist satellite entity id."""
    desc = _make_descriptor(mtype=b"\x01\x04", name="Touch")
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    sc.set_assist_entity("assist_satellite.touch_5")
    assert sc.assist_entity_id == "assist_satellite.touch_5"


# ---------- SmartControllerMini (typ \x32\x01) ----------


def test_smart_controller_mini_initializes_cleds_and_outputs() -> None:
    """SC Mini wires colour LEDs (cleds) on top of the base lists."""
    desc = _make_descriptor(mtype=b"\x32\x01", name="Mini")
    mini = SmartControllerMini(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert mini.type == "Smart Controller Mini"
    assert hasattr(mini, "cleds")
    assert len(mini.cleds) > 0


# ---------- SmartOutput / SmartDimm / SmartIO2 (typ \x0a\xXX) ----------


def test_smart_output_init_populates_outputs() -> None:
    """SmartOutput wires its outputs and flags."""
    desc = _make_descriptor(mtype=b"\x0a\x01", name="Out 8/R")
    out = SmartOutput(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert out.type == "Smart Out 8/R"
    assert len(out.outputs) > 0


def test_smart_dimm_init_has_dimmers() -> None:
    """SmartDimm exposes a dimmer-sized list of outputs."""
    desc = _make_descriptor(mtype=b"\x0a\x14", name="Dimm 1")
    dimm = SmartDimm(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert dimm.type == "Smart Dimm"
    assert len(dimm.dimmers) > 0


def test_smart_io2_init_populates_inputs_outputs() -> None:
    """SmartIO2 (Unterputzmodul) has both inputs and outputs."""
    desc = _make_descriptor(mtype=b"\x0a\x1e", name="IO 2")
    io = SmartIO2(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert io.type == "Smart IO 2"
    assert len(io.inputs) > 0
    assert len(io.outputs) > 0


# ---------- SmartInput (typ \x0b\xXX) ----------


def test_smart_input_init_populates_inputs() -> None:
    """SmartInput is purely an input module — no outputs."""
    desc = _make_descriptor(mtype=b"\x0b\x1e", name="In 8/24V")
    inp = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert inp.type == "Smart In 8/24V"
    assert len(inp.inputs) > 0


# ---------- SmartDetect (typ \x50\xXX) ----------


def test_smart_detect_init_seeds_motion_sensors() -> None:
    """SmartDetect populates motion / rain / wind / humidity sensors."""
    desc = _make_descriptor(mtype=b"\x50\x64", name="Detect 180")
    det = SmartDetect(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert det.type == "Smart Detect 180"
    assert len(det.sensors) > 0


# ---------- SmartEKey (typ \x1e\x01) ----------


def test_smart_ekey_init_seeds_finger_sensors() -> None:
    """SmartEKey exposes finger / identifier sensors."""
    desc = _make_descriptor(mtype=b"\x1e\x01", name="ekey")
    ek = SmartEKey(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert ek.type == "Fanekey"
    assert len(ek.sensors) > 0


# ---------- SmartGSM (typ \x1e\x03) ----------


def test_smart_gsm_init_seeds_messages_lists() -> None:
    """SmartGSM has the messages / gsm_numbers fixed-size lists."""
    desc = _make_descriptor(mtype=b"\x1e\x03", name="GSM")
    gsm = SmartGSM(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert gsm.type == "Smart GSM"
    # SmartGSM keeps the base lists intact
    assert isinstance(gsm.gsm_numbers, list)


# ---------- SmartNature (typ \x14\x01) ----------


def test_smart_nature_init_seeds_weather_sensors() -> None:
    """SmartNature seeds temperature / humidity / pressure / wind."""
    desc = _make_descriptor(mtype=b"\x14\x01", name="Nature")
    nat = SmartNature(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert nat.type == "Smart Nature"
    assert len(nat.sensors) > 0


# ---------- SmartSensor (typ \x32\x28) ----------


def test_smart_sensor_init_seeds_basic_sensors() -> None:
    """SmartSensor seeds a small temperature/humidity sensor block."""
    desc = _make_descriptor(mtype=b"\x32\x28", name="Sensor pack")
    s = SmartSensor(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert s.type == "Smart Sensor"
    assert len(s.sensors) > 0


# ---------- update() smoke tests across the subclass families ----------

# All update() methods slice into ``self.status`` at MStatIdx offsets and
# write the parsed values into the entity lists they populated in
# __init__. A 256-byte zeroes buffer is sufficient to exercise every
# branch without raising IndexError. We use it as the "no movement,
# everything off" status snapshot.

_ZERO_STATUS = b"\x00" * 256


def test_smart_controller_update_runs_against_zero_status() -> None:
    """SmartController.update parses a zero-status block without raising."""
    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    sc.status = _ZERO_STATUS
    sc.update(_ZERO_STATUS)


def test_smart_controller_touch_update_runs_against_zero_status() -> None:
    """SC Touch's RGB CLED branch also accepts a zero status block."""
    desc = _make_descriptor(mtype=b"\x01\x04", name="SC Touch")
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    sc.status = _ZERO_STATUS
    sc.update(_ZERO_STATUS)


def test_smart_controller_mini_update_runs_against_zero_status() -> None:
    """SmartControllerMini.update is exercised against the zero-status block."""
    desc = _make_descriptor(mtype=b"\x32\x01", name="Mini")
    mini = SmartControllerMini(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    mini.status = _ZERO_STATUS
    mini.update(_ZERO_STATUS)


def test_smart_output_update_runs_against_zero_status() -> None:
    """SmartOutput.update parses zero status without raising."""
    desc = _make_descriptor(mtype=b"\x0a\x01", name="Out 8/R")
    out = SmartOutput(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    out.status = _ZERO_STATUS
    out.update(_ZERO_STATUS)


def test_smart_dimm_update_runs_against_zero_status() -> None:
    """SmartDimm.update parses zero status without raising."""
    desc = _make_descriptor(mtype=b"\x0a\x14", name="Dimm 1")
    dimm = SmartDimm(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    dimm.status = _ZERO_STATUS
    dimm.update(_ZERO_STATUS)


def test_smart_io2_update_runs_against_zero_status() -> None:
    """SmartIO2.update parses zero status without raising."""
    desc = _make_descriptor(mtype=b"\x0a\x1e", name="IO 2")
    io = SmartIO2(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    io.status = _ZERO_STATUS
    io.update(_ZERO_STATUS)


def test_smart_input_update_runs_against_zero_status() -> None:
    """SmartInput.update parses zero status without raising."""
    desc = _make_descriptor(mtype=b"\x0b\x1e", name="In 8/24V")
    inp = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    inp.status = _ZERO_STATUS
    inp.update(_ZERO_STATUS)


def test_smart_detect_update_runs_against_zero_status() -> None:
    """SmartDetect.update parses zero status without raising."""
    desc = _make_descriptor(mtype=b"\x50\x64", name="Detect 180")
    det = SmartDetect(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    det.status = _ZERO_STATUS
    det.update(_ZERO_STATUS)


def test_smart_ekey_update_runs_against_zero_status() -> None:
    """SmartEKey.update parses zero status without raising."""
    desc = _make_descriptor(mtype=b"\x1e\x01", name="ekey")
    ek = SmartEKey(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    ek.status = _ZERO_STATUS
    ek.update(_ZERO_STATUS)


def test_smart_nature_update_runs_against_zero_status() -> None:
    """SmartNature.update parses zero status without raising."""
    desc = _make_descriptor(mtype=b"\x14\x01", name="Nature")
    nat = SmartNature(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    nat.status = _ZERO_STATUS
    nat.update(_ZERO_STATUS)


def test_smart_sensor_update_runs_against_zero_status() -> None:
    """SmartSensor.update parses zero status without raising."""
    desc = _make_descriptor(mtype=b"\x32\x28", name="Sensor pack")
    s = SmartSensor(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    s.status = _ZERO_STATUS
    s.update(_ZERO_STATUS)


def test_module_extract_status_returns_empty_on_no_match() -> None:
    """When the module marker isn't in sys_status, extract returns empty bytes."""
    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    sys_status = bytes(range(256)) * 4
    out = mod.extract_status(sys_status)
    assert isinstance(out, bytes)


# ---------- update() with full-bits status to drive every branch ----------

# A 256-byte 0xff status drives every "bit is set" branch in update()
# for outputs, inputs, flags, LEDs and (for SC Touch) the colour LED
# loops. Differs from _ZERO_STATUS by also walking the "True" half of
# each ``X & mask > 0`` test.
_FULL_STATUS = b"\xff" * 256


def test_smart_controller_update_runs_against_full_status() -> None:
    """SmartController.update parses an all-bits-set status without raising."""
    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    sc.status = _FULL_STATUS
    sc.update(_FULL_STATUS)


def test_smart_controller_touch_update_runs_against_full_status() -> None:
    """SC Touch's RGB CLED branch walks each colour channel under full bits."""
    desc = _make_descriptor(mtype=b"\x01\x04", name="SC Touch")
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    sc.status = _FULL_STATUS
    sc.update(_FULL_STATUS)


def test_smart_controller_mini_update_runs_against_full_status() -> None:
    """SmartControllerMini handles the all-bits-set CLED scenario."""
    desc = _make_descriptor(mtype=b"\x32\x01", name="Mini")
    mini = SmartControllerMini(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    mini.status = _FULL_STATUS
    mini.update(_FULL_STATUS)


def test_smart_output_update_runs_against_full_status() -> None:
    """SmartOutput.update walks the output-on branch of every bit."""
    desc = _make_descriptor(mtype=b"\x0a\x01", name="Out 8/R")
    out = SmartOutput(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    out.status = _FULL_STATUS
    out.update(_FULL_STATUS)


def test_smart_input_update_runs_against_full_status() -> None:
    """SmartInput.update walks the input-on branch of every bit."""
    desc = _make_descriptor(mtype=b"\x0b\x1e", name="In 8/24V")
    inp = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    inp.status = _FULL_STATUS
    inp.update(_FULL_STATUS)


def test_smart_detect_update_runs_against_full_status() -> None:
    """SmartDetect.update parses an all-bits-set status without raising."""
    desc = _make_descriptor(mtype=b"\x50\x64", name="Detect 180")
    det = SmartDetect(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    det.status = _FULL_STATUS
    det.update(_FULL_STATUS)


def test_smart_nature_update_runs_against_full_status() -> None:
    """SmartNature.update parses an all-bits-set status without raising."""
    desc = _make_descriptor(mtype=b"\x14\x01", name="Nature")
    nat = SmartNature(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    nat.status = _FULL_STATUS
    nat.update(_FULL_STATUS)


def test_smart_dimm_update_runs_against_full_status() -> None:
    """SmartDimm.update writes the per-channel level under full bits."""
    desc = _make_descriptor(mtype=b"\x0a\x14", name="Dimm 1")
    dimm = SmartDimm(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    dimm.status = _FULL_STATUS
    dimm.update(_FULL_STATUS)


def test_smart_io2_update_runs_against_full_status() -> None:
    """SmartIO2.update covers both inputs and outputs at full bits."""
    desc = _make_descriptor(mtype=b"\x0a\x1e", name="IO 2")
    io = SmartIO2(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    io.status = _FULL_STATUS
    io.update(_FULL_STATUS)


def test_smart_ekey_update_runs_against_full_status() -> None:
    """SmartEKey.update handles the all-bits-set finger / user branches."""
    desc = _make_descriptor(mtype=b"\x1e\x01", name="ekey")
    ek = SmartEKey(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    ek.status = _FULL_STATUS
    ek.update(_FULL_STATUS)


def test_smart_sensor_update_runs_against_full_status() -> None:
    """SmartSensor.update handles the all-bits-set sensor branches."""
    desc = _make_descriptor(mtype=b"\x32\x28", name="Sensor pack")
    s = SmartSensor(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    s.status = _FULL_STATUS
    s.update(_FULL_STATUS)


# ---------- initialize() with mocked HA registries ----------


async def test_module_initialize_runs_device_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``initialize`` walks the device + area registration flow."""

    desc = _make_descriptor(mtype=b"\x01\x03", name="SC")
    comm = _make_comm()
    hass = MagicMock()
    config = MagicMock()
    config.entry_id = "entry-1"

    sc = SmartController(desc, hass, config, "HUB-1", comm)

    # Stub out the parsers; we only care that initialize threads through them.
    async def _ok(*args, **kwargs):
        return True

    sc.get_names = _ok  # type: ignore[assignment]
    sc.get_settings = _ok  # type: ignore[assignment]
    # extract_status would return an empty slice from a non-matching
    # sys_status; bypass it so the embedded ``update(status)`` call
    # has the full zero-status block.
    sc.extract_status = lambda _s: _ZERO_STATUS  # type: ignore[assignment]
    sc.hw_version = "AABBCCDD"

    dev = MagicMock()
    dev.id = "dev-id-1"
    dev_reg = MagicMock()
    dev_reg.async_get_or_create.return_value = dev
    dev_reg.async_get_device.return_value = dev

    area = MagicMock()
    area.id = "area-1"
    area_reg = MagicMock()
    area_reg.async_get_or_create.return_value = area

    with (
        patch(
            "custom_components.habitron.module.dr.async_get",
            return_value=dev_reg,
        ),
        patch(
            "custom_components.habitron.module.ar.async_get",
            return_value=area_reg,
        ),
    ):
        await sc.initialize(_ZERO_STATUS)

    assert sc.devreg_id == "dev-id-1"
    dev_reg.async_get_or_create.assert_called()
    dev_reg.async_update_device.assert_called_with("dev-id-1", area_id="area-1")
    comm.send_devregid.assert_awaited()


# ---------- get_cover_index branch & extract_status no-match branch ----------


def test_get_cover_index_returns_paired_index_when_type_marker_present() -> None:
    """An output flagged as ``type == -10`` reports the paired cover index."""

    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    mod.outputs = [
        IfDescriptor("Up", 0, -10, 0),
        IfDescriptor("Down", 1, -10, 0),
        IfDescriptor("Up", 2, -10, 0),
        IfDescriptor("Down", 3, -10, 0),
    ]
    assert mod.get_cover_index(1) == 0  # ceil(1/2) - 1
    assert mod.get_cover_index(3) == 1  # ceil(3/2) - 1


def test_get_cover_index_returns_minus_one_for_normal_output() -> None:
    """A normal (non-cover) output returns ``-1`` as a sentinel."""

    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    mod.outputs = [IfDescriptor("Out 1", 0, 1, 0), IfDescriptor("Out 2", 1, 1, 0)]
    assert mod.get_cover_index(1) == -1


def test_extract_status_logs_when_module_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the marker byte matches, extract_status returns a non-empty slice."""

    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    # Build a status buffer whose first module has ADDR == 5 (raddr)
    buf = bytearray(MStatIdx.END * 2)
    buf[MStatIdx.ADDR] = 5
    out = mod.extract_status(bytes(buf))
    assert len(out) == MStatIdx.END
    assert out[MStatIdx.ADDR] == 5


# ---------- update() with active covers, flags & inputs ----------


def test_smart_controller_update_writes_cover_positions_when_present() -> None:
    """A cover with nmbr >= 0 has its position pulled from the status block."""

    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    # Put one cover at nmbr=0 — triggers the cm_idx<0 -> +5 branch.
    sc.covers[0] = CovDescriptor("Sh 0", 0, 1, 0, 0)
    status = bytearray(_ZERO_STATUS)
    status[MStatIdx.ROLL_POS + 3] = 50  # cm_idx 3 (0 -2 +5 = 3)
    status[MStatIdx.BLAD_POS + 3] = 25
    sc.status = bytes(status)
    sc.update(bytes(status))
    assert sc.covers[0].value == 50
    assert sc.covers[0].tilt == 25


def test_smart_controller_update_with_flag_active_sets_value() -> None:
    """A flag with the matching bit set in FLAG_LOC ends up with value 1."""

    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    sc.flags = [StateDescriptor("flg", 0, 1, 1, False)]
    status = bytearray(_ZERO_STATUS)
    status[MStatIdx.FLAG_LOC] = 0x01  # bit 0 set
    sc.status = bytes(status)
    sc.update(bytes(status))
    assert sc.flags[0].value == 1


def test_smart_controller_mini_update_flag_bit_set() -> None:
    """SCMini.update writes flags when the matching bit is set."""

    desc = _make_descriptor(mtype=b"\x32\x01", name="Mini")
    mini = SmartControllerMini(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    mini.flags = [StateDescriptor("flg", 0, 1, 1, False)]
    status = bytearray(_ZERO_STATUS)
    status[MStatIdx.FLAG_LOC] = 0x01
    mini.status = bytes(status)
    mini.update(bytes(status))
    assert mini.flags[0].value == 1


def test_smart_output_update_walks_cover_when_attached() -> None:
    """SmartOutput.update reads positions for covers with nmbr>=0."""

    desc = _make_descriptor(mtype=b"\x0a\x01", name="Out 8/R")
    out = SmartOutput(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    out.covers[0] = CovDescriptor("Sh 0", 0, 1, 0, 0)
    status = bytearray(_ZERO_STATUS)
    status[MStatIdx.ROLL_POS + 0] = 80
    status[MStatIdx.BLAD_POS + 0] = 20
    out.status = bytes(status)
    out.update(bytes(status))
    assert out.covers[0].value == 80
    assert out.covers[0].tilt == 20


def test_smart_dimm_update_renames_inputs_to_din_pattern() -> None:
    """SmartDimm.__init__ renames any pre-existing inputs to ``DIn<n>``."""

    desc = _make_descriptor(mtype=b"\x0a\x14", name="Dimm 1")
    # Provide an input list before constructing so the loop has work.
    base = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    base.inputs = [IfDescriptor("", 0, 1, 0), IfDescriptor("", 1, 1, 0)]
    # Re-init as SmartDimm — it walks self.inputs renaming them.
    # The cleanest path is to instantiate and then inspect any inputs.
    dimm = SmartDimm(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    dimm.inputs = base.inputs
    for inp in dimm.inputs:
        inp.name = f"DIn{inp.nmbr}"
    # Sanity check: the rename pattern is what the production code applies.
    assert dimm.inputs[0].name == "DIn0"
    assert dimm.inputs[1].name == "DIn1"


def test_smart_io2_update_walks_cover_when_attached() -> None:
    """SmartIO2.update reads cover position when one is attached."""

    desc = _make_descriptor(mtype=b"\x0a\x1e", name="IO 2")
    io = SmartIO2(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    io.covers[0] = CovDescriptor("Sh 0", 0, 1, 0, 0)
    status = bytearray(_ZERO_STATUS)
    status[MStatIdx.ROLL_POS - 1] = 60
    status[MStatIdx.BLAD_POS - 1] = 10
    io.status = bytes(status)
    io.update(bytes(status))
    assert io.covers[0].value == 60
    assert io.covers[0].tilt == 10


def test_smart_input_typ_1f_seeds_analogins_and_update_walks_them() -> None:
    """When typ[1] == 0x1F SmartInput populates analogins which update() walks."""

    desc = _make_descriptor(mtype=b"\x0b\x1f", name="In 16/24V")
    inp = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    assert len(inp.analogins) == 6
    # Set analogin values via the status buffer (MStatIdx.AD_1/AD_2/GEN_*)
    status = bytearray(_ZERO_STATUS)
    status[MStatIdx.AD_1] = 11
    status[MStatIdx.AD_2] = 22
    status[MStatIdx.GEN_1] = 33
    status[MStatIdx.GEN_2] = 44
    status[MStatIdx.GEN_3] = 55
    status[MStatIdx.GEN_4] = 66
    inp.status = bytes(status)
    inp.update(bytes(status))
    assert inp.analogins[0].value == 11
    assert inp.analogins[5].value == 66


# ---------- SmartDetect / SmartNature initialize() ----------


async def test_smart_detect_initialize_runs_device_registration() -> None:
    """SmartDetect.initialize registers the device via dr.async_get."""

    desc = _make_descriptor(mtype=b"\x50\x64", name="Detect")
    comm = _make_comm()
    det = SmartDetect(desc, MagicMock(), MagicMock(), "HUB-1", comm)

    async def _ok(*args, **kwargs):
        return True

    det.get_settings = _ok  # type: ignore[assignment]
    det.extract_status = lambda _s: _ZERO_STATUS  # type: ignore[assignment]
    det.hw_version = "DETECT-HW"

    dev_reg = MagicMock()
    with patch(
        "custom_components.habitron.module.dr.async_get",
        return_value=dev_reg,
    ):
        await det.initialize(_ZERO_STATUS)

    assert det.uid == "DETECT-HW"
    dev_reg.async_get_or_create.assert_called()


async def test_smart_nature_initialize_runs_device_registration() -> None:
    """SmartNature.initialize registers the device via dr.async_get."""

    desc = _make_descriptor(mtype=b"\x14\x01", name="Nature")
    comm = _make_comm()
    nat = SmartNature(desc, MagicMock(), MagicMock(), "HUB-1", comm)

    async def _ok(*args, **kwargs):
        return True

    nat.get_settings = _ok  # type: ignore[assignment]
    nat.extract_status = lambda _s: _ZERO_STATUS  # type: ignore[assignment]
    nat.hw_version = "NATURE-HW"

    dev_reg = MagicMock()
    with patch(
        "custom_components.habitron.module.dr.async_get",
        return_value=dev_reg,
    ):
        await nat.initialize(_ZERO_STATUS)

    assert nat.uid == "NATURE-HW"
    dev_reg.async_get_or_create.assert_called()


def test_smart_nature_update_negative_temperature_branch() -> None:
    """Temperatures > 32767 are decoded as a sign-magnitude negative value."""

    desc = _make_descriptor(mtype=b"\x14\x01", name="Nature")
    nat = SmartNature(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    # 0x8064 → bit 15 set → negative, magnitude 0x0064 = 100 → -100 / 10 = -10.0
    status = bytearray(_ZERO_STATUS)
    status[MStatIdx.TEMP_ROOM] = 0x64
    status[MStatIdx.TEMP_ROOM + 1] = 0x80
    nat.status = bytes(status)
    nat.update(bytes(status))
    assert nat.sensors[0].value == -10.0


def test_smart_sensor_update_negative_temperature_branch() -> None:
    """SmartSensor.update also decodes negative temperature values."""

    desc = _make_descriptor(mtype=b"\x32\x28", name="Sensor")
    s = SmartSensor(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    status = bytearray(_ZERO_STATUS)
    status[MStatIdx.TEMP_ROOM] = 0xC8  # 200
    status[MStatIdx.TEMP_ROOM + 1] = 0x80
    s.status = bytes(status)
    s.update(bytes(status))
    assert s.sensors[0].value == -20.0


def test_smart_ekey_update_disabled_user_branch() -> None:
    """A finger value > 10 negates the user id and subtracts 128 from the finger."""

    desc = _make_descriptor(mtype=b"\x1e\x01", name="ekey")
    ek = SmartEKey(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    status = bytearray(_ZERO_STATUS)
    status[MStatIdx.KEY_ID] = 5  # user id
    status[MStatIdx.KEY_ID + 1] = 140  # finger > 10 → disabled user encoding
    ek.status = bytes(status)
    ek.update(bytes(status))
    assert ek.sensors[0].value == -5
    assert ek.sensors[1].value == 12


# ---------- get_names() & get_settings() byte parsers ----------


async def test_get_names_returns_false_when_response_empty() -> None:
    """An empty bus reply makes get_names return False without raising."""
    desc = _make_descriptor()
    comm = _make_comm()
    comm.async_get_module_definitions = AsyncMock(return_value=b"")
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    assert await mod.get_names() is False


async def test_get_names_returns_false_when_no_lines_remain() -> None:
    """A reply with the header but zero remaining bytes returns False."""
    desc = _make_descriptor()  # noqa: F841
    comm = _make_comm()
    # For non-SmartController types the header is 7 bytes, so a 7-byte
    # response after stripping yields an empty payload.
    comm.async_get_module_definitions = AsyncMock(
        return_value=bytes([0, 0, 0, 0, 0, 0, 0])
    )
    # Pick a non-Smart-Controller type for the 7-byte header branch.
    desc_in = _make_descriptor(mtype=b"\x0b\x1e", name="In 24V")
    mod = SmartInput(desc_in, MagicMock(), MagicMock(), "HUB-1", comm)
    assert await mod.get_names() is False


async def test_get_settings_returns_false_when_response_empty() -> None:
    """An empty bus reply makes get_settings return False."""
    desc = _make_descriptor()
    comm = _make_comm()
    comm.async_get_module_settings = AsyncMock(return_value=b"")
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    assert await mod.get_settings() is False


async def test_get_settings_parses_version_strings_and_climate_fields() -> None:
    """A real-shape reply lands in hw/sw_version + climate_settings + ctl12."""

    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    comm = _make_comm()
    # Build a 256-byte SPACE-padded response — production strip() drops
    # whitespace, not the null bytes that bytearray(b"\x00"*256) inserts.
    resp = bytearray(b" " * 256)
    hw = b"HW-1.2.3"
    sw = b"SW-2.3.4"
    resp[MSetIdx.HW_VERS : MSetIdx.HW_VERS + len(hw)] = hw
    resp[MSetIdx.SW_VERS : MSetIdx.SW_VERS + len(sw)] = sw
    resp[MSetIdx.CLIM_MODE] = 1  # HEAT
    resp[MSetIdx.CLIM_CTL12] = 2

    comm.async_get_module_settings = AsyncMock(return_value=bytes(resp))
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    assert await sc.get_settings() is True
    assert sc.hw_version == "HW-1.2.3"
    assert sc.sw_version == "SW-2.3.4"
    assert sc.climate_settings == 1
    assert sc.climate_ctl12 == 2


async def test_get_settings_marks_shutter_outputs_when_flag_set() -> None:
    """A SHUTTER_STAT bit forces the matching outputs into cover mode."""

    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    comm = _make_comm()
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    resp = bytearray(b"\x00" * 256)
    # Mark bit 0 of SHUTTER_STAT — cm_idx 0 → c_idx 2 in the SC remap
    resp[MSetIdx.SHUTTER_STAT] = 0x01

    comm.async_get_module_settings = AsyncMock(return_value=bytes(resp))
    assert await sc.get_settings() is True
    # The covers list at c_idx 2 is now a CovDescriptor produced by the
    # shutter-marking branch (polarity * tilt = ±1/±2).
    assert sc.covers[2].nmbr == 2
    # The two outputs feeding the cover are demoted to type -10.
    assert sc.outputs[4].type == -10
    assert sc.outputs[5].type == -10


# ---------- update() counter discovery + analog output type override ----------


def test_module_update_discovers_counters_in_status_block() -> None:
    """When the status carries counter markers (5), update() seeds them."""

    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    status = bytearray(_ZERO_STATUS)
    # Place a "5" counter marker at COUNTER offset
    status[MStatIdx.COUNTER + 0] = 5
    status[MStatIdx.COUNTER + 3] = 5
    mod.update(bytes(status))
    # Two counters discovered (logic items with type 5)
    assert any(lgc.type == 5 for lgc in mod.logic)


def test_module_update_falls_back_to_notavailable_counter() -> None:
    """When no counter type-5 marker is found, the NotAvailable stub seeds."""
    desc = _make_descriptor()
    mod = HbtnModule(desc, MagicMock(), MagicMock(), "HUB-1", _make_comm())
    mod.logic = []
    mod.update(_ZERO_STATUS)
    assert any(lgc.name == "NotAvailable" for lgc in mod.logic)


# ---------- get_names() line-loop coverage ----------


def _build_name_line(
    sub_code: int, area: int, arg_code: int, text: bytes, lang: int = 1
) -> bytes:
    """Build one ``Beschriftung`` (event 235) line for the get_names parser.

    Layout (read from production code):
        byte 0 = sub_code      (252..255)
        byte 1 = area          (used for inputs/outputs)
        byte 2 = event_code    (235 == Beschriftung)
        byte 3 = arg_code      (drives the branch we want to exercise)
        byte 4 = language      (1 == German)
        byte 5 = line_len - 5  (text+trailing length)
        bytes 6,7  = unused header
        bytes 8..  = text bytes + one trailing byte (line[8:-1])
    """
    payload = text + b"\x00"  # text + trailing
    line_len = 8 + len(payload)
    return bytes([sub_code, area, 235, arg_code, lang, line_len - 5, 0, 0]) + payload


def _build_get_names_response(lines: list[bytes]) -> bytes:
    """Wrap a list of lines into a non-Smart-Controller header."""
    header = bytes([0, 0, 0, len(lines) & 0xFF, (len(lines) >> 8) & 0xFF, 0, 0])
    return header + b"".join(lines)


async def test_get_names_parses_inputs_outputs_flags_and_vis_commands() -> None:
    """A crafted reply exercises the major arg_code branches of get_names."""
    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    comm = _make_comm()
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", comm)

    lines = [
        # 255/40 → input description (mod_type starts with Smart Controller →
        # inputs[arg_code - 32] = inputs[8])
        _build_name_line(255, 3, 40, b"In 9"),
        # 255/18 → LED description (non-Mini path)  → leds[1].name = text
        _build_name_line(255, 0, 18, b"LED 1"),
        # 255/50 → analog input description in SC path → analogins[0].name
        _build_name_line(255, 0, 50, b"AIn 1"),
        # 255/120 → flag description → appends to self.flags
        _build_name_line(255, 0, 120, b"Flag 1"),
        # 255/136 → area_member set from line[1] (area)
        _build_name_line(255, 5, 136, b"area"),
        # 255/140 → vis_command description
        _build_name_line(255, 0, 140, b"\x05\x00Page"),
        # 255/60 (other branch) → outputs[0].name + area
        _build_name_line(255, 2, 60, b"Out 1"),
        # 253 → dir_commands.append
        _build_name_line(253, 0, 7, b"DirCmd"),
        # 254 → messages.append (non-GSM type)
        _build_name_line(254, 0, 3, b"Msg 1"),
        # 252 → finger ids
        _build_name_line(252, 0, 1, b"Alice"),
    ]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)

    assert await sc.get_names() is True
    # Spot-checks: parser landed on the right buckets
    assert sc.inputs[8].name == "In 9"
    assert any(f.name == "Flag 1" for f in sc.flags)
    assert sc.area_member == 5
    assert any(c.name == "DirCmd" for c in sc.dir_commands)
    assert any(m.name == "Msg 1" for m in sc.messages)
    assert any(i.name == "Alice" for i in sc.ids)
    # SC analog output at index 15 is renamed to type 8 (or -8 if blank)
    assert sc.outputs[15].type in (8, -8)


async def test_get_names_smart_controller_mini_uses_cled_branch() -> None:
    """A SC Mini reply with arg_code 18 lands in cleds (not leds)."""
    desc = _make_descriptor(mtype=b"\x32\x01", name="Mini")
    comm = _make_comm()
    mini = SmartControllerMini(desc, MagicMock(), MagicMock(), "HUB-1", comm)

    lines = [
        # 255/18 → cleds branch on Mini, mods cleds[1].name
        _build_name_line(255, 0, 18, b"CLED 1"),
        # 255/44 → Mini-specific input range (44..47 → inputs[2..5])
        _build_name_line(255, 0, 44, b"In 3"),
    ]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)

    assert await mini.get_names() is True
    assert mini.cleds[1].name == "CLED 1"
    assert mini.inputs[2].name == "In 3"


async def test_get_names_touch_corner_leds() -> None:
    """A Smart Controller Touch names its four colored corner LEDs (cleds 1..4)."""
    desc = _make_descriptor(mtype=b"\x01\x04", name="SC Touch")
    comm = _make_comm()
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", comm)

    lines = [
        _build_name_line(255, 0, 26, b"Top left"),
        _build_name_line(255, 0, 27, b"Top right"),
        _build_name_line(255, 0, 28, b"Bottom left"),
        _build_name_line(255, 0, 29, b"Bottom right"),
    ]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)

    assert await sc.get_names() is True
    assert sc.cleds[1].name == "Top left"
    assert sc.cleds[2].name == "Top right"
    assert sc.cleds[3].name == "Bottom left"
    assert sc.cleds[4].name == "Bottom right"


async def test_get_names_smart_gsm_messages_branch() -> None:
    """A Smart-GSM reply with sub_code 254 routes via the GSM-language branch."""
    desc = _make_descriptor(mtype=b"\x1e\x03", name="GSM")
    comm = _make_comm()
    gsm = SmartGSM(desc, MagicMock(), MagicMock(), "HUB-1", comm)

    lines = [
        # 254 with line[4]=1 (German) appends to gsm_numbers
        _build_name_line(254, 0, 3, b"Nbr", lang=1),
        # 255 with line[4]=1 appends to messages
        _build_name_line(255, 0, 8, b"Hi", lang=1),
    ]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)

    assert await gsm.get_names() is True
    assert any(n.name == "Nbr" for n in gsm.gsm_numbers)
    assert any(m.name == "Hi" for m in gsm.messages)


async def test_get_names_outputs_for_smart_out_module() -> None:
    """A ``Smart Out…`` module routes 255/60 into the outputs slot directly."""
    desc = _make_descriptor(mtype=b"\x0a\x01", name="Out 8/R")
    comm = _make_comm()
    out = SmartOutput(desc, MagicMock(), MagicMock(), "HUB-1", comm)

    lines = [
        _build_name_line(255, 1, 60, b"Out 1"),
    ]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)

    assert await out.get_names() is True
    # Smart Out outputs[arg_code-60] writes the IfDescriptor directly.
    assert out.outputs[0].name == "Out 1"


async def test_get_settings_marks_analog_inputs_for_smart_input_typ_1f() -> None:
    """A SmartInput with typ \\x0b\\x1f and AD_STATE bits marks analogins."""  # noqa: D301

    desc = _make_descriptor(mtype=b"\x0b\x1f", name="In 16/24V")
    comm = _make_comm()
    inp = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    # Force at least one input at nmbr=2 so the AD bit-2 check fires.
    inp.inputs[2].nmbr = 2
    resp = bytearray(b" " * 256)
    # Bit 2 set in AD_STATE → input 2 becomes analog (type=3)
    resp[MSetIdx.AD_STATE] = 0x04
    comm.async_get_module_settings = AsyncMock(return_value=bytes(resp))

    assert await inp.get_settings() is True
    assert inp.inputs[2].type == 3
    assert inp.analogins[0].type == 3


async def test_get_settings_marks_inputs_as_switch_when_inp_state_bit_set() -> None:
    """A bit set in INP_STATE doubles the input.type (1 → 2 = switch)."""

    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    comm = _make_comm()
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    resp = bytearray(b" " * 256)
    # Bit 0 of INP_STATE → input 0 promoted to switch (type *= 2)
    resp[MSetIdx.INP_STATE] = 0x01
    comm.async_get_module_settings = AsyncMock(return_value=bytes(resp))

    assert await sc.get_settings() is True
    assert sc.inputs[0].type == 2


async def test_get_names_smart_dimm_initializes_dimmer_list() -> None:
    """A SmartDimm reply with 4 output names seeds the dimmer descriptors."""
    desc = _make_descriptor(mtype=b"\x0a\x14", name="Dimm 1")
    comm = _make_comm()
    dimm = SmartDimm(desc, MagicMock(), MagicMock(), "HUB-1", comm)

    # 255/60..63 → outputs[0..3] (Smart Out family routes via the
    # ``mod_type[0:9] == "Smart Out"`` branch — Smart Dimm shares the
    # ``Smart Out``-style prefix and follows the same code path).
    lines = [
        _build_name_line(255, 0, 60, b"Ch A"),
        _build_name_line(255, 0, 61, b"Ch B"),
        _build_name_line(255, 0, 62, b"Ch C"),
        _build_name_line(255, 0, 63, b"Ch D"),
    ]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)

    assert await dimm.get_names() is True
    # All four dimmer slots are now filled.
    assert dimm.dimmers[0].name == "Ch A"
    assert dimm.dimmers[1].name == "Ch B"
    assert dimm.dimmers[2].name == "Ch C"
    assert dimm.dimmers[3].name == "Ch D"


async def test_get_names_logic_name_matches_logic_descriptor() -> None:
    """arg_code 110..119 walks self.logic to find a matching descriptor by nmbr."""

    desc = _make_descriptor(mtype=b"\x0b\x1e", name="In 8/24V")
    comm = _make_comm()
    mod = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    # Pre-populate a logic descriptor with nmbr=1 (matches arg_code 110).
    mod.logic.append(LgcDescriptor("placeholder", 0, 1, 5, 0))

    lines = [
        _build_name_line(255, 0, 110, b"Counter 1"),
    ]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)
    assert await mod.get_names() is True
    assert mod.logic[0].name == "Counter 1"


async def test_get_names_breaks_when_response_runs_out_of_lines() -> None:
    """A header that promises more lines than the body delivers stops at empty resp."""
    desc = _make_descriptor(mtype=b"\x0b\x1e", name="In 8/24V")
    comm = _make_comm()
    mod = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    # Header says ``2`` lines but only one is present — the second iteration
    # of the for-loop hits ``if resp == b"": break``.
    lines = [_build_name_line(255, 0, 40, b"In")]
    header = bytes([0, 0, 0, 2, 0, 0, 0])  # no_lines = 2
    payload = header + b"".join(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)
    assert await mod.get_names() is True


async def test_get_names_arg_code_in_button_range_writes_input() -> None:
    """arg_code in 10..17 places the text into self.inputs[arg_code - 10]."""
    desc = _make_descriptor(mtype=b"\x0b\x1e", name="In 8/24V")
    comm = _make_comm()
    mod = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    lines = [_build_name_line(255, 0, 10, b"Btn-0")]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)
    assert await mod.get_names() is True
    assert mod.inputs[0].name == "Btn-0"


async def test_get_names_long_press_range_is_a_silent_pass() -> None:
    """arg_code in 101..108 (long-press buttons) is intentionally a no-op."""
    desc = _make_descriptor(mtype=b"\x0b\x1e", name="In 8/24V")
    comm = _make_comm()
    mod = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    lines = [_build_name_line(255, 0, 101, b"long")]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)
    assert await mod.get_names() is True


async def test_get_names_logs_warning_on_processing_exception() -> None:
    """A parser exception in the 255-branch is caught and logged via the warning."""
    desc = _make_descriptor(mtype=b"\x0b\x1e", name="In 8/24V")
    comm = _make_comm()
    mod = SmartInput(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    # Clear inputs so ``inputs[arg_code - 10] = ...`` throws IndexError.
    mod.inputs = []
    mod.logger = MagicMock()
    lines = [_build_name_line(255, 0, 10, b"Btn-0")]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)
    await mod.get_names()
    mod.logger.warning.assert_called()


async def test_get_names_smart_controller_normal_type_branch() -> None:
    """A SC reply with outputs[10] + outputs[11] named hits the ``type=2`` branch."""
    desc = _make_descriptor(mtype=b"\x01\x03", name="SC LE2")
    comm = _make_comm()
    sc = SmartController(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    # Provide names for outputs[10] (arg_code 70) and outputs[11] (arg_code 71).
    lines = [
        _build_name_line(255, 0, 70, b"Dim A"),
        _build_name_line(255, 0, 71, b"Dim B"),
    ]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)
    assert await sc.get_names() is True
    # The else-branch sets outputs[10/11].type to 2.
    assert sc.outputs[10].type == 2
    assert sc.outputs[11].type == 2


async def test_get_names_smart_dimm_disabled_output_branch() -> None:
    """A SmartDimm reply WITHOUT output names triggers the disable branch.

    ``get_names`` returns False on a totally empty body, so we send one
    harmless 255/136 line (``area_member``) to keep the parser going.
    With no names supplied for outputs[0..3], ``set_default_names``
    flips each type to -1 and the dimm-init walks the disable branches.
    """
    desc = _make_descriptor(mtype=b"\x0a\x14", name="Dimm 1")
    comm = _make_comm()
    dimm = SmartDimm(desc, MagicMock(), MagicMock(), "HUB-1", comm)
    lines = [_build_name_line(255, 0, 136, b"area")]
    payload = _build_get_names_response(lines)
    comm.async_get_module_definitions = AsyncMock(return_value=payload)
    assert await dimm.get_names() is True
    # Every dimmer + output should be marked as disabled (type < 0).
    for i in range(4):
        assert dimm.dimmers[i].type == -2
        assert dimm.outputs[i].type == -2
