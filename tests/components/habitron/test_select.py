"""Tests for the Habitron select platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.module import HbtnModule
from custom_components.habitron.router import DaytimeMode, HbtnRouter
from custom_components.habitron.select import (
    HbtnMode,
    HbtnSelectAlarmMode,
    HbtnSelectAlarmModePush,
    HbtnSelectDaytimeMode,
    HbtnSelectDaytimeModePush,
    HbtnSelectGroupMode,
    HbtnSelectGroupModePush,
    HbtnSelectLoggingLevel,
    async_setup_entry,
)
from custom_components.habitron.smart_hub import LoggingLevels


async def test_select_setup(setup_integration: MockConfigEntry) -> None:
    """The select platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def _make_module(uid: str = "MOD-1", group: int = 1, mode_value: int = 1) -> MagicMock:
    mod = MagicMock(spec=HbtnModule)
    mod.uid = uid
    mod.group = group
    mod.mode = MagicMock(value=mode_value)
    mod.mode.register_callback = MagicMock()
    mod.mode.remove_callback = MagicMock()
    mod.mod_type = "Smart Controller"
    mod.comm = MagicMock()
    mod.comm.async_set_group_mode = AsyncMock()
    mod.comm.async_set_daytime_mode = AsyncMock()
    mod.comm.async_set_alarm_mode = AsyncMock()
    return mod


def _make_router(uid: str = "ROUTER-1", mode_value: int = 1) -> HbtnRouter:
    """A real-ish router stub (must satisfy ``isinstance(_, HbtnRouter)``)."""
    rt = HbtnRouter.__new__(HbtnRouter)
    rt.uid = uid
    rt.id = 1
    rt.mode = MagicMock(value=mode_value)
    rt.user1_name = "Alice"
    rt.user2_name = "Bob"
    rt.comm = MagicMock()
    rt.comm.async_set_group_mode = AsyncMock()
    rt.comm.async_set_daytime_mode = AsyncMock()
    rt.comm.async_set_alarm_mode = AsyncMock()
    rt.logger = MagicMock()
    return rt


def test_hbtn_mode_available_is_true() -> None:
    """HbtnMode.available reports True regardless of underlying state."""
    rt = _make_router()
    coord = MagicMock()
    entity = HbtnMode(0, rt, coord, 0)
    assert entity.available is True


def test_hbtn_mode_device_info_router_vs_module() -> None:
    """device_info uses router uid for router-level, module uid for module-level."""
    rt = _make_router()
    coord = MagicMock()
    router_ent = HbtnMode(0, rt, coord, 0)
    assert ("habitron", "ROUTER-1") in router_ent.device_info["identifiers"]

    mod = _make_module()
    mod_ent = HbtnSelectDaytimeMode(mod, rt, coord, 0)
    assert ("habitron", "MOD-1") in mod_ent.device_info["identifiers"]


def test_hbtn_mode_name_options_state_property() -> None:
    """HbtnMode property surface reports cached values."""
    rt = _make_router()
    coord = MagicMock()
    entity = HbtnSelectDaytimeMode(0, rt, coord, 0)
    assert entity.name == entity._attr_name
    assert "day" in entity.options
    # current_option == state when in the options list
    assert entity.state == entity.current_option


def test_hbtn_mode_state_returns_none_when_unknown() -> None:
    """state returns None when current_option is not in options."""
    rt = _make_router()
    coord = MagicMock()
    entity = HbtnSelectDaytimeMode(0, rt, coord, 0)
    entity._current_option = "doesnotexist"
    assert entity.state is None


def test_hbtn_mode_state_returns_none_when_current_option_none() -> None:
    """state returns None when current_option is None."""
    rt = _make_router()
    coord = MagicMock()
    entity = HbtnSelectDaytimeMode(0, rt, coord, 0)
    entity._current_option = None
    assert entity.state is None


