"""Tests for the Habitron cover platform."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.cover import HbtnBlind, HbtnShutter, async_setup_entry
from homeassistant.components.cover import CoverDeviceClass
from homeassistant.core import HomeAssistant

from .conftest import class_attr


async def test_cover_setup(setup_integration: MockConfigEntry) -> None:
    """The cover platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_cover_classes_register_device_classes() -> None:
    """Shutter is a SHUTTER device, Blind a BLIND."""
    assert class_attr(HbtnShutter, "_attr_device_class") is CoverDeviceClass.SHUTTER
    assert class_attr(HbtnBlind, "_attr_device_class") is CoverDeviceClass.BLIND


def _make_shutter() -> HbtnShutter:
    """Build a minimal HbtnShutter stub for unit-testing the helpers."""
    cover_desc = MagicMock()
    cover_desc.nmbr = 0
    cover_desc.area = 0
    cover_desc.type = 1
    cover_desc.name = "Test"
    module = MagicMock()
    module.uid = "MOD-1"
    module.comm.router.cover_autostop_del = 5
    coord = MagicMock()
    coord.last_update_success = True

    shutter = HbtnShutter(cover_desc, module, coord, 0)
    shutter.hass = MagicMock()
    # ``_schedule_stop`` calls ``_stop_cover_after_delay`` which returns a
    # coroutine. Replace it with a sync stub so the test does not leak a
    # never-awaited coroutine warning.
    shutter._stop_cover_after_delay = MagicMock(return_value=MagicMock())
    shutter.hass.async_create_task = MagicMock(
        return_value=MagicMock(done=lambda: False)
    )
    return shutter


@pytest.mark.parametrize("position", [0, 100])
async def test_schedule_stop_deduplicates(position: int) -> None:
    """Repeated ticks at an endpoint do not spawn additional stop tasks."""
    shutter = _make_shutter()

    shutter._schedule_stop(5)
    first_call_count = shutter.hass.async_create_task.call_count
    shutter._schedule_stop(5)
    assert shutter.hass.async_create_task.call_count == first_call_count


async def test_schedule_stop_after_completed_task_runs_again() -> None:
    """Once the previous stop task is done, a new tick schedules another."""
    shutter = _make_shutter()
    shutter._schedule_stop(5)
    # Mark the previous task as done so the helper schedules a new one.
    shutter._stop_task = MagicMock(done=lambda: True)
    shutter._schedule_stop(5)
    assert shutter.hass.async_create_task.call_count == 2


def _make_cover_descriptor() -> MagicMock:
    """Build a stub CovDescriptor for shutter tests."""
    cov = MagicMock()
    cov.nmbr = 0
    cov.area = 0
    cov.type = 1
    cov.name = "Test cover"
    cov.value = 0
    cov.tilt = 0
    return cov


def _make_cover_module() -> MagicMock:
    """Build a module stub with output channels for the shutter pair."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.typ = b"\x01\x03"
    mod.mod_type = "Smart Out"
    mod.comm.router.cover_autostop_del = 5
    mod.comm.async_set_output = AsyncMock()
    mod.comm.async_set_shutterpos = AsyncMock()
    mod.comm.async_set_blindtilt = AsyncMock()
    out_up = MagicMock()
    out_up.value = 0
    out_down = MagicMock()
    out_down.value = 0
    mod.outputs = [out_up, out_down]
    cover = MagicMock()
    cover.value = 0
    cover.tilt = 0
    mod.covers = [cover]
    return mod


async def test_async_open_cover_drives_up_channel() -> None:
    """async_open_cover writes 1 to the upward output channel."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    coord = MagicMock()
    coord.last_update_success = True
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.async_write_ha_state = MagicMock()
    await shutter.async_open_cover()
    mod.comm.async_set_output.assert_awaited_with(105, 1, 1)
    assert shutter._moving == 1


