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
