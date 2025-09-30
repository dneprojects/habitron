"""Habitron direct WebRTC and Voice provider (HA <-> Flutter client)."""

import asyncio
import base64
import logging
import os
import re
import socket
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    async_pipeline_from_audio_stream,
)
from homeassistant.components.camera import (
    Camera,
    CameraWebRTCProvider,
    RTCIceCandidateInit,
    WebRTCAnswer,
    WebRTCCandidate,
    WebRTCError,
    WebRTCSendMessage,
    async_register_webrtc_provider,
)
from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
)
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .binary_sensor import ListeningStatusSensor
from .const import DOMAIN
from .router import HbtnRouter

_LOGGER = logging.getLogger(__name__)

# --- Global Dictionaries for Stateless Futures/Callbacks ---
# State is managed in the provider instance, but these are for async operations.
_webrtc_futures: dict[str, asyncio.Future] = {}
_webrtc_send_message_callbacks: dict[str, WebRTCSendMessage] = {}
_session_to_stream_map: dict[str, str] = {}
_pending_candidates: dict[str, list[WebRTCCandidate]] = {}
_snapshot_futures: dict[str, dict] = {}
_voice_pipelines: dict[str, dict[str, Any]] = {}


def _filter_ipv6_candidates(sdp: str) -> str:
    """Remove IPv6 candidates from an SDP offer."""
    return re.sub(r"a=candidate:.* IP6 .*\r\n", "", sdp)