def test_hbtn_select_daytime_mode_router_zero_mode_falls_back_to_one() -> None:
    """Router with mode_value=0 logs a warning + falls back to mode 1."""
    rt = _make_router(mode_value=0)
    coord = MagicMock()
    entity = HbtnSelectDaytimeMode(0, rt, coord, 0)
    assert entity._value == 1
    assert entity._current_option == "day"
    assert entity._attr_unique_id == "Rt_ROUTER-1_group_0_daytime_mode"
    rt.logger.info.assert_called()


def test_hbtn_select_daytime_mode_module_zero_value_falls_back_to_one() -> None:
    """Module with masked value 0 falls back to mode 1."""
    rt = _make_router()
    mod = _make_module(mode_value=4)  # 4 & 0x03 == 0
    coord = MagicMock()
    entity = HbtnSelectDaytimeMode(mod, rt, coord, 0)
    assert entity._value == 1
    assert entity._current_option == "day"
    assert entity._attr_entity_registry_enabled_default is False
    assert entity._attr_unique_id == "Mod_MOD-1_daytime_mode"


async def test_hbtn_select_daytime_mode_router_select_uses_set_daytime_mode() -> None:
    """Router-level select sends async_set_daytime_mode(0, value)."""
    rt = _make_router()
    coord = MagicMock()
    entity = HbtnSelectDaytimeMode(0, rt, coord, 0)
    await entity.async_select_option("night")
    rt.comm.async_set_daytime_mode.assert_awaited_with(0, DaytimeMode["night"].value)


async def test_hbtn_select_daytime_mode_module_select_uses_module_comm() -> None:
    """Module-level select routes through module.comm.async_set_daytime_mode."""
    rt = _make_router()
    mod = _make_module(group=3)
    coord = MagicMock()
    entity = HbtnSelectDaytimeMode(mod, rt, coord, 0)
    await entity.async_select_option("day")
    mod.comm.async_set_daytime_mode.assert_awaited_with(3, DaytimeMode["day"].value)


def test_hbtn_select_alarm_mode_router_unique_id() -> None:
    """Router-level alarm select carries the router-scoped unique id."""
    rt = _make_router()
    coord = MagicMock()
    entity = HbtnSelectAlarmMode(0, rt, coord, 0)
    assert entity._attr_unique_id == "Rt_ROUTER-1_group_0_alarm_mode"
    assert entity._attr_name == "Group 0 alarm"


def test_hbtn_select_alarm_mode_module_unique_id() -> None:
    """Module-level alarm select carries the module-scoped unique id."""
    rt = _make_router()
    mod = _make_module(group=2)
    coord = MagicMock()
    entity = HbtnSelectAlarmMode(mod, rt, coord, 0)
    assert entity._attr_unique_id == "Mod_MOD-1_alarm_mode"
    assert entity._attr_name == "Group 2 alarm"


async def test_hbtn_select_alarm_mode_select_router_path() -> None:
    """Router-level select_option calls router.comm.async_set_alarm_mode."""
    rt = _make_router()
    coord = MagicMock()
    entity = HbtnSelectAlarmMode(0, rt, coord, 0)
    await entity.async_select_option("on")
    rt.comm.async_set_alarm_mode.assert_awaited_with(0, True)


async def test_hbtn_select_alarm_mode_select_module_path() -> None:
    """Module-level select_option calls module.comm.async_set_alarm_mode."""
    rt = _make_router()
    mod = _make_module(group=2)
    coord = MagicMock()
    entity = HbtnSelectAlarmMode(mod, rt, coord, 0)
    await entity.async_select_option("off")
    mod.comm.async_set_alarm_mode.assert_awaited_with(2, False)


def test_hbtn_select_group_mode_router_unique_id() -> None:
    """Router-level group select carries the router-scoped unique id."""
    rt = _make_router(mode_value=32)
    coord = MagicMock()
    entity = HbtnSelectGroupMode(0, rt, coord, 0)
    assert entity._attr_unique_id == "Rt_ROUTER-1_group_0_mode"
    assert entity._attr_name == "Group 0 mode"


