"""Tests for the Habitron select platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Module, Router, Sensor

from custom_components.habitron.const import AlarmMode, DaytimeMode
from custom_components.habitron.select import (
    HbtnMode,
    HbtnSelectAlarmModePush,
    HbtnSelectDaytimeModePush,
    HbtnSelectGroupModePush,
    HbtnSelectLoggingLevel,
    async_setup_entry,
)
from custom_components.habitron.smart_hub import LoggingLevels
from homeassistant.core import HomeAssistant


def _coord() -> MagicMock:
    coord = MagicMock()
    coord.comm = MagicMock()
    coord.comm.async_set_daytime_mode = AsyncMock()
    coord.comm.async_set_alarm_mode = AsyncMock()
    coord.comm.async_set_group_mode = AsyncMock()
    return coord


def _router() -> Router:
    return Router(uid="ROUTER-1", user1_name="Alice", user2_name="Bob")


def _module(mode: int = 0x21, group: int = 3) -> Module:
    module = Module(
        uid="MOD-1", addr=105, typ=b"\x01\x02", name="SC", mod_type="Smart Controller"
    )
    module.mode.value = mode
    module.group = group
    return module


# ---------------------------------------------------------------------------
# Daytime / Alarm / Group selects
# ---------------------------------------------------------------------------


def test_daytime_options() -> None:
    """The daytime selector lists the DaytimeMode names."""
    entity = HbtnSelectDaytimeModePush(_module(), _router(), _coord(), 0)
    assert entity.options == [m.name for m in DaytimeMode]
    assert entity.unique_id == "Mod_MOD-1_daytime_mode"


async def test_daytime_select_module_path() -> None:
    """A module-level daytime change targets the module's group."""
    coord = _coord()
    entity = HbtnSelectDaytimeModePush(_module(group=3), _router(), coord, 0)
    await entity.async_select_option("night")
    coord.comm.async_set_daytime_mode.assert_awaited_with(3, DaytimeMode["night"].value)


async def test_daytime_select_router_path() -> None:
    """A router-level daytime change targets group 0."""
    coord = _coord()
    entity = HbtnSelectDaytimeModePush(0, _router(), coord, 0)
    await entity.async_select_option("day")
    coord.comm.async_set_daytime_mode.assert_awaited_with(0, DaytimeMode["day"].value)
    assert entity.unique_id == "Rt_ROUTER-1_group_0_daytime_mode"


async def test_alarm_select_module_path() -> None:
    """An alarm change forwards a boolean to the bus."""
    coord = _coord()
    entity = HbtnSelectAlarmModePush(_module(group=2), _router(), coord, 0)
    await entity.async_select_option("on")
    coord.comm.async_set_alarm_mode.assert_awaited_with(2, True)


def test_alarm_options() -> None:
    """The alarm selector lists the AlarmMode names."""
    entity = HbtnSelectAlarmModePush(_module(), _router(), _coord(), 0)
    assert entity.options == [m.name for m in AlarmMode]


async def test_group_select_uses_user_names() -> None:
    """The group selector includes the router user names and forwards values."""
    coord = _coord()
    entity = HbtnSelectGroupModePush(_module(group=4), _router(), coord, 0)
    assert "Alice" in entity.options
    assert "Bob" in entity.options
    await entity.async_select_option("present")
    coord.comm.async_set_group_mode.assert_awaited_with(4, 32)


def test_mode_handle_coordinator_update_sets_option() -> None:
    """The handler maps the module mode to the matching enum option."""
    module = _module(mode=0x22)  # daytime bits -> 2 (night)
    entity = HbtnSelectDaytimeModePush(module, _router(), _coord(), 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.current_option == "night"


async def test_daytime_push_listener_lifecycle() -> None:
    """A module-level select subscribes/unsubscribes the mode listener."""
    module = _module()
    entity = HbtnSelectDaytimeModePush(module, _router(), _coord(), 0)
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
        assert len(module.mode._listeners) == 1
        await entity.async_will_remove_from_hass()
        assert len(module.mode._listeners) == 0


# ---------------------------------------------------------------------------
# Logging level
# ---------------------------------------------------------------------------


def _smhub() -> MagicMock:
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    smhub.comm = MagicMock()
    smhub.comm.async_set_log_level = AsyncMock()
    return smhub


def test_logging_level_current_option() -> None:
    """The logging-level selector maps the raw value (x10) to a level name."""
    level = Sensor(name="Logging level console", nmbr=0, type=2, value=20)
    entity = HbtnSelectLoggingLevel(_smhub(), level, _coord(), 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.current_option == LoggingLevels(2).name  # info
    assert entity.options == [lvl.name for lvl in LoggingLevels]


async def test_logging_level_select_option() -> None:
    """Selecting a level forwards value x10 to the hub on the right handler."""
    smhub = _smhub()
    level = Sensor(name="Logging level file", nmbr=1, type=2, value=0)
    entity = HbtnSelectLoggingLevel(smhub, level, _coord(), 0)
    await entity.async_select_option("warning")
    smhub.comm.async_set_log_level.assert_awaited_with(
        1, LoggingLevels["warning"].value * 10
    )


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_async_setup_entry_emits_mode_and_log_selects(
    hass: HomeAssistant,
) -> None:
    """Setup emits per-controller + group-0 mode selects and log-level selects."""
    module = _module()
    router = _router()
    router.modules = [module]
    smhub = _smhub()
    smhub.router = router
    smhub.coordinator = _coord()
    smhub.loglvl = [Sensor(name="Logging level console", nmbr=0, type=2, value=20)]
    entry = MagicMock()
    entry.runtime_data = smhub

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, HbtnSelectDaytimeModePush) for e in added)
    assert any(isinstance(e, HbtnSelectAlarmModePush) for e in added)
    assert any(isinstance(e, HbtnSelectGroupModePush) for e in added)
    assert any(isinstance(e, HbtnSelectLoggingLevel) for e in added)


