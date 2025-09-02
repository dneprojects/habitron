"""Habitron direct WebRTC provider (HA <-> Flutter client)."""

import asyncio
import base64
import logging
import os
import socket
from typing import Any
import uuid

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.camera import (
    Camera,
    CameraWebRTCProvider,
    RTCIceCandidateInit,
    WebRTCAnswer,
    WebRTCCandidate,
    WebRTCSendMessage,
    async_register_webrtc_provider,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Zentraler Speicher für aktive WebSocket-Verbindungen: stream_name -> connection
_active_ws_connections: dict[str, websocket_api.ActiveConnection] = {}

# Speicher für ausstehende WebRTC-Futures: session_id -> asyncio.Future
_webrtc_futures: dict[str, asyncio.Future] = {}

# Speicherung der send_message-Callbacks für jede WebRTC-Sitzung
_webrtc_send_message_callbacks: dict[str, WebRTCSendMessage] = {}

# Mapping session_id -> stream_name
_session_to_stream_map: dict[str, str] = {}

# Warteschlange für ausstehende Kandidaten
# Der Schlüssel ist die session_id, der Wert ist eine Liste von WebRTCCandidate-Objekten
_pending_candidates: dict[str, list[WebRTCCandidate]] = {}

# Speicher für ausstehende Snapshot-Futures: request_id -> dict mit 'future' und 'stream_name'
_snapshot_futures: dict[str, dict] = {}


class HabitronWebRTCProvider(CameraWebRTCProvider):
    """WebRTC provider that forwards offers and snapshot requests to connected Flutter clients."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the provider."""
        self.hass = hass

    @property
    def domain(self) -> str:
        """Return the domain of the provider."""
        return DOMAIN

    @callback
    def async_is_supported(self, stream_source: str) -> bool:
        """Return True if the stream source is supported."""
        return stream_source.startswith("habitron://")

    async def async_handle_async_webrtc_offer(
        self,
        camera: Camera,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
    ) -> None:
        """Forward the WebRTC offer to the Flutter client."""
        _LOGGER.info(
            "Received WebRTC offer from HA frontend for session: %s", session_id
        )
        stream_source = await camera.stream_source()
        if not stream_source:
            raise HomeAssistantError("Stream source unavailable.")

        stream_name = stream_source.replace("habitron://", "")
        ws_connection = _active_ws_connections.get(stream_name)
        if not ws_connection:
            _LOGGER.error("No Flutter client connected for stream '%s'", stream_name)
            send_message(WebRTCAnswer(answer=""))
            return

        try:
            _session_to_stream_map[session_id] = stream_name
            _webrtc_send_message_callbacks[session_id] = send_message
            _LOGGER.debug("Mapped session %s to stream '%s'", session_id, stream_name)

            # Determine local IP dynamically
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
                _LOGGER.warning(
                    "Failed to determine local IP, fallback to 127.0.0.1: %s", e
                )

            modified_offer_sdp = offer_sdp.replace("127.0.0.1", local_ip)
            _LOGGER.info("Replaced SDP IP with %s", local_ip)
            _LOGGER.debug("Original SDP: %s", offer_sdp)
            _LOGGER.debug("Modified SDP: %s", modified_offer_sdp)

            # Send offer via WebSocket to Flutter client
            ws_connection.send_message(
                {
                    "type": "habitron/webrtc_offer",
                    "value": modified_offer_sdp,
                    "session_id": session_id,
                }
            )

            # Wait for the answer
            fut: asyncio.Future = asyncio.Future()
            _webrtc_futures[session_id] = fut
            _LOGGER.info(
                "Waiting for answer from Flutter client for session: %s", session_id
            )
            await asyncio.wait_for(fut, timeout=30)
            answer_sdp = fut.result()
            send_message(WebRTCAnswer(answer=answer_sdp))
            _LOGGER.info("WebRTC answer delivered for stream: %s", stream_name)
            _LOGGER.debug("Answer SDP from Flutter: %s", answer_sdp)

            # NEU: Kandidaten aus der Warteschlange verarbeiten
            if session_id in _pending_candidates:
                _LOGGER.info(
                    "Processing %d pending candidates for session %s",
                    len(_pending_candidates[session_id]),
                    session_id,
                )
                for candidate_obj in _pending_candidates[session_id]:
                    # KEIN await, da send_message ein Callback ist
                    send_message(candidate_obj)
                del _pending_candidates[session_id]
                _LOGGER.info("Pending candidates sent")

        except TimeoutError as err:
            _LOGGER.error("WebRTC answer from Flutter client timed out")
            raise HomeAssistantError(
                "WebRTC answer from Flutter client timed out"
            ) from err
        except Exception as err:
            _LOGGER.error("WebRTC negotiation with Flutter failed: %s", err)
            raise HomeAssistantError(
                f"WebRTC negotiation with Flutter failed: {err}"
            ) from err

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Forward all valid ICE candidates to the Flutter client."""
        _LOGGER.info(
            "Received ICE candidate from HA frontend for session %s: %s",
            session_id,
            candidate.candidate,
        )

        send_message = _webrtc_send_message_callbacks.get(session_id)

        # Verpackt das RTCIceCandidateInit-Objekt in ein WebRTCCandidate-Objekt.
        webrtc_candidate_obj = WebRTCCandidate(candidate=candidate)

        # Das korrekt verpackte Objekt an die Home Assistant Core senden
        if send_message:
            try:
                # KEIN await, da send_message ein Callback ist
                send_message(webrtc_candidate_obj)
                _LOGGER.info(
                    "Forwarded ICE candidate to HA frontend for session %s",
                    session_id,
                )
            except Exception as e:
                _LOGGER.error("Error forwarding candidate to HA frontend: %s", e)
                raise HomeAssistantError(
                    "Error forwarding candidate to HA frontend"
                ) from e
        else:
            # Kandidat zur Warteschlange hinzufügen, falls send_message noch nicht verfügbar ist
            # Hinzufügen des korrekten Typs zum Pending-Array
            _pending_candidates.setdefault(session_id, []).append(webrtc_candidate_obj)
            _LOGGER.info(
                "No send_message callback found. Candidate added to pending queue for session %s",
                session_id,
            )

    async def async_take_snapshot(self, stream_name: str) -> bytes:
        """Handles a request from Home Assistant to take a snapshot from the stream."""
        _LOGGER.info("Received snapshot request for stream: %s", stream_name)
        ws_connection = _active_ws_connections.get(stream_name)

        if not ws_connection:
            _LOGGER.error("No Flutter client connected for stream '%s'", stream_name)
            raise HomeAssistantError("No active client for this stream.")

        request_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.Future()
        _snapshot_futures[request_id] = {"future": fut, "stream_name": stream_name}

        ws_connection.send_message(
            {
                "type": "habitron/snapshot_request",
                "request_id": request_id,
            }
        )

        try:
            snapshot_data = await asyncio.wait_for(fut, timeout=30)
            _LOGGER.info("Received snapshot data for stream: %s", stream_name)
            return snapshot_data
        except TimeoutError as err:
            _LOGGER.error("Snapshot request for stream '%s' timed out", stream_name)
            raise HomeAssistantError("Snapshot request timed out.") from err
        except Exception as e:
            _LOGGER.error(
                "Error receiving snapshot for stream '%s': %s", stream_name, e
            )
            raise HomeAssistantError("Error receiving snapshot.") from e
        finally:
            _snapshot_futures.pop(request_id, None)


@callback
def _async_on_ws_disconnect(
    stream_name: str, connection: websocket_api.ActiveConnection
) -> None:
    """Clean up when a Flutter client disconnects."""
    _LOGGER.info("Flutter client for stream '%s' disconnected", stream_name)
    if _active_ws_connections.get(stream_name) == connection:
        del _active_ws_connections[stream_name]

    # Clean up related sessions
    sessions_to_delete = [
        s for s, sn in _session_to_stream_map.items() if sn == stream_name
    ]
    for session_id in sessions_to_delete:
        _webrtc_futures.pop(session_id, None)
        _webrtc_send_message_callbacks.pop(session_id, None)
        _session_to_stream_map.pop(session_id, None)
        _pending_candidates.pop(session_id, None)

    # Clean up related snapshot futures
    snapshot_requests_to_delete = [
        r
        for r, data in _snapshot_futures.items()
        if data["stream_name"] == stream_name and not data["future"].done()
    ]
    for request_id in snapshot_requests_to_delete:
        _snapshot_futures.pop(request_id, None)


@websocket_api.websocket_command(
    {vol.Required("type"): "habitron/register_stream", vol.Required("stream_name"): str}
)
@websocket_api.async_response
async def handle_register_stream(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
):
    """Handle Flutter stream registration."""
    _LOGGER.info("Received message: %s", msg)  # Hinzugefügt für das Debugging
    stream_name = msg["stream_name"]
    _active_ws_connections[stream_name] = connection
    connection.subscriptions[stream_name] = lambda: _async_on_ws_disconnect(
        stream_name, connection
    )
    connection.send_message(
        websocket_api.messages.result_message(msg["id"], {"status": "ok"})
    )
    _LOGGER.info("Flutter client registered stream '%s'", stream_name)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "habitron/webrtc_answer",
        vol.Required("session_id"): str,
        vol.Required("sdp"): str,
        vol.Required("stream_name"): str,
    }
)
@websocket_api.async_response
async def handle_webrtc_answer(hass: HomeAssistant, connection, msg):
    """Handle WebRTC answer from Flutter app."""
    _LOGGER.info("Received message: %s", msg)  # Hinzugefügt für das Debugging
    session_id = msg["session_id"]
    sdp = msg["sdp"]
    fut = _webrtc_futures.get(session_id)
    if fut and not fut.done():
        fut.set_result(sdp)
        _LOGGER.info("Set WebRTC answer for session %s", session_id)
        _LOGGER.debug("Received answer SDP from Flutter: %s", sdp)
    else:
        _LOGGER.error("WebRTC session '%s' not found or already completed", session_id)


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
async def handle_webrtc_candidate(hass: HomeAssistant, connection, msg):
    """Handle ICE candidate from Flutter app."""
    _LOGGER.info("Received message: %s", msg)  # Hinzugefügt für das Debugging
    _LOGGER.info(
        "Received ICE candidate from Flutter client for session %s", msg["session_id"]
    )

    send_message = _webrtc_send_message_callbacks.get(msg["session_id"])

    # Umwandlung des eingehenden Dictionaries in ein RTCIceCandidateInit-Objekt
    candidate_init_obj = RTCIceCandidateInit(
        candidate=msg["candidate"],
        sdp_mid=msg["sdp_mid"],
        sdp_m_line_index=msg["sdp_m_line_index"],
    )

    # Verpacken des RTCIceCandidateInit-Objekts in ein WebRTCCandidate-Objekt
    webrtc_candidate_obj = WebRTCCandidate(candidate=candidate_init_obj)

    # Das korrekt verpackte Objekt an die Home Assistant Core senden
    if send_message:
        try:
            # KEIN await, da send_message ein Callback ist
            send_message(webrtc_candidate_obj)
            _LOGGER.info(
                "Forwarded ICE candidate to HA frontend for session %s",
                msg["session_id"],
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error forwarding candidate to HA frontend: %s", e)
    else:
        # Kandidat zur Warteschlange hinzufügen, falls send_message noch nicht verfügbar ist
        _pending_candidates.setdefault(msg["session_id"], []).append(
            webrtc_candidate_obj
        )
        _LOGGER.info(
            "No send_message callback found. Candidate added to pending queue for session %s",
            msg["session_id"],
        )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "habitron/snapshot_result",
        vol.Required("request_id"): str,
        vol.Required("data"): str,
    }
)
@websocket_api.async_response
async def handle_snapshot_result(hass: HomeAssistant, connection, msg):
    """Handle snapshot result from Flutter app."""
    request_id = msg["request_id"]
    data = _snapshot_futures.get(request_id)
    if data and not data["future"].done():
        try:
            snapshot_data = base64.b64decode(msg["data"])
            data["future"].set_result(snapshot_data)
            _LOGGER.info("Set snapshot result for request %s", request_id)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error decoding snapshot data: %s", e)
            data["future"].set_exception(
                HomeAssistantError("Failed to decode snapshot data.")
            )
    else:
        _LOGGER.warning(
            "Snapshot request %s not found or already completed", request_id
        )
    connection.send_message(websocket_api.messages.result_message(msg["id"]))


# Funktion zur Registrierung des WebRTC-Providers
async def async_setup_provider(hass: HomeAssistant):
    """Set up the Habitron WebRTC provider."""
    _LOGGER.info("Registering Habitron WebRTC provider")
    provider = HabitronWebRTCProvider(hass)
    async_register_webrtc_provider(hass, provider)

    # Register the WebSocket command handlers
    websocket_api.async_register_command(hass, handle_register_stream)
    websocket_api.async_register_command(hass, handle_webrtc_answer)
    websocket_api.async_register_command(hass, handle_webrtc_candidate)
    websocket_api.async_register_command(hass, handle_snapshot_result)

    _LOGGER.info("Habitron WebRTC provider registered successfully")
    return provider