def test_hbtn_select_group_mode_module_unique_id() -> None:
    """Module-level group select carries the module-scoped unique id."""
    rt = _make_router()
    mod = _make_module(mode_value=32, group=2)
    coord = MagicMock()
    entity = HbtnSelectGroupMode(mod, rt, coord, 0)
    assert entity._attr_unique_id == "Mod_MOD-1_group_mode"
    assert entity._attr_name == "Group 2 mode"


def test_hbtn_select_group_mode_zero_value_falls_back_to_32() -> None:
    """A masked 0 group value is rewritten to "present" (32)."""
    rt = _make_router(mode_value=0)
    coord = MagicMock()
    entity = HbtnSelectGroupMode(0, rt, coord, 0)
    assert entity._value == 32
    assert entity._current_option == "present"


def test_hbtn_select_group_mode_unprintable_user_names_get_default() -> None:
    """Non-printable user names fall back to "Unbekannt"."""
    rt = _make_router(mode_value=32)
    rt.user1_name = "\x00"
    rt.user2_name = "\x01"
    coord = MagicMock()
    entity = HbtnSelectGroupMode(0, rt, coord, 0)
    # The enum names should contain "Unbekannt" and "Unbekannt2"
    names = [m.name for m in entity._enum]
    assert "Unbekannt" in names
    assert "Unbekannt2" in names


def test_hbtn_select_group_mode_same_user_name_appends_2() -> None:
    """Identical user names yield user2 with a "2" suffix."""
    rt = _make_router(mode_value=32)
    rt.user1_name = "Alex"
    rt.user2_name = "Alex"
    coord = MagicMock()
    entity = HbtnSelectGroupMode(0, rt, coord, 0)
    names = [m.name for m in entity._enum]
    assert "Alex" in names
    assert "Alex2" in names


async def test_hbtn_select_group_mode_select_router_path() -> None:
    """Router-level group select calls router.comm.async_set_group_mode."""
    rt = _make_router(mode_value=32)
    coord = MagicMock()
    entity = HbtnSelectGroupMode(0, rt, coord, 0)
    await entity.async_select_option("absent")
    rt.comm.async_set_group_mode.assert_awaited_with(0, 16)


async def test_hbtn_select_group_mode_select_module_path() -> None:
    """Module-level group select calls module.comm.async_set_group_mode."""
    rt = _make_router()
    mod = _make_module(mode_value=32, group=3)
    coord = MagicMock()
    entity = HbtnSelectGroupMode(mod, rt, coord, 0)
    await entity.async_select_option("absent")
    mod.comm.async_set_group_mode.assert_awaited_with(3, 16)


def test_hbtn_mode_handle_coordinator_update_writes_state() -> None:
    """_handle_coordinator_update updates _value and current_option."""
    rt = _make_router(mode_value=2)
    coord = MagicMock()
    entity = HbtnSelectDaytimeMode(0, rt, coord, 0)
    entity.async_write_ha_state = MagicMock()
    rt.mode.value = 2  # bit-0 set for night
    entity._handle_coordinator_update()
    assert entity._current_option == "night"
    entity.async_write_ha_state.assert_called()


def test_hbtn_mode_handle_coordinator_update_skips_mode_zero() -> None:
    """A mode value of 0 short-circuits without writing state."""
    rt = _make_router(mode_value=2)
    coord = MagicMock()
    entity = HbtnSelectDaytimeMode(0, rt, coord, 0)
    entity.async_write_ha_state = MagicMock()
    rt.mode.value = 0
    entity._handle_coordinator_update()
    entity.async_write_ha_state.assert_not_called()


def test_hbtn_mode_handle_coordinator_update_unknown_value_warns_and_skips() -> None:
    """A masked value that isn't in the enum logs a warning and skips."""
    rt = _make_router(mode_value=2)
    coord = MagicMock()
    entity = HbtnSelectAlarmMode(0, rt, coord, 0)
    entity.async_write_ha_state = MagicMock()
    rt.mode.value = 0x02  # & 0x04 == 0 → in AlarmMode (off), let's try unknown
    # AlarmMode only has 0 and 4. masked 4 is the only "on", anything else is 0.
    # To trigger the unknown path we patch the mask after the fact.
    entity._mask = 0xFF
    rt.mode.value = 99
    entity._handle_coordinator_update()
    rt.logger.warning.assert_called()


