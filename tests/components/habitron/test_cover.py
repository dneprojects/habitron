"""Tests for the Habitron cover platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Area, Cover, Module, Output, Router

from custom_components.habitron.cover import HbtnBlind, HbtnShutter, async_setup_entry
from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
)
from homeassistant.core import HomeAssistant

from .conftest import class_attr


def _coord(autostop: int = 5) -> MagicMock:
    """Build a mock coordinator with comm stubs and the autostop delay."""
    coord = MagicMock()
    coord.comm = MagicMock()
    coord.comm.router.cover_autostop_del = autostop
    coord.comm.async_set_output = AsyncMock()
    coord.comm.async_set_shutterpos = AsyncMock()
    coord.comm.async_set_blindtilt = AsyncMock()
    return coord


def _module(typ: bytes = b"\x0a\x01", **kwargs) -> Module:
    """Build a Smart Out module with two outputs backing one cover."""
    module = Module(uid="MOD-1", addr=105, typ=typ, name="Mod", **kwargs)
    if not module.outputs:
        module.outputs = [Output(name="o", nmbr=i, type=-10) for i in range(2)]
    return module


def _shutter(cover: Cover | None = None, module: Module | None = None) -> HbtnShutter:
    """Build a ready-to-test HbtnShutter with a stubbed hass."""
    cover = cover or Cover(name="Sh", nmbr=0, type=1, position=0)
    entity = HbtnShutter(cover, module or _module(), _coord(), 0)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    return entity


def test_cover_device_classes() -> None:
    """Shutter is a SHUTTER device, Blind a BLIND."""
    assert class_attr(HbtnShutter, "_attr_device_class") is CoverDeviceClass.SHUTTER
    assert class_attr(HbtnBlind, "_attr_device_class") is CoverDeviceClass.BLIND


def test_shutter_unique_id_and_position() -> None:
    """Position is reported inverted (100 - bus value)."""
    cover = Cover(name="Sh", nmbr=0, type=1, position=30)
    entity = _shutter(cover)
    assert entity.unique_id == "Mod_MOD-1_cover0"
    assert entity.current_cover_position == 70


def test_shutter_empty_name_disabled() -> None:
    """An empty cover name disables the entity by default."""
    entity = _shutter(Cover(name=" ", nmbr=0, type=1, position=0))
    assert entity._attr_entity_registry_enabled_default is False


def test_shutter_polarity_swaps_outputs() -> None:
    """A negative polarity swaps the up/down backing outputs."""
    pos = _shutter(Cover(name="Sh", nmbr=0, type=1, position=0))
    assert (pos._out_up, pos._out_down) == (0, 1)
    neg = _shutter(Cover(name="Sh", nmbr=0, type=-1, position=0))
    assert (neg._out_up, neg._out_down) == (1, 0)


async def test_shutter_open_close_stop() -> None:
    """Open/close/stop drive the matching backing outputs."""
    entity = _shutter()
    await entity.async_open_cover()
    entity.coordinator.comm.async_set_output.assert_awaited_with(105, 1, 1)
    assert entity.is_opening is True
    await entity.async_close_cover()
    entity.coordinator.comm.async_set_output.assert_awaited_with(105, 2, 1)
    assert entity.is_closing is True
    await entity.async_stop_cover()
    assert entity._moving == 0


async def test_shutter_set_position_calls_shutterpos() -> None:
    """Setting a position forwards the inverted target to the bus."""
    entity = _shutter(Cover(name="Sh", nmbr=0, type=1, position=0))  # at 100
    await entity.async_set_cover_position(**{ATTR_POSITION: 40})
    entity.coordinator.comm.async_set_shutterpos.assert_awaited_with(105, 1, 60)


async def test_shutter_set_position_smart_controller_remap() -> None:
    """On a Smart Controller cover indexes 1..2 remap to 4..5."""
    module = _module(typ=b"\x01\x02")
    module.mod_type = "Smart Controller XL-2"
    module.outputs = [Output(name="o", nmbr=i, type=-10) for i in range(4)]
    cover = Cover(name="Sh", nmbr=0, type=1, position=0)
    entity = HbtnShutter(cover, module, _coord(), 0)
    entity.hass = MagicMock()
    await entity.async_set_cover_position(**{ATTR_POSITION: 40})
    # sh_nmbr = 1 -> -2 -> +5 = 4
    entity.coordinator.comm.async_set_shutterpos.assert_awaited_with(105, 4, 60)


def test_shutter_moving_from_outputs() -> None:
    """Moving state derives from the backing outputs' on/off state."""
    module = _module()
    entity = _shutter(Cover(name="Sh", nmbr=0, type=1, position=50), module)
    module.outputs[0].is_on = True
    entity._handle_coordinator_update()
    assert entity._moving == 1
    module.outputs[0].is_on = False
    module.outputs[1].is_on = True
    entity._handle_coordinator_update()
    assert entity._moving == -1


