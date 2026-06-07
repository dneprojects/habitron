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


@pytest.mark.parametrize("position", [0, 100])
async def test_schedule_stop_deduplicates(position: int) -> None:
    """Repeated ticks at an endpoint do not spawn additional stop tasks."""
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
    # Patch hass for the helper.
    shutter.hass = MagicMock()
    shutter.hass.async_create_task = MagicMock(return_value=MagicMock(done=lambda: False))

    shutter._schedule_stop(5)
    first_call_count = shutter.hass.async_create_task.call_count
    # Second schedule with the same active task is a no-op.
    shutter._schedule_stop(5)
    assert shutter.hass.async_create_task.call_count == first_call_count