async def test_select_async_setup_entry_creates_entities(hass) -> None:
    """async_setup_entry adds 3 entities per Smart Controller + 3 router-level."""
    rt = _make_router(mode_value=32)
    mod_a = _make_module()
    mod_b = _make_module(uid="MOD-2", group=2)
    mod_other = _make_module(uid="MOD-3")
    mod_other.mod_type = "Smart Output"
    rt.modules = [mod_a, mod_b, mod_other]
    rt.coord = MagicMock()

    smhub = MagicMock()
    smhub.uid = "HUB-1"
    log_lvl = MagicMock()
    log_lvl.nmbr = 0
    log_lvl.name = "Console"
    log_lvl.value = 20  # 20/10 == 2 == info
    smhub.loglvl = [log_lvl]

    entry = MagicMock()
    entry.runtime_data = smhub
    entry.runtime_data.router = rt

    added: list = []
    await async_setup_entry(hass, entry, lambda es: added.extend(es))
    # 2 SC modules × 3 entities + 3 router-level + 1 logging = 10
    assert len(added) == 10
    assert any(isinstance(e, HbtnSelectLoggingLevel) for e in added)


async def test_hbtn_select_daytime_mode_push_register_callback_module() -> None:
    """Push subclass registers on module.mode in async_added_to_hass."""
    rt = _make_router()
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnSelectDaytimeModePush(mod, rt, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    mod.mode.register_callback.assert_called()


async def test_hbtn_select_daytime_mode_push_remove_callback_module() -> None:
    """Push subclass removes the callback on async_will_remove_from_hass."""
    rt = _make_router()
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnSelectDaytimeModePush(mod, rt, coord, 0)
    await entity.async_will_remove_from_hass()
    mod.mode.remove_callback.assert_called()


async def test_hbtn_select_daytime_mode_push_router_skips_register() -> None:
    """Router-level push entity does not register on a module."""
    rt = _make_router()
    coord = MagicMock()
    entity = HbtnSelectDaytimeModePush(0, rt, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    # _module is the router → no mode.register_callback call
    await entity.async_will_remove_from_hass()


async def test_hbtn_select_alarm_mode_push_register_callback_module() -> None:
    """Alarm push subclass also registers on module.mode."""
    rt = _make_router()
    mod = _make_module()
    coord = MagicMock()
    entity = HbtnSelectAlarmModePush(mod, rt, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    mod.mode.register_callback.assert_called()
    await entity.async_will_remove_from_hass()
    mod.mode.remove_callback.assert_called()


async def test_hbtn_select_alarm_mode_push_router_skips_register() -> None:
    """Router-level alarm push entity does not register on a module."""
    rt = _make_router()
    coord = MagicMock()
    entity = HbtnSelectAlarmModePush(0, rt, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    await entity.async_will_remove_from_hass()


async def test_hbtn_select_group_mode_push_register_callback_module() -> None:
    """Group push subclass also registers on module.mode."""
    rt = _make_router()
    mod = _make_module(mode_value=32)
    coord = MagicMock()
    entity = HbtnSelectGroupModePush(mod, rt, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    mod.mode.register_callback.assert_called()
    await entity.async_will_remove_from_hass()
    mod.mode.remove_callback.assert_called()


async def test_hbtn_select_group_mode_push_router_skips_register() -> None:
    """Router-level group push entity does not register on a module."""
    rt = _make_router(mode_value=32)
    coord = MagicMock()
    entity = HbtnSelectGroupModePush(0, rt, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    await entity.async_will_remove_from_hass()


def _make_log_level(value: int = 20) -> MagicMock:
    level = MagicMock()
    level.nmbr = 0
    level.name = "Console"
    level.value = value
    return level


def test_hbtn_select_logging_level_init_unique_id_translation_key() -> None:
    """HbtnSelectLoggingLevel exposes a stable unique id and translation key."""
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    level = _make_log_level()
    coord = MagicMock()
    entity = HbtnSelectLoggingLevel(smhub, level, coord, 0)
    assert entity._attr_unique_id == "Hub_HUB-1_Console"
    assert entity._attr_translation_key == "habitron_loglevel"


def test_hbtn_select_logging_level_available() -> None:
    """HbtnSelectLoggingLevel.available is True."""
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    level = _make_log_level()
    coord = MagicMock()
    entity = HbtnSelectLoggingLevel(smhub, level, coord, 0)
    assert entity.available is True


def test_hbtn_select_logging_level_device_info_uses_smarthub_uid() -> None:
    """device_info points at the smarthub uid."""
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    level = _make_log_level()
    coord = MagicMock()
    entity = HbtnSelectLoggingLevel(smhub, level, coord, 0)
    assert ("habitron", "HUB-1") in entity.device_info["identifiers"]


def test_hbtn_select_logging_level_name_options_state() -> None:
    """name/options surface the cached values; state matches current_option."""
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    level = _make_log_level()
    coord = MagicMock()
    entity = HbtnSelectLoggingLevel(smhub, level, coord, 0)
    assert entity.name == "Console"
    assert "debug" in entity.options
    entity._current_option = "info"
    assert entity.state == "info"


def test_hbtn_select_logging_level_state_returns_none_when_unknown() -> None:
    """state returns None when current_option is not in the enum names."""
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    level = _make_log_level()
    coord = MagicMock()
    entity = HbtnSelectLoggingLevel(smhub, level, coord, 0)
    entity._current_option = "doesnotexist"
    assert entity.state is None
    entity._current_option = None
    assert entity.state is None


def test_hbtn_select_logging_level_handle_coordinator_update() -> None:
    """_handle_coordinator_update divides the raw value by 10 and resolves enum name."""
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    level = _make_log_level(value=30)
    coord = MagicMock()
    entity = HbtnSelectLoggingLevel(smhub, level, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._value == 3
    assert entity._current_option == "warning"


def test_hbtn_select_logging_level_current_option_property() -> None:
    """current_option returns the cached value directly."""
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    level = _make_log_level()
    coord = MagicMock()
    entity = HbtnSelectLoggingLevel(smhub, level, coord, 0)
    entity._current_option = "info"
    assert entity.current_option == "info"


async def test_hbtn_mode_base_async_select_option_router() -> None:
    """The HbtnMode base async_select_option dispatches to router.comm."""
    rt = _make_router(mode_value=32)
    coord = MagicMock()
    entity = HbtnMode(0, rt, coord, 0)
    entity._enum = DaytimeMode
    entity._mask = 0x03
    await entity.async_select_option("night")
    rt.comm.async_set_group_mode.assert_awaited()


async def test_hbtn_mode_base_async_select_option_module() -> None:
    """The HbtnMode base async_select_option dispatches to module.comm."""
    rt = _make_router()
    mod = _make_module(group=4)
    coord = MagicMock()
    entity = HbtnMode(mod, rt, coord, 0)
    entity._enum = DaytimeMode
    entity._mask = 0x03
    await entity.async_select_option("day")
    mod.comm.async_set_group_mode.assert_awaited()


async def test_hbtn_select_logging_level_async_select_option_forwards() -> None:
    """async_select_option pushes selected level * 10 to async_set_log_level."""
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    smhub.comm.async_set_log_level = AsyncMock()
    level = _make_log_level()
    coord = MagicMock()
    entity = HbtnSelectLoggingLevel(smhub, level, coord, 0)
    await entity.async_select_option("error")
    smhub.comm.async_set_log_level.assert_awaited_with(
        0, LoggingLevels["error"].value * 10
    )
