"""Tests for the Habitron switch platform."""

from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.module import HbtnModule
from custom_components.habitron.router import HbtnRouter
from custom_components.habitron.switch import (
    ClimateCtlSwitch,
    HbtnFlag,
    HbtnFlagPush,
    MicrophoneSwitch,
    SwitchedLed,
    SwitchedOutput,
    SwitchedOutputPush,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant

from .conftest import class_attr


async def test_switch_setup(setup_integration: MockConfigEntry) -> None:
    """The switch platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_translation_keys_set() -> None:
    """State-based switch entities expose translation keys for icons."""
    assert class_attr(HbtnFlag, "_attr_translation_key") == "habitron_flag"
    assert class_attr(MicrophoneSwitch, "_attr_translation_key") == "microphone"
    assert class_attr(ClimateCtlSwitch, "_attr_translation_key") == "climate_ctl"


def _make_output(name: str = "Out 1", nmbr: int = 0, type_: int = 1) -> MagicMock:
    """Build a stub IfDescriptor for switch outputs."""
    out = MagicMock()
    out.nmbr = nmbr
    out.name = name
    out.type = type_
    out.area = 0
    out.value = 0
    return out


def _make_module() -> MagicMock:
    """Build a stub HbtnModule with output and address."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.comm.async_set_output = AsyncMock()
    return mod


def test_switched_output_unique_id_and_state() -> None:
    """SwitchedOutput exposes a stable unique id and initial off state."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    assert entity.unique_id == "Mod_MOD-1_out0"


async def test_switched_output_turn_on_forwards_to_comm() -> None:
    """``async_turn_on`` calls ``module.comm.async_set_output`` with 1."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    await entity.async_turn_on()
    mod.comm.async_set_output.assert_awaited_with(105, 1, 1)


async def test_switched_output_turn_off_forwards_to_comm() -> None:
    """``async_turn_off`` calls ``module.comm.async_set_output`` with 0."""
    out = _make_output()
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    await entity.async_turn_off()
    mod.comm.async_set_output.assert_awaited_with(105, 1, 0)


def test_switched_output_handles_coordinator_update_on() -> None:
    """_handle_coordinator_update flips is_on when the output is set."""
    out = _make_output()
    out.value = 1
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_is_on is True


def test_switched_output_handles_coordinator_update_off() -> None:
    """_handle_coordinator_update flips is_on=False when value is 0."""
    out = _make_output()
    out.value = 0
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_is_on is False


def _make_led_descriptor(nmbr: int = 0) -> MagicMock:
    """Build a stub IfDescriptor for SwitchedLed."""
    led = MagicMock()
    led.nmbr = nmbr
    led.name = f"LED {nmbr}"
    led.type = 1
    led.value = 0
    return led


def _make_led_module() -> MagicMock:
    """Build a stub HbtnModule for a SwitchedLed entity."""
    mod = _make_module()
    mod.comm.async_set_led_outp = AsyncMock()
    return mod


async def test_switched_led_turn_on_calls_comm() -> None:
    """SwitchedLed.async_turn_on forwards to ``comm.async_set_led_outp``."""

    led = _make_led_descriptor(nmbr=1)
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    await entity.async_turn_on()
    mod.comm.async_set_led_outp.assert_awaited_with(105, 1, 1)


def _make_flag_descriptor(nmbr: int = 0) -> MagicMock:
    """Build a stub StateDescriptor for HbtnFlag."""
    flag = MagicMock()
    flag.nmbr = nmbr
    flag.name = "Test flag"
    flag.type = 1
    flag.value = 0
    return flag


def _make_flag_module() -> MagicMock:
    """Build a stub HbtnModule for HbtnFlag tests."""
    mod = _make_module()
    mod.comm.async_set_flag = AsyncMock()
    return mod


async def test_habitron_flag_turn_on_forwards_to_comm() -> None:
    """HbtnFlag.async_turn_on writes 1 to the bus."""
    flag = _make_flag_descriptor(nmbr=5)
    mod = _make_flag_module()
    coord = MagicMock()
    entity = HbtnFlag(flag, mod, coord, 0)
    await entity.async_turn_on()
    mod.comm.async_set_flag.assert_awaited()


async def test_habitron_flag_turn_off_forwards_to_comm() -> None:
    """HbtnFlag.async_turn_off writes 0 to the bus."""
    flag = _make_flag_descriptor(nmbr=5)
    mod = _make_flag_module()
    coord = MagicMock()
    entity = HbtnFlag(flag, mod, coord, 0)
    await entity.async_turn_off()
    mod.comm.async_set_flag.assert_awaited()


def test_habitron_flag_handles_coordinator_update() -> None:
    """HbtnFlag._handle_coordinator_update mirrors the flag value."""
    flag = _make_flag_descriptor()
    flag.value = 1
    mod = _make_flag_module()
    coord = MagicMock()
    entity = HbtnFlag(flag, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.is_on is True


def test_climate_ctl_switch_initial_state_from_climate_ctl12() -> None:
    """ClimateCtlSwitch derives its initial state from module.climate_ctl12."""
    mod = _make_module()
    mod.climate_ctl12 = 2
    mod.comm.async_set_climate_mode = AsyncMock()
    entity = ClimateCtlSwitch(mod)
    assert entity.is_on is True
    mod.climate_ctl12 = 0
    assert entity.is_on is False


async def test_climate_ctl_switch_turn_on_sets_module_state() -> None:
    """ClimateCtlSwitch.async_turn_on flips climate_ctl12 to 2."""
    mod = _make_module()
    mod.climate_ctl12 = 0
    mod.comm.async_set_climate_mode = AsyncMock()
    entity = ClimateCtlSwitch(mod)
    await entity.async_turn_on()
    assert mod.climate_ctl12 == 2


async def test_climate_ctl_switch_turn_off_sets_module_state() -> None:
    """ClimateCtlSwitch.async_turn_off flips climate_ctl12 to 1."""
    mod = _make_module()
    mod.climate_ctl12 = 2
    mod.comm.async_set_climate_mode = AsyncMock()
    entity = ClimateCtlSwitch(mod)
    await entity.async_turn_off()
    assert mod.climate_ctl12 == 1


def test_switched_output_empty_name_falls_back_to_default() -> None:
    """An empty output name produces the auto-generated ``Out <n+1>``."""
    out = _make_output(name=" ", nmbr=2)
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    assert entity._attr_name == "Out 3"


def test_switched_output_negative_type_is_disabled_default() -> None:
    """A negative output.type marks the entity disabled by default."""
    out = _make_output(type_=-1)
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutput(out, mod, coord, 0)
    assert entity._attr_entity_registry_enabled_default is False


async def test_switched_output_push_register_callback_on_added() -> None:
    """SwitchedOutputPush registers its callback on async_added_to_hass."""
    out = _make_output()
    out.register_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutputPush(out, mod, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    out.register_callback.assert_called()


async def test_switched_output_push_remove_callback_on_remove() -> None:
    """SwitchedOutputPush unregisters its callback on async_will_remove_from_hass."""
    out = _make_output()
    out.remove_callback = MagicMock()
    mod = _make_module()
    coord = MagicMock()
    entity = SwitchedOutputPush(out, mod, coord, 0)
    await entity.async_will_remove_from_hass()
    out.remove_callback.assert_called()


def test_switched_led_icon_for_red_led_off() -> None:
    """LED with nmbr > 0 and state off → circle-outline icon."""
    led = _make_led_descriptor(nmbr=1)
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    entity._state = False
    assert entity.icon == "mdi:circle-outline"


def test_switched_led_icon_for_red_led_on() -> None:
    """LED with nmbr > 0 and state on → circle-double icon."""
    led = _make_led_descriptor(nmbr=1)
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    entity._state = True
    assert entity.icon == "mdi:circle-double"


def test_switched_led_icon_for_white_led_on() -> None:
    """LED 0 with state on → white-balance-sunny icon."""
    led = _make_led_descriptor(nmbr=0)
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    entity._state = True
    assert entity.icon == "mdi:white-balance-sunny"


def test_switched_led_icon_for_white_led_off() -> None:
    """LED 0 with state off → circle-medium icon."""
    led = _make_led_descriptor(nmbr=0)
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    entity._state = False
    assert entity.icon == "mdi:circle-medium"


def test_switched_led_handle_coordinator_update_on() -> None:
    """_handle_coordinator_update sets _state from the LED descriptor value."""
    led = _make_led_descriptor()
    led.value = 1
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.is_on is True


async def test_switched_led_async_turn_off_writes_zero() -> None:
    """SwitchedLed.async_turn_off forwards 0 to ``async_set_led_outp``."""
    led = _make_led_descriptor(nmbr=2)
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    await entity.async_turn_off()
    mod.comm.async_set_led_outp.assert_awaited_with(105, 2, 0)
    assert entity.is_on is False


async def test_switched_led_async_added_to_hass_registers() -> None:
    """SwitchedLed.async_added_to_hass registers a coordinator-update callback."""
    led = _make_led_descriptor()
    led.register_callback = MagicMock()
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    led.register_callback.assert_called()


async def test_switched_led_async_will_remove_from_hass_unregisters() -> None:
    """SwitchedLed.async_will_remove_from_hass removes the callback."""
    led = _make_led_descriptor()
    led.remove_callback = MagicMock()
    mod = _make_led_module()
    coord = MagicMock()
    entity = SwitchedLed(led, mod, coord, 0)
    await entity.async_will_remove_from_hass()
    led.remove_callback.assert_called()


async def test_habitron_flag_turn_on_module_path() -> None:
    """HbtnFlag.async_turn_on uses mod.mod_addr for HbtnModule instances."""
    flag = _make_flag_descriptor(nmbr=5)
    mod = MagicMock(spec=HbtnModule)
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.comm = MagicMock()
    mod.comm.async_set_flag = AsyncMock()
    coord = MagicMock()
    entity = HbtnFlag(flag, mod, coord, 0)
    await entity.async_turn_on()
    mod.comm.async_set_flag.assert_awaited_with(105, 5, 1)
    assert entity.is_on is True


async def test_habitron_flag_turn_off_module_path() -> None:
    """HbtnFlag.async_turn_off uses mod.mod_addr for HbtnModule instances."""
    flag = _make_flag_descriptor(nmbr=5)
    mod = MagicMock(spec=HbtnModule)
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.comm = MagicMock()
    mod.comm.async_set_flag = AsyncMock()
    coord = MagicMock()
    entity = HbtnFlag(flag, mod, coord, 0)
    await entity.async_turn_off()
    mod.comm.async_set_flag.assert_awaited_with(105, 5, 0)
    assert entity.is_on is False


async def test_habitron_flag_turn_on_router_path() -> None:
    """For an HbtnRouter target, async_turn_on uses ``router.id`` as address."""

    flag = _make_flag_descriptor(nmbr=3)
    rt = HbtnRouter.__new__(HbtnRouter)
    rt.uid = "ROUTER-1"
    rt.id = 7
    rt.comm = MagicMock()
    rt.comm.async_set_flag = AsyncMock()
    coord = MagicMock()
    entity = HbtnFlag(flag, rt, coord, 0)
    await entity.async_turn_on()
    rt.comm.async_set_flag.assert_awaited_with(7, 3, 1)


async def test_habitron_flag_turn_off_router_path() -> None:
    """For an HbtnRouter target, async_turn_off uses ``router.id`` as address."""

    flag = _make_flag_descriptor(nmbr=3)
    rt = HbtnRouter.__new__(HbtnRouter)
    rt.uid = "ROUTER-1"
    rt.id = 7
    rt.comm = MagicMock()
    rt.comm.async_set_flag = AsyncMock()
    coord = MagicMock()
    entity = HbtnFlag(flag, rt, coord, 0)
    await entity.async_turn_off()
    rt.comm.async_set_flag.assert_awaited_with(7, 3, 0)
    assert entity.is_on is False


async def test_habitron_flag_push_register_callback() -> None:
    """HbtnFlagPush registers its callback on async_added_to_hass."""
    flag = _make_flag_descriptor()
    flag.register_callback = MagicMock()
    mod = _make_flag_module()
    coord = MagicMock()
    entity = HbtnFlagPush(flag, mod, coord, 0)
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    flag.register_callback.assert_called()


async def test_habitron_flag_push_remove_callback() -> None:
    """HbtnFlagPush unregisters its callback on remove."""
    flag = _make_flag_descriptor()
    flag.remove_callback = MagicMock()
    mod = _make_flag_module()
    coord = MagicMock()
    entity = HbtnFlagPush(flag, mod, coord, 0)
    await entity.async_will_remove_from_hass()
    flag.remove_callback.assert_called()


def _make_microphone_module(stream_name: str = "touch_1") -> MagicMock:
    mod = MagicMock()
    mod.uid = "MOD-MIC"
    mod.name = "Touch 1"
    provider = MagicMock()
    provider.active_ws_connections = {stream_name: MagicMock()}
    mod.comm.router.smhub.ws_provider = provider
    return mod


def test_microphone_switch_unique_id_and_device_info() -> None:
    """MicrophoneSwitch exposes a stable unique id and device info."""
    mod = _make_microphone_module()
    entity = MicrophoneSwitch(mod)
    assert "Mod_MOD-MIC" in entity.unique_id
    assert ("habitron", "MOD-MIC") in entity.device_info["identifiers"]
    assert entity.is_on is False


async def test_microphone_switch_turn_on_sends_ws_message() -> None:
    """async_turn_on sends an audio-enable message on the ws connection."""
    mod = _make_microphone_module()
    ws_connection = mod.comm.router.smhub.ws_provider.active_ws_connections["touch_1"]
    entity = MicrophoneSwitch(mod)
    await entity.async_turn_on()
    ws_connection.send_message.assert_called_with(
        {"type": "habitron/set_webrtc_audio_mode", "audio_enabled": True}
    )
    assert entity.is_on is True


async def test_microphone_switch_turn_off_sends_ws_message() -> None:
    """async_turn_off sends an audio-disable message on the ws connection."""
    mod = _make_microphone_module()
    ws_connection = mod.comm.router.smhub.ws_provider.active_ws_connections["touch_1"]
    entity = MicrophoneSwitch(mod)
    entity._state = True
    await entity.async_turn_off()
    ws_connection.send_message.assert_called_with(
        {"type": "habitron/set_webrtc_audio_mode", "audio_enabled": False}
    )
    assert entity.is_on is False


async def test_microphone_switch_turn_on_no_ws_connection_no_op() -> None:
    """No active WebSocket → still updates internal state without crashing."""
    mod = _make_microphone_module()
    mod.comm.router.smhub.ws_provider.active_ws_connections = {}
    entity = MicrophoneSwitch(mod)
    await entity.async_turn_on()
    assert entity.is_on is True


async def test_microphone_switch_turn_off_no_ws_connection_no_op() -> None:
    """No active WebSocket → still updates state to off without crashing."""
    mod = _make_microphone_module()
    mod.comm.router.smhub.ws_provider.active_ws_connections = {}
    entity = MicrophoneSwitch(mod)
    entity._state = True
    await entity.async_turn_off()
    assert entity.is_on is False


def test_climate_ctl_switch_handle_coordinator_update() -> None:
    """ClimateCtlSwitch._handle_coordinator_update rereads module.climate_ctl12."""
    mod = _make_module()
    mod.climate_ctl12 = 2
    entity = ClimateCtlSwitch(mod)
    entity.async_write_ha_state = MagicMock()
    mod.climate_ctl12 = 1
    entity._handle_coordinator_update()
    assert entity.is_on is False


def test_climate_ctl_switch_device_info() -> None:
    """ClimateCtlSwitch.device_info uses the module uid."""
    mod = _make_module()
    mod.climate_ctl12 = 2
    entity = ClimateCtlSwitch(mod)
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]


async def test_async_setup_entry_emits_switch_and_led_and_flag(
    hass: HomeAssistant,
) -> None:
    """async_setup_entry creates Switch, Led, Flag, ClimateCtl, Microphone, RouterFlag."""
    out = _make_output(type_=1, nmbr=0)
    led_white = _make_led_descriptor(nmbr=0)
    led_white.type = 0
    led_white.name = "white"
    led_white.set_name = MagicMock()
    led_red = _make_led_descriptor(nmbr=1)
    led_red.type = 0
    led_red.name = ""
    led_red.set_name = MagicMock()
    flag = _make_flag_descriptor(nmbr=0)

    mod = MagicMock()
    mod.uid = "MOD-MIC"
    mod.name = "Touch 1"
    mod.mod_addr = 105
    mod.mod_type = "Smart Controller Touch"
    mod.area_member = 0
    mod.typ = b"\x01\x05"
    mod.outputs = [out]
    mod.leds = [led_white, led_red]
    mod.flags = [flag]
    mod.climate_ctl12 = 0
    provider = MagicMock()
    provider.active_ws_connections = {}
    mod.comm.router.smhub.ws_provider = provider

    rt_flag = _make_flag_descriptor(nmbr=0)
    router = MagicMock()
    router.modules = [mod]
    router.flags = [rt_flag]
    router.uid = "ROUTER-1"
    router.id = 7
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    with patch(
        "custom_components.habitron.switch.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="switch.fake")
        reg_entry = MagicMock()
        reg_entry.hidden = False
        registry.async_get.return_value = reg_entry
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, added.extend)

    assert any(isinstance(e, SwitchedOutputPush) for e in added)
    assert any(isinstance(e, SwitchedLed) for e in added)
    assert any(isinstance(e, HbtnFlagPush) for e in added)
    assert any(isinstance(e, ClimateCtlSwitch) for e in added)
    assert any(isinstance(e, MicrophoneSwitch) for e in added)


async def test_async_setup_entry_skips_cled_zero_for_rgb(hass: HomeAssistant) -> None:
    """For typ b"\x01\x04" the CLED 0 is dedicated to ambient and is skipped."""  # noqa: D301
    out = _make_output(type_=1, nmbr=0)
    led_white = _make_led_descriptor(nmbr=0)
    led_white.type = 0
    led_red = _make_led_descriptor(nmbr=1)
    led_red.type = 0
    led_red.name = "Red 1"
    led_red.set_name = MagicMock()

    mod = MagicMock()
    mod.uid = "MOD-RGB"
    mod.mod_addr = 105
    mod.mod_type = "Smart Output"
    mod.area_member = 0
    mod.typ = b"\x01\x04"  # RGB → skip cled 0
    mod.outputs = [out]
    mod.leds = [led_white, led_red]
    mod.flags = []

    router = MagicMock()
    router.modules = [mod]
    router.flags = []
    router.uid = "ROUTER-1"
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    with patch(
        "custom_components.habitron.switch.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value=None)
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, added.extend)

    # Only one LED added (the red), not the white one
    leds = [e for e in added if isinstance(e, SwitchedLed)]
    assert len(leds) == 1


async def test_async_setup_entry_logs_warning_when_entity_not_found(
    hass: HomeAssistant,
) -> None:
    """A missing registry entry triggers a warning log path."""
    out = _make_output(type_=1, nmbr=0)
    out.area = 5

    mod = MagicMock()
    mod.uid = "MOD-X"
    mod.mod_addr = 105
    mod.mod_type = "Smart Output"
    mod.area_member = 0
    mod.outputs = [out]
    mod.leds = []
    mod.flags = []
    mod.typ = b"\x00\x00"

    router = MagicMock()
    router.modules = [mod]
    router.flags = []
    router.uid = "ROUTER-1"
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.switch.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value=None)
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)


