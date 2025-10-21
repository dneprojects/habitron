"""Media Player platform for Habitron integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib import parse

from aiohttp import ClientError, ClientSession

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_get_clientsession,
)
from homeassistant.config_entries import ConfigEntry  # FIX 2: Added missing import
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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

    # Create a media player entity for each 'Smart Controller Touch' module.
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
        # Create a stream name from the module name.
        self._stream_name: str = module.name.lower().replace(" ", "_")
        self._attr_name = f"Player {module.name}"
        self._attr_unique_id = f"Mod_{self._module.uid}_mediaplayer"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}
        self._attr_state = MediaPlayerState.IDLE

        # Define supported features for the media player.
        self._attr_supported_features = (
            MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.TURN_ON
            # | MediaPlayerEntityFeature.NEXT_TRACK
            # | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.BROWSE_MEDIA
            # | MediaPlayerEntityFeature.MEDIA_ENQUEUE
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
        """Run when entity is about to be added to hass."""
        await super().async_added_to_hass()
        # Register the media player with the WebSocket provider.
        self._provider.register_media_player(self)
        _LOGGER.info("Habitron media player %s added", self.name)

    async def get_token(self):
        """Get an internal Home Assistant auth token for API calls."""
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
            # Return status code for error handling (e.g., 401 Unauthorized)
            return response.status

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Forward the play_media command to the client."""

        _LOGGER.warning(
            "[%s] play_media triggered. Media ID: %s, kwargs: %s",
            self.entity_id,
            media_id,
            kwargs,
        )

        self._source_player_entity_id = None

        # --- Media Resolution (TTS/Media Source) ---
        # Resolve media_id to a full, playable URL, handling media-source and TTS.
        final_media_url = await self._process_media_id(media_id)
        if not final_media_url:
            _LOGGER.error(
                "[%s] Could not resolve media_id to a playable URL", self.entity_id
            )
            self._attr_state = MediaPlayerState.IDLE
            self.async_write_ha_state()
            return

        # --- Metadata Initialization from Browsing Data ---
        title = "Playing Media"
        artist = "Home Assistant"  # Default fallback
        artwork_url = None

        # Attempt to get metadata via the Browse Media mechanism for the media-source ID
        if media_id.startswith("media-source://"):
            try:
                # Use async_browse_media to get metadata for the specific item
                browse_result = await media_source.async_browse_media(
                    self.hass,
                    media_id,
                )

                # Check if results have metadata on the root level
                if browse_result.title:
                    title = browse_result.title
                    if " - " in title:
                        parts = title.split(" - ", 1)
                        artist = parts[0].strip()
                        title = parts[1].strip()

                    elif "/" in title:
                        parts = title.split("/", 1)
                        artist = parts[1].strip()
                        title = parts[0].strip()

                if browse_result.thumbnail:
                    artwork_url = browse_result.thumbnail

                _LOGGER.warning(
                    "[%s] Metadata found via browse: Title=%s, Artwork=%s",
                    self.entity_id,
                    title,
                    artwork_url,
                )

            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "[%s] Failed to fetch rich metadata via media_source browse: %s",
                    self.entity_id,
                    str(e),
                )

        # Prepare metadata payload for the client
        client_metadata = {
            "title": title,
            "artist": artist,
        }
        if artwork_url:
            client_metadata["entity_picture"] = artwork_url

        # --- SEND TO CLIENT ---
        payload = {
            "media_content_id": final_media_url,
            "metadata": client_metadata,
        }
        payload["origin"] = None

        # Send the play_media command via WebSocket to the Habitron client
        await self._provider.async_send_json_message(
            self._stream_name,
            {
                "type": "habitron/play_media",
                "payload": payload,
            },
        )

        # Update entity state attributes
        self._attr_media_image_url = artwork_url
        self._attr_media_title = title
        self._attr_media_artist = artist

        _LOGGER.info(
            "[%s] Sent play_media to client",
            self.entity_id,
        )
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        """Implement the websocket media browsing helper."""
        # Use Home Assistant's media_source helper to browse for audio content.
        res = await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )
        _LOGGER.warning("Browse media called. Result: %s", res)
        return res

    async def _process_media_id(self, media_id: str) -> str:
        """Check media_id and convert to a playable url, handling TTS and media-source."""

        if media_id.startswith("media-source://tts/"):
            # Logic for Text-to-Speech (TTS) resolution
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

                # Handle token expiration by refreshing and retrying
                if resolved_path == 401:
                    _LOGGER.warning(
                        "Token expired or invalid. Getting new token and retrying"
                    )
                    await self.get_token()
                    resolved_path = await self._async_resolve_tts_url(
                        session, url, payload
                    )

                if isinstance(resolved_path, str):
                    # Return the full internal URL for the resolved TTS path
                    return f"{self.hass.config.internal_url}{resolved_path}"
                _LOGGER.error(
                    "Failed to resolve TTS URL. Final status was: %s", resolved_path
                )
                return ""  # noqa: TRY300
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Error while processing TTS request in play_media: %s", e)
                return ""

        elif media_id.startswith("media-source://"):
            # Logic for standard media-source resolution
            try:
                _LOGGER.debug(
                    "[%s] Resolving media_source URL: %s", self.entity_id, media_id
                )
                # Use Home Assistant's async_resolve_media helper
                resolved_media = await media_source.async_resolve_media(
                    self.hass, media_id, self.entity_id
                )
                url = resolved_media.url
                _LOGGER.info(
                    "[%s] Resolved media_source URL to: %s", self.entity_id, url
                )

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

        # Fallback for regular URLs
        return media_id

    async def async_media_play(self, **kwargs: Any) -> None:
        """Send a command to the client to resume playback."""
        # Send a WebSocket message for play
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/play"}
        )

    async def async_media_pause(self, **kwargs: Any) -> None:
        """Send a command to the client to pause playback."""
        # Send a WebSocket message for pause
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/pause"}
        )

    async def async_media_stop(self, **kwargs: Any) -> None:
        """Send a command to the client to stop media."""
        # Send a WebSocket message for stop
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/stop"}
        )

    # async def async_media_next_track(self, **kwargs: Any) -> None:
    #     """Send a command to the client to skip to the next track."""
    #     _LOGGER.debug("[%s] Skipping to next track", self.entity_id)

    # async def async_media_previous_track(self, **kwargs: Any) -> None:
    #     """Send a command to the client to skip to the previous track."""
    #     _LOGGER.debug("[%s] Skipping to previous track", self.entity_id)

    async def async_set_volume_level(self, volume: float) -> None:
        """Send a command to the client to set the volume."""
        # Send a WebSocket message to set volume
        await self._provider.async_send_json_message(
            self._stream_name,
            {"type": "habitron/set_volume", "payload": {"volume_level": volume}},
        )
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the volume."""
        if mute:
            # Save current volume before muting
            self._pre_mute_volume = self._attr_volume_level
            await self.async_set_volume_level(0)
        else:
            # Restore volume or default if no pre-mute volume is saved
            await self.async_set_volume_level(self._pre_mute_volume or 0.5)

        self._attr_is_volume_muted = mute
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on the media player."""
        # Send a WebSocket message to turn on the player
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/player_turn_on"}
        )

    async def async_turn_off(self) -> None:
        """Turn off the media player."""
        # Send a WebSocket message to turn off the player
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/player_turn_off"}
        )

    async def _async_fetch_image(self, url: str) -> tuple[bytes | None, str | None]:
        """Fetch an image from a URL (used for album art)."""

        _LOGGER.debug("Fetching media artwork from: %s", url)
        try:
            websession = async_get_clientsession(self.hass)
            # Fetch image data from the URL
            async with websession.get(url) as response:
                if response.status != 200:
                    _LOGGER.warning(
                        "Error fetching artwork from %s: %s", url, response.status
                    )
                    return None, None
                return await response.read(), response.content_type
        except ClientError as err:
            _LOGGER.warning("Error fetching artwork from %s: %s", url, err)
            return None, None

    async def async_get_browse_image(
        self, media_content_type, media_content_id, media_image_id=None
    ):
        """Serve album art. Returns (content, content_type)."""
        # Use the currently set media image URL for fetching artwork
        image_url = self._attr_media_image_url
        if not image_url:
            return None, None
        return await self._async_fetch_image(image_url)

    @callback
    def update_from_client(
        self, state: str, attributes: dict[str, Any] | None = None
    ) -> None:
        """Update the entity's state when a message is received from the client."""
        try:
            # Convert incoming state string to MediaPlayerState enum
            self._attr_state = MediaPlayerState(state.lower())
        except ValueError:
            _LOGGER.warning("Received unknown media player state: %s", state)
            self._attr_state = MediaPlayerState.IDLE

        try:
            if attributes:
                # Update various media attributes from client data
                self._attr_media_title = attributes.get("media_title")
                self._attr_media_artist = attributes.get("media_artist")
                self._attr_media_image_url = attributes.get("entity_picture")
                if "volume_level" in attributes:
                    self._attr_volume_level = attributes["volume_level"]
                if "is_volume_muted" in attributes:
                    self._attr_is_volume_muted = attributes["is_volume_muted"]
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error updating attributes from client: %s", e)

        self.async_write_ha_state()

    # The TTS and media-source logic is in _process_media_id
    async def process_media_id(self, media_id: str) -> str:
        """Check media_id and convert to url. (Mostly redundant due to _process_media_id)."""
        return await self._process_media_id(media_id)
