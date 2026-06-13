"""Tests for the Habitron number platform."""

from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.number import (
    HbtnAnalogOutput,
    HbtnSetTemperature,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant

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


def test_set_temperature_device_info_name_and_handle_update() -> None:
    """device_info + name + _handle_coordinator_update for HbtnSetTemperature."""
    sp = _make_setpoint()
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnSetTemperature(sp, mod, coord, 0)
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]
    assert entity.name == "Set temp 1"
    sp.value = 22.5
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_native_value == 22.5


def test_analog_output_empty_name_falls_back_to_default() -> None:
    """An empty output name produces ``Out <nmbr+1>``."""
    out = _make_output(name=" ", nmbr=2)
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnAnalogOutput(out, mod, coord, 0)
    assert entity._attr_name == "Out 3"


def test_analog_output_negative_type_disabled_by_default() -> None:
    """A negative output.type marks the entity disabled by default."""
    out = _make_output(type_=-8)
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnAnalogOutput(out, mod, coord, 0)
    assert entity._attr_entity_registry_enabled_default is False


def test_analog_output_device_info_and_name_property() -> None:
    """device_info + name properties on HbtnAnalogOutput."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnAnalogOutput(out, mod, coord, 0)
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]
    assert entity.name == "Analog 1"


async def test_async_setup_entry_adds_temperature_and_analog(
    hass: HomeAssistant,
) -> None:
    """async_setup_entry emits SetTemperature for setvalues and AnalogOutput."""
    sp = _make_setpoint()
    out = _make_output(type_=8, nmbr=0)
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.area_member = 0
    mod.setvalues = [sp]
    mod.outputs = [out]
    mod.comm.async_set_analog_val = AsyncMock()
    mod.comm.async_set_setpoint = AsyncMock()

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    with patch("custom_components.habitron.number.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="number.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, HbtnSetTemperature) for e in added)
    assert any(isinstance(e, HbtnAnalogOutput) for e in added)


async def test_async_setup_entry_external_area_assigns_id(hass: HomeAssistant) -> None:
    """When mod_output.area is not the module's area_member the area_id is assigned."""
    out = _make_output(type_=8, nmbr=0)
    out.area = 5
    mod = MagicMock()
    mod.uid = "MOD-A"
    mod.mod_addr = 105
    mod.area_member = 0
    mod.setvalues = []
    mod.outputs = [out]

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    area = MagicMock()
    area.get_name_id = MagicMock(return_value="area_5_id")
    router.areas = {0: area, 5: area}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch("custom_components.habitron.number.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="number.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_called_with("number.fake", area_id="area_5_id")
