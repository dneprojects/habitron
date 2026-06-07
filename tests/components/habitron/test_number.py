"""Tests for the Habitron number platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.number import HbtnAnalogOutput, HbtnSetTemperature

from .conftest import class_attr


async def test_number_setup(setup_integration: MockConfigEntry) -> None:
    """The number platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_key() -> None:
    """HbtnAnalogOutput uses the icon-translation key."""
    assert class_attr(HbtnAnalogOutput, "_attr_translation_key") == "analog_output"


def _make_output(name: str = "Analog 1", nmbr: int = 0, type_: int = 8) -> MagicMock:
    out = MagicMock()
    out.nmbr = nmbr
    out.name = name
    out.type = type_
    out.area = 0
    out.value = 50
    return out


def _make_module() -> MagicMock:
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.comm.async_set_analog_val = AsyncMock()
    mod.comm.async_set_setpoint = AsyncMock()
    return mod


def test_analog_output_unique_id_and_initial_value() -> None:
    """HbtnAnalogOutput exposes a stable unique id."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    coord.last_update_success = True
    entity = HbtnAnalogOutput(out, mod, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_out0"


def test_analog_output_handles_coordinator_update() -> None:
    """_handle_coordinator_update mirrors the output value."""
    out = _make_output()
    out.value = 75
    mod = _make_module()
    coord = MagicMock()
    coord.last_update_success = True
    entity = HbtnAnalogOutput(out, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_native_value == 75


async def test_analog_output_set_native_value_forwards_to_comm() -> None:
    """async_set_native_value forwards integer value to async_set_analog_val."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    coord.last_update_success = True
    coord.async_request_refresh = AsyncMock()
    entity = HbtnAnalogOutput(out, mod, coord, 0)
    await entity.async_set_native_value(85)
    mod.comm.async_set_analog_val.assert_awaited_with(105, 1, 85)


def _make_setpoint() -> MagicMock:
    sp = MagicMock()
    sp.nmbr = 0
    sp.name = "Set temp 1"
    sp.value = 21.5
    return sp


def test_set_temperature_unique_id_and_name() -> None:
    """HbtnSetTemperature has a stable unique id and inherits the setpoint name."""
    sp = _make_setpoint()
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnSetTemperature(sp, mod, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_number48"
    assert entity._attr_name == "Set temp 1"
    assert entity._attr_native_value == 21.5


async def test_set_temperature_forwards_via_setpoint() -> None:
    """async_set_native_value forwards integer °C * 10 to the bus."""
    sp = _make_setpoint()
    mod = _make_module()
    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    entity = HbtnSetTemperature(sp, mod, coord, 0)
    await entity.async_set_native_value(23.0)
    mod.comm.async_set_setpoint.assert_awaited_with(105, 1, 230)