class HabitronWebRTCProvider(CameraWebRTCProvider):
    """WebRTC provider that forwards offers and snapshot requests to connected Flutter clients."""

    def __init__(self, hass: HomeAssistant, hbtn_rt: HbtnRouter) -> None:
        """Initialize the provider."""
        self.hass = hass
        self.rtr = hbtn_rt
        self.active_ws_connections: dict[str, websocket_api.ActiveConnection] = {}

    @property
    def domain(self) -> str:
        """Return the domain of this provider."""
        return DOMAIN

    @callback
    def async_is_supported(self, stream_source: str) -> bool:
        """Return True if the stream source is supported by this provider."""
        return stream_source.startswith("habitron://")

    def get_listening_sensor(self, stream_name: str) -> ListeningStatusSensor | None:
        """Return the listening status sensor for the given stream name."""
        for mod in self.rtr.modules:
            if mod.name.lower().replace(" ", "_") == stream_name and hasattr(
                mod, "vce_stat"
            ):
                return mod.vce_stat
        return None

    async def async_handle_async_webrtc_offer(
        self,
        camera: Camera,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
    ) -> None:
        """Handle an incoming WebRTC offer from Home Assistant."""
        _LOGGER.info("Received WebRTC offer for session: %s", session_id)
        stream_source = await camera.stream_source()
        if not stream_source:
            raise HomeAssistantError("Stream source unavailable.")

        stream_name = stream_source.replace("habitron://", "")
        ws_connection = self.active_ws_connections.get(stream_name)
        if not ws_connection:
            _LOGGER.error("No client connected for stream '%s'", stream_name)
            send_message(WebRTCAnswer(answer=""))
            return

        try:
            _session_to_stream_map[session_id] = stream_name
            _webrtc_send_message_callbacks[session_id] = send_message
            local_ip = "127.0.0.1"
            try:
                if os.environ.get("DOCKER_HOST") or os.environ.get(
                    "HOMEASSISTANT_DOCKER"
                ):
                    local_ip = "host.docker.internal"
                else:
                    hostname = socket.gethostname()
                    local_ip = socket.gethostbyname(hostname)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Failed to determine local IP: %s", e)

            modified_offer_sdp = _filter_ipv6_candidates(offer_sdp)
            modified_offer_sdp = modified_offer_sdp.replace("127.0.0.1", local_ip)

            ws_connection.send_message(
                {
                    "type": "habitron/webrtc_offer",
                    "value": modified_offer_sdp,
                    "session_id": session_id,
                }
            )

            fut: asyncio.Future = asyncio.Future()
            _webrtc_futures[session_id] = fut
            _LOGGER.info("Waiting for answer from client for session: %s", session_id)
            try:
                answer_sdp = await asyncio.wait_for(fut, timeout=10)
                send_message(WebRTCAnswer(answer=answer_sdp))
            except TimeoutError:
                _LOGGER.error("WebRTC answer timed out for session %s", session_id)
                send_message(
                    WebRTCError(code="timeout", message="WebRTC answer timed out.")
                )
            finally:
                if session_id in _pending_candidates:
                    for candidate_obj in _pending_candidates.pop(session_id, []):
                        send_message(candidate_obj)
        except Exception as err:
            _LOGGER.error("WebRTC negotiation failed: %s", err)
            send_message(WebRTCError(code="negotiation_failed", message=str(err)))
            raise HomeAssistantError(f"WebRTC negotiation failed: {err}") from err

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Handle an incoming ICE candidate from Home Assistant."""
        stream_name = _session_to_stream_map.get(session_id)
        if not stream_name or not (
            ws_connection := self.active_ws_connections.get(stream_name)
        ):
            return

        ws_connection.send_message(
            {
                "type": "habitron/webrtc_candidate",
                "candidate": candidate.candidate,
                "sdp_mid": candidate.sdp_mid,
                "sdp_m_line_index": candidate.sdp_m_line_index,
            }
        )

    async def async_take_snapshot(self, stream_name: str) -> bytes:
        """Request a snapshot from the connected client."""
        ws_connection = self.active_ws_connections.get(stream_name)
        if not ws_connection:
            raise HomeAssistantError(f"No active client for stream '{stream_name}'.")

        request_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.Future()
        _snapshot_futures[request_id] = {"future": fut, "stream_name": stream_name}

        ws_connection.send_message(
            {"type": "habitron/snapshot_request", "request_id": request_id}
        )

        try:
            snapshot_data = await asyncio.wait_for(fut, timeout=5)
            if snapshot_data is None:
                raise HomeAssistantError("Snapshot data was not retrieved.")
            return snapshot_data  # noqa: TRY300
        except TimeoutError as err:
            raise HomeAssistantError("Snapshot request timed out.") from err
        finally:
            _snapshot_futures.pop(request_id, None)


async def async_setup_provider(  # noqa: C901
    hass: HomeAssistant, hbtn_rt: HbtnRouter
) -> HabitronWebRTCProvider:
    """Set up the Habitron WebRTC provider and its WebSocket handlers."""
    _LOGGER.info("Registering Habitron provider and WebSocket commands")

    provider = HabitronWebRTCProvider(hass, hbtn_rt)
    async_register_webrtc_provider(hass, provider)

    @callback
    def _async_on_ws_disconnect(
        stream_name: str, connection: websocket_api.ActiveConnection
    ) -> None:
        _LOGGER.info("Client for stream '%s' disconnected", stream_name)
        if provider.active_ws_connections.get(stream_name) == connection:
            del provider.active_ws_connections[stream_name]
        if sensor := provider.get_listening_sensor(stream_name):
            if hasattr(sensor, "set_listening_state"):
                sensor.set_listening_state(False)
        sessions_to_delete = [
            s for s, sn in _session_to_stream_map.items() if sn == stream_name
        ]
        for session_id in sessions_to_delete:
            if fut := _webrtc_futures.pop(session_id, None):
                if not fut.done():
                    fut.set_exception(HomeAssistantError("Client disconnected"))
            _webrtc_send_message_callbacks.pop(session_id, None)
            _session_to_stream_map.pop(session_id, None)
            _pending_candidates.pop(session_id, None)
        if pipeline_data := _voice_pipelines.pop(stream_name, None):
            if not pipeline_data["task"].done():
                pipeline_data["task"].cancel()

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "habitron/register_stream",
            vol.Required("stream_name"): str,
        }
    )
    @websocket_api.async_response
    async def handle_register_stream(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ):
        stream_name = msg["stream_name"]
        provider.active_ws_connections[stream_name] = connection
        connection.subscriptions[stream_name] = lambda: _async_on_ws_disconnect(
            stream_name, connection
        )
        connection.send_result(msg["id"])
        _LOGGER.info("Client registered stream '%s'", stream_name)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "habitron/webrtc_answer",
            vol.Required("session_id"): str,
            vol.Required("sdp"): str,
            vol.Required("stream_name"): str,
        }
    )
    @websocket_api.async_response
    async def handle_webrtc_answer(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ):
        session_id = msg["session_id"]
        if (fut := _webrtc_futures.get(session_id)) and not fut.done():
            fut.set_result(msg["sdp"])
        connection.send_result(msg["id"])

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "habitron/webrtc_candidate",
            vol.Required("session_id"): str,
            vol.Required("candidate"): str,
            vol.Required("sdp_mid"): str,
            vol.Required("sdp_m_line_index"): int,
        }
    )
    @websocket_api.async_response
    async def handle_webrtc_candidate(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ):
        session_id = msg["session_id"]
        send_message = _webrtc_send_message_callbacks.get(session_id)
        candidate = WebRTCCandidate(
            candidate=RTCIceCandidateInit(
                candidate=msg["candidate"],
                sdp_mid=msg["sdp_mid"],
                sdp_m_line_index=msg["sdp_m_line_index"],
            )
        )
        if send_message:
            send_message(candidate)
        else:
            _pending_candidates.setdefault(session_id, []).append(candidate)
        connection.send_result(msg["id"])

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "habitron/snapshot_result",
            vol.Required("request_id"): str,
            vol.Optional("data"): str,
            vol.Optional("error"): str,
        }
    )
    @websocket_api.async_response
    async def handle_snapshot_result(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ):
        request_id = msg["request_id"]
        if (data := _snapshot_futures.get(request_id)) and not data["future"].done():
            if error_msg := msg.get("error"):
                data["future"].set_exception(
                    HomeAssistantError(f"Snapshot failed on client: {error_msg}")
                )
            elif "data" in msg:
                try:
                    snapshot_data = base64.b64decode(msg["data"])
                    data["future"].set_result(snapshot_data)
                except Exception as e:  # noqa: BLE001
                    data["future"].set_exception(
                        HomeAssistantError(f"Failed to decode snapshot: {e}")
                    )
        connection.send_result(msg["id"])

    async def _run_voice_pipeline(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        stream_name: str,
        start_payload: dict[str, Any],
        context: Context,
    ) -> None:
        _LOGGER.info("Starting voice pipeline for stream '%s'", stream_name)
        audio_queue = asyncio.Queue()
        _voice_pipelines[stream_name] = {
            "queue": audio_queue,
            "task": asyncio.current_task(),
        }

        try:

            async def audio_stream():
                while True:
                    chunk = await audio_queue.get()
                    if chunk is None:
                        break
                    yield chunk

            @callback
            def event_callback(event: PipelineEvent):
                if (
                    event.type == "tts-end"
                    and event.data
                    and (tts_output := event.data.get("tts_output"))
                ):
                    if wav_bytes := tts_output.get("wav_bytes"):
                        connection.send_message(
                            {
                                "type": "habitron/voice_tts_chunk",
                                "payload": base64.b64encode(wav_bytes).decode("utf-8"),
                            }
                        )

            metadata = SpeechMetadata(
                language=hass.config.language,
                format=AudioFormats.WAV,
                codec=AudioCodecs.PCM,
                bit_rate=AudioBitRates.BITRATE_16,
                sample_rate=AudioSampleRates.SAMPLERATE_16000,
                channel=AudioChannels.CHANNEL_MONO,
            )

            await async_pipeline_from_audio_stream(
                hass,
                context=context,
                event_callback=event_callback,
                stt_stream=audio_stream(),
                pipeline_id=None,
                conversation_id=None,
                stt_metadata=metadata,
            )
        except asyncio.CancelledError:
            _LOGGER.info("Voice pipeline for stream '%s' was cancelled", stream_name)
        except Exception:
            _LOGGER.exception(
                "Unexpected error in voice pipeline for stream '%s'", stream_name
            )
        finally:
            _LOGGER.info("Voice pipeline for stream '%s' finished", stream_name)
            if sensor := provider.get_listening_sensor(stream_name):
                if hasattr(sensor, "set_listening_state"):
                    sensor.set_listening_state(False)

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "habitron/voice_pipeline_start",
            vol.Required("payload"): vol.Schema(
                {
                    vol.Required("sample_rate"): int,
                    vol.Required("sample_width"): int,
                    vol.Required("channels"): int,
                }
            ),
        }
    )
    @websocket_api.async_response
    async def handle_voice_pipeline_start(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ):
        stream_name = next(
            (n for n, c in provider.active_ws_connections.items() if c == connection),
            None,
        )
        if not stream_name or stream_name in _voice_pipelines:
            return

        if sensor := provider.get_listening_sensor(stream_name):
            if hasattr(sensor, "set_listening_state"):
                sensor.set_listening_state(True)

        context = connection.context(msg)
        asyncio.create_task(
            _run_voice_pipeline(hass, connection, stream_name, msg["payload"], context)
        )
        connection.send_result(msg["id"])

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "habitron/voice_audio_chunk",
            vol.Required("payload"): str,
        }
    )
    @websocket_api.async_response
    async def handle_voice_audio_chunk(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ):
        stream_name = next(
            (n for n, c in provider.active_ws_connections.items() if c == connection),
            None,
        )
        if not stream_name or stream_name not in _voice_pipelines:
            return
        if queue := _voice_pipelines[stream_name].get("queue"):
            try:
                await queue.put(base64.b64decode(msg["payload"]))
            except Exception:
                _LOGGER.exception(
                    "Error processing audio chunk for stream '%s'", stream_name
                )

    @websocket_api.websocket_command(
        {vol.Required("type"): "habitron/voice_pipeline_end"}
    )
    @websocket_api.async_response
    async def handle_voice_pipeline_end(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ):
        stream_name = next(
            (n for n, c in provider.active_ws_connections.items() if c == connection),
            None,
        )
        if not stream_name or stream_name not in _voice_pipelines:
            return
        if queue := _voice_pipelines[stream_name].get("queue"):
            await queue.put(None)
        connection.send_result(msg["id"])

    # --- Register ALL Command Handlers ---
    _LOGGER.info("Registering all WebSocket command handlers")
    websocket_api.async_register_command(hass, handle_register_stream)
    websocket_api.async_register_command(hass, handle_webrtc_answer)
    websocket_api.async_register_command(hass, handle_webrtc_candidate)
    websocket_api.async_register_command(hass, handle_snapshot_result)

    websocket_api.async_register_command(hass, handle_voice_pipeline_start)
    websocket_api.async_register_command(hass, handle_voice_audio_chunk)
    websocket_api.async_register_command(hass, handle_voice_pipeline_end)
    _LOGGER.info("All handlers registered successfully")

    return provider
