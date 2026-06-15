"""Tests for the Habitron event platform."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.event import (
    EkeyUserEvent,
    FingerDetected,
    HbtnEvent,
    InputPressed,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant


async def test_event_setup(setup_integration: MockConfigEntry) -> None:
    """The event platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def _make_input(nmbr: int = 0, name: str = "Btn 1") -> MagicMock:
    inp = MagicMock()
    inp.nmbr = nmbr
    inp.name = name
    inp.type = 1
    inp.area = 0
    inp.value = 0
    inp.register_callback = MagicMock()
    inp.remove_callback = MagicMock()
    return inp


def _make_module() -> MagicMock:
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.fingers = []
    mod.ids = []
    return mod


def test_input_pressed_unique_id() -> None:
    """InputPressed builds a stable, module + input scoped unique id."""
    inp = _make_input(nmbr=3)
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_evnt3"


def test_input_pressed_supports_press_event_types() -> None:
    """InputPressed reports single / long press as event types."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    assert "single_press" in entity._attr_event_types
    assert "long_press" in entity._attr_event_types
    assert "long_press_end" in entity._attr_event_types


def test_finger_detected_has_extra_state_attrs() -> None:
    """FingerDetected exposes ``last_user``/``last_finger`` attributes."""
    finger = _make_input(nmbr=2, name="Index left")
    mod = _make_module()
    coord = MagicMock()
    entity = FingerDetected(finger, mod, coord, 0)
    assert "last_user" in entity._attr_extra_state_attributes
    assert "last_finger" in entity._attr_extra_state_attributes


def test_ekey_user_event_constructor_extra_args() -> None:
    """EkeyUserEvent takes a user id and a user name."""
    user = _make_input(nmbr=1, name="ekey")
    mod = _make_module()
    coord = MagicMock()
    entity = EkeyUserEvent(user, mod, coord, 0, 5, "Alice")
    # Instance was constructed without error and inherits HbtnEvent.
    assert isinstance(entity, HbtnEvent)


def test_input_pressed_handles_callback_short_press() -> None:
    """A single_press event triggers the entity."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("single_press")
    entity._trigger_event.assert_called()


def test_input_pressed_handles_callback_long_press() -> None:
    """A long_press event triggers the entity."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("long_press")
    entity._trigger_event.assert_called()


def test_input_pressed_ignores_inactive_reset() -> None:
    """The bus 'inactive' reset is not a button event and must be ignored."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("inactive")
    entity._trigger_event.assert_not_called()


