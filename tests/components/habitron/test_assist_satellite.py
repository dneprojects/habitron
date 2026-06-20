"""Tests for the Habitron assist_satellite platform."""

from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import SmartController

from custom_components.habitron.assist_satellite import HbtnAssistSat, async_setup_entry
from homeassistant.components.assist_pipeline import PipelineEventType

# AssistSatelliteState is only exposed on the .entity module, mirroring the
# integration source's own import.
from homeassistant.components.assist_satellite.entity import (  # pylint: disable=home-assistant-component-root-import
    AssistSatelliteState,
)
from homeassistant.core import HomeAssistant


def _make_touch_module(uid: str = "MOD-T") -> MagicMock:
    mod = MagicMock(spec=SmartController)
    mod.uid = uid
    mod.name = "Touch 1"
    mod.mod_type = "Smart Controller Touch"
    mod.stream_name = "touch_1_5"
    return mod


def _make_provider() -> MagicMock:
    p = MagicMock()
    p.async_send_json_message = AsyncMock()
    p.assist_satellites = {}
    # The media player is registered with the provider (keyed by stream name);
    # the satellite reaches it from there for announcements.
    player = MagicMock()
    player.process_media_id = AsyncMock(return_value="http://media/file.mp3")
    p.media_players = {"touch_1_5": player}
    return p


def _make_sat(hass: HomeAssistant | None = None) -> HbtnAssistSat:
    """Construct an HbtnAssistSat with all dependencies stubbed."""
    fake_hass = hass if hass is not None else MagicMock()
    sat = HbtnAssistSat(fake_hass, _make_touch_module(), _make_provider())
    sat.hass = fake_hass
    sat.entity_id = "assist_satellite.touch_1"
    return sat


def test_assist_sat_init_seeds_attrs() -> None:
    """__init__ wires unique id, device info and supported features."""
    sat = _make_sat()
    assert sat.unique_id == "Mod_MOD-T_assist_sat"
    assert ("habitron", "MOD-T") in sat._attr_device_info["identifiers"]
    assert sat.stream_name == "touch_1_5"
    assert sat.recognition_disabled is False


def test_set_listening_processing_responding_idle_callbacks() -> None:
    """Each state-setter callback flips the entity's state."""

    sat = _make_sat()
    sat._set_state = MagicMock()

    sat.set_listening()
    sat._set_state.assert_called_with(AssistSatelliteState.LISTENING)
    sat.set_processing()
    sat._set_state.assert_called_with(AssistSatelliteState.PROCESSING)
    sat.set_responding()
    sat._set_state.assert_called_with(AssistSatelliteState.RESPONDING)
    sat.set_idle()
    sat._set_state.assert_called_with(AssistSatelliteState.IDLE)


async def test_async_start_conversation_without_announcement() -> None:
    """Without a start_announcement, only the start_streaming WS message is sent."""
    sat = _make_sat()
    sat.async_announce = AsyncMock()
    await sat.async_start_conversation(None)
    sat.async_announce.assert_not_awaited()
    sat._provider.async_send_json_message.assert_awaited()


async def test_async_start_conversation_with_announcement_runs_both() -> None:
    """A non-None announcement is also forwarded to ``async_announce``."""
    sat = _make_sat()
    sat.async_announce = AsyncMock()
    announcement = MagicMock()
    await sat.async_start_conversation(announcement)
    sat.async_announce.assert_awaited_with(announcement)


async def test_async_announce_without_preannounce_sends_main_url() -> None:
    """An announcement without a preannounce only emits a single WS message."""
    sat = _make_sat()
    announcement = MagicMock()
    announcement.preannounce_media_id = None
    announcement.media_id = "media-source://x"
    await sat.async_announce(announcement)
    sat._provider.async_send_json_message.assert_awaited()
    assert sat._provider.async_send_json_message.await_count == 1


async def test_async_announce_with_preannounce_sends_both_messages() -> None:
    """A preannounce is played first followed by the main announcement."""
    sat = _make_sat()
    announcement = MagicMock()
    announcement.preannounce_media_id = "media-source://pre"
    announcement.media_id = "media-source://main"
    with patch("asyncio.sleep", new=AsyncMock()):
        await sat.async_announce(announcement)
    assert sat._provider.async_send_json_message.await_count == 2


async def test_async_get_configuration_returns_de_wake_word() -> None:
    """async_get_configuration returns the German "OK, home" wake word."""
    sat = _make_sat()
    config = sat.async_get_configuration()
    assert config is not None
    assert any(ww.id == "ok_home" for ww in config.available_wake_words)


async def test_async_set_configuration_is_a_no_op() -> None:
    """async_set_configuration is a placeholder; just verify it does not raise."""
    sat = _make_sat()
    await sat.async_set_configuration(MagicMock())