async def test_async_close_cover_drives_down_channel() -> None:
    """async_close_cover writes 1 to the downward output channel."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    coord = MagicMock()
    coord.last_update_success = True
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.async_write_ha_state = MagicMock()
    await shutter.async_close_cover()
    mod.comm.async_set_output.assert_awaited_with(105, 2, 1)
    assert shutter._moving == -1


async def test_async_stop_cover_writes_zero_to_both_outputs() -> None:
    """async_stop_cover writes 0 to both shutter outputs."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    coord = MagicMock()
    coord.last_update_success = True
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.async_write_ha_state = MagicMock()
    await shutter.async_stop_cover()
    # at least 2 set_output calls were made (one per direction)
    assert mod.comm.async_set_output.await_count >= 2


async def test_async_set_cover_position_calls_set_shutterpos() -> None:
    """async_set_cover_position forwards the inverted percentage."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    coord = MagicMock()
    coord.last_update_success = True
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.async_write_ha_state = MagicMock()
    await shutter.async_set_cover_position(position=30)
    mod.comm.async_set_shutterpos.assert_awaited()


def test_blind_tilt_position_updated_from_coordinator() -> None:
    """HbtnBlind exposes 100 - module.covers[0].tilt after a coordinator tick."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    mod.covers[0].tilt = 30
    coord = MagicMock()
    coord.last_update_success = True
    blind = HbtnBlind(cov, mod, coord, 0)
    blind.async_write_ha_state = MagicMock()
    # Initial state before any coordinator tick.
    assert blind.current_cover_tilt_position == 0
    # After a coordinator tick the module's tilt is reflected.
    blind._handle_coordinator_update()
    assert blind.current_cover_tilt_position == 70


def test_shutter_disabled_when_cover_name_empty() -> None:
    """Empty cover name → disabled-by-default + auto-generated name."""
    cov = _make_cover_descriptor()
    cov.name = "  "
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    assert shutter._attr_entity_registry_enabled_default is False
    assert shutter._attr_name == "Out 1"


def test_shutter_polarity_negative_swaps_outputs() -> None:
    """A negative cover.type swaps up/down output channels."""
    cov = _make_cover_descriptor()
    cov.type = -1
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    # cov.nmbr = 0 → out_up = 1, out_down = 0
    assert shutter._out_up == 1
    assert shutter._out_down == 0


def test_shutter_current_cover_position_reflects_value() -> None:
    """current_cover_position is 100 - cover.value."""
    cov = _make_cover_descriptor()
    cov.value = 40
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    assert shutter.current_cover_position == 60


def test_shutter_is_closed_only_when_at_zero_and_idle() -> None:
    """is_closed returns True only when position == 0 and not moving."""
    cov = _make_cover_descriptor()
    cov.value = 100  # position = 0
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter._position = 0
    shutter._moving = 0
    assert shutter.is_closed
    shutter._moving = -1
    assert not shutter.is_closed


def test_shutter_is_open_only_when_at_hundred_and_idle() -> None:
    """is_open returns True only when position == 100 and not moving."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter._position = 100
    shutter._moving = 0
    assert shutter.is_open
    shutter._moving = 1
    assert not shutter.is_open


def test_shutter_is_closing_and_is_opening() -> None:
    """is_closing/is_opening report based on the _moving sign."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter._moving = -1
    assert shutter.is_closing
    shutter._moving = 1
    assert shutter.is_opening


def test_shutter_handle_coordinator_update_moving_up_at_top_schedules_stop() -> None:
    """Position at 100, moving up, auto-stop ≥ 0 → schedule a stop task."""
    cov = _make_cover_descriptor()
    cov.value = 0  # position = 100
    mod = _make_cover_module()
    mod.outputs[0].value = 1  # up channel active
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.hass = MagicMock()
    shutter.async_write_ha_state = MagicMock()
    shutter._schedule_stop = MagicMock()
    shutter._handle_coordinator_update()
    assert shutter._moving == 1
    shutter._schedule_stop.assert_called_with(5)


