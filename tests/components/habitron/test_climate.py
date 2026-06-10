"""Tests for the Habitron climate platform."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.climate import HbtnClimate, async_setup_entry


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


async def test_climate_set_temperature_without_temp_kwarg_noop() -> None:
    """No ``temperature`` kwarg → no upstream call."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    coord.async_request_refresh = AsyncMock()
    climate = HbtnClimate(mod, coord, 0)
    await climate.async_set_temperature()
    mod.comm.async_set_setpoint.assert_not_called()


def test_climate_device_info_links_to_module_uid() -> None:
    """device_info exposes the module uid identifier."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 0)
    info = climate.device_info
    assert ("habitron", "MOD-1") in info["identifiers"]


def test_climate_min_max_temp_step() -> None:
    """min_temp/max_temp + target step report fixed defaults."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 0)
    assert climate.min_temp == 12.5
    assert climate.max_temp == 27.5
    assert climate.target_temperature_step == 0.5


def test_climate_current_temperature_target_temperature_humidity() -> None:
    """The active properties expose the cached sensor values."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 0)
    assert climate.current_temperature == 21.5  # sensors[1]
    assert climate.target_temperature == 21.5  # setvalues[0]
    assert climate.current_humidity == 45  # sensors[3]


def test_climate_current_humidity_none_when_unmapped() -> None:
    """current_humidity falls back to None when not set."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 0)
    climate._curr_humidity = None
    assert climate.current_humidity is None


def test_climate_hvac_mode_property_reads_internal_state() -> None:
    """hvac_mode mirrors the cached _curr_hvac_mode."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 0)
    assert climate.hvac_mode == HVACMode.HEAT


def test_climate_entity_registry_enabled_default_first_unit_always_true() -> None:
    """First unit (idx 0) is always enabled by default."""
    mod = _make_climate_module()
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 0)
    assert climate.entity_registry_enabled_default is True


def test_climate_entity_registry_enabled_default_second_unit_dual_mode() -> None:
    """Second unit (idx 1) is enabled only when climate_ctl12 == 2."""
    mod = _make_climate_module()
    mod.climate_ctl12 = 2
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 1)
    assert climate.entity_registry_enabled_default is True


def test_climate_entity_registry_enabled_default_second_unit_single_mode() -> None:
    """Second unit (idx 1) is disabled when climate_ctl12 != 2."""
    mod = _make_climate_module()
    mod.climate_ctl12 = 0
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 1)
    assert climate.entity_registry_enabled_default is False


def test_climate_handle_coordinator_update_refreshes_state() -> None:
    """_handle_coordinator_update updates local state and writes."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.last_update_success = True
    climate = HbtnClimate(mod, coord, 0)
    climate.async_write_ha_state = MagicMock()
    # Change underlying values
    mod.sensors[1].value = 30.0
    mod.setvalues[0].value = 24.0
    climate._handle_coordinator_update()
    assert climate._curr_temperature == 30.0
    assert climate._target_temperature == 24.0
    climate.async_write_ha_state.assert_called()


def test_climate_update_local_state_single_sensor_path() -> None:
    """When only one sensor exists, _update_local_state uses sensors[0]."""
    mod = _make_climate_module()
    # Drop sensors to a single entry
    mod.sensors = mod.sensors[:1]
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 0)
    # init already ran with len 4 — reset to single + call again
    assert climate._curr_temperature == mod.sensors[0].value


def test_climate_update_action_heating() -> None:
    """HEAT mode with temperature below target → HEATING action."""
    mod = _make_climate_module()
    mod.climate_settings = 1
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 0)
    climate._target_temperature = 22.0
    climate._curr_temperature = 19.0
    climate.update_action()
    assert climate.hvac_action == HVACAction.HEATING


def test_climate_update_action_cooling() -> None:
    """COOL mode with temperature above target → COOLING action."""
    mod = _make_climate_module()
    mod.climate_settings = 2
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 0)
    climate._target_temperature = 22.0
    climate._curr_temperature = 26.0
    climate.update_action()
    assert climate.hvac_action == HVACAction.COOLING


def test_climate_update_action_off_when_mode_off() -> None:
    """HVAC mode OFF → action OFF early-return."""
    mod = _make_climate_module()
    mod.climate_settings = 4
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 0)
    assert climate.hvac_action == HVACAction.OFF


def test_climate_update_action_heatcool_heating() -> None:
    """HEAT_COOL with cold temp → HEATING."""
    mod = _make_climate_module()
    mod.climate_settings = 3
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 0)
    climate._target_temperature = 22.0
    climate._curr_temperature = 18.0
    climate.update_action()
    assert climate.hvac_action == HVACAction.HEATING


def test_climate_update_action_heatcool_cooling() -> None:
    """HEAT_COOL with hot temp → COOLING."""
    mod = _make_climate_module()
    mod.climate_settings = 3
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 0)
    climate._target_temperature = 22.0
    climate._curr_temperature = 26.0
    climate.update_action()
    assert climate.hvac_action == HVACAction.COOLING


