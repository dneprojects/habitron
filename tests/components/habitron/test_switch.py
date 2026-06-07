"""Tests for the Habitron switch platform."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from unittest.mock import AsyncMock, MagicMock

from custom_components.habitron.switch import (
    ClimateCtlSwitch,
    HbtnFlag,
    MicrophoneSwitch,
    SwitchedOutput,
)

from .conftest import class_attr


async def test_switch_setup(setup_integration: MockConfigEntry) -> None:
    """The switch platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_keys_set() -> None:
    """State-based switch entities expose translation keys for icons."""
    assert class_attr(HbtnFlag, "_attr_translation_key") == "habitron_flag"
    assert class_attr(MicrophoneSwitch, "_attr_translation_key") == "microphone"
    assert class_attr(ClimateCtlSwitch, "_attr_translation_key") == "climate_ctl"


def _make_output(name: str = "Out 1", nmbr: int = 0, type_: int = 1) -> MagicMock:
    """Build a stub IfDescriptor for switch outputs."""
    out = MagicMock()
    out.nmbr = nmbr
    out.name = name
    out.type = type_
    out.area = 0
    out.value = 0
    return out


def _make_module() -> MagicMock:
    """Build a stub HbtnModule with output and address."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.comm.async_set_output = AsyncMock()
    return mod


def test_switched_output_unique_id_and_state() -> None:
    """SwitchedOutput exposes a stable unique id and initial off state."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_out0"


async def test_switched_output_turn_on_forwards_to_comm() -> None:
    """``async_turn_on`` calls ``module.comm.async_set_output`` with 1."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    await entity.async_turn_on()
    mod.comm.async_set_output.assert_awaited_with(105, 1, 1)


async def test_switched_output_turn_off_forwards_to_comm() -> None:
    """``async_turn_off`` calls ``module.comm.async_set_output`` with 0."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    await entity.async_turn_off()
    mod.comm.async_set_output.assert_awaited_with(105, 1, 0)


def test_switched_output_handles_coordinator_update_on() -> None:
    """_handle_coordinator_update flips is_on when the output is set."""
    out = _make_output()
    out.value = 1
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_is_on is True


def test_switched_output_handles_coordinator_update_off() -> None:
    """_handle_coordinator_update flips is_on=False when value is 0."""
    out = _make_output()
    out.value = 0
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_is_on is False


def _make_led_descriptor(nmbr: int = 0) -> MagicMock:
    """Build a stub IfDescriptor for SwitchedLed."""
    led = MagicMock()
    led.nmbr = nmbr
    led.name = f"LED {nmbr}"
    led.type = 1
    led.value = 0
    return led


def _make_led_module() -> MagicMock:
    """Build a stub HbtnModule for a SwitchedLed entity."""
    mod = _make_module()
    mod.comm.async_set_led_outp = AsyncMock()
    return mod


async def test_switched_led_turn_on_calls_comm() -> None:
    """SwitchedLed.async_turn_on forwards to ``comm.async_set_led_outp``."""
    from custom_components.habitron.switch import SwitchedLed  # noqa: PLC0415
    led = _make_led_descriptor(nmbr=1)
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    await entity.async_turn_on()
    mod.comm.async_set_led_outp.assert_awaited_with(105, 1, 1)


def _make_flag_descriptor(nmbr: int = 0) -> MagicMock:
    """Build a stub StateDescriptor for HbtnFlag."""
    flag = MagicMock()
    flag.nmbr = nmbr
    flag.name = "Test flag"
    flag.type = 1
    flag.value = 0
    return flag


def _make_flag_module() -> MagicMock:
    """Build a stub HbtnModule for HbtnFlag tests."""
    mod = _make_module()
    mod.comm.async_set_flag = AsyncMock()
    return mod


async def test_habitron_flag_turn_on_forwards_to_comm() -> None:
    """HbtnFlag.async_turn_on writes 1 to the bus."""
    flag = _make_flag_descriptor(nmbr=5)
    mod = _make_flag_module()
    coord = MagicMock()
    entity = HbtnFlag(flag, mod, coord, 0)
    await entity.async_turn_on()
    mod.comm.async_set_flag.assert_awaited()


async def test_habitron_flag_turn_off_forwards_to_comm() -> None:
    """HbtnFlag.async_turn_off writes 0 to the bus."""
    flag = _make_flag_descriptor(nmbr=5)
    mod = _make_flag_module()
    coord = MagicMock()
    entity = HbtnFlag(flag, mod, coord, 0)
    await entity.async_turn_off()
    mod.comm.async_set_flag.assert_awaited()


def test_habitron_flag_handles_coordinator_update() -> None:
    """HbtnFlag._handle_coordinator_update mirrors the flag value."""
    flag = _make_flag_descriptor()
    flag.value = 1
    mod = _make_flag_module()
    coord = MagicMock()
    entity = HbtnFlag(flag, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.is_on is True


def test_climate_ctl_switch_initial_state_from_climate_ctl12() -> None:
    """ClimateCtlSwitch derives its initial state from module.climate_ctl12."""
    mod = _make_module()
    mod.climate_ctl12 = 2
    mod.comm.async_set_climate_mode = AsyncMock()
    entity = ClimateCtlSwitch(mod)
    assert entity.is_on is True
    mod.climate_ctl12 = 0
    assert entity.is_on is False


async def test_climate_ctl_switch_turn_on_sets_module_state() -> None:
    """ClimateCtlSwitch.async_turn_on flips climate_ctl12 to 2."""
    mod = _make_module()
    mod.climate_ctl12 = 0
    mod.comm.async_set_climate_mode = AsyncMock()
    entity = ClimateCtlSwitch(mod)
    await entity.async_turn_on()
    assert mod.climate_ctl12 == 2


async def test_climate_ctl_switch_turn_off_sets_module_state() -> None:
    """ClimateCtlSwitch.async_turn_off flips climate_ctl12 to 1."""
    mod = _make_module()
    mod.climate_ctl12 = 2
    mod.comm.async_set_climate_mode = AsyncMock()
    entity = ClimateCtlSwitch(mod)
    await entity.async_turn_off()
    assert mod.climate_ctl12 == 1
