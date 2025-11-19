"""Habitron web socket provider for direct WebRTC and Voice (HA <-> Flutter client)."""

import asyncio
import base64
import hashlib
import logging
import os
from pathlib import Path
import re
import shutil
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
        _LOGGER.debug(
            "Assist satellite registered for stream: %s", satellite.stream_name
        )

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

    async def async_broadcast_message(self, msg: dict) -> None:
        """Broadcast a structured JSON message to all connected clients."""
        for stream_name, ws_connection in self.active_ws_connections.items():
            _LOGGER.debug(
                "Broadcasting message to stream '%s': %s",
                stream_name,
                msg.get("type"),
            )
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
            send_message(WebRTCAnswer(answer=""))  # Send empty answer to signal failure
            return

        try:
            self.session_to_stream_map[session_id] = stream_name
            self.webrtc_send_message_callbacks[session_id] = send_message

            # Try to determine the local IP address visible to the client
            local_ip = "127.0.0.1"  # Default fallback
            try:
                # Check for Docker environment variables
                if os.environ.get("DOCKER_HOST") or os.environ.get(
                    "HOMEASSISTANT_DOCKER"
                ):
                    local_ip = (
                        "host.docker.internal"  # Special hostname for Docker host
                    )
                else:
                    # Try getting the hostname's IP (might not always be correct)
                    local_ip = socket.gethostbyname(socket.gethostname())
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Failed to determine local IP: %s", e)

            # Modify SDP: Filter IPv6, replace localhost IP
            modified_offer_sdp = _filter_ipv6_candidates(offer_sdp)
            modified_offer_sdp = modified_offer_sdp.replace("127.0.0.1", local_ip)

            # Send the modified offer to the Flutter client
            await self.async_send_json_message(
                stream_name,
                {
                    "type": "habitron/webrtc_offer",
                    "value": modified_offer_sdp,
                    "session_id": session_id,
                },
            )

            # Prepare to wait for the client's answer
            fut: asyncio.Future = asyncio.Future()
            self.webrtc_futures[session_id] = fut
            _LOGGER.info("Waiting for answer from client for session: %s", session_id)

            # Wait for the answer with a timeout
            try:
                answer_sdp = await asyncio.wait_for(fut, timeout=10)
                send_message(WebRTCAnswer(answer=answer_sdp))  # Send answer back to HA
            except TimeoutError:
                _LOGGER.error("WebRTC answer timed out for session %s", session_id)
                send_message(
                    WebRTCError(code="timeout", message="WebRTC answer timed out.")
                )
            finally:
                # Send any candidates that arrived before the answer was processed
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
            _LOGGER.debug("Ignoring candidate for unknown session: %s", session_id)
            return

        # Forward the candidate to the Flutter client
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

        # Send request to client
        await self.async_send_json_message(
            stream_name, {"type": "habitron/snapshot_request", "request_id": request_id}
        )

        # Wait for the result with timeout
        try:
            return await asyncio.wait_for(fut, timeout=5)
        except TimeoutError as err:
            raise HomeAssistantError("Snapshot request timed out.") from err
        finally:
            self.snapshot_futures.pop(request_id, None)  # Clean up future

    @callback
    def async_register_websocket_handlers(self) -> None:  # noqa: C901
        """Register all custom websocket command handlers."""
        _LOGGER.info("Registering all Habitron WebSocket command handlers")

        @callback
        def _async_on_ws_disconnect(stream_name: str) -> None:
            """Handle client disconnection and clean up resources."""
            _LOGGER.info("Client for stream '%s' disconnected", stream_name)
            self.active_ws_connections.pop(
                stream_name, None
            )  # Remove connection reference

            # Cancel any ongoing voice pipeline for this client
            if pipeline_data := self.voice_pipelines.pop(stream_name, None):
                if not pipeline_data["task"].done():
                    pipeline_data["task"].cancel()

            # Clean up any related WebRTC futures and state
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
            """Start and manage the Assist pipeline for incoming audio."""
            _LOGGER.info(
                "Starting manual voice pipeline for stream '%s' with pipeline_id: %s",
                stream_name,
                pipeline_id,
            )
            audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
            playback_finished_event = asyncio.Event()
            self.voice_pipelines[stream_name] = {
                "queue": audio_queue,
                "task": asyncio.current_task(),  # Store reference to this task
                "playback_event": playback_finished_event,
            }

            # Set satellite state to LISTENING immediately
            satellite = self.assist_satellites.get(stream_name)
            if satellite:
                _LOGGER.info(
                    "Setting satellite %s state to LISTENING via base class _set_state",
                    satellite.entity_id,
                )
                # Use the inherited _set_state method from AssistSatelliteEntity
                satellite.set_listening()
            else:
                _LOGGER.warning(
                    "Could not find satellite for stream '%s' to update state",
                    stream_name,
                )

            try:
                last_err = ""

                async def audio_stream():
                    """Yield audio chunks for the pipeline, starting with a WAV header."""
                    # Create a 44-byte WAV header for 16-bit 16kHz mono PCM
                    channels = 1
                    sample_width_bytes = 2  # 16 bits
                    sample_rate = 16000  # 16 kHz
                    header = struct.pack(
                        "<4sI4s4sIHHIIHH4sI",
                        b"RIFF",
                        0,  # Placeholder for file size
                        b"WAVE",
                        b"fmt ",
                        16,  # PCM format chunk size
                        1,  # PCM format
                        channels,
                        sample_rate,
                        sample_rate * channels * sample_width_bytes,  # byte_rate
                        channels * sample_width_bytes,  # block_align
                        sample_width_bytes * 8,  # bits_per_sample
                        b"data",
                        0,  # Placeholder for data size
                    )
                    yield header

                    # Yield chunks from the queue until None is received
                    while True:
                        chunk = await audio_queue.get()
                        if chunk is None:
                            break
                        yield chunk

                tts_task: asyncio.Task | None = (
                    None  # Task for streaming TTS audio back
                )
                tts_was_streamed = False

                @callback
                def event_callback(event: PipelineEvent):
                    """Handle pipeline events FOR TTS STREAMING ONLY."""
                    # This callback is executed synchronously by the pipeline.
                    nonlocal tts_task
                    _LOGGER.warning(
                        "Provider event_callback received: %s for %s",
                        event.type,
                        stream_name,
                    )
                    sat = self.assist_satellites.get(stream_name)
                    if sat:
                        # Forward the event to the satellite entity's on_pipeline_event method
                        # Run as task because on_pipeline_event might become async or do async things
                        sat.on_pipeline_event(event)
                    else:
                        _LOGGER.warning(
                            "Event_callback: Could not find satellite for stream '%s' to forward event",
                            stream_name,
                        )
                    # --- Specific handling for TTS_END to stream audio ---
                    if (
                        event.type == PipelineEventType.TTS_END
                        and event.data
                        and (tts_output := event.data.get("tts_output"))
                        and (token := tts_output.get("token"))
                    ):

                        async def _stream_tts_to_client():
                            """Fetch TTS audio stream and send chunks to the client."""
                            _LOGGER.debug(
                                "Starting TTS stream to client for token %s", token
                            )
                            try:
                                # Get the TTS audio stream using the token
                                stream = tts.async_get_stream(self.hass, token)
                                if stream is None:
                                    _LOGGER.error(
                                        "Could not find TTS stream for token %s", token
                                    )
                                    return

                                # Send each chunk base64 encoded
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
                                # Send empty payload to signal end of TTS stream
                                await self.async_send_json_message(
                                    stream_name,
                                    {"type": "habitron/voice_tts_chunk", "payload": ""},
                                )
                                _LOGGER.debug(
                                    "Finished streaming TTS to client for token %s",
                                    token,
                                )
                            except Exception:
                                _LOGGER.exception("Error streaming TTS to client")

                        # Start the TTS streaming task
                        tts_task = self.hass.async_create_task(_stream_tts_to_client())
                        nonlocal tts_was_streamed
                        tts_was_streamed = True
                    # --- End of TTS_END handling ---

                # Define the expected audio format from the client
                stt_metadata = SpeechMetadata(
                    language=self.hass.config.language,
                    format=AudioFormats.WAV,
                    codec=AudioCodecs.PCM,
                    bit_rate=AudioBitRates.BITRATE_16,
                    sample_rate=AudioSampleRates.SAMPLERATE_16000,
                    channel=AudioChannels.CHANNEL_MONO,
                )

                # Specify preferred TTS output format and optional voice
                tts_audio_output = {
                    tts.ATTR_PREFERRED_FORMAT: AudioFormats.WAV.value,
                    tts.ATTR_PREFERRED_SAMPLE_RATE: AudioSampleRates.SAMPLERATE_16000.value,
                    tts.ATTR_PREFERRED_SAMPLE_CHANNELS: AudioChannels.CHANNEL_MONO.value,
                }
                if tts_voice:
                    tts_audio_output["voice"] = tts_voice

                # Run the Assist pipeline
                await async_pipeline_from_audio_stream(
                    self.hass,
                    context=context,
                    event_callback=event_callback,  # Pass our local callback for TTS
                    stt_stream=audio_stream(),
                    stt_metadata=stt_metadata,
                    pipeline_id=pipeline_id,  # Use configured or default pipeline
                    conversation_id=None,  # Start new conversation
                    device_id=device_id,
                    satellite_id=satellite_id,
                    tts_audio_output=tts_audio_output,
                )

                # Wait for the TTS streaming task (if any) to complete
                if tts_task:
                    _LOGGER.debug("Waiting for TTS streaming task to complete")
                    await tts_task
                    _LOGGER.debug("TTS streaming task completed")

                    if tts_was_streamed:
                        # Wait for client 'tts_playback_finished' event
                        _LOGGER.debug(
                            "Waiting for client to signal TTS playback finished for stream %s",
                            stream_name,
                        )
                        try:
                            # Wait for the event set by handle_tts_playback_finished
                            await asyncio.wait_for(
                                playback_finished_event.wait(), timeout=30
                            )
                            _LOGGER.debug(
                                "Client confirmed TTS playback finished for stream %s",
                                stream_name,
                            )
                        except TimeoutError:
                            _LOGGER.warning(
                                "Client did not confirm TTS playback for stream %s, timing out",
                                stream_name,
                            )

            except asyncio.CancelledError:
                _LOGGER.info(
                    "Voice pipeline task cancelled for stream '%s'", stream_name
                )
            except Exception as err:
                _LOGGER.exception(
                    "Unexpected error in voice pipeline for stream '%s'", stream_name
                )
                last_err = str(err)
            finally:
                _LOGGER.info("Voice pipeline for stream '%s' finished", stream_name)
                self.voice_pipelines.pop(stream_name, None)
                connection.send_message(
                    {"type": "habitron/voice_pipeline_finished", "error": last_err}
                )

        # --- WebSocket Command Handlers ---
        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/voice_pipeline_status",
                vol.Required("disabled"): bool,  # Expects an empty dict for now
            }
        )
        @websocket_api.async_response
        async def handle_voice_pipeline_status(hass: HomeAssistant, connection, msg):
            """Handle request from client to start the voice pipeline."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            # Ignore if client unknown or pipeline already running for this client
            if not stream_name or stream_name in self.voice_pipelines:
                _LOGGER.debug(
                    "Ignoring voice_pipeline_status for %s (unknown)",
                    stream_name,
                )
                # Still send a result so the client isn't waiting indefinitely
                connection.send_result(msg["id"])
                return
            disabled = msg["disabled"]  # Get the disabled status
            _LOGGER.info(
                "Received voice_pipeline_status for %s: disabled=%s",
                stream_name,
                disabled,
            )
            satEntity = self.assist_satellites.get(stream_name)
            if satEntity:
                satEntity.recognition_disabled = disabled
                satEntity.set_idle()  # Reset state to IDLE on status change
            else:
                _LOGGER.warning(
                    "No assist_satellite found for stream '%s' to update recognition_disabled",
                    stream_name,
                )

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/voice_pipeline_start",
                vol.Required("payload"): dict,  # Expects an empty dict for now
            }
        )
        @websocket_api.async_response
        async def handle_voice_pipeline_start(hass: HomeAssistant, connection, msg):
            """Handle request from client to start the voice pipeline."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            # Ignore if client unknown or pipeline already running for this client
            if not stream_name or stream_name in self.voice_pipelines:
                _LOGGER.debug(
                    "Ignoring voice_pipeline_start for %s (unknown or already running)",
                    stream_name,
                )
                # Still send a result so the client isn't waiting indefinitely
                connection.send_result(msg["id"])
                return

            # Determine pipeline configuration based on the registered satellite entity
            pipeline_id = None
            device_id = None
            satellite_id = None
            tts_voice = None
            satellite = self.assist_satellites.get(stream_name)

            if satellite:
                # Use the satellite's entity_id and device_id
                satellite_id = satellite.entity_id
                if satellite.registry_entry:
                    device_id = satellite.registry_entry.device_id
                # Get pipeline and voice settings from entity options (if configured)
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
                    "Found satellite '%s' (device: %s, entity: %s), using pipeline: %s, voice: %s",
                    stream_name,
                    device_id,
                    satellite_id,
                    pipeline_id,
                    tts_voice,
                )
            else:
                # Fallback if no satellite entity is registered for this stream name
                _LOGGER.warning(
                    "No assist_satellite found for stream '%s', using default pipeline and no device/entity ID",
                    stream_name,
                )

            # Get the context from the WebSocket message
            context = connection.context(msg)
            # Create a new task to run the pipeline
            asyncio.create_task(  # Use create_task to run concurrently  # noqa: RUF006
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
            # Send result back to client immediately to confirm start request received
            connection.send_result(msg["id"])

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/voice_audio_chunk",
                vol.Required("payload"): str,  # base64 encoded string
            }
        )
        @websocket_api.async_response  # Use async_response for commands that don't need a result
        async def handle_voice_audio_chunk(hass: HomeAssistant, connection, msg):
            """Handle incoming audio chunks from the client."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            # Find the running pipeline and its audio queue
            if not stream_name or not (
                pipeline_data := self.voice_pipelines.get(stream_name)
            ):
                # _LOGGER.warning("Received audio chunk for unknown or inactive pipeline: %s", stream_name)
                return  # Ignore chunks if pipeline isn't running

            # Put the decoded audio data into the queue
            if queue := pipeline_data.get("queue"):
                try:
                    audio_data = base64.b64decode(msg["payload"])
                    await queue.put(audio_data)
                except (TypeError, ValueError):
                    _LOGGER.error(
                        "Failed to decode base64 audio chunk for %s", stream_name
                    )
                except asyncio.QueueFull:
                    _LOGGER.warning(
                        "Audio queue full for %s, dropping chunk", stream_name
                    )
            # No result message is sent back for chunks to minimize overhead

        @websocket_api.websocket_command(
            {vol.Required("type"): "habitron/voice_pipeline_end"}
        )
        @websocket_api.async_response
        async def handle_voice_pipeline_end(_, connection, msg):
            """Handle signal from client that audio streaming is finished."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            if not stream_name or not (
                pipeline_data := self.voice_pipelines.get(stream_name)
            ):
                _LOGGER.debug(
                    "Ignoring voice_pipeline_end for unknown or inactive pipeline: %s",
                    stream_name,
                )
                connection.send_result(msg["id"])  # Still acknowledge
                return

            # Put None into the queue to signal the end of the audio stream
            if queue := pipeline_data.get("queue"):
                _LOGGER.debug(
                    "Received end signal, putting None in audio queue for %s",
                    stream_name,
                )
                await queue.put(None)
            connection.send_result(msg["id"])  # Acknowledge command

        @websocket_api.websocket_command(
            {vol.Required("type"): "habitron/tts_playback_finished"}
        )
        @websocket_api.async_response
        async def handle_tts_playback_finished(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ) -> None:
            """Handle signal from client that TTS playback has finished."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            # Find the running pipeline and trigger its wait event
            if stream_name and (pipeline_data := self.voice_pipelines.get(stream_name)):
                if event := pipeline_data.get("playback_event"):
                    _LOGGER.debug(
                        "Setting playback_finished_event for stream %s", stream_name
                    )
                    event.set()

            if stream_name and (satellite := self.assist_satellites.get(stream_name)):
                _LOGGER.info(
                    "Client finished TTS playback, setting satellite %s state to IDLE",
                    satellite.entity_id,
                )
                # Call inherited method to set state to IDLE
                satellite.set_idle()
            else:
                _LOGGER.warning(
                    "Received tts_playback_finished for unknown stream: %s", stream_name
                )
            connection.send_result(msg["id"])  # Acknowledge command

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/register_stream",
                vol.Required("stream_name"): str,
                vol.Required("version"): str,
            }
        )
        @websocket_api.async_response
        async def handle_register_stream(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ):
            """Handle client registering its stream name."""
            stream_name = msg["stream_name"]
            client_version = msg.get("version", "unknown")
            module = self.rtr.get_module_by_stream(stream_name)
            if module:
                module.client_version = client_version
            if existing_conn := self.active_ws_connections.get(stream_name):
                if existing_conn != connection:
                    _LOGGER.warning(
                        "Stream '%s' re-registered by new client, disconnecting old one",
                        stream_name,
                    )
            _LOGGER.info("Client registered stream '%s'", stream_name)
            self.active_ws_connections[stream_name] = connection
            # Register disconnect handler
            connection.subscriptions[msg["id"]] = lambda: _async_on_ws_disconnect(
                stream_name
            )
            connection.send_result(msg["id"])  # Acknowledge registration
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
            """Handle the WebRTC answer SDP from the client."""
            session_id = msg["session_id"]
            # Find the corresponding future and set the result
            if (fut := self.webrtc_futures.get(session_id)) and not fut.done():
                _LOGGER.debug("Received WebRTC answer for session %s", session_id)
                fut.set_result(msg["sdp"])
            else:
                _LOGGER.warning(
                    "Received WebRTC answer for unknown or completed session %s",
                    session_id,
                )
            connection.send_result(msg["id"])  # Acknowledge

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
            """Handle an ICE candidate received from the client."""
            session_id = msg["session_id"]
            send_message = self.webrtc_send_message_callbacks.get(session_id)
            candidate_init = RTCIceCandidateInit(
                candidate=msg["candidate"],
                sdp_mid=msg["sdp_mid"],
                sdp_m_line_index=msg["sdp_m_line_index"],
            )
            candidate = WebRTCCandidate(candidate=candidate_init)

            # If the HA-side send_message callback is ready, send immediately
            if send_message:
                _LOGGER.debug(
                    "Forwarding WebRTC candidate for session %s to HA", session_id
                )
                send_message(candidate)
            # Otherwise, store it temporarily until the answer is processed
            else:
                _LOGGER.debug("Queueing WebRTC candidate for session %s", session_id)
                self.pending_candidates.setdefault(session_id, []).append(candidate)
            connection.send_result(msg["id"])  # Acknowledge

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/snapshot_result",
                vol.Required("request_id"): str,
                vol.Optional("data"): str,  # Base64 encoded image data
                vol.Optional("error"): str,  # Error message if snapshot failed
            }
        )
        @websocket_api.async_response
        async def handle_snapshot_result(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ):
            """Handle the snapshot result (image data or error) from the client."""
            request_id = msg["request_id"]
            # Find the corresponding future
            if (data := self.snapshot_futures.get(request_id)) and not data[
                "future"
            ].done():
                if error_msg := msg.get("error"):
                    # Set exception if client reported an error
                    _LOGGER.error(
                        "Snapshot request %s failed on client: %s",
                        request_id,
                        error_msg,
                    )
                    data["future"].set_exception(
                        HomeAssistantError(f"Snapshot failed on client: {error_msg}")
                    )
                elif "data" in msg:
                    # Decode base64 data and set result
                    try:
                        snapshot_data = base64.b64decode(msg["data"])
                        _LOGGER.debug(
                            "Received snapshot data for request %s (%d bytes)",
                            request_id,
                            len(snapshot_data),
                        )
                        data["future"].set_result(snapshot_data)
                    except (TypeError, ValueError) as e:
                        _LOGGER.error(
                            "Failed to decode snapshot data for request %s: %s",
                            request_id,
                            e,
                        )
                        data["future"].set_exception(
                            HomeAssistantError(f"Failed to decode snapshot: {e}")
                        )
                else:
                    # No data and no error - treat as failure
                    _LOGGER.error(
                        "Snapshot result for request %s missing data and error",
                        request_id,
                    )
                    data["future"].set_exception(
                        HomeAssistantError("Snapshot result missing data and error.")
                    )
            else:
                _LOGGER.warning(
                    "Received snapshot result for unknown or completed request %s",
                    request_id,
                )
            connection.send_result(msg["id"])  # Acknowledge

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/call_announcement",
                vol.Required("message"): str,  # message to announce
            }
        )
        @websocket_api.async_response
        async def handle_call_announcement(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ):
            """Announce message from client."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            if not stream_name:
                _LOGGER.warning(
                    f"Received call_announcement from unknown client {connection}"  # noqa: G004
                )
                connection.send_result(
                    msg["id"], {"success": False, "error": "Unknown client"}
                )
                return
            # Extract the message text from the payload
            message_text = msg.get("message")
            if not message_text:
                # Handle missing message text
                _LOGGER.warning(
                    "Received call_announcement from %s with no message", stream_name
                )
                connection.send_result(
                    msg["id"], {"success": False, "error": "No message provided"}
                )
                return

            # Find the corresponding satellite entity for this stream
            satellite = self.assist_satellites.get(stream_name)
            if not satellite:
                # Handle missing satellite entity
                _LOGGER.warning(
                    "Received call_announcement for stream '%s', but no satellite entity is registered",
                    stream_name,
                )
                connection.send_result(
                    msg["id"], {"success": False, "error": "Satellite not registered"}
                )
                return

            # Call the satellite's internal announce method to trigger TTS
            try:
                _LOGGER.debug(
                    "Triggering internal announcement for %s: '%s'",
                    stream_name,
                    message_text,
                )
                # This helper method generates the TTS audio and then calls
                # satellite.async_announce() to send the media URL to the client.
                await satellite.async_internal_announce(
                    message=message_text, preannounce=True
                )
                # Send success result to the client
                connection.send_result(msg["id"])
            except Exception as e:
                # Handle any errors during the announcement process
                _LOGGER.exception(
                    "Error processing call_announcement for %s: %s", stream_name, e
                )
                connection.send_result(msg["id"], {"success": False, "error": str(e)})

        @websocket_api.websocket_command(
            {
                vol.Required("type"): "habitron/update_media_state",
                vol.Required("state"): str,  # e.g., "playing", "paused", "idle"
                vol.Optional("attributes"): dict,  # e.g., {"volume_level": 0.5}
            }
        )
        @websocket_api.async_response
        async def handle_update_media_state(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ):
            """Handle media player state updates pushed from the client."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            if not stream_name:
                _LOGGER.warning(
                    f"Received media state update from unknown client {connection}"  # noqa: G004
                )
                connection.send_result(
                    msg["id"], {"success": False, "error": "Unknown client"}
                )
                return

            # Find the corresponding media player entity and update its state
            if player := self.media_players.get(stream_name):
                _LOGGER.debug(
                    "Updating state for %s from client: %s", player.name, msg["state"]
                )
                player.update_from_client(msg["state"], msg.get("attributes", {}))
                connection.send_result(msg["id"])  # Acknowledge update
            else:
                _LOGGER.warning(
                    "Received media state update for unregistered player: %s",
                    stream_name,
                )
                connection.send_result(
                    msg["id"], {"success": False, "error": "Player not registered"}
                )

        @websocket_api.websocket_command(
            {vol.Required("type"): "habitron/media_next_track"}
        )
        @websocket_api.async_response
        async def handle_media_next_track(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ) -> None:
            """Handle skip to next track command triggered from the client UI."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            success = False
            if stream_name and (player := self.media_players.get(stream_name)):
                _LOGGER.debug("Forwarding next_track command to player %s", player.name)
                try:
                    await player.async_media_next_track()
                    success = True
                except Exception:
                    _LOGGER.exception(
                        "Error calling async_media_next_track for %s", player.name
                    )

            connection.send_result(msg["id"], {"success": success})

        @websocket_api.websocket_command(
            {vol.Required("type"): "habitron/media_previous_track"}
        )
        @websocket_api.async_response
        async def handle_media_previous_track(
            hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
        ) -> None:
            """Handle skip to previous track command triggered from the client UI."""
            stream_name = next(
                (n for n, c in self.active_ws_connections.items() if c == connection),
                None,
            )
            success = False
            if stream_name and (player := self.media_players.get(stream_name)):
                _LOGGER.debug(
                    "Forwarding previous_track command to player %s", player.name
                )
                try:
                    await player.async_media_previous_track()
                    success = True
                except Exception:
                    _LOGGER.exception(
                        "Error calling async_media_previous_track for %s", player.name
                    )

            connection.send_result(msg["id"], {"success": success})

        # --- REGISTRATION OF ALL HANDLERS ---
        websocket_api.async_register_command(self.hass, handle_register_stream)
        websocket_api.async_register_command(self.hass, handle_webrtc_answer)
        websocket_api.async_register_command(self.hass, handle_webrtc_candidate)
        websocket_api.async_register_command(self.hass, handle_call_announcement)
        websocket_api.async_register_command(self.hass, handle_snapshot_result)
        websocket_api.async_register_command(self.hass, handle_update_media_state)
        websocket_api.async_register_command(self.hass, handle_voice_pipeline_status)
        websocket_api.async_register_command(self.hass, handle_voice_pipeline_start)
        websocket_api.async_register_command(self.hass, handle_voice_audio_chunk)
        websocket_api.async_register_command(self.hass, handle_voice_pipeline_end)
        websocket_api.async_register_command(self.hass, handle_media_next_track)
        websocket_api.async_register_command(self.hass, handle_media_previous_track)
        websocket_api.async_register_command(self.hass, handle_tts_playback_finished)
