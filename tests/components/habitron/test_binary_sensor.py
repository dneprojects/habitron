"""Tests for the Habitron binary_sensor platform.

Skeleton with smoke-level setup test and translation_key sanity checks.
Extend with per-entity state-transition tests and snapshot-based UI tests.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.binary_sensor import (
    HbtnBinSensor,
    HbtnState,
    InputSwitch,
    InputSwitchPush,
    ListeningStatusSensor,
    MotionSensor,
    MotionSensorPush,
    RainSensor,
    async_setup_entry,
)
from custom_components.habitron.interfaces import TYPE_DIAG
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .conftest import class_attr


async def test_binary_sensor_setup(setup_integration: MockConfigEntry) -> None:
    """The platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_keys_set() -> None:
    """Every state-based binary sensor exposes the icon translation key."""
    assert class_attr(InputSwitch, "_attr_translation_key") == "input_switch"
    assert class_attr(MotionSensor, "_attr_translation_key") == "motion"
    assert class_attr(RainSensor, "_attr_translation_key") == "rain"
    assert class_attr(HbtnState, "_attr_translation_key") == "hub_state"
    assert (
        class_attr(ListeningStatusSensor, "_attr_translation_key") == "listening_status"
    )


def _make_input(name: str = "Sw 1", nmbr: int = 0, type_: int = 2) -> MagicMock:
    """Build a stub IfDescriptor for input-switch entities."""
    inp = MagicMock()
    inp.nmbr = nmbr
    inp.name = name
    inp.type = type_
    inp.area = 0
    return inp


def _make_module() -> MagicMock:
    """Build a stub HbtnModule with input list."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.inputs = [MagicMock(value=0, nmbr=0)]
    mod.sensors = [MagicMock(value=0, nmbr=0)]
    return mod


def test_input_switch_initial_state_off() -> None:
    """An InputSwitch starts as off when the underlying input value is 0."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputSwitch(inp, mod, coord, 0)
    assert entity.is_on is False
    assert entity.unique_id == "Mod_MOD-1_in0"