def test_shutter_handle_coordinator_update_moving_down_at_bottom_schedules_stop() -> (
    None
):
    """Position at 0, moving down → schedule a stop task."""
    cov = _make_cover_descriptor()
    cov.value = 100  # position = 0
    mod = _make_cover_module()
    mod.outputs[1].value = 1  # down channel active
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.hass = MagicMock()
    shutter.async_write_ha_state = MagicMock()
    shutter._schedule_stop = MagicMock()
    shutter._handle_coordinator_update()
    assert shutter._moving == -1
    shutter._schedule_stop.assert_called_with(5)


def test_shutter_handle_coordinator_update_idle() -> None:
    """When no output is active the moving state collapses to 0."""
    cov = _make_cover_descriptor()
    cov.value = 50
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.async_write_ha_state = MagicMock()
    shutter._handle_coordinator_update()
    assert shutter._moving == 0


async def test_stop_cover_after_delay_resets_moving_up_branch() -> None:
    """_stop_cover_after_delay sends async_set_output for the up channel."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter._moving = 1
    with patch("custom_components.habitron.cover.asyncio.sleep", new=AsyncMock()):
        await shutter._stop_cover_after_delay(0)
    mod.comm.async_set_output.assert_awaited_with(105, 1, 0)
    assert shutter._moving == 0


async def test_stop_cover_after_delay_down_branch() -> None:
    """_stop_cover_after_delay uses the down channel when moving down."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter._moving = -1
    with patch("custom_components.habitron.cover.asyncio.sleep", new=AsyncMock()):
        await shutter._stop_cover_after_delay(0)
    mod.comm.async_set_output.assert_awaited_with(105, 2, 0)