async def test_async_setup_entry_external_area_with_hidden_entity_alias(
    hass: HomeAssistant,
) -> None:
    """Hidden entities with the same original name are also moved to the area."""
    out = _make_output(type_=1, nmbr=0)
    out.area = 5

    mod = MagicMock()
    mod.uid = "MOD-AL"
    mod.mod_addr = 105
    mod.mod_type = "Smart Output"
    mod.area_member = 0
    mod.outputs = [out]
    mod.leds = []
    mod.flags = []
    mod.typ = b"\x00\x00"

    router = MagicMock()
    router.modules = [mod]
    router.flags = []
    router.uid = "ROUTER-1"
    router.coord = MagicMock()
    area = MagicMock()
    area.get_name_id = MagicMock(return_value="area_5_id")
    # Fill enough areas so the overflow clamp does not kick in for index 5
    router.areas = dict.fromkeys(range(6), area)

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.switch.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="switch.fake")
        reg_entry = MagicMock()
        reg_entry.hidden = True
        reg_entry.device_id = "dev_1"
        reg_entry.original_name = "Out 1"
        registry.async_get.return_value = reg_entry
        alias_entry = MagicMock()
        alias_entry.entity_id = "switch.alias"
        alias_entry.original_name = "Out 1"
        mock_get.return_value = registry
        with patch(
            "custom_components.habitron.switch.er.async_entries_for_device",
            return_value=[alias_entry],
        ):
            await async_setup_entry(hass, entry, lambda es: None)

    # The alias entity must have been moved into the area too.
    registry.async_update_entity.assert_any_call("switch.alias", area_id="area_5_id")