def test_finger_detected_ignores_inactive_reset() -> None:
    """FingerDetected ignores the 'inactive' reset emitted after a read."""
    finger = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = FingerDetected(finger, mod, coord, 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("inactive", user=0, finger=0)
    entity._trigger_event.assert_not_called()


def test_input_pressed_remove_callback() -> None:
    """async_will_remove_from_hass unregisters the callback."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    entity._if = inp
    asyncio.run(entity.async_will_remove_from_hass())
    inp.remove_callback.assert_called()


def test_hbtn_event_device_info_links_module() -> None:
    """HbtnEvent.device_info exposes the module uid identifier."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnEvent(inp, mod, coord, 0)
    info = entity.device_info
    ids = info["identifiers"]
    assert ("habitron", "MOD-1") in ids


def test_hbtn_event_disabled_when_input_type_negative() -> None:
    """A negative input type marks the event as disabled by default."""
    inp = _make_input()
    inp.type = -1
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnEvent(inp, mod, coord, 0)
    assert entity._attr_entity_registry_enabled_default is False


def test_hbtn_event_handle_event_triggers_and_writes() -> None:
    """HbtnEvent base class _async_handle_event triggers + writes state."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnEvent(inp, mod, coord, 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("single_press")
    entity._trigger_event.assert_called_with("single_press", {"extra_data": 123})
    entity.async_write_ha_state.assert_called()


def test_finger_detected_disabled_user_branch() -> None:
    """Finger > 10 negates the user id and offsets the finger value."""
    finger = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = FingerDetected(finger, mod, coord, 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("finger", user=7, finger=140)
    # finger 140 > 10 → user becomes -7, finger becomes 12
    assert entity._attr_extra_state_attributes["last_user"] == -7
    assert entity._attr_extra_state_attributes["last_finger"] == 12
    entity._trigger_event.assert_called()


def test_finger_detected_normal_branch() -> None:
    """Finger <= 10 keeps user/finger as-is."""
    finger = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = FingerDetected(finger, mod, coord, 0)
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("finger", user=3, finger=5)
    assert entity._attr_extra_state_attributes["last_user"] == 3
    assert entity._attr_extra_state_attributes["last_finger"] == 5


def test_ekey_user_event_triggers_for_matching_user() -> None:
    """EkeyUserEvent only fires when calc_user matches own u_id."""
    user_if = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = EkeyUserEvent(user_if, mod, coord, 0, 5, "Alice")
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("finger", user=5, finger=4)
    # finger 4 -> left_index
    entity._trigger_event.assert_called_with("left_index", {"finger_id": 4})


def test_ekey_user_event_disabled_branch_matches() -> None:
    """EkeyUserEvent matches via negated user id when finger > 10."""
    user_if = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = EkeyUserEvent(user_if, mod, coord, 0, 5, "Alice")
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    # user = -5 (disabled, but encoded as positive), finger = 134 -> 6
    entity._async_handle_event("finger", user=-5, finger=134)
    entity._trigger_event.assert_called_with("right_thumb", {"finger_id": 6})


def test_ekey_user_event_does_not_trigger_for_other_user() -> None:
    """EkeyUserEvent stays silent for foreign user ids."""
    user_if = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = EkeyUserEvent(user_if, mod, coord, 0, 5, "Alice")
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("finger", user=99, finger=4)
    entity._trigger_event.assert_not_called()


def test_ekey_user_event_invalid_finger_does_not_trigger() -> None:
    """EkeyUserEvent ignores fingers outside [1..10]."""
    user_if = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = EkeyUserEvent(user_if, mod, coord, 0, 5, "Alice")
    entity._trigger_event = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._async_handle_event("finger", user=5, finger=0)
    entity._trigger_event.assert_not_called()


def test_ekey_user_event_finger_names() -> None:
    """EkeyUserEvent populates all ten finger event types."""
    user_if = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = EkeyUserEvent(user_if, mod, coord, 0, 5, "Alice")
    assert "left_pinky" in entity._attr_event_types
    assert "right_pinky" in entity._attr_event_types
    assert len(entity._attr_event_types) == 10
    # unknown finger fallback path
    assert entity._get_finger_name(99) == "Finger 99"


async def test_async_added_to_hass_registers_callback() -> None:
    """async_added_to_hass registers the entity callback on its input."""
    inp = _make_input()
    mod = _make_module()
    coord = MagicMock()
    entity = InputPressed(inp, mod, coord, 0)
    entity._if = inp
    # Patch ``super().async_added_to_hass`` chain — its body needs ``hass``.
    entity.async_on_remove = MagicMock()
    base_added = AsyncMock()
    # Bypass HA base class chain.
    with _patch_base_async_added(base_added):
        await entity.async_added_to_hass()
    inp.register_callback.assert_called()


def _patch_base_async_added(mock: AsyncMock):
    """Patch EventEntity.async_added_to_hass to avoid needing self.hass."""

    return patch(
        "homeassistant.components.event.EventEntity.async_added_to_hass",
        new=mock,
    )


async def test_async_setup_entry_iterates_modules(hass: HomeAssistant) -> None:
    """async_setup_entry builds InputPressed/FingerDetected/EkeyUserEvent."""
    # Pulse-switch module
    inp_pulse = _make_input(nmbr=1, name="Btn 1")
    inp_pulse.type = 1
    inp_pulse.area = 0
    inp_skip = _make_input(nmbr=2, name="Btn 2")
    inp_skip.type = 2  # not a pulse switch
    inp_skip.area = 0
    mod_a = MagicMock()
    mod_a.uid = "MOD-A"
    mod_a.mod_type = "Standard"
    mod_a.mod_addr = 100
    mod_a.area_member = 0
    mod_a.inputs = [inp_pulse, inp_skip]
    mod_a.fingers = []
    mod_a.ids = []
    # Fanekey module
    finger = _make_input(nmbr=0, name="Finger")
    user_obj = MagicMock()
    user_obj.nmbr = 5
    user_obj.name = "Alice"
    mod_b = MagicMock()
    mod_b.uid = "MOD-B"
    mod_b.mod_type = "Fanekey"
    mod_b.mod_addr = 101
    mod_b.area_member = 0
    mod_b.inputs = []
    mod_b.fingers = [finger]
    mod_b.ids = [user_obj]

    # Build the runtime-data graph.
    router = MagicMock()
    router.modules = [mod_a, mod_b]
    router.coord = MagicMock()
    area = MagicMock()
    area.get_name_id = MagicMock(return_value="area_id_42")
    router.areas = {0: area, 1: area}

    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []

    def _add(entities) -> None:
        added.extend(entities)

    # Make sure the registry call inside async_setup_entry sees an entry id.

    with patch(
        "custom_components.habitron.event.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="event.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, _add)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, InputPressed) for e in added)
    assert any(isinstance(e, FingerDetected) for e in added)
    assert any(isinstance(e, EkeyUserEvent) for e in added)
    registry.async_update_entity.assert_called()


async def test_async_setup_entry_with_area_member_skips_area_update(
    hass: HomeAssistant,
) -> None:
    """When mod_input.area is the module's area_member, no area_id set."""
    inp_pulse = _make_input(nmbr=1, name="Btn 1")
    inp_pulse.type = 1
    inp_pulse.area = 3
    mod_a = MagicMock()
    mod_a.uid = "MOD-A"
    mod_a.mod_type = "Standard"
    mod_a.mod_addr = 100
    mod_a.area_member = 3  # matches input area
    mod_a.inputs = [inp_pulse]
    mod_a.fingers = []
    mod_a.ids = []

    router = MagicMock()
    router.modules = [mod_a]
    router.coord = MagicMock()
    router.areas = {3: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []

    with patch(
        "custom_components.habitron.event.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="event.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    # default-area path called async_update_entity with area_id=None
    registry.async_update_entity.assert_called_with("event.fake", area_id=None)


async def test_async_setup_entry_external_area_assigns_area_id(
    hass: HomeAssistant,
) -> None:
    """An input whose area differs from area_member assigns the area_id."""
    inp_pulse = _make_input(nmbr=1, name="Btn 1")
    inp_pulse.type = 1
    inp_pulse.area = 2  # different from area_member
    mod_a = MagicMock()
    mod_a.uid = "MOD-A"
    mod_a.mod_type = "Standard"
    mod_a.mod_addr = 100
    mod_a.area_member = 0
    mod_a.inputs = [inp_pulse]
    mod_a.fingers = []
    mod_a.ids = []

    router = MagicMock()
    router.modules = [mod_a]
    router.coord = MagicMock()
    area = MagicMock()
    area.get_name_id = MagicMock(return_value="area_2_id")
    router.areas = {0: area, 2: area}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.event.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="event.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_called_with("event.fake", area_id="area_2_id")


async def test_async_setup_entry_skips_missing_registry_entry(
    hass: HomeAssistant,
) -> None:
    """Missing registry entries fall through without calling async_update_entity."""
    inp_pulse = _make_input(nmbr=1, name="Btn 1")
    inp_pulse.type = 1
    inp_pulse.area = 0
    mod_a = MagicMock()
    mod_a.uid = "MOD-A"
    mod_a.mod_type = "Standard"
    mod_a.mod_addr = 100
    mod_a.area_member = 0
    mod_a.inputs = [inp_pulse]
    mod_a.fingers = []
    mod_a.ids = []

    router = MagicMock()
    router.modules = [mod_a]
    router.coord = MagicMock()
    router.areas = {}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.event.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value=None)
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_not_called()
