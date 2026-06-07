"""Tests for the Habitron climate platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.climate import HVACMode
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.climate import HbtnClimate


async def test_climate_setup(setup_integration: MockConfigEntry) -> None:
    """The climate platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def _make_climate_module() -> MagicMock:
    """Build a stub module with the setvalues + sensors a climate entity reads.

    Two setpoints and two reading sensors are required for the second
    controller index to map correctly.
    """
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105

    def _val(v: float) -> MagicMock:
        s = MagicMock()
        s.value = v
        return s

    mod.setvalues = [_val(21.5), _val(22.0)]
    mod.sensors = [_val(21.0), _val(21.5), _val(22.0), _val(45.0)]
    mod.climate_ctl12 = 0
    mod.climate_settings = 1  # HEAT mode
    mod.comm.async_set_setpoint = AsyncMock()
    mod.comm.async_set_climate_mode = AsyncMock()
    return mod


def test_climate_first_unit_unique_id_and_name() -> None:
    """The first controller index is named ``Climate`` with a stable id."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 0)
    assert climate.unique_id == "Mod_MOD-1_climate"
    assert climate._attr_name == "Climate"


def test_climate_second_unit_has_distinct_unique_id() -> None:
    """The second controller index gets a distinct id and name."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 1)
    assert "climate" in climate.unique_id
    assert climate.unique_id != "Mod_MOD-1_climate"


def test_climate_attr_temperature_unit_is_celsius() -> None:
    """Habitron reports temperatures in Celsius."""
    from homeassistant.const import UnitOfTemperature  # noqa: PLC0415

    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 0)
    assert climate.temperature_unit == UnitOfTemperature.CELSIUS


def test_climate_hvac_modes_include_heat_cool() -> None:
    """The HVAC mode list covers OFF / HEAT / COOL / HEAT_COOL."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 0)
    assert HVACMode.OFF in climate.hvac_modes
    assert HVACMode.HEAT in climate.hvac_modes
    assert HVACMode.COOL in climate.hvac_modes
    assert HVACMode.HEAT_COOL in climate.hvac_modes


async def test_climate_set_temperature_forwards_to_setpoint() -> None:
    """async_set_temperature calls async_set_setpoint with the integer °C * 10."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    coord.async_request_refresh = AsyncMock()
    climate = HbtnClimate(mod, coord, 0)
    climate.async_write_ha_state = MagicMock()
    await climate.async_set_temperature(temperature=23.0)
    mod.comm.async_set_setpoint.assert_awaited_with(105, 1, 230)
    coord.async_request_refresh.assert_awaited()
