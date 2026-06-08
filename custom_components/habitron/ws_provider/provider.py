"""Habitron WebRTC / WebSocket provider.

This module holds the provider class itself: lifecycle, the message-passing
API (send/broadcast/system command), the WebRTC negotiation and the
snapshot request flow. The voice pipeline lives in ``voice_pipeline`` and
the WebSocket command handlers in ``handlers``; both are wired in via
``async_register_websocket_handlers`` below to keep this module readable.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components.camera import (  # type: ignore[attr-defined]
    Camera,
    CameraWebRTCProvider,
    RTCIceCandidateInit,
    WebRTCAnswer,
    WebRTCCandidate,
    WebRTCError,
    WebRTCSendMessage,
    async_register_webrtc_provider,
)
from homeassistant.components.websocket_api import (  # type: ignore[attr-defined]
    ActiveConnection,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from ..const import DOMAIN
from ..router import HbtnRouter

if TYPE_CHECKING:
    from ..assist_satellite import HbtnAssistSat
    from ..media_player import HbtnMediaPlayer


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
        self.active_ws_connections: dict[str, ActiveConnection] = {}
        self.webrtc_futures: dict[str, asyncio.Future[Any]] = {}
        self.webrtc_send_message_callbacks: dict[str, WebRTCSendMessage] = {}
        self.session_to_stream_map: dict[str, str] = {}
        self.pending_candidates: dict[str, list[WebRTCCandidate]] = {}
        self.snapshot_futures: dict[str, dict[str, Any]] = {}
        self.media_players: dict[str, HbtnMediaPlayer] = {}
        self.assist_satellites: dict[str, HbtnAssistSat] = {}
        self.voice_pipelines: dict[str, dict[str, Any]] = {}

        # Register this instance as the WebRTC provider and keep the
        # cleanup callback so we can detach on entry unload.
        self._remove_provider: Callable[[], None] | None = (
            async_register_webrtc_provider(self.hass, self)
        )

    @callback
    def async_close(self) -> None:
        """Detach the provider and release per-entry state.

        Called from ``async_unload_entry``. Cancels in-flight voice
        pipeline tasks, clears all session/future maps and unregisters
        the WebRTC provider so a subsequent reload does not duplicate it.
        """
        if self._remove_provider is not None:
            self._remove_provider()
            self._remove_provider = None

        for pipeline in self.voice_pipelines.values():
            task = pipeline.get("task")
            if task is not None and not task.done():
                task.cancel()

        self.voice_pipelines.clear()
        self.webrtc_futures.clear()
        self.webrtc_send_message_callbacks.clear()
        self.session_to_stream_map.clear()
        self.pending_candidates.clear()
        self.snapshot_futures.clear()
        self.active_ws_connections.clear()
        self.media_players.clear()
        self.assist_satellites.clear()

    @property
    def domain(self) -> str:
        """Return the domain of this provider."""
        return DOMAIN

    @callback
    def register_media_player(self, player: HbtnMediaPlayer) -> None:
        """Allow media player entities to register themselves with the provider."""
        self.media_players[player.stream_name] = player
        _LOGGER.info("Media player registered for stream: %s", player.stream_name)

    @callback
    def register_assist_satellite(self, satellite: HbtnAssistSat) -> None:
        """Allow assist satellite entities to register themselves with the provider."""
        self.assist_satellites[satellite.stream_name] = satellite
        _LOGGER.debug(
            "Assist satellite registered for stream: %s", satellite.stream_name
        )

    async def async_send_json_message(
        self, stream_name: str, msg: dict[str, Any]
    ) -> None:
        """Send a structured JSON message to a specific connected client."""
        if not (ws_connection := self.active_ws_connections.get(stream_name)):
            _LOGGER.warning(
                "Cannot send message, no client for stream '%s': %s",
                stream_name,
                msg.get("type"),
            )
            return
        ws_connection.send_message(msg)

    async def async_broadcast_message(self, msg: dict[str, Any]) -> None:
        """Broadcast a structured JSON message to all connected clients."""
        # Snapshot the dict before iterating: ``send_message`` may
        # synchronously trigger a disconnect callback that mutates
        # ``active_ws_connections``.
        for stream_name, ws_connection in list(self.active_ws_connections.items()):
            _LOGGER.debug(
                "Broadcasting message to stream '%s': %s",
                stream_name,
                msg.get("type"),
            )
            ws_connection.send_message(msg)

    async def async_send_system_command(
        self, stream_id: str, command: str, new_ip: str | None = None
    ) -> None:
        """Send a system command like 'restart' to a specific Habitron client."""
        ws_connection = self.active_ws_connections.get(stream_id)

        # Log error and abort if client is not connected
        if not ws_connection:
            _LOGGER.error(
                "Failed to send command: No client connected for stream %s", stream_id
            )
            return

        payload = {"type": "habitron/system_command", "command": command}
        if new_ip is not None:
            payload["new_ip"] = new_ip
        ws_connection.send_message(payload)

        # Log success
        _LOGGER.info("Sent %s command to client %s", command, stream_id)

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
            raise HomeAssistantError("Stream source unavailable")

        stream_name = stream_source.replace("habitron://", "")
        if not self.active_ws_connections.get(stream_name):
            _LOGGER.error("No client connected for stream '%s'", stream_name)
            send_message(WebRTCAnswer(answer=""))  # Send empty answer to signal failure
            return

        try:
            self.session_to_stream_map[session_id] = stream_name
            self.webrtc_send_message_callbacks[session_id] = send_message

            # Modify SDP: Filter IPv6 (Do NOT touch the IP addresses, let P2P handle it!)
            modified_offer_sdp = _filter_ipv6_candidates(offer_sdp)

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
            fut: asyncio.Future[Any] = asyncio.Future()
            self.webrtc_futures[session_id] = fut
            _LOGGER.info("Waiting for answer from client for session: %s", session_id)

            # Wait for the answer with a timeout
            try:
                answer_sdp = await asyncio.wait_for(fut, timeout=10)
                send_message(WebRTCAnswer(answer=answer_sdp))  # Send answer back to HA
            except TimeoutError:
                _LOGGER.error("WebRTC answer timed out for session %s", session_id)
                send_message(
                    WebRTCError(code="timeout", message="WebRTC answer timed out")
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
            raise HomeAssistantError(f"No active client for stream '{stream_name}'")

        request_id = uuid.uuid4().hex
        fut: asyncio.Future[Any] = asyncio.Future()
        self.snapshot_futures[request_id] = {"future": fut}

        # Send request to client
        await self.async_send_json_message(
            stream_name, {"type": "habitron/snapshot_request", "request_id": request_id}
        )

        # Wait for the result with timeout
        try:
            return await asyncio.wait_for(fut, timeout=5)
        except TimeoutError as err:
            raise HomeAssistantError("Snapshot request timed out") from err
        finally:
            self.snapshot_futures.pop(request_id, None)  # Clean up future

    @callback
    def async_register_websocket_handlers(self) -> None:
        """Register all custom websocket command handlers.

        Delegates to the ``handlers`` module so this file stays focused on
        the provider itself and the WebRTC / snapshot flows.
        """
        # Imported here to break the otherwise-cyclic chain between
        # ``provider`` and ``handlers``: the handlers module needs the
        # provider for type hints and the voice pipeline imports come
        # back here for the helper protocol.
        from .handlers import register_handlers

        register_handlers(self)

    def _get_stream_or_send_error(
        self, connection: ActiveConnection, msg: dict[str, Any]
    ) -> str | None:
        """Look up the stream name for a connection or send an error to it."""
        stream_name = next(
            (n for n, c in self.active_ws_connections.items() if c == connection),
            None,
        )

        if not stream_name:
            _LOGGER.warning(
                "Received command '%s' from unknown client %s, forcing reconnect",
                msg.get("type", "unknown"),
                connection,
            )
            # Send error to Dart to trigger _forceDisconnect()
            connection.send_error(
                msg["id"], "unregistered", "Client not registered. Please reconnect"
            )
            return None

        return stream_name
