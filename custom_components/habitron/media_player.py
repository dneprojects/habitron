"""Media player entity for Habitron integration."""
# custom_components/habitron/media_player.py

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib import parse

from aiohttp import ClientSession

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    ATTR_MEDIA_ENQUEUE,
    BrowseMedia,
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_get_clientsession,
    async_process_play_media_url,
)
from homeassistant.components.media_source import MediaSourceProtocol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.entity_registry as er

from .const import DOMAIN
from .module import SmartController

if TYPE_CHECKING:
    from .module import HbtnModule
    from .smart_hub import SmartHub
    from .ws_provider import HabitronWebRTCProvider

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Habitron media player entities."""
    smhub: SmartHub = hass.data[DOMAIN][entry.entry_id]
    provider = smhub.ws_provider
    new_devices = []

    if provider is None:
        _LOGGER.error("WebSocket provider not available for media player setup")
        return

    for hbt_module in smhub.router.modules:
        if (
            isinstance(hbt_module, SmartController)
            and hbt_module.mod_type == "Smart Controller Touch"
        ):
            new_devices.append(HbtnMediaPlayer(hbt_module, provider))
            hbt_module.media_player = new_devices[-1]

    if new_devices:
        async_add_entities(new_devices)
        _LOGGER.info("Added %d Habitron media player(s)", len(new_devices))


class HbtnMediaPlayer(MediaPlayerEntity):
    """Representation of a Habitron client as a media player."""

    _attr_should_poll = False

    def __init__(
        self,
        module: HbtnModule,
        provider: HabitronWebRTCProvider,
    ) -> None:
        """Initialize the media player."""
        self._module: HbtnModule = module
        self._provider = provider
        self._stream_name: str = module.name.lower().replace(" ", "_")
        self._attr_name = f"Player {module.name}"
        self._attr_unique_id = f"Mod_{self._module.uid}_mediaplayer"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}
        self._attr_state = MediaPlayerState.IDLE
        self._attr_supported_features = (
            MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.BROWSE_MEDIA
        )
        self._attr_icon = "mdi:speaker"
        self._attr_volume_level: float = 0.3
        self._attr_is_volume_muted = False
        self._pre_mute_volume: float = 0.3
        self._source_player_entity_id: str | None = None
        self._internal_auth_token: str

    @property
    def stream_name(self) -> str:
        """Return private stream name."""
        return self._stream_name

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        self._provider.register_media_player(self)
        _LOGGER.info("Habitron media player %s added", self.name)

    async def get_token(self):
        """Get auth token."""
        owner = await self.hass.auth.async_get_owner()
        if not owner:
            _LOGGER.error("Could not get owner to create internal auth token")
            return
        refresh_token = await self.hass.auth.async_create_refresh_token(
            owner, "habitron-login"
        )
        self._internal_auth_token = self.hass.auth.async_create_access_token(
            refresh_token, "habitron_media_player"
        )

    # This method seems unused in the play_media logic, but kept for completeness
    async def _async_resolve_tts_url(
        self, session: ClientSession, url: str, payload: dict
    ) -> str | int | None:
        """Make the API call to resolve the TTS URL."""
        headers = {"Authorization": f"Bearer {self._internal_auth_token}"}
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                resolved_path = data.get("path")
                _LOGGER.info("Successfully resolved TTS path: %s", resolved_path)
                return resolved_path
            return response.status

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Forward the play_media command to the client."""
        _LOGGER.debug(
            "[%s] play_media triggered. Media ID: %s, Kwargs: %s",
            self.entity_id,
            media_id,
            kwargs,
        )

        origin_entity_id = kwargs.get("origin") or kwargs.get("source_entity_id")
        if origin_entity_id:
            self._source_player_entity_id = origin_entity_id
            _LOGGER.info(
                "[%s] Origin/Source detected: %s", self.entity_id, origin_entity_id
            )

        # --- Bestehende Media-Auflösung ---
        final_media_url = await self._process_media_id(media_id)
        if not final_media_url:
            _LOGGER.error(
                "[%s] Could not resolve media_id to a playable URL", self.entity_id
            )
            self._attr_state = MediaPlayerState.IDLE
            self.async_write_ha_state()
            return

        # --- FALLBACK: Wenn keine Quelle übergeben, Music Assistant prüfen ---
        if not self._source_player_entity_id:
            ent_reg = er.async_get(self.hass)
            ma_players = [
                e.entity_id for e in ent_reg.entities.values() if e.platform == "mass"
            ]
            for ma_player_id in ma_players:
                ma_state = self.hass.states.get(ma_player_id)
                if (
                    ma_state
                    and ma_state.attributes.get("active_queue_player") == self.entity_id
                ):
                    self._source_player_entity_id = ma_player_id
                    _LOGGER.info(
                        "[%s] Source player '%s' detected via Music Assistant",
                        self.entity_id,
                        ma_player_id,
                    )
                    break

        if not self._source_player_entity_id:
            _LOGGER.warning(
                "[%s] No source or origin found — skip/next won't work properly",
                self.entity_id,
            )

        # --- METADATA ---
        source_state = self.hass.states.get(self._source_player_entity_id or "")
        source_attrs = source_state.attributes if source_state else {}
        client_metadata = {
            "title": source_attrs.get("media_title"),
            "artist": source_attrs.get("media_artist"),
            "entity_picture": source_attrs.get("entity_picture"),
        }
        client_metadata = {k: v for k, v in client_metadata.items() if v}

        # --- NEU: Origin mit in Payload übergeben ---
        payload = {
            "media_content_id": final_media_url,
            "metadata": client_metadata,
        }
        if self._source_player_entity_id:
            payload["origin"] = self._source_player_entity_id

        # --- SEND TO CLIENT ---
        await self._provider.async_send_json_message(
            self._stream_name,
            {
                "type": "habitron/play_media",
                "payload": payload,
            },
        )

        _LOGGER.info(
            "[%s] Sent play_media to client with origin: %s",
            self.entity_id,
            self._source_player_entity_id,
        )
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        """Implement the websocket media browsing helper."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    async def _process_media_id(self, media_id: str) -> str:
        """Check media_id and convert to a playable url, handling TTS."""
        if not media_id.startswith("media-source://"):
            return media_id  # It's a regular URL, return as is.

        try:
            _LOGGER.debug(
                "[%s] Resolving media_source URL: %s", self.entity_id, media_id
            )
            resolved_media = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            url = resolved_media.url
            _LOGGER.info("[%s] Resolved media_source URL to: %s", self.entity_id, url)

            # Make it an absolute URL if it's relative
            if url.startswith("/"):
                return f"{self.hass.config.internal_url}{url}"
            return url  # noqa: TRY300

        except Exception:
            _LOGGER.exception(
                "Error while resolving media_source URL '%s'",
                media_id,
            )
            return ""

    async def async_media_play(self) -> None:
        """Send a command to the client to resume playback."""
        self.state = MediaPlayerState.PLAYING
        self.async_write_ha_state()
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/play"}
        )

    async def async_media_pause(self) -> None:
        """Send a command to the client to pause playback."""
        self.state = MediaPlayerState.PAUSED
        self.async_write_ha_state()
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/pause"}
        )

    async def async_media_stop(self) -> None:
        """Send a command to the client to stop media."""
        self.state = MediaPlayerState.STANDBY
        self.async_write_ha_state()
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/stop"}
        )

    async def _forward_command_to_source(self, service: str) -> None:
        """Forward a media command to the original source player."""
        if not self._source_player_entity_id:
            _LOGGER.warning(
                "[%s] Cannot forward command '%s': source player entity ID is not set",
                self.entity_id,
                service,
            )
            return

        _LOGGER.info(
            "[%s] Forwarding '%s' command to source player: %s",
            self.entity_id,
            service,
            self._source_player_entity_id,
        )
        await self.hass.services.async_call(
            "media_player",
            service,
            {"entity_id": self._source_player_entity_id},
            blocking=False,
        )

    async def async_media_next_track(self) -> None:
        """Forward the next_track command to the source player."""
        await self._forward_command_to_source("media_next_track")

    async def async_media_previous_track(self) -> None:
        """Forward the previous_track command to the source player."""
        await self._forward_command_to_source("media_previous_track")

    async def async_set_volume_level(self, volume: float) -> None:
        """Send a command to the client to set the volume."""
        await self._provider.async_send_json_message(
            self._stream_name,
            {"type": "habitron/set_volume", "payload": {"volume_level": volume}},
        )
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute the volume."""
        if mute:
            self._pre_mute_volume = self._attr_volume_level
            await self.async_set_volume_level(0)
        else:
            await self.async_set_volume_level(self._pre_mute_volume or 0.5)

        self._attr_is_volume_muted = mute
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on the media player."""
        self.state = MediaPlayerState.ON
        self.async_write_ha_state()
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/player_turn_on"}
        )

    async def async_turn_off(self) -> None:
        """Turn off the media player."""
        self.state = MediaPlayerState.OFF
        self.async_write_ha_state()
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/player_turn_off"}
        )

    @callback
    def update_from_client(
        self, state: str, attributes: dict[str, Any] | None = None
    ) -> None:
        """Update the entity's state when a message is received from the client."""
        try:
            self._attr_state = MediaPlayerState(state.lower())
        except ValueError:
            _LOGGER.warning("Received unknown media player state: %s", state)
            self._attr_state = MediaPlayerState.IDLE

        if attributes:
            self._attr_media_title = attributes.get("media_title")
            self._attr_media_artist = attributes.get("media_artist")
            self._attr_media_image_url = attributes.get("entity_picture")
            if "volume_level" in attributes:
                self._attr_volume_level = attributes["volume_level"]
            if "is_volume_muted" in attributes:
                self._attr_is_volume_muted = attributes["is_volume_muted"]

        self.async_write_ha_state()

    async def process_media_id(self, media_id: str) -> str:
        """Check media_id and convert to url."""
        if media_id.startswith("media-source://tts/"):
            try:
                parts = media_id.replace("media-source://tts/", "").split("?")
                engine_id = parts[0]
                params = dict(parse.parse_qsl(parts[1]))
                message = params.get("message", "Error: No message found.")
                _LOGGER.info("Resolving TTS URL for message: '%s'", message)

                session = async_get_clientsession(self.hass)
                url = f"{self.hass.config.internal_url}/api/tts_get_url"
                payload = {"engine_id": engine_id, "message": message}

                resolved_path = await self._async_resolve_tts_url(session, url, payload)

                if resolved_path == 401:
                    _LOGGER.warning(
                        "Token expired or invalid. Getting new token and retrying"
                    )
                    await self.get_token()
                    resolved_path = await self._async_resolve_tts_url(
                        session, url, payload
                    )

                if isinstance(resolved_path, str):
                    return f"{self.hass.config.internal_url}{resolved_path}"
                _LOGGER.error(
                    "Failed to resolve TTS URL. Final status was: %s", resolved_path
                )
                return ""  # noqa: TRY300
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Error while processing TTS request in play_media: %s", e)
                return ""
        else:
            return media_id
