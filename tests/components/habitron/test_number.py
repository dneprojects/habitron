"""Tests for the Habitron number platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Area, Dimmer, Module, Router, SetValue

from custom_components.habitron.number import (
    HbtnAnalogOutput,
    HbtnSetTemperature,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant


def _module(uid: str = "MOD-1", **kwargs) -> Module:
    return Module(uid=uid, addr=105, typ=b"\x01\x02", name="Mod", **kwargs)


def _coord() -> MagicMock:
    coord = MagicMock()
    coord.comm = MagicMock()
    coord.comm.async_set_setpoint = AsyncMock()
    coord.comm.async_set_analog_val = AsyncMock()
    coord.async_request_refresh = AsyncMock()
    return coord


# ---------------------------------------------------------------------------
# HbtnSetTemperature
# ---------------------------------------------------------------------------


def test_set_temperature_unique_id_and_value() -> None:
    """The set-temperature number reflects the set value and a stable id."""
    setval = SetValue(name="Set temperature", nmbr=0, type=2, value=21.5)
    entity = HbtnSetTemperature(setval, _module(), _coord(), 0)
    assert entity.unique_id == "Mod_MOD-1_number48"
    assert entity.native_value == 21.5


async def test_set_temperature_set_value_forwards_setpoint() -> None:
    """Setting a value forwards a tenths-of-degree setpoint to the bus."""
    coord = _coord()
    setval = SetValue(name="Set temperature", nmbr=1, type=2, value=20.0)
    entity = HbtnSetTemperature(setval, _module(), coord, 0)
    await entity.async_set_native_value(22.0)
    coord.comm.async_set_setpoint.assert_awaited_with(105, 2, 220)
    coord.async_request_refresh.assert_awaited()


# ---------------------------------------------------------------------------
# HbtnAnalogOutput
# ---------------------------------------------------------------------------


def test_analog_output_unique_id_and_value() -> None:
    """The analogue output number reflects the dimmer brightness."""
    analog = Dimmer(name="AOut", nmbr=15, type=8, brightness=50)
    entity = HbtnAnalogOutput(analog, _module(), _coord(), 0)
    assert entity.unique_id == "Mod_MOD-1_out15"
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.native_value == 50


def test_analog_output_negative_type_disabled() -> None:
    """A negative analogue-output type disables the entity by default."""
    analog = Dimmer(name="AOut", nmbr=15, type=-8)
    entity = HbtnAnalogOutput(analog, _module(), _coord(), 0)
    assert entity._attr_entity_registry_enabled_default is False


async def test_analog_output_set_value() -> None:
    """Setting a value writes the model + forwards to the bus."""
    coord = _coord()
    analog = Dimmer(name="AOut", nmbr=15, type=8)
    entity = HbtnAnalogOutput(analog, _module(), coord, 0)
    await entity.async_set_native_value(42.0)
    assert analog.brightness == 42
    coord.comm.async_set_analog_val.assert_awaited_with(105, 16, 42)
    coord.async_request_refresh.assert_awaited()


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_async_setup_entry_emits_setvalue_and_analog(hass: HomeAssistant) -> None:
    """async_setup_entry creates set-temperature and analogue-output numbers."""
    module = _module()
    module.setvalues = [SetValue(name="Set temperature", nmbr=0, type=2, value=20.0)]
    module.analog_outputs = [Dimmer(name="AOut", nmbr=15, type=8)]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    router.areas = [Area(nmbr=0, name="House")]
    entry = MagicMock()
    entry.runtime_data.router = router
    entry.runtime_data.coordinator = _coord()

    added: list = []
    with patch("custom_components.habitron.number.er.async_get") as mock_get:
        mock_get.return_value.async_get_entity_id = MagicMock(return_value=None)
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, HbtnSetTemperature) for e in added)
    assert any(isinstance(e, HbtnAnalogOutput) for e in added)
