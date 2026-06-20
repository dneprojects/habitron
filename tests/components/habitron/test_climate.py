"""Tests for the Habitron climate platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock

from habitron_client import Module, Router, Sensor, SetValue

from custom_components.habitron.climate import HbtnClimate, async_setup_entry
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant


def _coord() -> MagicMock:
    coord = MagicMock()
    coord.comm = MagicMock()
    coord.comm.async_set_setpoint = AsyncMock()
    coord.comm.async_set_climate_mode = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=lambda: None)
    return coord


def _module(
    *, climate_settings: int = 1, room: float = 20.0, target: float = 22.0, **kwargs
) -> Module:
    """Build a Smart Controller module with climate sensors/setvalues."""
    module = Module(
        uid="MOD-1",
        addr=105,
        typ=b"\x01\x02",
        name="SC",
        mod_type="Smart Controller XL-2",
        climate_settings=climate_settings,
        **kwargs,
    )
    module.sensors = [
        Sensor(name="Movement", nmbr=0, type=2, value=0),
        Sensor(name="Temperature", nmbr=1, type=2, value=room),
        Sensor(name="Temperature ext.", nmbr=2, type=2, value=room),
        Sensor(name="Humidity", nmbr=3, type=2, value=45),
    ]
    module.setvalues = [
        SetValue(name="Set temperature", nmbr=0, type=2, value=target),
        SetValue(name="Set temperature 2", nmbr=1, type=2, value=target),
    ]
    return module


def test_climate_unique_id_and_readings() -> None:
    """The climate entity exposes a unique id and reads temp/target/humidity."""
    entity = HbtnClimate(_module(room=19.0, target=23.0), _coord(), 0)
    assert entity.unique_id == "Mod_MOD-1_climate"
    assert entity.current_temperature == 19.0
    assert entity.target_temperature == 23.0
    assert entity.current_humidity == 45


def test_climate_second_unit_unique_id() -> None:
    """The second controller climate gets a distinct unique id."""
    entity = HbtnClimate(_module(), _coord(), 1)
    assert entity.unique_id == "Mod_MOD-1_climate_2"


def test_climate_hvac_mode_mapping() -> None:
    """climate_settings maps to the HA HVAC mode."""
    assert (
        HbtnClimate(_module(climate_settings=1), _coord(), 0).hvac_mode is HVACMode.HEAT
    )
    assert (
        HbtnClimate(_module(climate_settings=2), _coord(), 0).hvac_mode is HVACMode.COOL
    )
    assert (
        HbtnClimate(_module(climate_settings=4), _coord(), 0).hvac_mode is HVACMode.OFF
    )


def test_climate_hvac_action_heating() -> None:
    """Below target in HEAT mode reports HEATING."""
    entity = HbtnClimate(
        _module(climate_settings=1, room=18.0, target=22.0), _coord(), 0
    )
    assert entity.hvac_action is HVACAction.HEATING


def test_climate_hvac_action_off() -> None:
    """OFF mode reports the OFF action."""
    entity = HbtnClimate(_module(climate_settings=4), _coord(), 0)
    assert entity.hvac_action is HVACAction.OFF


def test_climate_second_unit_enabled_default_follows_ctl12() -> None:
    """Unit 2 is enabled by default only when the module runs dual control."""
    enabled = HbtnClimate(_module(climate_ctl12=2), _coord(), 1)
    assert enabled.entity_registry_enabled_default is True
    disabled = HbtnClimate(_module(climate_ctl12=1), _coord(), 1)
    assert disabled.entity_registry_enabled_default is False


async def test_climate_set_temperature() -> None:
    """Setting a temperature forwards a tenths-of-degree setpoint."""
    coord = _coord()
    entity = HbtnClimate(_module(), coord, 0)
    await entity.async_set_temperature(**{ATTR_TEMPERATURE: 21.5})
    coord.comm.async_set_setpoint.assert_awaited_with(105, 1, 215)
    coord.async_request_refresh.assert_awaited()


async def test_climate_set_hvac_mode() -> None:
    """Setting an HVAC mode writes the climate mode to the bus."""
    coord = _coord()
    module = _module(climate_ctl12=1)
    entity = HbtnClimate(module, coord, 0)
    await entity.async_set_hvac_mode(HVACMode.COOL)
    assert module.climate_settings == 2
    coord.comm.async_set_climate_mode.assert_awaited_with(105, 2, 1)


async def test_async_setup_entry_emits_two_units_for_controller(
    hass: HomeAssistant,
) -> None:
    """A Smart Controller (typ[0]==1) yields two climate units."""
    module = _module()
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    entry = MagicMock()
    entry.runtime_data.router = router
    entry.runtime_data.coordinator = _coord()

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    assert sum(isinstance(e, HbtnClimate) for e in added) == 2
