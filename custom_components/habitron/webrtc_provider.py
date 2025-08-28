"""Habitron direct WebRTC provider (HA <-> Flutter client)."""

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.camera import (
    Camera,
    CameraWebRTCProvider,
    RTCIceCandidateInit,
    WebRTCAnswer,
    WebRTCSendMessage,
    async_register_webrtc_provider,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Ein zentraler Speicher für aktive WebSocket-Verbindungen.
# Zuordnung von stream_name -> WebSocket-Verbindung.
_active_ws_connections: dict[str, websocket_api.ActiveConnection] = {}
# Ein Dictionary zum Speichern ausstehender WebRTC-Sitzungs-Futures.
# Zuordnung von session_id -> asyncio.Future
_webrtc_futures: dict[str, asyncio.Future] = {}
# Neues Mapping, um die WebRTC-Sitzung mit dem Stream-Namen zu verknüpfen
_session_to_stream_map: dict[str, str] = {}


class HabitronWebRTCProvider(CameraWebRTCProvider):
    """WebRTC-Anbieter, der Angebote an verbundene Flutter-Clients weiterleitet."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialisiert den Anbieter mit dem Home Assistant-Objekt."""
        self.hass = hass

    @property
    def domain(self) -> str:
        """Gibt die Domäne des Anbieters zurück."""
        return DOMAIN

    @callback
    def async_is_supported(self, stream_source: str) -> bool:
        """Überprüft, ob der Anbieter diese Quelle unterstützt."""
        return stream_source.startswith("habitron://")

    async def async_handle_async_webrtc_offer(
        self,
        camera: Camera,
        offer_sdp: str,
        session_id: str,
        send_message: WebRTCSendMessage,
    ) -> None:
        """
        Sendet das Angebot an die vorhandene WS-Verbindung zum Flutter-Client.
        WARTET AUF DIE ANTWORT VOM FLUTTER-CLIENT.
        """
        _LOGGER.info(
            "Empfange WebRTC-Angebot vom HA-Frontend für Sitzung: %s", session_id
        )
        stream_source = await camera.stream_source()
        if stream_source is None:
            _LOGGER.error("Stream-Quelle nicht verfügbar.")
            raise HomeAssistantError("Stream-Quelle nicht verfügbar.")

        stream_name = stream_source.replace("habitron://", "")
        _LOGGER.info(
            "HA-Angebot wird an Flutter-Client mit Stream '%s' gesendet", stream_name
        )

        ws_connection = _active_ws_connections.get(stream_name)
        if not ws_connection:
            _LOGGER.error(
                "Kein verbundener Flutter-Client für Stream '%s' gefunden", stream_name
            )
            # Sendet eine leere Antwort, um das Frontend nicht zu blockieren
            send_message(WebRTCAnswer(answer=""))
            return

        try:
            # Erstellt das Mapping von Lovelace-Sitzungs-ID zu Stream-Namen.
            _session_to_stream_map[session_id] = stream_name

            # ** NEUE ÄNDERUNG: Ersetzt die fehlerhafte 127.0.0.1 IP im SDP-Angebot **
            # Diese IP muss die tatsächliche IP-Adresse Ihres HA-Hosts sein.
            # Wir rufen sie jetzt dynamisch ab, anstatt sie zu fest zu kodieren.
            # try:
            #     # Ruft die IP-Adresse direkt vom HTTP-Server-Objekt ab
            #     local_ip = self.hass.http.server_info["internal_url_netloc"]
            #     if local_ip.count(":") > 1:
            #         local_ip = f"[{local_ip}]"
            #     local_ip = local_ip.rsplit(":", 1)[0]
            # except (KeyError, ValueError):
            #     # Fallback auf die Konfigurationsadresse
            #     local_ip = self.hass.config.api["http"]["base_url"].host

            local_ip = "192.168.178.45"
            modified_offer_sdp = offer_sdp.replace("127.0.0.1", local_ip)
            _LOGGER.info("IP-Adresse in SDP von 127.0.0.1 zu %s geändert", local_ip)

            # Sendet das MODIFIZIERTE Angebot direkt über die WebSocket-Verbindung an den Client.
            ws_connection.send_message(
                {
                    "type": "habitron/webrtc_offer",
                    "value": modified_offer_sdp,
                    "session_id": session_id,
                }
            )

            # Wartet auf die Antwort vom Flutter-Client über ein Future.
            fut: asyncio.Future = asyncio.Future()
            _webrtc_futures[session_id] = fut
            _LOGGER.info(
                "Warte auf Antwort vom Flutter-Client für Sitzung: %s", session_id
            )

            # Setzt ein Timeout, falls keine Antwort empfangen wird.
            await asyncio.wait_for(fut, timeout=15)
            answer_sdp = fut.result()
            _LOGGER.info(
                "WebRTC-Antwort für %s empfangen. Sende an Frontend...", stream_name
            )
            send_message(WebRTCAnswer(answer=answer_sdp))
            _LOGGER.info("WebRTC-Antwort für %s geliefert", stream_name)

        except TimeoutError as err:
            _LOGGER.error("WebRTC-Antwort vom Flutter-Client abgelaufen")
            raise HomeAssistantError(
                "WebRTC-Antwort vom Flutter-Client abgelaufen"
            ) from err
        except Exception as err:
            _LOGGER.error(f"WebRTC-Verhandlung mit Flutter fehlgeschlagen: {err}")
            raise HomeAssistantError(
                f"WebRTC-Verhandlung mit Flutter fehlgeschlagen: {err}"
            ) from err
        # Der fehlerhafte "finally"-Block wurde entfernt. Die Bereinigung erfolgt jetzt nur bei Trennung der Verbindung.

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Leitet ICE-Kandidaten an den Flutter-Client weiter."""
        # Neue Zeile: Protokolliert den empfangenen Kandidaten vor der Weiterleitung.
        _LOGGER.info("Empfangener ICE-Kandidat: %s", candidate)

        _LOGGER.info(
            "Empfange ICE-Kandidaten vom HA-Frontend für Sitzung: %s", session_id
        )
        stream_name = _session_to_stream_map.get(session_id)

        # Überprüft, ob der stream_name gefunden wurde, bevor er verwendet wird.
        if stream_name:
            ws_connection = _active_ws_connections.get(stream_name)

            if ws_connection:
                try:
                    ws_connection.send_message(
                        {
                            "type": "habitron/webrtc_candidate",
                            "candidate": candidate.candidate,
                            "sdp_mid": candidate.sdp_mid,
                            "sdp_m_line_index": candidate.sdp_m_line_index,
                        }
                    )
                    _LOGGER.info(
                        "Lokaler ICE-Kandidat an Flutter-Client für Sitzung %s gesendet",
                        session_id,
                    )
                except Exception as err:
                    _LOGGER.error(
                        "Fehler beim Senden des ICE-Kandidaten für Sitzung %s: %s",
                        session_id,
                        err,
                    )
            else:
                _LOGGER.info(
                    "Keine aktive Verbindung zum Weiterleiten des ICE-Kandidaten für Sitzung %s gefunden",
                    session_id,
                )
        else:
            _LOGGER.info(
                "Kein Stream-Name für Sitzung %s im Mapping gefunden",
                session_id,
            )


@callback
def _async_on_ws_disconnect(
    stream_name: str, connection: websocket_api.ActiveConnection
) -> None:
    """Bereinigt Verbindungen, wenn ein Client die Verbindung trennt."""
    _LOGGER.info("Flutter-Client für Stream '%s' getrennt", stream_name)
    if (
        stream_name in _active_ws_connections
        and _active_ws_connections[stream_name] == connection
    ):
        del _active_ws_connections[stream_name]

    # Bereinigt auch das Mapping, falls eine Sitzung noch existiert.
    sessions_to_delete = [
        session_id
        for session_id, mapped_stream_name in _session_to_stream_map.items()
        if mapped_stream_name == stream_name
    ]
    for session_id in sessions_to_delete:
        if session_id in _webrtc_futures:
            _LOGGER.info("Lösche zukünftiges Objekt für Sitzung %s", session_id)
            del _webrtc_futures[session_id]
        if session_id in _session_to_stream_map:
            _LOGGER.info("Lösche Mapping für Sitzung %s", session_id)
            del _session_to_stream_map[session_id]


@websocket_api.websocket_command(
    {
        vol.Required("type"): "habitron/register_stream",
        vol.Required("stream_name"): str,
    }
)
@websocket_api.async_response
async def handle_register_stream(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Behandelt die Stream-Registrierung."""
    _LOGGER.info("Flutter-Client registrierte Stream '%s'", msg["stream_name"])

    stream_name = msg["stream_name"]
    _active_ws_connections[stream_name] = connection

    # Registriert den Callback für die Bereinigung bei Trennung.
    connection.subscriptions[stream_name] = lambda: _async_on_ws_disconnect(
        stream_name, connection
    )

    connection.send_message(
        websocket_api.messages.result_message(msg["id"], {"status": "ok"})
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "habitron/webrtc_answer",
        vol.Required("session_id"): str,
        vol.Required("sdp"): str,
        # Hinzugefügt, um den Fehler mit zusätzlichen Schlüsseln zu beheben
        vol.Required("stream_name"): str,
    }
)
@websocket_api.async_response
async def handle_webrtc_answer(hass: HomeAssistant, connection, msg):
    """Behandelt die WebRTC-Antwort von der Flutter-App."""
    _LOGGER.info("Empfange WebRTC-Antwort-Nachricht: %s", msg)
    session_id = msg["session_id"]
    sdp = msg["sdp"]

    _LOGGER.info("Suche nach Future mit session_id: %s", session_id)
    fut = _webrtc_futures.get(session_id)
    if fut and not fut.done():
        _LOGGER.info("Future gefunden. Setze Ergebnis...")
        fut.set_result(sdp)
    else:
        _LOGGER.error(
            "WebRTC-Sitzung '%s' nicht gefunden oder bereits abgeschlossen", session_id
        )


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
    """Behandelt den WebRTC-Kandidaten von der Flutter-App."""
    _LOGGER.info("Empfange WebRTC-Kandidaten-Nachricht: %s", msg)
    session_id = msg["session_id"]
    candidate = msg["candidate"]
    sdp_mid = msg["sdp_mid"]
    sdp_m_line_index = msg["sdp_m_line_index"]

    # Sendet den Kandidaten zurück an den Anbieter, der ihn an Lovelace weiterleitet
    provider: HabitronWebRTCProvider = hass.data[DOMAIN]["webrtc_provider"]
    ice_candidate = RTCIceCandidateInit(
        candidate=candidate,
        sdp_mid=sdp_mid,
        sdp_m_line_index=sdp_m_line_index,
    )
    await provider.async_on_webrtc_candidate(session_id, ice_candidate)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "habitron/get_local_ip",
    }
)
@websocket_api.async_response
async def handle_get_local_ip(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Liefert die lokale IP-Adresse des Home Assistant-Servers."""
    # Ruft die IP-Adresse direkt vom HTTP-Server-Objekt ab
    # try:
    #     local_ip = hass.http.server_info["internal_url_netloc"]
    #     if local_ip.count(":") > 1:
    #         local_ip = f"[{local_ip}]"
    #     local_ip = local_ip.rsplit(":", 1)[0]
    # except (KeyError, ValueError):
    #     # Fallback auf die Konfigurationsadresse
    #     local_ip = hass.config.api["http"]["base_url"].host

    # _LOGGER.info("Anfrage für lokale IP erhalten. Sende '%s' an Client.", local_ip)
    local_ip = "192.168.178.45"
    connection.send_message(
        websocket_api.messages.result_message(msg["id"], {"local_ip": local_ip})
    )


async def async_setup_provider(hass: HomeAssistant):
    """Registriert den WebSocket-Handler für den WebRTC-Responder und den Anbieter."""
    websocket_api.async_register_command(hass, handle_register_stream)
    websocket_api.async_register_command(hass, handle_webrtc_answer)
    websocket_api.async_register_command(hass, handle_webrtc_candidate)
    websocket_api.async_register_command(hass, handle_get_local_ip)

    hass.data.setdefault(DOMAIN, {})
    provider = HabitronWebRTCProvider(hass)
    hass.data[DOMAIN]["webrtc_provider"] = provider
    async_register_webrtc_provider(hass, provider)
    _LOGGER.info("Habitron WebRTC Provider registriert")