async def test_respond_no_text_recognized_runs_internal_announce() -> None:
    """respond_no_text_recognized fires an internal announce + flips state IDLE."""
    sat = _make_sat()
    sat.async_internal_announce = AsyncMock()
    sat._set_state = MagicMock()
    await sat.respond_no_text_recognized()
    sat.async_internal_announce.assert_awaited()


async def test_not_recognized_retry_announces_and_reactivates() -> None:
    """not_recognized_retry plays Wie bitte? + reactivates the voice request."""
    sat = _make_sat()
    sat.async_internal_announce = AsyncMock()
    with patch("asyncio.sleep", new=AsyncMock()):
        await sat.not_recognized_retry()
    sat.async_internal_announce.assert_awaited()
    sat._provider.async_send_json_message.assert_awaited()


def _make_pipeline_event(event_type: object, data: dict | None = None) -> MagicMock:
    event = MagicMock()
    event.type = event_type
    event.data = data or {}
    return event


def test_on_pipeline_event_intent_start_sets_processing() -> None:
    """INTENT_START events flip the entity into PROCESSING state."""

    sat = _make_sat()
    sat.set_processing = MagicMock()
    sat.on_pipeline_event(_make_pipeline_event(PipelineEventType.INTENT_START))
    sat.set_processing.assert_called()


def test_on_pipeline_event_tts_start_sets_responding() -> None:
    """TTS_START events flip the entity into RESPONDING + clear not_recognized."""

    sat = _make_sat()
    sat._not_recognized = True
    sat.set_responding = MagicMock()
    sat.on_pipeline_event(_make_pipeline_event(PipelineEventType.TTS_START))
    sat.set_responding.assert_called()
    assert sat._not_recognized is False


def test_on_pipeline_event_run_end_logs_only() -> None:
    """RUN_END events just log; the entity state isn't touched."""

    sat = _make_sat()
    sat.set_idle = MagicMock()
    sat.on_pipeline_event(_make_pipeline_event(PipelineEventType.RUN_END))
    sat.set_idle.assert_not_called()


def test_on_pipeline_event_error_no_text_recognized_first_time() -> None:
    """An stt-no-text-recognized error toggles _not_recognized + triggers retry."""

    sat = _make_sat()
    sat._not_recognized = False
    sat.hass.async_create_task = MagicMock()
    sat.on_pipeline_event(
        _make_pipeline_event(
            PipelineEventType.ERROR, {"code": "stt-no-text-recognized"}
        )
    )
    # Toggles to True and schedules a not_recognized_retry coroutine
    assert sat._not_recognized is True
    sat.hass.async_create_task.assert_called()


def test_on_pipeline_event_error_no_text_recognized_second_time() -> None:
    """A second stt-no-text-recognized triggers the respond_no_text_recognized path."""

    sat = _make_sat()
    sat._not_recognized = True
    sat.hass.async_create_task = MagicMock()
    sat.on_pipeline_event(
        _make_pipeline_event(
            PipelineEventType.ERROR, {"code": "stt-no-text-recognized"}
        )
    )
    # Toggles back to False
    assert sat._not_recognized is False
    sat.hass.async_create_task.assert_called()


def test_on_pipeline_event_generic_error_sets_idle() -> None:
    """Any other ERROR (non-text-recognized) flips the entity to IDLE."""

    sat = _make_sat()
    sat._not_recognized = True
    sat.set_idle = MagicMock()
    sat.on_pipeline_event(
        _make_pipeline_event(PipelineEventType.ERROR, {"code": "other-error"})
    )
    sat.set_idle.assert_called()
    assert sat._not_recognized is False


def test_on_pipeline_event_error_without_data_sets_idle() -> None:
    """An ERROR without a data payload falls into the generic ``set_idle`` branch."""

    sat = _make_sat()
    sat.set_idle = MagicMock()
    sat.on_pipeline_event(_make_pipeline_event(PipelineEventType.ERROR, None))
    sat.set_idle.assert_called()


# ---------- async_setup_entry ----------


async def test_async_setup_entry_creates_satellite_per_touch_module(
    hass: HomeAssistant,
) -> None:
    """async_setup_entry adds one HbtnAssistSat per Smart Controller Touch."""
    touch = _make_touch_module()
    other = MagicMock()
    other.mod_type = "Smart Controller"
    provider = _make_provider()
    smhub = MagicMock()
    smhub.router.modules = [touch, other]
    smhub.ws_provider = provider

    entry = MagicMock()
    entry.runtime_data = smhub

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    assert len(added) == 1
    assert isinstance(added[0], HbtnAssistSat)
    assert provider.assist_satellites["touch_1_5"] is added[0]


async def test_async_setup_entry_short_circuits_without_provider(
    hass: HomeAssistant,
) -> None:
    """No WS provider → no entities and an error log."""
    touch = _make_touch_module()
    smhub = MagicMock()
    smhub.router.modules = [touch]
    smhub.ws_provider = None

    entry = MagicMock()
    entry.runtime_data = smhub

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    assert added == []
