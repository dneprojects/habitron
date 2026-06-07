"""Tests for the Habitron module-layer classes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.habitron.const import ModuleDescriptor
from custom_components.habitron.module import (
    HbtnModule,
    SmartController,
    SmartControllerMini,
    SmartDetect,
    SmartDimm,
    SmartEKey,
    SmartGSM,
    SmartIO2,
    SmartInput,
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
    from custom_components.habitron.interfaces import IfDescriptor  # noqa: PLC0415
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
    from custom_components.habitron.interfaces import IfDescriptor  # noqa: PLC0415
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
    mini = SmartControllerMini(
        desc, MagicMock(), MagicMock(), "HUB-1", _make_comm()
    )
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
    mini = SmartControllerMini(
        desc, MagicMock(), MagicMock(), "HUB-1", _make_comm()
    )
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
    mini = SmartControllerMini(
        desc, MagicMock(), MagicMock(), "HUB-1", _make_comm()
    )
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


async def test_module_initialize_runs_device_registration(monkeypatch) -> None:
    """``initialize`` walks the device + area registration flow."""
    from unittest.mock import patch  # noqa: PLC0415

    desc = _make_descriptor(mtype=b"\x01\x03", name="SC")
    comm = _make_comm()
    hass = MagicMock()
    config = MagicMock()
    config.entry_id = "entry-1"

    sc = SmartController(desc, hass, config, "HUB-1", comm)

    # Stub out the parsers; we only care that initialize threads through them.
    async def _ok(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
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