# ---------------------------------------------------------------------------
# base HbtnMode._handle_coordinator_update branches + base select_option
# ---------------------------------------------------------------------------


def test_mode_handle_ignores_zero_full_mode() -> None:
    """A full mode of 0 (uninitialised) is skipped without writing state."""
    module = _module(mode=0x02)
    entity = HbtnSelectDaytimeModePush(module, _router(), _coord(), 0)
    entity.async_write_ha_state = MagicMock()
    module.mode.value = 0
    entity._handle_coordinator_update()
    entity.async_write_ha_state.assert_not_called()


def test_mode_handle_skips_uninitialised_submode() -> None:
    """A non-zero full mode with a 0 masked sub-mode is skipped quietly."""
    module = _module(mode=0x02)
    entity = HbtnSelectDaytimeModePush(module, _router(), _coord(), 0)
    entity.async_write_ha_state = MagicMock()
    module.mode.value = 0x04  # 0x04 & 0x03 == 0
    entity._handle_coordinator_update()
    entity.async_write_ha_state.assert_not_called()


def test_mode_handle_warns_on_unknown_nonzero_value() -> None:
    """An unknown non-zero masked value is skipped (logged as a warning)."""
    module = _module(mode=0x20)  # valid 'present' for construction
    entity = HbtnSelectGroupModePush(module, _router(), _coord(), 0)
    entity.async_write_ha_state = MagicMock()
    module.mode.value = 0x80  # 0x80 & 0xF0 == 128, not a group value
    entity._handle_coordinator_update()
    entity.async_write_ha_state.assert_not_called()


def test_mode_handle_sets_valid_option() -> None:
    """A valid masked value sets the current option and writes state."""
    module = _module(mode=0x02)
    entity = HbtnSelectDaytimeModePush(module, _router(), _coord(), 0)
    entity.async_write_ha_state = MagicMock()
    module.mode.value = 0x02  # daytime 'night'
    entity._handle_coordinator_update()
    assert entity.current_option == "night"
    entity.async_write_ha_state.assert_called_once()


async def test_base_mode_select_option_module_and_router() -> None:
    """The base HbtnMode.async_select_option targets group vs router (group 0)."""
    coord = _coord()
    mod_entity = HbtnMode(_module(group=7), _router(), coord, 0)
    await mod_entity.async_select_option("day")
    assert coord.comm.async_set_group_mode.await_args.args[0] == 7

    rt_entity = HbtnMode(0, _router(), coord, 0)
    await rt_entity.async_select_option("night")
    assert coord.comm.async_set_group_mode.await_args.args[0] == 0


# ---------------------------------------------------------------------------
# router-backed + edge-case subclass branches
# ---------------------------------------------------------------------------


async def test_alarm_select_router_path() -> None:
    """The router-backed alarm select targets group 0."""
    coord = _coord()
    entity = HbtnSelectAlarmModePush(0, _router(), coord, 0)
    await entity.async_select_option("on")
    coord.comm.async_set_alarm_mode.assert_awaited_with(0, True)


async def test_group_select_module_and_router_paths() -> None:
    """Group-mode select forwards the resolved value for module + router."""
    coord = _coord()
    mod_entity = HbtnSelectGroupModePush(_module(group=5), _router(), coord, 0)
    await mod_entity.async_select_option("present")
    coord.comm.async_set_group_mode.assert_awaited_with(5, 32)

    rt_entity = HbtnSelectGroupModePush(0, _router(), coord, 0)
    await rt_entity.async_select_option("absent")
    coord.comm.async_set_group_mode.assert_awaited_with(0, 16)


def test_group_mode_handles_unprintable_and_equal_user_names() -> None:
    """Non-printable / duplicate user names fall back to ``Unbekannt(2)``."""
    router = Router(uid="ROUTER-Z", user1_name="\x00\x01", user2_name="\x00\x01")
    entity = HbtnSelectGroupModePush(_module(group=4), router, _coord(), 0)
    assert "Unbekannt" in entity.options
    assert "Unbekannt2" in entity.options


def test_daytime_module_zero_value_hotfix() -> None:
    """A module daytime sub-mode of 0 is hot-fixed to 'day'."""
    entity = HbtnSelectDaytimeModePush(_module(mode=0x04), _router(), _coord(), 0)
    assert entity.current_option == "day"


def test_daytime_router_zero_value_hotfix() -> None:
    """A router daytime sub-mode of 0 is hot-fixed to 'day'."""
    router = _router()
    router.mode.value = 0x04  # 0x04 & 0x03 == 0
    entity = HbtnSelectDaytimeModePush(0, router, _coord(), 0)
    assert entity.current_option == "day"


def test_group_mode_zero_value_hotfix() -> None:
    """A group sub-mode of 0 is hot-fixed to 'present' (32)."""
    entity = HbtnSelectGroupModePush(_module(mode=0x05), _router(), _coord(), 0)
    assert entity.current_option == "present"
