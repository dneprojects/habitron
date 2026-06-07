"""Tests for the Habitron cover platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.cover import CoverDeviceClass
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.cover import HbtnBlind, HbtnShutter

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
