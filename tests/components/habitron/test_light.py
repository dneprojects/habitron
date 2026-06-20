"""Tests for the Habitron light platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Area, ColorLed, Dimmer, Module, Output, Router

from custom_components.habitron.light import (
    DimmedOutput,
    DimmedOutputPush,
    HbtnColorLight,
    SwitchedLight,
    async_setup_entry,
)
from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ColorMode
from homeassistant.core import HomeAssistant

from .conftest import class_attr


def _module(uid: str = "MOD-1", typ: bytes = b"\x0a\x14", **kwargs) -> Module:
    """Build a v2 model module (Smart Dimm by default, out_offs 0)."""
    return Module(uid=uid, addr=105, typ=typ, name="Mod", **kwargs)


def _coord() -> MagicMock:
    """Build a mock coordinator whose ``comm`` is an async stub."""
    coord = MagicMock()
    coord.comm = MagicMock()
    coord.comm.async_set_output = AsyncMock()
    coord.comm.async_set_dimmval = AsyncMock()
    coord.comm.async_set_rgbval = AsyncMock()
    coord.comm.async_set_rgb_output = AsyncMock()
    return coord


def _stub_write(entity) -> None:
    entity.async_write_ha_state = MagicMock()


# ---------------------------------------------------------------------------
# Class-level metadata
# ---------------------------------------------------------------------------


def test_color_modes_class_level() -> None:
    """Light classes advertise the right colour modes."""
    assert class_attr(SwitchedLight, "_attr_color_mode") is ColorMode.ONOFF
    assert class_attr(DimmedOutput, "_attr_color_mode") is ColorMode.BRIGHTNESS
    assert class_attr(HbtnColorLight, "_attr_color_mode") is ColorMode.RGB


def test_dimmed_output_translation_key() -> None:
    """DimmedOutput exposes its icon translation key."""
    assert class_attr(DimmedOutput, "_attr_translation_key") == "dimmed_output"


# ---------------------------------------------------------------------------
# SwitchedLight
# ---------------------------------------------------------------------------


def test_switched_light_unique_id_and_state() -> None:
    """SwitchedLight exposes a stable unique id and reflects the output."""
    out = Output(name="Lamp", nmbr=0, type=2)
    entity = SwitchedLight(out, _module(), _coord(), 0)
    assert entity.unique_id == "Mod_MOD-1_out0"
    assert entity.is_on is False
    out.is_on = True
    assert entity.is_on is True


def test_switched_light_empty_name_disabled() -> None:
    """An empty output name disables the entity by default."""
    out = Output(name=" ", nmbr=1, type=2)
    entity = SwitchedLight(out, _module(), _coord(), 0)
    assert entity._attr_name == "Out 2"
    assert entity._attr_entity_registry_enabled_default is False


async def test_switched_light_turn_on_off() -> None:
    """SwitchedLight forwards on/off to ``async_set_output``."""
    coord = _coord()
    entity = SwitchedLight(Output(name="Lamp", nmbr=0, type=2), _module(), coord, 0)
    await entity.async_turn_on()
    coord.comm.async_set_output.assert_awaited_with(105, 1, 1)
    await entity.async_turn_off()
    coord.comm.async_set_output.assert_awaited_with(105, 1, 0)


# ---------------------------------------------------------------------------
# DimmedOutput
# ---------------------------------------------------------------------------


def test_dimmed_output_reads_dimmer_brightness() -> None:
    """DimmedOutput derives HA brightness (0..255) from the dimmer (0..100)."""
    module = _module()
    module.dimmers = [Dimmer(name="D", nmbr=0, type=2, brightness=100)]
    out = Output(name="Lamp", nmbr=0, type=2)
    entity = DimmedOutput(out, module, _coord(), 0)
    _stub_write(entity)
    entity._handle_coordinator_update()
    assert entity.brightness == 255  # round(100 * 2.55)


async def test_dimmed_output_turn_on_with_brightness() -> None:
    """DimmedOutput.async_turn_on forwards a 0..100 dim value."""
    coord = _coord()
    module = _module()
    module.dimmers = [Dimmer(name="D", nmbr=0, type=2)]
    entity = DimmedOutput(Output(name="L", nmbr=0, type=2), module, coord, 0)
    await entity.async_turn_on(**{ATTR_BRIGHTNESS: 255})
    coord.comm.async_set_dimmval.assert_awaited_with(105, 1, 100)


def test_dimmed_output_controller_offset() -> None:
    """On a Smart Controller the dimmer offset shifts output 10/11 to dim 0/1."""
    module = _module(typ=b"\x01\x02")  # controller -> out_offs 10
    module.dimmers = [Dimmer(name="D", nmbr=0, type=2, brightness=50)]
    out = Output(name="Lamp", nmbr=10, type=2)
    entity = DimmedOutput(out, module, _coord(), 0)
    assert entity._out_offs == 10
    _stub_write(entity)
    entity._handle_coordinator_update()
    assert entity.brightness == 127  # round(50 * 2.55) == round(127.4999...)


async def test_dimmed_output_push_listener_lifecycle() -> None:
    """DimmedOutputPush subscribes/unsubscribes the output listener."""
    module = _module()
    module.dimmers = [Dimmer(name="D", nmbr=0, type=2)]
    out = Output(name="L", nmbr=0, type=2)
    entity = DimmedOutputPush(out, module, _coord(), 0)
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
        assert len(out._listeners) == 1
        await entity.async_will_remove_from_hass()
        assert len(out._listeners) == 0


# ---------------------------------------------------------------------------
# HbtnColorLight
# ---------------------------------------------------------------------------


def _cled(nmbr: int = 1, name: str = "Corner", type_: int = 4) -> ColorLed:
    return ColorLed(name=name, nmbr=nmbr, type=type_, rgb=[0, 0, 0, 0])


def test_color_light_unique_id_and_is_on() -> None:
    """HbtnColorLight exposes a stable unique id and reflects is_on."""
    cled = _cled()
    entity = HbtnColorLight(cled, _module(), _coord(), 0)
    assert entity.unique_id == "Mod_MOD-1_rgbled1"
    assert entity.is_on is False
    cled.is_on = True
    assert entity.is_on is True


def test_color_light_empty_name_and_corner_icons() -> None:
    """Empty name falls back; corner LEDs get directional icons."""
    entity = HbtnColorLight(_cled(nmbr=2, name=""), _module(), _coord(), 0)
    assert entity._attr_name == "CLED 2"
    assert entity._attr_icon == "mdi:arrow-top-right-bold-box-outline"


def test_color_light_negative_type_disabled() -> None:
    """A negative colour-LED type disables the entity by default."""
    entity = HbtnColorLight(_cled(type_=-4), _module(), _coord(), 0)
    assert entity._attr_entity_registry_enabled_default is False


def test_color_light_handle_update_derives_color_and_brightness() -> None:
    """_handle_coordinator_update rescales the dimmed rgb to a 100% colour."""
    cled = _cled()
    cled.is_on = True
    cled.rgb = [128, 64, 0, 0]
    entity = HbtnColorLight(cled, _module(), _coord(), 0)
    _stub_write(entity)
    entity._handle_coordinator_update()
    assert entity.brightness == 128
    assert entity.rgb_color == (255, 128, 0)


def test_color_light_handle_update_all_off_zero_brightness() -> None:
    """When all channels are zero the brightness drops to 0."""
    cled = _cled()
    cled.rgb = [0, 0, 0, 0]
    entity = HbtnColorLight(cled, _module(), _coord(), 0)
    _stub_write(entity)
    entity._handle_coordinator_update()
    assert entity.brightness == 0


async def test_color_light_turn_on_sets_rgb() -> None:
    """HbtnColorLight.async_turn_on writes the dimmed rgb to the bus + model."""
    coord = _coord()
    cled = _cled()
    entity = HbtnColorLight(cled, _module(), coord, 0)
    await entity.async_turn_on(**{ATTR_RGB_COLOR: (200, 100, 0), ATTR_BRIGHTNESS: 255})
    assert cled.is_on is True
    assert cled.rgb == [200, 100, 1, 0]  # blue channel clamped to min 1
    coord.comm.async_set_rgbval.assert_awaited_with(105, 1, [200, 100, 1])


async def test_color_light_turn_off() -> None:
    """HbtnColorLight.async_turn_off clears the LED and notifies the bus."""
    coord = _coord()
    cled = _cled()
    cled.is_on = True
    entity = HbtnColorLight(cled, _module(), coord, 0)
    await entity.async_turn_off()
    assert cled.is_on is False
    coord.comm.async_set_rgb_output.assert_awaited_with(105, 1, 0)


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_async_setup_entry_emits_dimmer_and_color(hass: HomeAssistant) -> None:
    """async_setup_entry creates dimmed outputs and colour LEDs."""
    module = Module(uid="MOD-1", addr=105, typ=b"\x01\x04", name="Touch")
    module.outputs = [Output(name="Dim", nmbr=0, type=2)]
    module.dimmers = [Dimmer(name="Dim", nmbr=0, type=2)]
    module.color_leds = [ColorLed(name="", nmbr=0, type=4, rgb=[0, 0, 0, 0])]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    router.areas = [Area(nmbr=0, name="House")]
    entry = MagicMock()
    entry.runtime_data.router = router
    entry.runtime_data.coordinator = _coord()

    added: list = []
    with patch("custom_components.habitron.light.er.async_get") as mock_get:
        mock_get.return_value.async_get_entity_id = MagicMock(return_value=None)
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, DimmedOutputPush) for e in added)
    assert any(isinstance(e, HbtnColorLight) for e in added)
