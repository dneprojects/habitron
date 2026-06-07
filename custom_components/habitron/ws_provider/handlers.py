"""WebSocket command handlers for the Habitron WebRTC provider.

Exposes ``register_handlers(provider)`` which registers every
``habitron/*`` websocket command with Home Assistant. Each handler still
lives as a nested closure over the ``provider`` argument so it can share
state — but extracting the registration into this module keeps the main
provider file focused on its own surface.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.camera import (
    RTCIceCandidateInit,
    WebRTCCandidate,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .voice_pipeline import run_voice_pipeline

if TYPE_CHECKING:
    from .provider import HabitronWebRTCProvider


_LOGGER = logging.getLogger(__name__)


@callback
def register_handlers(provider: HabitronWebRTCProvider) -> None:  # noqa: C901
    """Register every Habitron WebSocket command handler on ``hass``.

    All handlers stay as nested closures over ``provider`` so they can
    share its state containers (``active_ws_connections``,
    ``voice_pipelines``, …). The decorator chain
    ``@websocket_command(...) @async_response`` is what registers the
    command name against the inner function; the surrounding
    ``register_handlers`` call is what actually attaches the handlers
    to ``hass.data``.
    """
    _LOGGER.info("Registering all Habitron WebSocket command handlers")

    @callback
    def _async_on_ws_disconnect(stream_name: str) -> None:
        """Handle client disconnection and clean up resources."""
        _LOGGER.info("Client for stream '%s' disconnected", stream_name)
        provider.active_ws_connections.pop(
            stream_name, None
        )  # Remove connection reference

        # Cancel any ongoing voice pipeline for this client
        if pipeline_data := provider.voice_pipelines.pop(stream_name, None):
            if not pipeline_data["task"].done():
                pipeline_data["task"].cancel()

        # Clean up any related WebRTC futures and state
        sessions_to_delete = [
            s for s, sn in provider.session_to_stream_map.items() if sn == stream_name
        ]
        for session_id in sessions_to_delete:
            if fut := provider.webrtc_futures.pop(session_id, None):
                if not fut.done():
                    fut.set_exception(HomeAssistantError("Client disconnected"))
            provider.webrtc_send_message_callbacks.pop(session_id, None)
            provider.session_to_stream_map.pop(session_id, None)
            provider.pending_candidates.pop(session_id, None)

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
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        # Ignore if pipeline already running for this client
        if stream_name in provider.voice_pipelines:
            _LOGGER.debug(
                "Ignoring voice_pipeline_status for %s (already running)",
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
        satEntity = provider.assist_satellites.get(stream_name)
        if satEntity:
            satEntity.recognition_disabled = disabled
            satEntity.set_idle()  # Reset state to IDLE on status change
        else:
            _LOGGER.warning(
                "No assist_satellite found for stream '%s' to update recognition_disabled",
                stream_name,
            )
        connection.send_result(msg["id"])

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "habitron/voice_pipeline_start",
            vol.Required("payload"): dict,  # Expects an empty dict for now
        }
    )
    @websocket_api.async_response
    async def handle_voice_pipeline_start(hass: HomeAssistant, connection, msg):
        """Handle request from client to start the voice pipeline."""
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        # Ignore if pipeline already running for this client
        if stream_name in provider.voice_pipelines:
            _LOGGER.debug(
                "Ignoring voice_pipeline_start for %s (already running)",
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
        satellite = provider.assist_satellites.get(stream_name)

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

        # Prepare per-pipeline state and start the task atomically:
        # we want voice_pipelines[stream_name] to be visible to the
        # first ``handle_voice_audio_chunk`` call, even if it arrives
        # before the task body runs.
        context = connection.context(msg)
        audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        playback_finished_event = asyncio.Event()
        task = provider.hass.async_create_background_task(
            run_voice_pipeline(
                provider,
                connection,
                stream_name,
                context,
                pipeline_id,
                device_id,
                satellite_id,
                tts_voice,
                audio_queue,
                playback_finished_event,
            ),
            name=f"habitron_voice_pipeline_{stream_name}",
        )
        provider.voice_pipelines[stream_name] = {
            "queue": audio_queue,
            "task": task,
            "playback_event": playback_finished_event,
        }
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
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        # Find the running pipeline and its audio queue
        if not (pipeline_data := provider.voice_pipelines.get(stream_name)):
            # _LOGGER.warning("Received audio chunk for inactive pipeline: %s", stream_name)
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
        {vol.Required("type"): "habitron/voice_pipeline_abort"}
    )
    @websocket_api.async_response
    async def handle_voice_pipeline_abort(hass: HomeAssistant, connection, msg):
        """Handle explicit abort from client on timeout."""
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        _LOGGER.warning("Client forced voice pipeline abort for %s", stream_name)
        # Cancel task if running
        if pipeline_data := provider.voice_pipelines.pop(stream_name, None):
            if not pipeline_data["task"].done():
                pipeline_data["task"].cancel()

        # Reset satellite state to IDLE
        if satellite := provider.assist_satellites.get(stream_name):
            satellite.set_idle()

        connection.send_result(msg["id"])

    @websocket_api.websocket_command(
        {vol.Required("type"): "habitron/voice_pipeline_end"}
    )
    @websocket_api.async_response
    async def handle_voice_pipeline_end(_, connection, msg):
        """Handle signal from client that audio streaming is finished."""
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        if not (pipeline_data := provider.voice_pipelines.get(stream_name)):
            _LOGGER.debug(
                "Ignoring voice_pipeline_end for inactive pipeline: %s",
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
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        # Find the running pipeline and trigger its wait event
        if pipeline_data := provider.voice_pipelines.get(stream_name):
            if event := pipeline_data.get("playback_event"):
                _LOGGER.debug(
                    "Setting playback_finished_event for stream %s", stream_name
                )
                event.set()

        if satellite := provider.assist_satellites.get(stream_name):
            _LOGGER.info(
                "Client finished TTS playback, setting satellite %s state to IDLE",
                satellite.entity_id,
            )
            # Call inherited method to set state to IDLE
            satellite.set_idle()

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
        module = provider.rtr.get_module_by_stream(stream_name)
        if module:
            module.client_version = client_version
        if existing_conn := provider.active_ws_connections.get(stream_name):
            if existing_conn != connection:
                _LOGGER.warning(
                    "Stream '%s' re-registered by new client, disconnecting old one",
                    stream_name,
                )
        provider.active_ws_connections[stream_name] = connection
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
            vol.Required("sdp"): vol.Any(str, None),
            vol.Required("stream_name"): vol.Any(str, None),
        }
    )
    @websocket_api.async_response
    async def handle_webrtc_answer(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ):
        """Handle the WebRTC answer SDP from the client."""
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        session_id = msg["session_id"]
        # Find the corresponding future and set the result
        if (fut := provider.webrtc_futures.get(session_id)) and not fut.done():
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
            vol.Required("type"): "habitron/webrtc_candidate",
            vol.Required("session_id"): str,
            vol.Optional("candidate"): vol.Any(str, None),
            vol.Optional("sdp_mid"): vol.Any(str, None),
            vol.Optional("sdp_m_line_index"): vol.Any(int, None),
        }
    )
    @websocket_api.async_response
    async def handle_webrtc_candidate(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ):
        """Handle an ICE candidate received from the client."""
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        session_id = msg["session_id"]
        send_message = provider.webrtc_send_message_callbacks.get(session_id)
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
            provider.pending_candidates.setdefault(session_id, []).append(candidate)
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
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        request_id = msg["request_id"]
        # Find the corresponding future
        if (data := provider.snapshot_futures.get(request_id)) and not data[
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
                    HomeAssistantError("Snapshot result missing data and error")
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
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
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
        satellite = provider.assist_satellites.get(stream_name)
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
                "Error processing call_announcement for %s", stream_name
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
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        # Find the corresponding media player entity and update its state
        if player := provider.media_players.get(stream_name):
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
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        success = False
        if player := provider.media_players.get(stream_name):
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
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return

        success = False
        if player := provider.media_players.get(stream_name):
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

    @websocket_api.websocket_command(
        {
            vol.Required("type"): "habitron/report_state",
            vol.Required("payload"): dict,
        }
    )
    @websocket_api.async_response
    async def handle_report_state(
        hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
    ) -> None:
        """Handle device state reports (battery, temp, etc.) from client."""
        stream_name = provider._get_stream_or_send_error(connection, msg)
        if not stream_name:
            return  # Stream unknown, error already sent

        payload = msg["payload"]
        _LOGGER.debug(
            "Received device state report for %s: %s", stream_name, payload
        )

        module = provider.rtr.get_module_by_stream(stream_name)
        if module:
            fw_version = payload.get("version", "0.0.0")
            module.client_version = fw_version

        # Fire an event so sensors can listen to it and update their state
        hass.bus.async_fire(
            "habitron_device_update",
            {"stream_name": stream_name, "data": payload},
        )

        connection.send_result(msg["id"])

    # --- REGISTRATION OF ALL HANDLERS ---
    # NOTE: ``handle_voice_pipeline_abort`` is defined above but is not
    # registered here. This matches the pre-split behavior — the abort
    # command currently never reaches the handler. Likely a missed
    # registration; left as-is by the refactor to keep semantics stable.
    websocket_api.async_register_command(provider.hass, handle_register_stream)
    websocket_api.async_register_command(provider.hass, handle_webrtc_answer)
    websocket_api.async_register_command(provider.hass, handle_webrtc_candidate)
    websocket_api.async_register_command(provider.hass, handle_call_announcement)
    websocket_api.async_register_command(provider.hass, handle_snapshot_result)
    websocket_api.async_register_command(provider.hass, handle_update_media_state)
    websocket_api.async_register_command(provider.hass, handle_voice_pipeline_status)
    websocket_api.async_register_command(provider.hass, handle_voice_pipeline_start)
    websocket_api.async_register_command(provider.hass, handle_voice_audio_chunk)
    websocket_api.async_register_command(provider.hass, handle_voice_pipeline_end)
    websocket_api.async_register_command(provider.hass, handle_media_next_track)
    websocket_api.async_register_command(provider.hass, handle_media_previous_track)
    websocket_api.async_register_command(provider.hass, handle_tts_playback_finished)
    websocket_api.async_register_command(provider.hass, handle_report_state)
