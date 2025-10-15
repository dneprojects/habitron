"""Habitron direct WebRTC and Voice provider (HA <-> Flutter client)."""

import asyncio
import base64
import logging
import os
import re
import socket
import struct
from typing import TYPE_CHECKING, Any
import uuid

import voluptuous as vol

from homeassistant.components import tts, websocket_api
from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    PipelineEventType,
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

from .const import DOMAIN
from .router import HbtnRouter

if TYPE_CHECKING:
    from .assist_satellite import HbtnAssistSat
    from .media_player import HbtnMediaPlayer


_LOGGER = logging.getLogger(__name__)


def _filter_ipv6_candidates(sdp: str) -> str:
    """Remove IPv6 candidates from an SDP offer."""
    return re.sub(r"a=candidate:.* IP6 .*\r\n", "", sdp)


class HabitronWebRTCProvider(CameraWebRTCProvider):
    """WebRTC and Voice provider that forwards commands to connected Flutter clients."""

    def __init__(self, hass: HomeAssistant, hbtn_rt: HbtnRouter) -> None:
        """Initialize the provider."""
        self.hass = hass
        self.rtr = hbtn_rt

        # State is managed within the class instance.
        self.active_ws_connections: dict[str, websocket_api.ActiveConnection] = {}
        self.webrtc_futures: dict[str, asyncio.Future] = {}
        self.webrtc_send_message_callbacks: dict[str, WebRTCSendMessage] = {}
        self.session_to_stream_map: dict[str, str] = {}
        self.pending_candidates: dict[str, list[WebRTCCandidate]] = {}
        self.snapshot_futures: dict[str, dict] = {}
        self.media_players: dict[str, HbtnMediaPlayer] = {}
        self.assist_satellites: dict[str, HbtnAssistSat] = {}
        self.voice_pipelines: dict[str, dict[str, Any]] = {}

        # Register this instance as the WebRTC provider
        async_register_webrtc_provider(self.hass, self)

    @property
    def domain(self) -> str:
        """Return the domain of this provider."""
        return DOMAIN

    @callback
    def register_media_player(self, player: "HbtnMediaPlayer") -> None:
        """Allow media player entities to register themselves with the provider."""
        self.media_players[player.stream_name] = player
        _LOGGER.info("Media player registered for stream: %s", player.stream_name)

    @callback
    def register_assist_satellite(self, satellite: "HbtnAssistSat") -> None:
        """Allow assist satellite entities to register themselves with the provider."""
        self.assist_satellites[satellite.stream_name] = satellite

    async def async_send_json_message(self, stream_name: str, msg: dict) -> None:
        """Send a structured JSON message to a specific connected client."""
        if not (ws_connection := self.active_ws_connections.get(stream_name)):
            _LOGGER.warning(
                "Cannot send message, no client for stream '%s': %s",
                stream_name,
                msg.get("type"),
            )
            return
        ws_connection.send_message(msg)

    @callback
    def async_is_supported(self, stream_source: str) -> bool:
        """Return True if the stream source is supported by this provider."""
        return stream_source.startswith("habitron://")

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
        if not self.active_ws_connections.get(stream_name):
            _LOGGER.error("No client connected for stream '%s'", stream_name)
            send_message(WebRTCAnswer(answer=""))
            return
        try:
            self.session_to_stream_map[session_id] = stream_name
            self.webrtc_send_message_callbacks[session_id] = send_message
            local_ip = "127.0.0.1"
            try:
                if os.environ.get("DOCKER_HOST") or os.environ.get(
                    "HOMEASSISTANT_DOCKER"
                ):
                    local_ip = "host.docker.internal"
                else:
                    local_ip = socket.gethostbyname(socket.gethostname())
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Failed to determine local IP: %s", e)
            modified_offer_sdp = _filter_ipv6_candidates(offer_sdp)
            modified_offer_sdp = modified_offer_sdp.replace("127.0.0.1", local_ip)
            await self.async_send_json_message(
                stream_name,
                {
                    "type": "habitron/webrtc_offer",
                    "value": modified_offer_sdp,
                    "session_id": session_id,
                },
            )
            fut: asyncio.Future = asyncio.Future()
            self.webrtc_futures[session_id] = fut
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
                for candidate_obj in self.pending_candidates.pop(session_id, []):
                    send_message(candidate_obj)
        except Exception as err:
            _LOGGER.error("WebRTC negotiation failed: %s", err)
            send_message(WebRTCError(code="negotiation_failed", message=str(err)))
            raise HomeAssistantError(f"WebRTC negotiation failed: {err}") from err

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Handle an incoming ICE candidate from Home Assistant."""
        if not (stream_name := self.session_to_stream_map.get(session_id)):
            return
        await self.async_send_json_message(
            stream_name,
            {
                "type": "habitron/webrtc_candidate",
                "candidate": candidate.candidate,
                "sdp_mid": candidate.sdp_mid,
                "sdp_m_line_index": candidate.sdp_m_line_index,
            },
        )

    async def async_take_snapshot(self, stream_name: str) -> bytes:
        """Request a snapshot from the connected client."""
        if not self.active_ws_connections.get(stream_name):
            raise HomeAssistantError(f"No active client for stream '{stream_name}'.")
        request_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.Future()
        self.snapshot_futures[request_id] = {"future": fut}
        await self.async_send_json_message(
            stream_name, {"type": "habitron/snapshot_request", "request_id": request_id}
        )
        try:
            return await asyncio.wait_for(fut, timeout=5)
        except TimeoutError as err:
            raise HomeAssistantError("Snapshot request timed out.") from err
        finally:
            self.snapshot_futures.pop(request_id, None)

    @callback
    def async_register_websocket_handlers(self) -> None:  # noqa: C901
        """Register all custom websocket command handlers."""
        _LOGGER.info("Registering all Habitron WebSocket command handlers")

        @callback
        def _async_on_ws_disconnect(stream_name: str) -> None:
            """Handle client disconnection."""
            _LOGGER.info("Client for stream '%s' disconnected", stream_name)
            self.active_ws_connections.pop(stream_name, None)
            if pipeline_data := self.voice_pipelines.pop(stream_name, None):
                if not pipeline_data["task"].done():
                    pipeline_data["task"].cancel()
            sessions_to_delete = [
                s for s, sn in self.session_to_stream_map.items() if sn == stream_name
            ]
            for session_id in sessions_to_delete:
                if fut := self.webrtc_futures.pop(session_id, None):
                    if not fut.done():
                        fut.set_exception(HomeAssistantError("Client disconnected"))
                self.webrtc_send_message_callbacks.pop(session_id, None)
                self.session_to_stream_map.pop(session_id, None)
                self.pending_candidates.pop(session_id, None)

        async def _run_voice_pipeline(
            connection: websocket_api.ActiveConnection,
            stream_name: str,
            context: Context,
            pipeline_id: str | None,
            device_id: str | None,
            satellite_id: str | None,
            tts_voice: str | None,
        ) -> None:
            """Start manual voice pipeling."""
            _LOGGER.info(
                "Starting manual voice pipeline for stream '%s' with pipeline_id: %s",
                stream_name,
                pipeline_id,
            )
            audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
            self.voice_pipelines[stream_name] = {
                "queue": audio_queue,
                "task": asyncio.current_task(),
            }

            try:

                async def audio_stream():
                    # Create a 44-byte WAV header for 16-bit 16kHz mono PCM
                    channels = 1
                    sample_width_bytes = 2
                    sample_rate = 16000
                    header = struct.pack(
                        "<4sI4s4sIHHIIHH4sI",
                        b"RIFF",
                        0,
                        b"WAVE",
                        b"fmt ",
                        16,
                        1,
                        channels,
                        sample_rate,
                        sample_rate * channels * sample_width_bytes,
                        channels * sample_width_bytes,
                        sample_width_bytes * 8,
                        b"data",
                        0,
                    )
                    yield header

                    while True:
                        chunk = await audio_queue.get()
                        if chunk is None:
                            break
                        yield chunk

                tts_task: asyncio.Task | None = None

                @callback
                def event_callback(event: PipelineEvent):
                    nonlocal tts_task
                    if (
                        event.type == PipelineEventType.TTS_END
                        and event.data
                        and (tts_output := event.data.get("tts_output"))
                        and (token := tts_output.get("token"))
                    ):

                        async def _stream_tts_to_client():
                            _LOGGER.debug(
                                "Starting TTS stream to client for token %s", token
                            )
                            try:
                                stream = tts.async_get_stream(self.hass, token)
                                if stream is None:
                                    _LOGGER.error(
                                        "Could not find TTS stream for token %s", token
                                    )
                                    return

                                async for chunk in stream.async_stream_result():
                                    if chunk:
                                        await self.async_send_json_message(
                                            stream_name,
                                            {
                                                "type": "habitron/voice_tts_chunk",
                                                "payload": base64.b64encode(
                                                    chunk
                                                ).decode("utf-8"),
                                            },
                                        )
                                await self.async_send_json_message(
                                    stream_name,
                                    {"type": "habitron/voice_tts_chunk", "payload": ""},
                                )
                            except Exception:
                                _LOGGER.exception("Error streaming TTS to client")

                        tts_task = self.hass.async_create_task(_stream_tts_to_client())

                stt_metadata = SpeechMetadata(
                    language=self.hass.config.language,
                    format=AudioFormats.WAV,
                    codec=AudioCodecs.PCM,
                    bit_rate=AudioBitRates.BITRATE_16,
                    sample_rate=AudioSampleRates.SAMPLERATE_16000,
                    channel=AudioChannels.CHANNEL_MONO,
                )

                tts_audio_output = {tts.ATTR_PREFERRED_FORMAT: "wav"}
                if tts_voice:
                    tts_audio_output["voice"] = tts_voice

                await async_pipeline_from_audio_stream(
                    self.hass,
                    context=context,
                    event_callback=event_callback,
                    stt_stream=audio_stream(),
                    stt_metadata=stt_metadata,
                    pipeline_id=pipeline_id,
                    conversation_id=None,
                    device_id=device_id,
                    satellite_id=satellite_id,
                    tts_audio_output=tts_audio_output,
                )

                if tts_task:
                    await tts_task
            except Exception:
                _LOGGER.exception(
                    "Unexpected error in voice pipeline for stream '%s'", stream_name
                )
            finally:
                _LOGGER.info("Voice pipeline for stream '%s' finished", stream_name)
                connection.send_message({"type": "habitron/tts_pipeline_finished"})
                self.voice_pipelines.pop(stream_name, None)

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/voice_pipeline_start",
                vol.Required("payload"): dict,
            }
        )
        @websocket_api.async_response
        async def handle_voice_pipeline_start(hass: HomeAssistant, connection, msg):
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            if not stream_name or stream_name in self.voice_pipelines:
                return

            # Get the satellite entity and its configured pipeline
            pipeline_id = None
            device_id = None
            satellite_id = None
            tts_voice = None
            satellite = self.assist_satellites.get(stream_name)

            if satellite:
                satellite_id = satellite.entity_id
                if satellite.registry_entry:
                    device_id = satellite.registry_entry.device_id
                if satellite.registry_entry and satellite.registry_entry.options:
                    if isinstance(
                        p := satellite.registry_entry.options.get("pipeline"), str
                    ):
                        pipeline_id = p
                    if isinstance(
                        v := satellite.registry_entry.options.get("tts_voice"), str
                    ):
                        tts_voice = v

                _LOGGER.debug(
                    "Found satellite '%s' (device: %s), using language: %s, pipeline: %s, voice: %s",
                    stream_name,
                    device_id,
                    satellite_id,
                    pipeline_id,
                    tts_voice,
                )
            else:
                _LOGGER.warning(
                    "No assist_satellite found for stream '%s', using default pipeline",
                    stream_name,
                )

            context = connection.context(msg)
            asyncio.create_task(  # noqa: RUF006
                _run_voice_pipeline(
                    connection,
                    stream_name,
                    context,
                    pipeline_id,
                    device_id,
                    satellite_id,
                    tts_voice,
                )
            )
            connection.send_result(msg["id"])

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/voice_audio_chunk",
                vol.Required("payload"): str,  # base64 encoded string
            }
        )
        @websocket_api.async_response
        async def handle_voice_audio_chunk(hass: HomeAssistant, connection, msg):
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            if not stream_name or not (
                pipeline_data := self.voice_pipelines.get(stream_name)
            ):
                return
            if queue := pipeline_data.get("queue"):
                await queue.put(base64.b64decode(msg["payload"]))
            # No result needed for audio chunks for performance

        @websocket_api.websocket_command(
            {vol.Required("type"): "habitron/voice_pipeline_end"}
        )
        @websocket_api.async_response
        async def handle_voice_pipeline_end(_, connection, msg):
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            if not stream_name or not (
                pipeline_data := self.voice_pipelines.get(stream_name)
            ):
                return

            if queue := pipeline_data.get("queue"):
                await queue.put(None)  # Signal end of stream
            connection.send_result(msg["id"])

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/register_stream",
                vol.Required("stream_name"): str,
            }
        )
        @websocket_api.async_response
        async def handle_register_stream(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ):
            stream_name = msg["stream_name"]
            self.active_ws_connections[stream_name] = connection
            connection.subscriptions[msg["id"]] = lambda: _async_on_ws_disconnect(
                stream_name
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
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ):
            session_id = msg["session_id"]
            if (fut := self.webrtc_futures.get(session_id)) and not fut.done():
                fut.set_result(msg["sdp"])
            connection.send_result(msg["id"])

        @websocket_api.websocket_command(
            {
                "type": "habitron/webrtc_candidate",
                "session_id": str,
                "candidate": str,
                "sdp_mid": str,
                "sdp_m_line_index": int,
            }
        )
        @websocket_api.async_response
        async def handle_webrtc_candidate(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ):
            session_id = msg["session_id"]
            send_message = self.webrtc_send_message_callbacks.get(session_id)
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
                self.pending_candidates.setdefault(session_id, []).append(candidate)
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
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ):
            request_id = msg["request_id"]
            if (data := self.snapshot_futures.get(request_id)) and not data[
                "future"
            ].done():
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

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/update_media_state",
                vol.Required("state"): str,
                vol.Optional("attributes"): dict,
            }
        )
        @websocket_api.async_response
        async def handle_update_media_state(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ):
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            if not stream_name:
                _LOGGER.warning("Received media state update from unknown client")
                return
            if player := self.media_players.get(stream_name):
                _LOGGER.debug("Updating state for %s: %s", player.name, msg["state"])
                player.update_from_client(msg["state"], msg.get("attributes", {}))
            else:
                _LOGGER.warning(
                    "Received media state update for unregistered player: %s",
                    stream_name,
                )
            connection.send_result(msg["id"])

        @websocket_api.websocket_command(
            {vol.Required("type"): "habitron/media_next_track"}
        )
        @websocket_api.async_response
        async def handle_media_next_track(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ) -> None:
            """Handle skip to next track command from the client."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            if stream_name and (player := self.media_players.get(stream_name)):
                await player.async_media_next_track()
            connection.send_result(msg["id"])

        @websocket_api.websocket_command(
            {vol.Required("type"): "habitron/media_previous_track"}
        )
        @websocket_api.async_response
        async def handle_media_previous_track(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ) -> None:
            """Handle skip to previous track command from the client."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            if stream_name and (player := self.media_players.get(stream_name)):
                await player.async_media_previous_track()
            connection.send_result(msg["id"])

        # --- REGISTRATION OF ALL HANDLERS ---

        websocket_api.async_register_command(self.hass, handle_register_stream)
        websocket_api.async_register_command(self.hass, handle_webrtc_answer)
        websocket_api.async_register_command(self.hass, handle_webrtc_candidate)
        websocket_api.async_register_command(self.hass, handle_snapshot_result)
        websocket_api.async_register_command(self.hass, handle_update_media_state)
        websocket_api.async_register_command(self.hass, handle_voice_pipeline_start)
        websocket_api.async_register_command(self.hass, handle_voice_audio_chunk)
        websocket_api.async_register_command(self.hass, handle_voice_pipeline_end)
        websocket_api.async_register_command(self.hass, handle_media_next_track)
        websocket_api.async_register_command(self.hass, handle_media_previous_track)