def test_shutter_schedules_stop_at_endpoint() -> None:
    """Reaching the top while moving up schedules a delayed stop."""
    module = _module()
    cover = Cover(name="Sh", nmbr=0, type=1, position=0)  # -> position 100
    entity = _shutter(cover, module)
    module.outputs[0].is_on = True  # moving up
    entity._handle_coordinator_update()
    entity.hass.async_create_task.assert_called()


async def test_stop_cover_after_delay_resets_moving() -> None:
    """The delayed stop writes 0 to the active channel and resets moving."""
    entity = _shutter()
    entity._moving = 1
    with patch("custom_components.habitron.cover.asyncio.sleep", new=AsyncMock()):
        await entity._stop_cover_after_delay(0)
    entity.coordinator.comm.async_set_output.assert_awaited_with(105, 1, 0)
    assert entity._moving == 0


async def test_shutter_listener_lifecycle() -> None:
    """The entity subscribes/unsubscribes the cover listener."""
    cover = Cover(name="Sh", nmbr=0, type=1, position=0)
    entity = HbtnShutter(cover, _module(), _coord(), 0)
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
        assert len(cover._listeners) == 1
        await entity.async_will_remove_from_hass()
        assert len(cover._listeners) == 0


# ---------------------------------------------------------------------------
# HbtnBlind (tilt)
# ---------------------------------------------------------------------------


def test_blind_tilt_position() -> None:
    """Blind tilt position is reported inverted from the cover tilt."""
    module = _module()
    cover = Cover(name="Bl", nmbr=0, type=2, position=0, tilt=30)
    module.covers = [cover]
    entity = HbtnBlind(cover, module, _coord(), 0)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.current_cover_tilt_position == 70


async def test_blind_set_tilt_calls_blindtilt() -> None:
    """Setting a tilt forwards the inverted target to the bus."""
    module = _module()
    cover = Cover(name="Bl", nmbr=0, type=2, position=0, tilt=0)
    module.covers = [cover]
    entity = HbtnBlind(cover, module, _coord(), 0)
    entity.hass = MagicMock()
    await entity.async_set_cover_tilt_position(**{ATTR_TILT_POSITION: 40})
    entity.coordinator.comm.async_set_blindtilt.assert_awaited_with(105, 1, 60)


async def test_blind_open_close_tilt() -> None:
    """Open/close tilt emit the 0 / 100 extremes."""
    module = _module()
    cover = Cover(name="Bl", nmbr=0, type=2, position=0, tilt=0)
    module.covers = [cover]
    entity = HbtnBlind(cover, module, _coord(), 0)
    entity.hass = MagicMock()
    await entity.async_open_cover_tilt()
    entity.coordinator.comm.async_set_blindtilt.assert_awaited_with(105, 1, 0)
    await entity.async_close_cover_tilt()
    entity.coordinator.comm.async_set_blindtilt.assert_awaited_with(105, 1, 100)


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


def _entry_for(router: Router) -> MagicMock:
    entry = MagicMock()
    entry.runtime_data.router = router
    entry.runtime_data.coordinator = _coord()
    return entry


async def test_async_setup_entry_builds_shutter_and_blind(hass: HomeAssistant) -> None:
    """async_setup_entry emits one Shutter + one Blind based on cover types."""
    module = _module()
    module.covers = [
        Cover(name="Sh", nmbr=0, type=1, position=0),
        Cover(name="Bl", nmbr=1, type=2, position=0),
    ]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    router.areas = [Area(nmbr=0, name="House")]
    entry = _entry_for(router)

    added: list = []
    with patch("custom_components.habitron.cover.er.async_get") as mock_get:
        mock_get.return_value.async_get_entity_id = MagicMock(return_value=None)
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(
        isinstance(e, HbtnShutter) and not isinstance(e, HbtnBlind) for e in added
    )
    assert any(isinstance(e, HbtnBlind) for e in added)


async def test_async_setup_entry_assigns_external_area(hass: HomeAssistant) -> None:
    """A cover in a known non-module area is moved into that HA area."""
    module = _module(typ=b"\x00\x00")
    module.covers = [Cover(name="Sh", nmbr=0, type=1, position=0, area=5)]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    router.areas = [Area(nmbr=5, name="Living Room")]
    entry = _entry_for(router)

    with patch("custom_components.habitron.cover.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="cover.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_called_with("cover.fake", area_id="living_room")