def test_motion_sensor_unique_id() -> None:
    """MotionSensor has a stable, module-scoped unique id."""
    inp = _make_input(name="Motion")
    mod = _make_module()
    coord = MagicMock()
    entity = MotionSensor(inp, mod, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_motion"


def test_rain_sensor_initial_state_off() -> None:
    """RainSensor starts off when the underlying sensor value is 0."""
    inp = _make_input(name="Rain")
    mod = _make_module()
    coord = MagicMock()
    entity = RainSensor(inp, mod, coord, 0)
    assert entity.is_on is False
    assert entity.unique_id == "Mod_MOD-1_rain"


def test_input_switch_push_inherits_translation_key() -> None:
    """The push subclass keeps the input_switch translation key."""
    assert class_attr(InputSwitchPush, "_attr_translation_key") == "input_switch"
    # Verify it inherits from HbtnBinSensor through InputSwitch
    assert issubclass(InputSwitchPush, HbtnBinSensor)


def test_hbtn_bin_sensor_disabled_when_input_type_negative() -> None:
    """A negative input type marks the entity disabled by default."""
    inp = _make_input(type_=-2)
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnBinSensor(inp, mod, coord, 0)
    assert entity._attr_entity_registry_enabled_default is False


def test_hbtn_bin_sensor_device_info() -> None:
    """device_info uses the module uid identifier."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnBinSensor(inp, mod, coord, 0)
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]


def test_hbtn_bin_sensor_name_property() -> None:
    """Name property surfaces the cached _attr_name."""
    inp = _make_input(name="My Switch")
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnBinSensor(inp, mod, coord, 0)
    assert entity.name == "My Switch"


def test_input_switch_handle_coordinator_update_on() -> None:
    """When the input value is 1 the switch reports on."""
    inp = _make_input()
    mod = _make_module()
    mod.inputs = [MagicMock(value=1, nmbr=0)]
    coord = MagicMock()
    entity = InputSwitch(inp, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.is_on is True


async def test_input_switch_push_register_callback_in_added_to_hass() -> None:
    """InputSwitchPush.async_added_to_hass registers the push callback."""
    inp = _make_input()
    inp.register_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    entity = InputSwitchPush(inp, mod, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    inp.register_callback.assert_called()


async def test_input_switch_push_remove_callback() -> None:
    """InputSwitchPush.async_will_remove_from_hass removes the callback."""
    inp = _make_input()
    inp.remove_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    entity = InputSwitchPush(inp, mod, coord, 0)
    await entity.async_will_remove_from_hass()
    inp.remove_callback.assert_called()


def test_motion_sensor_handle_coordinator_update_active() -> None:
    """MotionSensor reports on when the underlying sensor value > 0."""
    inp = _make_input(name="Motion")
    mod = _make_module()
    mod.sensors = [MagicMock(value=3, nmbr=0)]
    coord = MagicMock()
    entity = MotionSensor(inp, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.is_on is True


async def test_motion_sensor_push_register_callback() -> None:
    """MotionSensorPush registers a callback in async_added_to_hass."""
    sens = _make_input(name="Motion")
    sens.register_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    entity = MotionSensorPush(sens, mod, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    sens.register_callback.assert_called()


async def test_motion_sensor_push_remove_callback() -> None:
    """MotionSensorPush.async_will_remove_from_hass calls remove_callback."""
    sens = _make_input(name="Motion")
    sens.remove_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    entity = MotionSensorPush(sens, mod, coord, 0)
    await entity.async_will_remove_from_hass()
    sens.remove_callback.assert_called()


def test_rain_sensor_handle_coordinator_update_match_74() -> None:
    """RainSensor reports on for the special value 74."""
    sens = _make_input(name="Rain")
    mod = _make_module()
    mod.sensors = [MagicMock(value=74, nmbr=0)]
    coord = MagicMock()
    entity = RainSensor(sens, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.is_on is True


def test_hbtn_state_diag_disabled_default() -> None:
    """A TYPE_DIAG state is registered as diagnostic and disabled by default."""
    state = MagicMock()
    state.nmbr = 1
    state.name = "Diag State"
    state.type = TYPE_DIAG
    state.value = 0
    mod = MagicMock()
    mod.uid = "MOD-1"
    coord = MagicMock()
    entity = HbtnState(state, mod, coord, 0)

    assert entity._attr_entity_category == EntityCategory.DIAGNOSTIC
    assert entity._attr_entity_registry_enabled_default is False


def test_hbtn_state_negative_type_disabled_default() -> None:
    """A negative state type is disabled by default."""
    state = MagicMock()
    state.nmbr = 1
    state.name = "Hidden"
    state.type = -1
    state.value = 0
    mod = MagicMock()
    mod.uid = "MOD-1"
    coord = MagicMock()
    entity = HbtnState(state, mod, coord, 0)
    assert entity._attr_entity_registry_enabled_default is False


def test_hbtn_state_device_info_returns_module_uid() -> None:
    """device_info uses the module/router uid."""
    state = MagicMock()
    state.nmbr = 0
    state.name = "n"
    state.type = 1
    state.value = 0
    mod = MagicMock()
    mod.uid = "ROUTER"
    mod.id = 1
    coord = MagicMock()
    entity = HbtnState(state, mod, coord, 0)
    assert ("habitron", "ROUTER") in entity.device_info["identifiers"]


def test_hbtn_state_device_info_non_router() -> None:
    """device_info still uses the module uid even when module.id is non-int."""
    state = MagicMock()
    state.nmbr = 0
    state.name = "n"
    state.type = 1
    state.value = 0
    mod = MagicMock()
    mod.uid = "MOD-X"
    mod.id = "ABC"  # not an int
    coord = MagicMock()
    entity = HbtnState(state, mod, coord, 0)
    assert ("habitron", "MOD-X") in entity.device_info["identifiers"]


def test_hbtn_state_name_property() -> None:
    """HbtnState surfaces the cached state name."""
    state = MagicMock()
    state.nmbr = 0
    state.name = "S 1"
    state.type = 1
    state.value = 0
    mod = MagicMock()
    mod.uid = "MOD-1"
    coord = MagicMock()
    entity = HbtnState(state, mod, coord, 0)
    assert entity.name == "S 1"


def test_hbtn_state_handle_coordinator_update_on() -> None:
    """HbtnState._handle_coordinator_update reads state.value == 1."""
    state = MagicMock()
    state.nmbr = 0
    state.name = "S 1"
    state.type = 1
    state.value = 1
    mod = MagicMock()
    mod.uid = "MOD-1"
    coord = MagicMock()
    entity = HbtnState(state, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.is_on is True


def test_listening_status_sensor_initial_state_off() -> None:
    """ListeningStatusSensor starts off."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.name = "Touch 1"
    entity = ListeningStatusSensor(mod)
    assert entity.is_on is False
    assert entity.unique_id == "Mod_MOD-1_listening_status"
    assert entity._stream_name == "touch_1"
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]


