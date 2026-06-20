"""Tests for the Habitron binary_sensor platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Area, Flag, Input, Module, Router, Sensor

from custom_components.habitron.binary_sensor import (
    HbtnState,
    InputSwitch,
    InputSwitchPush,
    ListeningStatusSensor,
    MotionSensor,
    RainSensor,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant

from .conftest import class_attr


def _module(uid: str = "MOD-1", name: str = "Mod", **kwargs) -> Module:
    """Build a v2 model module."""
    return Module(uid=uid, addr=105, typ=b"\x01\x02", name=name, **kwargs)


def _stub_write(entity) -> None:
    """Replace ``async_write_ha_state`` so handlers run without hass."""
    entity.async_write_ha_state = MagicMock()


def test_translation_keys_set() -> None:
    """Every state-based binary sensor exposes the icon translation key."""
    assert class_attr(InputSwitch, "_attr_translation_key") == "input_switch"
    assert class_attr(MotionSensor, "_attr_translation_key") == "motion"
    assert class_attr(RainSensor, "_attr_translation_key") == "rain"
    assert class_attr(HbtnState, "_attr_translation_key") == "hub_state"
    assert (
        class_attr(ListeningStatusSensor, "_attr_translation_key") == "listening_status"
    )


# ---------------------------------------------------------------------------
# InputSwitch
# ---------------------------------------------------------------------------


def test_input_switch_unique_id_and_state() -> None:
    """InputSwitch exposes a stable unique id and reflects the input value."""
    module = _module()
    module.inputs = [Input(name="Sw", nmbr=0, type=2, value=0)]
    entity = InputSwitch(module.inputs[0], module, MagicMock(), 0)
    assert entity.unique_id == "Mod_MOD-1_in0"
    _stub_write(entity)
    entity._handle_coordinator_update()
    assert entity.is_on is False
    module.inputs[0].value = 1
    entity._handle_coordinator_update()
    assert entity.is_on is True


def test_input_switch_negative_type_disabled() -> None:
    """A negative input type disables the entity by default."""
    module = _module()
    inp = Input(name="Sw", nmbr=0, type=-2, value=0)
    module.inputs = [inp]
    entity = InputSwitch(inp, module, MagicMock(), 0)
    assert entity._attr_entity_registry_enabled_default is False


async def test_input_switch_push_listener_lifecycle() -> None:
    """InputSwitchPush subscribes/unsubscribes the input listener."""
    module = _module()
    inp = Input(name="Sw", nmbr=0, type=2, value=0)
    module.inputs = [inp]
    entity = InputSwitchPush(inp, module, MagicMock(), 0)
    with (
        patch(
            "homeassistant.helpers.update_coordinator."
            "CoordinatorEntity.async_added_to_hass",
            new=AsyncMock(),
        ),
        patch(
            "homeassistant.helpers.update_coordinator."
            "CoordinatorEntity.async_will_remove_from_hass",
            new=AsyncMock(),
        ),
    ):
        await entity.async_added_to_hass()
        assert len(inp._listeners) == 1
        await entity.async_will_remove_from_hass()
        assert len(inp._listeners) == 0


# ---------------------------------------------------------------------------
# MotionSensor / RainSensor
# ---------------------------------------------------------------------------


def test_motion_sensor_state() -> None:
    """MotionSensor is on when the movement value is greater than zero."""
    module = _module()
    module.sensors = [Sensor(name="Movement", nmbr=0, type=2, value=0)]
    entity = MotionSensor(module.sensors[0], module, MagicMock(), 0)
    assert entity.unique_id == "Mod_MOD-1_motion"
    _stub_write(entity)
    entity._handle_coordinator_update()
    assert entity.is_on is False
    module.sensors[0].value = 5
    entity._handle_coordinator_update()
    assert entity.is_on is True


def test_rain_sensor_state() -> None:
    """RainSensor is on only for the rain marker value (74)."""
    module = _module()
    module.sensors = [Sensor(name="Rain", nmbr=0, type=0, value=0)]
    entity = RainSensor(module.sensors[0], module, MagicMock(), 0)
    assert entity.unique_id == "Mod_MOD-1_rain"
    _stub_write(entity)
    module.sensors[0].value = 74
    entity._handle_coordinator_update()
    assert entity.is_on is True
    module.sensors[0].value = 0
    entity._handle_coordinator_update()
    assert entity.is_on is False


# ---------------------------------------------------------------------------
# HbtnState (router system states)
# ---------------------------------------------------------------------------


def test_hbtn_state_reflects_flag_value() -> None:
    """HbtnState mirrors the router state member value."""
    router = Router(uid="ROUTER-1")
    state = Flag(name="System OK", nmbr=0, idx=0, value=0)
    router.states = [state]
    entity = HbtnState(state, router, MagicMock(), 0)
    assert entity.unique_id == "Mod_ROUTER-1_state0"
    assert ("habitron", "ROUTER-1") in entity.device_info["identifiers"]
    _stub_write(entity)
    entity._handle_coordinator_update()
    assert entity.is_on is False
    state.value = 1
    entity._handle_coordinator_update()
    assert entity.is_on is True


# ---------------------------------------------------------------------------
# ListeningStatusSensor
# ---------------------------------------------------------------------------


def test_listening_status_sensor_set_state() -> None:
    """ListeningStatusSensor toggles its state via set_listening_state."""
    module = _module(uid="MOD-MIC", name="Touch 1")
    entity = ListeningStatusSensor(module)
    assert entity.unique_id == "Mod_MOD-MIC_listening_status"
    assert entity.is_on is False
    _stub_write(entity)
    entity.set_listening_state(True)
    assert entity.is_on is True


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


def _entry_for(router: Router) -> MagicMock:
    """Build a config entry whose runtime_data exposes router/coordinator."""
    entry = MagicMock()
    entry.runtime_data.router = router
    entry.runtime_data.coordinator = MagicMock()
    return entry


async def test_async_setup_entry_emits_entities(hass: HomeAssistant) -> None:
    """async_setup_entry creates input/motion/rain/listening + router state."""
    module = Module(
        uid="MOD-1",
        addr=105,
        typ=b"\x01\x04",
        name="Touch 1",
        mod_type="Smart Controller Touch",
    )
    module.inputs = [Input(name="Sw", nmbr=0, type=2, value=0)]
    module.sensors = [
        Sensor(name="Movement", nmbr=0, type=2, value=0),
        Sensor(name="Rain", nmbr=1, type=0, value=0),
    ]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    router.states = [Flag(name="System OK", nmbr=0, idx=0, value=1)]
    router.areas = [Area(nmbr=0, name="House")]
    entry = _entry_for(router)

    added: list = []
    with patch("custom_components.habitron.binary_sensor.er.async_get") as mock_get:
        mock_get.return_value.async_get_entity_id = MagicMock(return_value=None)
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, InputSwitch) for e in added)
    assert any(isinstance(e, MotionSensor) for e in added)
    assert any(isinstance(e, RainSensor) for e in added)
    assert any(isinstance(e, ListeningStatusSensor) for e in added)
    assert any(isinstance(e, HbtnState) for e in added)


async def test_async_setup_entry_assigns_switch_input_area(hass: HomeAssistant) -> None:
    """A switch input in a known non-module area is moved into that HA area."""
    module = Module(uid="MOD-1", addr=105, typ=b"\x00\x00", name="In")
    module.inputs = [Input(name="Sw", nmbr=0, type=2, value=0, area=5)]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    router.areas = [Area(nmbr=5, name="Living Room")]
    entry = _entry_for(router)

    with patch("custom_components.habitron.binary_sensor.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="binary_sensor.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_called_with(
        "binary_sensor.fake", area_id="living_room"
    )
