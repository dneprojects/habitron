"""Tests for the Habitron switch platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Area, Flag, Led, Module, Output, Router

from custom_components.habitron.switch import (
    ClimateCtlSwitch,
    HbtnFlag,
    MicrophoneSwitch,
    SwitchedLed,
    SwitchedOutput,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant

from .conftest import class_attr

# ---------------------------------------------------------------------------
# Builders for real v2 model objects
# ---------------------------------------------------------------------------


def _module(uid: str = "MOD-1", addr: int = 105, name: str = "Mod", **kwargs) -> Module:
    """Build a v2 model module with sensible defaults."""
    return Module(uid=uid, addr=addr, typ=b"\x01\x02", name=name, **kwargs)


def _coord() -> MagicMock:
    """Build a mock coordinator whose ``comm`` is an async stub."""
    coord = MagicMock()
    coord.comm = MagicMock()
    coord.comm.async_set_output = AsyncMock()
    coord.comm.async_set_led_outp = AsyncMock()
    coord.comm.async_set_flag = AsyncMock()
    coord.comm.async_set_climate_mode = AsyncMock()
    return coord


# ---------------------------------------------------------------------------
# Class-level metadata
# ---------------------------------------------------------------------------


def test_translation_keys_set() -> None:
    """State-based switch entities expose translation keys for icons."""
    assert class_attr(HbtnFlag, "_attr_translation_key") == "habitron_flag"
    assert class_attr(MicrophoneSwitch, "_attr_translation_key") == "microphone"
    assert class_attr(ClimateCtlSwitch, "_attr_translation_key") == "climate_ctl"


# ---------------------------------------------------------------------------
# SwitchedOutput
# ---------------------------------------------------------------------------


def test_switched_output_unique_id_and_state() -> None:
    """SwitchedOutput exposes a stable unique id and reflects member state."""
    out = Output(name="Out 1", nmbr=0, type=1)
    entity = SwitchedOutput(_coord(), _module(), out, 0)
    assert entity.unique_id == "Mod_MOD-1_out0"
    assert entity.is_on is False
    out.is_on = True
    assert entity.is_on is True


def test_switched_output_empty_name_falls_back_to_default() -> None:
    """An empty output name produces the auto-generated ``Out <n+1>``."""
    out = Output(name=" ", nmbr=2, type=1)
    entity = SwitchedOutput(_coord(), _module(), out, 0)
    assert entity._attr_name == "Out 3"


def test_switched_output_negative_type_is_disabled_default() -> None:
    """A negative output.type marks the entity disabled by default."""
    out = Output(name="Out 1", nmbr=0, type=-1)
    entity = SwitchedOutput(_coord(), _module(), out, 0)
    assert entity._attr_entity_registry_enabled_default is False


async def test_switched_output_turn_on_forwards_to_comm() -> None:
    """``async_turn_on`` calls ``comm.async_set_output`` with the module addr."""
    coord = _coord()
    entity = SwitchedOutput(coord, _module(), Output(name="Out 1", nmbr=0, type=1), 0)
    await entity.async_turn_on()
    coord.comm.async_set_output.assert_awaited_with(105, 1, 1)


async def test_switched_output_turn_off_forwards_to_comm() -> None:
    """``async_turn_off`` calls ``comm.async_set_output`` with 0."""
    coord = _coord()
    entity = SwitchedOutput(coord, _module(), Output(name="Out 1", nmbr=0, type=1), 0)
    await entity.async_turn_off()
    coord.comm.async_set_output.assert_awaited_with(105, 1, 0)


async def test_switched_output_listener_lifecycle() -> None:
    """The entity subscribes/unsubscribes the member listener on add/remove."""
    out = Output(name="Out 1", nmbr=0, type=1)
    entity = SwitchedOutput(_coord(), _module(), out, 0)
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
# SwitchedLed
# ---------------------------------------------------------------------------


def test_switched_led_naming_and_unique_id() -> None:
    """LED naming follows the white/red convention and a stable unique id."""
    white = SwitchedLed(_coord(), _module(), Led(name="", nmbr=0, type=0), 0)
    assert white._attr_name == "LED white "
    assert white.unique_id == "Mod_MOD-1_led0"
    red = SwitchedLed(_coord(), _module(), Led(name="Strip", nmbr=1, type=0), 0)
    assert red._attr_name == "LED red 1: Strip"


def test_switched_led_icons() -> None:
    """Icon depends on the LED number and on/off state."""
    red = SwitchedLed(_coord(), _module(), Led(name="r", nmbr=1, type=0), 0)
    red._led.is_on = False
    assert red.icon == "mdi:circle-outline"
    red._led.is_on = True
    assert red.icon == "mdi:circle-double"
    white = SwitchedLed(_coord(), _module(), Led(name="w", nmbr=0, type=0), 0)
    white._led.is_on = True
    assert white.icon == "mdi:white-balance-sunny"
    white._led.is_on = False
    assert white.icon == "mdi:circle-medium"


async def test_switched_led_turn_on_off() -> None:
    """SwitchedLed forwards on/off to ``async_set_led_outp``."""
    coord = _coord()
    entity = SwitchedLed(coord, _module(), Led(name="r", nmbr=2, type=0), 0)
    await entity.async_turn_on()
    coord.comm.async_set_led_outp.assert_awaited_with(105, 2, 1)
    await entity.async_turn_off()
    coord.comm.async_set_led_outp.assert_awaited_with(105, 2, 0)


# ---------------------------------------------------------------------------
# HbtnFlag (module + router)
# ---------------------------------------------------------------------------


async def test_habitron_flag_module_path() -> None:
    """A module flag uses the module address; is_on tracks the value."""
    coord = _coord()
    flag = Flag(name="F", nmbr=5, value=0)
    entity = HbtnFlag(coord, flag, device_uid="MOD-1", mod_addr=105, idx=0)
    assert entity.unique_id == "Mod_MOD-1_flag5"
    assert entity.is_on is False
    await entity.async_turn_on()
    coord.comm.async_set_flag.assert_awaited_with(105, 5, 1)
    flag.value = 1
    assert entity.is_on is True
    await entity.async_turn_off()
    coord.comm.async_set_flag.assert_awaited_with(105, 5, 0)


async def test_habitron_flag_router_path() -> None:
    """A router flag uses the router id as the address."""
    coord = _coord()
    flag = Flag(name="F", nmbr=3, value=0)
    entity = HbtnFlag(coord, flag, device_uid="ROUTER-1", mod_addr=7, idx=0)
    await entity.async_turn_on()
    coord.comm.async_set_flag.assert_awaited_with(7, 3, 1)


async def test_habitron_flag_listener_lifecycle() -> None:
    """HbtnFlag subscribes/unsubscribes its flag listener."""
    flag = Flag(name="F", nmbr=1, value=0)
    entity = HbtnFlag(_coord(), flag, device_uid="MOD-1", mod_addr=105, idx=0)
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
        assert len(flag._listeners) == 1
        await entity.async_will_remove_from_hass()
        assert len(flag._listeners) == 0


# ---------------------------------------------------------------------------
# ClimateCtlSwitch
# ---------------------------------------------------------------------------


def test_climate_ctl_switch_state_and_device_info() -> None:
    """ClimateCtlSwitch derives its state from ``module.climate_ctl12``."""
    module = _module()
    module.climate_ctl12 = 2
    entity = ClimateCtlSwitch(_coord(), module)
    assert entity.is_on is True
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]
    module.climate_ctl12 = 1
    assert entity.is_on is False


async def test_climate_ctl_switch_turn_on_off() -> None:
    """Turning the switch on/off flips ``climate_ctl12`` and calls comm."""
    coord = _coord()
    module = _module()
    module.climate_ctl12 = 1
    entity = ClimateCtlSwitch(coord, module)
    await entity.async_turn_on()
    assert module.climate_ctl12 == 2
    await entity.async_turn_off()
    assert module.climate_ctl12 == 1
    coord.comm.async_set_climate_mode.assert_awaited()


# ---------------------------------------------------------------------------
# MicrophoneSwitch
# ---------------------------------------------------------------------------


def _mic_provider(stream_name: str = "touch_1") -> MagicMock:
    """Build a ws provider with one active connection."""
    provider = MagicMock()
    provider.active_ws_connections = {stream_name: MagicMock()}
    return provider


def test_microphone_switch_unique_id_and_device_info() -> None:
    """MicrophoneSwitch exposes a stable unique id and device info."""
    module = _module(uid="MOD-MIC", name="Touch 1")
    entity = MicrophoneSwitch(module, _mic_provider())
    assert "Mod_MOD-MIC" in entity.unique_id
    assert ("habitron", "MOD-MIC") in entity.device_info["identifiers"]
    assert entity.is_on is False


async def test_microphone_switch_turn_on_off_sends_ws() -> None:
    """On/off send audio-mode messages over the active websocket."""
    module = _module(uid="MOD-MIC", name="Touch 1")
    provider = _mic_provider()
    ws_connection = provider.active_ws_connections["touch_1"]
    entity = MicrophoneSwitch(module, provider)
    await entity.async_turn_on()
    ws_connection.send_message.assert_called_with(
        {"type": "habitron/set_webrtc_audio_mode", "audio_enabled": True}
    )
    assert entity.is_on is True
    await entity.async_turn_off()
    ws_connection.send_message.assert_called_with(
        {"type": "habitron/set_webrtc_audio_mode", "audio_enabled": False}
    )
    assert entity.is_on is False


async def test_microphone_switch_no_ws_connection_no_op() -> None:
    """No active websocket → state still updates without crashing."""
    module = _module(uid="MOD-MIC", name="Touch 1")
    provider = MagicMock()
    provider.active_ws_connections = {}
    entity = MicrophoneSwitch(module, provider)
    await entity.async_turn_on()
    assert entity.is_on is True


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


def _entry_for(router: Router, *, ws_provider: MagicMock | None = None) -> MagicMock:
    """Build a config entry whose runtime_data exposes router/coordinator."""
    entry = MagicMock()
    entry.runtime_data.router = router
    entry.runtime_data.coordinator = _coord()
    entry.runtime_data.ws_provider = ws_provider
    return entry


async def test_async_setup_entry_emits_all_entity_types(hass: HomeAssistant) -> None:
    """async_setup_entry creates output/led/flag/climate/microphone + router flag."""
    module = Module(
        uid="MOD-MIC",
        addr=105,
        typ=b"\x01\x05",
        name="Touch 1",
        mod_type="Smart Controller Touch",
    )
    module.outputs = [Output(name="Out", nmbr=0, type=1)]
    module.leds = [Led(name="white", nmbr=0, type=0), Led(name="", nmbr=1, type=0)]
    module.flags = [Flag(name="F", nmbr=1, value=0)]
    router = Router(uid="ROUTER-1", id=7)
    router.modules = [module]
    router.flags = [Flag(name="RF", nmbr=1, value=0)]
    router.areas = [Area(nmbr=0, name="House")]
    entry = _entry_for(router, ws_provider=_mic_provider())

    added: list = []
    with patch("custom_components.habitron.switch.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value=None)
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert any(isinstance(e, SwitchedOutput) for e in added)
    assert sum(isinstance(e, SwitchedLed) for e in added) == 2
    assert sum(isinstance(e, HbtnFlag) for e in added) == 2  # module + router flag
    assert any(isinstance(e, ClimateCtlSwitch) for e in added)
    assert any(isinstance(e, MicrophoneSwitch) for e in added)


async def test_async_setup_entry_skips_cled_zero_for_rgb(hass: HomeAssistant) -> None:
    """For typ b"\x01\x04" the CLED 0 (ambient) is skipped."""  # noqa: D301
    module = Module(uid="MOD-RGB", addr=105, typ=b"\x01\x04", name="Touch")
    module.leds = [Led(name="w", nmbr=0, type=0), Led(name="r", nmbr=1, type=0)]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    entry = _entry_for(router)

    added: list = []
    with patch("custom_components.habitron.switch.er.async_get") as mock_get:
        mock_get.return_value.async_get_entity_id = MagicMock(return_value=None)
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert sum(isinstance(e, SwitchedLed) for e in added) == 1


async def test_async_setup_entry_assigns_external_area(hass: HomeAssistant) -> None:
    """An output in a known, non-module area is moved into that HA area."""
    module = Module(uid="MOD-AL", addr=105, typ=b"\x00\x00", name="Out")
    module.outputs = [Output(name="Out 1", nmbr=0, type=1, area=5)]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    router.areas = [Area(nmbr=5, name="Living Room")]
    entry = _entry_for(router)

    with patch("custom_components.habitron.switch.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="switch.fake")
        reg_entry = MagicMock()
        reg_entry.hidden = False
        registry.async_get.return_value = reg_entry
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_called_with(
        "switch.fake", area_id="living_room"
    )


async def test_async_setup_entry_unknown_area_clamped_to_default(
    hass: HomeAssistant,
) -> None:
    """An out-of-range area index is reset to the no-area default."""
    module = Module(uid="MOD-OV", addr=105, typ=b"\x00\x00", name="Out")
    module.outputs = [Output(name="Out 1", nmbr=0, type=1, area=99)]
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    router.areas = [Area(nmbr=0, name="House")]
    entry = _entry_for(router)

    with patch("custom_components.habitron.switch.er.async_get") as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="switch.fake")
        reg_entry = MagicMock()
        reg_entry.hidden = False
        registry.async_get.return_value = reg_entry
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    registry.async_update_entity.assert_called_with("switch.fake", area_id=None)