async def test_stop_cover_after_delay_handles_timeout() -> None:
    """A TimeoutError is logged but does not propagate."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    mod.comm.async_set_output = AsyncMock(side_effect=TimeoutError())
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter._moving = 1
    with patch("custom_components.habitron.cover.asyncio.sleep", new=AsyncMock()):
        await shutter._stop_cover_after_delay(0)
    assert shutter._moving == 0


async def test_stop_cover_after_delay_handles_generic_exception() -> None:
    """A generic Exception is logged but does not propagate."""
    cov = _make_cover_descriptor()
    mod = _make_cover_module()
    mod.comm.async_set_output = AsyncMock(side_effect=RuntimeError("boom"))
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter._moving = 1
    with patch("custom_components.habitron.cover.asyncio.sleep", new=AsyncMock()):
        await shutter._stop_cover_after_delay(0)
    assert shutter._moving == 0


async def test_async_set_cover_position_smart_controller_remaps_low_indexes() -> None:
    """``Smart Controller`` rewinds shutter index 0 → 4."""
    cov = _make_cover_descriptor()
    cov.value = 0
    mod = _make_cover_module()
    mod.mod_type = "Smart Controller XL"
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.async_write_ha_state = MagicMock()
    await shutter.async_set_cover_position(position=30)
    # sh_nmbr starts as 1, becomes -1, then +5 → 4
    mod.comm.async_set_shutterpos.assert_awaited_with(105, 4, 70)
    assert shutter._moving == -1


async def test_async_set_cover_position_no_op_when_equal() -> None:
    """Setting the current position is a no-op (no bus call)."""
    cov = _make_cover_descriptor()
    cov.value = 70  # position = 30
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.async_write_ha_state = MagicMock()
    await shutter.async_set_cover_position(position=30)
    mod.comm.async_set_shutterpos.assert_not_called()


async def test_async_set_cover_position_moving_down_branch() -> None:
    """Position above target → moving = -1."""
    cov = _make_cover_descriptor()
    cov.value = 30  # position = 70
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.async_write_ha_state = MagicMock()
    await shutter.async_set_cover_position(position=10)
    assert shutter._moving == -1


async def test_async_set_cover_position_moving_up_branch() -> None:
    """Position below target → moving = 1."""
    cov = _make_cover_descriptor()
    cov.value = 70  # position = 30
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    shutter.async_write_ha_state = MagicMock()
    await shutter.async_set_cover_position(position=70)
    assert shutter._moving == 1


async def test_async_added_to_hass_registers_callback() -> None:
    """async_added_to_hass registers the coordinator callback."""
    cov = _make_cover_descriptor()
    cov.register_callback = MagicMock()
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await shutter.async_added_to_hass()
    cov.register_callback.assert_called()


async def test_async_will_remove_from_hass_unregisters_and_cancels_stop_task() -> None:
    """async_will_remove_from_hass removes callback + cancels stop task."""
    cov = _make_cover_descriptor()
    cov.remove_callback = MagicMock()
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    task = MagicMock(done=lambda: False)
    shutter._stop_task = task
    await shutter.async_will_remove_from_hass()
    cov.remove_callback.assert_called()
    task.cancel.assert_called()


async def test_async_will_remove_from_hass_skips_done_stop_task() -> None:
    """Done stop tasks are not re-cancelled."""
    cov = _make_cover_descriptor()
    cov.remove_callback = MagicMock()
    mod = _make_cover_module()
    coord = MagicMock()
    shutter = HbtnShutter(cov, mod, coord, 0)
    task = MagicMock(done=lambda: True)
    shutter._stop_task = task
    await shutter.async_will_remove_from_hass()
    task.cancel.assert_not_called()


async def test_blind_async_set_cover_tilt_position_calls_blindtilt() -> None:
    """async_set_cover_tilt_position pushes inverted tilt to the bus."""
    cov = _make_cover_descriptor()
    cov.type = 2
    mod = _make_cover_module()
    coord = MagicMock()
    blind = HbtnBlind(cov, mod, coord, 0)
    blind.async_write_ha_state = MagicMock()
    await blind.async_set_cover_tilt_position(tilt_position=80)
    mod.comm.async_set_blindtilt.assert_awaited_with(105, 1, 20)


async def test_blind_async_set_cover_tilt_position_smart_controller_remap() -> None:
    """Smart Controller remap also applies to tilt setter."""
    cov = _make_cover_descriptor()
    cov.type = 2
    mod = _make_cover_module()
    mod.mod_type = "Smart Controller II"
    coord = MagicMock()
    blind = HbtnBlind(cov, mod, coord, 0)
    blind.async_write_ha_state = MagicMock()
    await blind.async_set_cover_tilt_position(tilt_position=50)
    # sh_nmbr 1 → -1 → +5 = 4
    mod.comm.async_set_blindtilt.assert_awaited_with(105, 4, 50)


async def test_blind_async_open_cover_tilt_emits_zero() -> None:
    """async_open_cover_tilt sends a tilt value of 0."""
    cov = _make_cover_descriptor()
    cov.type = 2
    mod = _make_cover_module()
    coord = MagicMock()
    blind = HbtnBlind(cov, mod, coord, 0)
    blind.async_write_ha_state = MagicMock()
    await blind.async_open_cover_tilt()
    mod.comm.async_set_blindtilt.assert_awaited_with(105, 1, 0)


async def test_blind_async_open_cover_tilt_smart_controller_remap() -> None:
    """Smart Controller remap also applies to open-tilt."""
    cov = _make_cover_descriptor()
    cov.type = 2
    mod = _make_cover_module()
    mod.mod_type = "Smart Controller"
    coord = MagicMock()
    blind = HbtnBlind(cov, mod, coord, 0)
    blind.async_write_ha_state = MagicMock()
    await blind.async_open_cover_tilt()
    mod.comm.async_set_blindtilt.assert_awaited_with(105, 4, 0)


async def test_blind_async_close_cover_tilt_emits_hundred() -> None:
    """async_close_cover_tilt sends a tilt value of 100."""
    cov = _make_cover_descriptor()
    cov.type = 2
    mod = _make_cover_module()
    coord = MagicMock()
    blind = HbtnBlind(cov, mod, coord, 0)
    blind.async_write_ha_state = MagicMock()
    await blind.async_close_cover_tilt()
    mod.comm.async_set_blindtilt.assert_awaited_with(105, 1, 100)


async def test_blind_async_close_cover_tilt_smart_controller_remap() -> None:
    """Smart Controller remap also applies to close-tilt."""
    cov = _make_cover_descriptor()
    cov.type = 2
    mod = _make_cover_module()
    mod.mod_type = "Smart Controller XL"
    coord = MagicMock()
    blind = HbtnBlind(cov, mod, coord, 0)
    blind.async_write_ha_state = MagicMock()
    await blind.async_close_cover_tilt()
    mod.comm.async_set_blindtilt.assert_awaited_with(105, 4, 100)


def test_blind_handle_coordinator_update_moving_up_schedules_stop() -> None:
    """Blind at top, moving up → _schedule_stop call."""
    cov = _make_cover_descriptor()
    cov.type = 2
    cov.value = 0
    mod = _make_cover_module()
    mod.outputs[0].value = 1
    coord = MagicMock()
    blind = HbtnBlind(cov, mod, coord, 0)
    blind.async_write_ha_state = MagicMock()
    blind._schedule_stop = MagicMock()
    blind._handle_coordinator_update()
    blind._schedule_stop.assert_called_with(5)
    assert blind._moving == 1


def test_blind_handle_coordinator_update_moving_down_schedules_stop() -> None:
    """Blind at bottom, moving down → _schedule_stop call."""
    cov = _make_cover_descriptor()
    cov.type = 2
    cov.value = 100
    mod = _make_cover_module()
    mod.outputs[1].value = 1
    coord = MagicMock()
    blind = HbtnBlind(cov, mod, coord, 0)
    blind.async_write_ha_state = MagicMock()
    blind._schedule_stop = MagicMock()
    blind._handle_coordinator_update()
    blind._schedule_stop.assert_called_with(5)
    assert blind._moving == -1


async def test_async_setup_entry_builds_shutter_and_blind(hass: HomeAssistant) -> None:
    """async_setup_entry emits one Shutter + one Blind based on cover types."""
    cov_shutter = MagicMock()
    cov_shutter.nmbr = 0
    cov_shutter.type = 1
    cov_shutter.name = "Sh 1"
    cov_shutter.area = 0
    cov_shutter.value = 0
    cov_shutter.tilt = 0
    cov_blind = MagicMock()
    cov_blind.nmbr = 1
    cov_blind.type = 2
    cov_blind.name = "Bl 1"
    cov_blind.area = 0
    cov_blind.value = 0
    cov_blind.tilt = 0
    cov_disabled = MagicMock()
    cov_disabled.nmbr = -1
    cov_disabled.type = 1
    cov_disabled.area = 0

    mod = _make_cover_module()
    mod.covers = [cov_shutter, cov_blind, cov_disabled]
    mod.outputs = [MagicMock(value=0) for _ in range(8)]
    mod.area_member = 0

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    with patch(
        "custom_components.habitron.cover.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="cover.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, HbtnShutter) for e in added)
    assert any(isinstance(e, HbtnBlind) for e in added)
    registry.async_update_entity.assert_called()


async def test_async_setup_entry_assigns_external_area(hass: HomeAssistant) -> None:
    """A cover area that differs from area_member writes the area_id."""
    cov = _make_cover_descriptor()
    cov.area = 1
    cov.nmbr = 0
    cov.value = 0
    mod = _make_cover_module()
    mod.covers = [cov]
    mod.outputs = [MagicMock(value=0), MagicMock(value=0)]
    mod.area_member = 0

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    area = MagicMock()
    area.get_name_id = MagicMock(return_value="area_1_id")
    router.areas = {0: area, 1: area}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.cover.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="cover.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_called_with("cover.fake", area_id="area_1_id")


async def test_async_setup_entry_area_overflow_falls_back_to_zero(
    hass: HomeAssistant,
) -> None:
    """An out-of-range area index is clamped to zero (default)."""
    cov = _make_cover_descriptor()
    cov.area = 99  # > len(areas)
    cov.nmbr = 0
    cov.value = 0
    mod = _make_cover_module()
    mod.covers = [cov]
    mod.outputs = [MagicMock(value=0), MagicMock(value=0)]
    mod.area_member = 0

    router = MagicMock()
    router.modules = [mod]
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.cover.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="cover.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_called_with("cover.fake", area_id=None)