async def test_async_setup_entry_area_overflow_falls_back_to_zero(
    hass: HomeAssistant,
) -> None:
    """An out-of-range area index gets clamped to zero (default)."""
    out = _make_output(type_=1, nmbr=0)
    out.area = 99

    mod = MagicMock()
    mod.uid = "MOD-OV"
    mod.mod_addr = 105
    mod.mod_type = "Smart Output"
    mod.area_member = 0
    mod.outputs = [out]
    mod.leds = []
    mod.flags = []
    mod.typ = b"\x00\x00"

    router = MagicMock()
    router.modules = [mod]
    router.flags = []
    router.uid = "ROUTER-1"
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.switch.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="switch.fake")
        reg_entry = MagicMock()
        reg_entry.hidden = False
        registry.async_get.return_value = reg_entry
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)

    registry.async_update_entity.assert_called_with("switch.fake", area_id=None)


async def test_async_setup_entry_external_area_for_hidden_alias_zero_area(
    hass: HomeAssistant,
) -> None:
    """A hidden entity that resolves to area 0 unsets the area on its alias."""
    out = _make_output(type_=1, nmbr=0)
    out.area = 0  # same as module area_member 0 → default branch

    mod = MagicMock()
    mod.uid = "MOD-ZE"
    mod.mod_addr = 105
    mod.mod_type = "Smart Output"
    mod.area_member = 0
    mod.outputs = [out]
    mod.leds = []
    mod.flags = []
    mod.typ = b"\x00\x00"

    router = MagicMock()
    router.modules = [mod]
    router.flags = []
    router.uid = "ROUTER-1"
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.switch.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="switch.fake")
        reg_entry = MagicMock()
        reg_entry.hidden = True
        reg_entry.device_id = "dev_1"
        reg_entry.original_name = "Out 1"
        registry.async_get.return_value = reg_entry
        alias_entry = MagicMock()
        alias_entry.entity_id = "switch.alias"
        alias_entry.original_name = "Out 1"
        mock_get.return_value = registry
        with patch(
            "custom_components.habitron.switch.er.async_entries_for_device",
            return_value=[alias_entry],
        ):
            await async_setup_entry(hass, entry, lambda es: None)

    registry.async_update_entity.assert_any_call("switch.alias", area_id=None)


async def test_async_setup_entry_skips_non_standard_outputs(
    hass: HomeAssistant,
) -> None:
    """Outputs with ``|type|`` != 1 fall through the else-branch of the area loop."""
    out = _make_output(type_=2, nmbr=0)

    mod = MagicMock()
    mod.uid = "MOD-S2"
    mod.mod_addr = 105
    mod.mod_type = "Smart Output"
    mod.area_member = 0
    mod.outputs = [out]
    mod.leds = []
    mod.flags = []
    mod.typ = b"\x00\x00"

    router = MagicMock()
    router.modules = [mod]
    router.flags = []
    router.uid = "ROUTER-1"
    router.coord = MagicMock()
    router.areas = {0: MagicMock()}

    entry = MagicMock()
    entry.runtime_data.router = router

    with patch(
        "custom_components.habitron.switch.er.async_get",
    ) as mock_get:
        registry = MagicMock()
        registry.async_get_entity_id = MagicMock(return_value="switch.fake")
        mock_get.return_value = registry
        await async_setup_entry(hass, entry, lambda es: None)
    # No update happened (the loop hit the else branch)
    registry.async_update_entity.assert_not_called()