def test_listening_status_sensor_set_listening_state_toggle() -> None:
    """set_listening_state toggles is_on and writes state."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.name = "Touch 1"
    entity = ListeningStatusSensor(mod)
    entity.async_write_ha_state = MagicMock()
    entity.set_listening_state(True)
    assert entity.is_on is True
    entity.async_write_ha_state.assert_called()


def test_listening_status_sensor_set_listening_state_noop_when_same() -> None:
    """Setting the same state again is a no-op."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.name = "Touch 1"
    entity = ListeningStatusSensor(mod)
    entity.async_write_ha_state = MagicMock()
    entity.set_listening_state(False)  # already False
    entity.async_write_ha_state.assert_not_called()


async def test_async_setup_entry_creates_all_entity_types(hass: HomeAssistant) -> None:
    """async_setup_entry builds input/motion/rain/listening/state entities."""
    inp = _make_input(type_=2)
    motion = MagicMock()
    motion.value = 0
    motion.nmbr = 0
    motion.name = "Movement"
    motion.type = 1
    rain = MagicMock()
    rain.value = 0
    rain.nmbr = 1
    rain.name = "Rain"
    rain.type = 1
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.name = "Touch"
    mod.mod_type = "Smart Controller Touch"
    mod.area_member = 0
    mod.inputs = [inp]
    mod.sensors = [motion, rain]

    state = MagicMock()
    state.nmbr = 0
    state.name = "Hub State"
    state.type = 1
    state.value = 0

    router = MagicMock()
    router.modules = [mod]
    router.states = [state]
    router.coord = MagicMock()
    router.areas = {0: MagicMock(), 1: MagicMock()}
    router.uid = "ROUTER-1"
    router.id = 1

    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    with patch(
        "custom_components.habitron.binary_sensor.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="binary_sensor.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, InputSwitchPush) for e in added)
    assert any(isinstance(e, MotionSensorPush) for e in added)
    assert any(isinstance(e, RainSensor) for e in added)
    assert any(isinstance(e, ListeningStatusSensor) for e in added)
    assert any(isinstance(e, HbtnState) for e in added)
    assert mod.vce_stat is not None


async def test_async_setup_entry_assigns_area_when_input_area_differs(
    hass: HomeAssistant,
) -> None:
    """A switch with area != module.area_member gets an area_id assigned."""
    inp = MagicMock()
    inp.nmbr = 0
    inp.type = 2
    inp.name = "Sw"
    inp.area = 5  # different from area_member 0
    mod = MagicMock()
    mod.uid = "MOD-X"
    mod.mod_type = "Other"
    mod.area_member = 0
    mod.inputs = [inp]
    mod.sensors = []

    router = MagicMock()
    router.modules = [mod]
    router.states = []
    router.coord = MagicMock()
    area = MagicMock()
    area.get_name_id = MagicMock(return_value="area_5_id")
    router.areas = {0: area, 5: area}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.binary_sensor.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="binary_sensor.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_called_with(
        "binary_sensor.fake", area_id="area_5_id"
    )