def test_climate_update_action_idle_default() -> None:
    """Within target ± 1 → IDLE."""
    mod = _make_climate_module()
    mod.climate_settings = 1
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 0)
    climate._target_temperature = 22.0
    climate._curr_temperature = 22.0
    climate.update_action()
    assert climate.hvac_action == HVACAction.IDLE


async def test_climate_set_hvac_mode_forwards_to_comm() -> None:
    """async_set_hvac_mode maps mode to int and pushes to the bus."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    climate = HbtnClimate(mod, coord, 0)
    await climate.async_set_hvac_mode(HVACMode.COOL)
    assert mod.climate_settings == 2
    mod.comm.async_set_climate_mode.assert_awaited_with(105, 2, mod.climate_ctl12)
    coord.async_request_refresh.assert_awaited()


async def test_climate_set_hvac_mode_unknown_falls_back_to_off() -> None:
    """An unrecognized HVAC mode is treated as OFF (4)."""
    mod = _make_climate_module()
    coord = MagicMock()
    coord.async_request_refresh = AsyncMock()
    climate = HbtnClimate(mod, coord, 0)
    await climate.async_set_hvac_mode("UNKNOWN_MODE")
    assert mod.climate_settings == 4


def test_climate_update_local_state_second_unit_uses_sensor_2() -> None:
    """Second controller index reads sensors[2] / setvalues[1]."""
    mod = _make_climate_module()
    coord = MagicMock()
    climate = HbtnClimate(mod, coord, 1)
    assert climate._curr_temperature == 22.0  # sensors[2]
    assert climate._target_temperature == 22.0  # setvalues[1]


async def test_climate_async_setup_entry_creates_first_and_second(hass: HomeAssistant) -> None:
    """async_setup_entry creates 1st climate + 2nd when typ[0] == 1."""
    mod = _make_climate_module()
    mod.mod_type = "Smart Controller XL"
    mod.typ = [1, 0]
    mod.climate_ctl12 = 2  # dual mode

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    await async_setup_entry(hass, entry, added.extend)
    assert len(added) == 2
    entry.async_on_unload.assert_called()


async def test_climate_async_setup_entry_smart_sensor_path(hass: HomeAssistant) -> None:
    """``Smart Sensor`` mod_type also triggers a climate entity."""
    mod = _make_climate_module()
    mod.mod_type = "Smart Sensor"
    mod.typ = [0, 0]  # no second unit

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    await async_setup_entry(hass, entry, added.extend)
    assert len(added) == 1


async def test_climate_async_setup_entry_skips_non_matching_module(hass: HomeAssistant) -> None:
    """A module that is neither Smart Controller nor Smart Sensor is skipped."""
    mod = _make_climate_module()
    mod.mod_type = "Smart Output"

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    await async_setup_entry(hass, entry, added.extend)
    assert added == []


async def test_climate_async_setup_entry_dual_mode_enable_logic_enables(hass: HomeAssistant) -> None:
    """The dual-mode listener enables the disabled second-climate entity."""
    mod = _make_climate_module()
    mod.mod_type = "Smart Controller"
    mod.typ = [1, 0]
    mod.climate_ctl12 = 2  # should be enabled
    mod.uid = "MOD-DUAL"

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    entry = MagicMock()
    entry.runtime_data.router = router

    listener_holder: list = []
    router.coord.async_add_listener = lambda cb: (
        listener_holder.append(cb) or (lambda: None)
    )

    await async_setup_entry(hass, entry, lambda es: None)
    assert listener_holder, "Expected a coordinator listener to be registered"

    # Patch registry → simulate disabled entry
    registry = MagicMock()
    entry_reg = MagicMock()
    entry_reg.disabled_by = "user"
    registry.async_get_entity_id.return_value = "climate.dual"
    registry.async_get.return_value = entry_reg

    with patch(
        "custom_components.habitron.climate.er.async_get",
        return_value=registry,
    ):
        listener_holder[0]()
    registry.async_update_entity.assert_called_with("climate.dual", disabled_by=None)


async def test_climate_async_setup_entry_single_mode_disables(hass: HomeAssistant) -> None:
    """The dual-mode listener disables the enabled second-climate entity."""
    mod = _make_climate_module()
    mod.mod_type = "Smart Controller"
    mod.typ = [1, 0]
    mod.climate_ctl12 = 0  # single mode
    mod.uid = "MOD-DIS"

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    entry = MagicMock()
    entry.runtime_data.router = router

    listener_holder: list = []
    router.coord.async_add_listener = lambda cb: (
        listener_holder.append(cb) or (lambda: None)
    )

    await async_setup_entry(hass, entry, lambda es: None)

    registry = MagicMock()
    entry_reg = MagicMock()
    entry_reg.disabled_by = None  # currently enabled
    registry.async_get_entity_id.return_value = "climate.dis"
    registry.async_get.return_value = entry_reg

    with patch(
        "custom_components.habitron.climate.er.async_get",
        return_value=registry,
    ):
        listener_holder[0]()
    # Was called with the INTEGRATION disabler enum
    args, kwargs = registry.async_update_entity.call_args
    assert args[0] == "climate.dis"
    assert "disabled_by" in kwargs
