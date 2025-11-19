"""Media Player platform for Habitron integration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import ClientError, ClientSession

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerEnqueue,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_get_clientsession,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval, timedelta
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .module import SmartController

if TYPE_CHECKING:
    from .module import HbtnModule
    from .smart_hub import SmartHub
    from .ws_provider import HabitronWebRTCProvider

_LOGGER = logging.getLogger(__name__)


# Helper class for queue items
class QueueItem:
    """Class to hold queue item data."""

    def __init__(
        self,
        media_id: str,
        media_type: str | MediaType,
        media_url: str,
        metadata: dict[str, Any],
    ) -> None:
        """Initialize the queue item."""
        self.media_id = media_id
        self.media_type = media_type
        self.media_url = media_url
        self.metadata = metadata


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
            new_devices.append(HbtnMediaPlayer(hbt_module, provider, hass))
            hbt_module.media_player = new_devices[-1]

    if new_devices:
        async_add_entities(new_devices)
        _LOGGER.info("Added %d Habitron media player(s)", len(new_devices))


# RestoreEntity stores state between Home Assistant restarts
class HbtnMediaPlayer(MediaPlayerEntity, RestoreEntity):
    """Representation of a Habitron client as a media player."""

    _attr_should_poll = False

    def __init__(
        self,
        module: HbtnModule,
        provider: HabitronWebRTCProvider,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the media player."""
        self._module: HbtnModule = module
        self._provider = provider
        self._stream_name: str = (
            module.name.lower().replace(" ", "_") + f"_{module.raddr}"
        )
        self._hass = hass
        self._attr_name = f"Player {module.name}"
        self._attr_unique_id = f"Mod_{self._module.uid}_mediaplayer"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}
        self._attr_state = MediaPlayerState.OFF

        self._queue: list[QueueItem] = []
        self._history: list[QueueItem] = []
        self._current_item: QueueItem | None = None
        self._play_request_lock = asyncio.Lock()
        self._attr_icon = "mdi:speaker"
        self._attr_volume_level: float = 0.3
        self._attr_is_volume_muted = False
        self._pre_mute_volume: float = 0.3

        self._source_player_entity_id: str | None = None
        self._internal_auth_token: str
        self._track_mode: str = "single"  # 'single' or 'multi'
        self._poll_remove = None

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

        # Restore previous state
        last_state = await self.async_get_last_state()
        if last_state is not None:
            vol = last_state.attributes.get("volume_level")
            muted = last_state.attributes.get("is_volume_muted")
            if vol is not None:
                self._attr_volume_level = vol
            if muted is not None:
                self._attr_is_volume_muted = muted

    # Dynamic supported_features based on track mode
    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Return the list of supported features, dynamic based on track mode."""

        # Start with the base features that are always available
        base_features = (
            MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.BROWSE_MEDIA
            | MediaPlayerEntityFeature.MEDIA_ENQUEUE
            | MediaPlayerEntityFeature.CLEAR_PLAYLIST
        )

        # Dynamically add skip buttons ONLY if in multi-track mode
        if self._track_mode == "multi":
            _LOGGER.debug("[%s] Multi-track mode: Adding Skip buttons", self.entity_id)
            base_features |= MediaPlayerEntityFeature.NEXT_TRACK
            base_features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        else:
            _LOGGER.debug(
                "[%s] Single-track mode: Removing Skip buttons", self.entity_id
            )

        return base_features

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
        self,
        media_type: MediaType | str,
        media_id: str,
        enqueue: MediaPlayerEnqueue | None = None,
        **kwargs: Any,
    ) -> None:
        """Handle play_media service call (populates internal queue)."""
        _LOGGER.info(
            "[%s] play_media received: media_id=%s, enqueue_mode=%s",
            self.entity_id,
            media_id,
            enqueue,
        )

        if enqueue in (
            MediaPlayerEnqueue.ADD,
            MediaPlayerEnqueue.NEXT,
            MediaPlayerEnqueue.PLAY,
        ):
            self._track_mode = "multi"
        else:
            self._track_mode = "single"
        _LOGGER.debug("[%s] Set track_mode to: %s", self.entity_id, self._track_mode)

        # Ensure that @property supported_features is queried again
        self.async_write_ha_state()

        if not self._poll_remove:
            self._poll_remove = async_track_time_interval(
                self.hass, self._poll_ma_metadata, timedelta(seconds=3)
            )
            _LOGGER.debug("[%s] Started proxy metadata polling", self.entity_id)

        # Prevent concurrent play_media calls
        async with self._play_request_lock:
            # Resolve URL and metadata
            try:
                media_url = await self._process_media_id(media_id)
                if not media_url:
                    _LOGGER.error("[%s] Could not resolve media_id", self.entity_id)
                    return

                metadata = await self._extract_metadata(media_id, kwargs)
                metadata["track_mode"] = self._track_mode

                item = QueueItem(media_id, media_type, media_url, metadata)

            except Exception as e:  # noqa: BLE001
                _LOGGER.error("[%s] Error processing media_id: %s", self.entity_id, e)
                return

            # Manage queue (based on MA enum)
            play_now = False

            if enqueue == MediaPlayerEnqueue.REPLACE or enqueue is None:
                _LOGGER.debug("[%s] Mode REPLACE: Clearing queue", self.entity_id)
                self._queue = [item]
                self._history = []
                if self._current_item:
                    self._history.append(self._current_item)
                self._current_item = None
                play_now = True

            elif enqueue == MediaPlayerEnqueue.ADD:
                _LOGGER.debug("[%s] Mode ADD: Appending to queue", self.entity_id)
                self._queue.append(item)

            elif enqueue == MediaPlayerEnqueue.NEXT:
                _LOGGER.debug(
                    "[%s] Mode NEXT: Inserting at top of queue", self.entity_id
                )
                self._queue.insert(0, item)

            elif enqueue == MediaPlayerEnqueue.PLAY:
                _LOGGER.debug(
                    "[%s] Mode PLAY: Inserting and forcing play", self.entity_id
                )
                if self._current_item:
                    self._history.append(self._current_item)
                self._queue.insert(0, item)
                play_now = True

            # Trigger playback if player is 'idle' or 'play_now' is forced
            if self._attr_state in (MediaPlayerState.IDLE, MediaPlayerState.OFF):
                play_now = True

            if play_now:
                _LOGGER.debug(
                    "[%s] Play is requested, calling _play_next_item_in_queue",
                    self.entity_id,
                )
                await self._play_next_item_in_queue()
            else:
                _LOGGER.debug(
                    "[%s] Player is busy or not idle, queueing track", self.entity_id
                )

    async def _poll_ma_metadata(self, _now) -> None:
        """Log metadata from Music Assistant if available."""

        if self._attr_state != MediaPlayerState.PLAYING:
            await self._stop_proxy_polling()
            return

        proxy_entity_id = self._get_mass_proxy_entity_id()
        if not proxy_entity_id:
            return

        state = self.hass.states.get(proxy_entity_id)
        if not state:
            return

        self._track_mode = "multi"
        title = state.attributes.get("media_title")
        artist = state.attributes.get("media_artist")
        artwork_url = state.attributes.get("entity_picture")
        _LOGGER.debug(
            "[%s] MA Proxy Metadata: Title=%s, Artist=%s, Artwork=%s",
            self.entity_id,
            title,
            artist,
            artwork_url,
        )
        current_metadata = {
            "title": title,
            "artist": artist,
            "entity_picture": artwork_url,
        }
        payload = {
            "metadata": current_metadata,
            "origin": "Music Assistant",
        }

        # Send the play_media command via WebSocket
        await self._provider.async_send_json_message(
            self._stream_name,
            {
                "type": "habitron/update_metadata",
                "payload": payload,
            },
        )

    async def _stop_proxy_polling(self):
        """Beende das Polling, falls aktiv."""
        if self._poll_remove:
            self._poll_remove()  # deregister the listener
            self._poll_remove = None
            _LOGGER.debug("[%s] Stopped proxy metadata polling", self.entity_id)

    async def _extract_metadata(self, media_id: str, kwargs: dict[str, Any]) -> dict:
        """Helper to extract metadata from kwargs or browse_media."""

        metadata_in = kwargs.get("extra", {}).get("metadata", {})
        title = metadata_in.get("title", "Unknown Title")
        artist = metadata_in.get("artist", "Unknown Artist")
        artwork_url = metadata_in.get("imageUrl") or metadata_in.get("entity_picture")

        if media_id.startswith("media-source://") and (
            artist in {"Home Assistant", "Unknown Artist"}
        ):
            try:
                browse_result = await media_source.async_browse_media(
                    self.hass, media_id
                )
                if browse_result and browse_result.title:
                    title = browse_result.title
                    if title == "Radio Browser":
                        title = "Internet Radio"
                        artist = "Home Assistant"
                    elif " - " in title:
                        parts = title.split(" - ", 1)
                        artist = parts[0].strip()
                        title = parts[1].strip()
                    elif "/" in title:
                        parts = title.split("/", 1)
                        artist = parts[1].strip()
                        title = parts[0].strip()

                if browse_result and browse_result.thumbnail:
                    artwork_url = browse_result.thumbnail

                _LOGGER.info(
                    "[%s] Metadata found via browse: Title=%s, Artist=%s, Artwork=%s",
                    self.entity_id,
                    title,
                    artist,
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
            if artwork_url.startswith("/"):
                artwork_url = f"{self.hass.config.internal_url}{artwork_url}"
            client_metadata["entity_picture"] = artwork_url

        return client_metadata

    async def _send_item_to_client(self, item: QueueItem) -> None:
        """Sends a single item to the client for playback."""
        _LOGGER.info(
            "[%s] Sending play_media to client: %s (Mode: %s)",
            self.entity_id,
            item.metadata.get("title"),
            self._track_mode,
        )

        payload = {
            "media_content_id": item.media_url,
            "metadata": item.metadata,
            "origin": None,
        }

        # Send the play_media command via WebSocket
        await self._provider.async_send_json_message(
            self._stream_name,
            {
                "type": "habitron/play_media",
                "payload": payload,
            },
        )

        # Update entity state attributes
        self._attr_media_image_url = item.metadata.get("entity_picture")
        self._attr_media_title = item.metadata.get("title")
        self._attr_media_artist = item.metadata.get("artist")

        # Important: Prevents "Race Condition"
        self._attr_state = MediaPlayerState.BUFFERING
        self.async_write_ha_state()

    async def _play_next_item_in_queue(self) -> None:
        """Plays the next item from the internal queue."""

        if not self._queue:
            _LOGGER.info(
                "[%s] Internal queue is empty. Setting state to IDLE", self.entity_id
            )
            self._attr_state = MediaPlayerState.IDLE
            if self._current_item:
                self._history.append(self._current_item)
            self._current_item = None
            self._attr_media_title = None
            self._attr_media_artist = None
            self._attr_media_image_url = None
            self.async_write_ha_state()
            return

        # Get current title (if available) and move to history
        if self._current_item:
            self._history.append(self._current_item)

        # Get next title from the queue
        self._current_item = self._queue.pop(0)
        await self._send_item_to_client(self._current_item)

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
        _LOGGER.debug("Browse media called. Result: %s", res)
        return res

    async def _process_media_id(self, media_id: str) -> str:
        """Check media_id and convert to a playable url, handling all media-source types."""

        # If it's a media-source URL (file, radio, or TTS),
        # let Home Assistant resolve it.
        if media_id.startswith("media-source://"):
            try:
                _LOGGER.debug(
                    "[%s] Resolving media_source URL: %s", self.entity_id, media_id
                )

                # This single function can resolve BOTH TTS and regular media files.
                resolved_media = await media_source.async_resolve_media(
                    self.hass, media_id, self.entity_id
                )

                url = resolved_media.url
                _LOGGER.info(
                    "[%s] Resolved media_source URL to: %s", self.entity_id, url
                )

                # Make it an absolute URL if it's relative
                # (e.g., /api/tts_proxy/... -> http://<ha_ip>:8123/api/tts_proxy/...)
                if url.startswith("/"):
                    return f"{self.hass.config.internal_url}{url}"

                # If it's already absolute (e.g., from a radio stream), return as is.
                return url  # noqa: TRY300

            except Exception:
                _LOGGER.exception(
                    "Error while resolving media_source URL '%s'",
                    media_id,
                )
                return ""

        # If it's not a media-source URL (e.g., a direct http:// URL),
        # return it as is.
        return media_id

    async def async_media_play(self, **kwargs: Any) -> None:
        """Send a command to the client to resume playback."""
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/play"}
        )
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_pause(self, **kwargs: Any) -> None:
        """Send a command to the client to pause playback."""
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/pause"}
        )
        self._attr_state = MediaPlayerState.PAUSED
        self.async_write_ha_state()

    async def async_media_stop(
        self, force_client_stop: bool = False, **kwargs: Any
    ) -> None:
        """Stop media playback."""
        _LOGGER.debug("[%s] Stop command received. Clearing queue", self.entity_id)
        self._queue = []
        self._history = []
        self._current_item = None
        self._track_mode = "single"

        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/stop"}
        )

        # If the stop was forced by 'play_now', do not set the status
        # to IDLE, as a new song is coming immediately.
        if not force_client_stop:
            self._attr_state = MediaPlayerState.IDLE
            self.async_write_ha_state()

    async def async_clear_playlist(self, **kwargs: Any) -> None:
        """Clear the internal playlist without stopping playback."""
        _LOGGER.debug("[%s] Clear playlist command received", self.entity_id)
        self._queue = []
        self._history = []
        # Do not stop current playback or change state
        self.async_write_ha_state()

    def _get_mass_proxy_entity_id(self) -> str | None:
        """Find the Music Assistant player entity ID that is proxying this player."""
        # Find the MA player that has this entity set as its active queue
        for state in self.hass.states.async_all("media_player"):
            if (
                state.attributes.get("mass_player_type") == "player"
                and state.attributes.get("active_queue") == self.entity_id
            ):
                _LOGGER.debug("Found MA proxy player: %s", state.entity_id)
                return state.entity_id
        _LOGGER.warning("Could not find MA proxy player for %s", self.entity_id)
        return None

    async def async_media_next_track(self, **kwargs: Any) -> None:
        """Skip to the next track in the internal queue, or delegate to MA if empty."""
        _LOGGER.debug("[%s] Next track called", self.entity_id)

        # Skip allowing in "multi" mode
        if self._track_mode == "single":
            _LOGGER.debug(
                "[%s] Skip ignored: Player is in 'single track' mode", self.entity_id
            )
            return

        # Check the internal queue
        if self._queue:
            _LOGGER.info("[%s] Playing next item from internal queue", self.entity_id)
            await self._play_next_item_in_queue()

        # Internal queue is empty - delegate to MA
        else:
            _LOGGER.info(
                "[%s] Internal queue empty. Delegating next_track to Music Assistant",
                self.entity_id,
            )
            proxy_entity_id = self._get_mass_proxy_entity_id()
            if not proxy_entity_id:
                _LOGGER.error(
                    "[%s] Cannot skip track: No MA proxy player found", self.entity_id
                )
                # If no proxy is found, set the status to IDLE
                await self._play_next_item_in_queue()  # This sets the status to IDLE
                return

            await self.hass.services.async_call(
                "media_player",
                "media_next_track",
                {"entity_id": proxy_entity_id},
                blocking=True,
            )

    async def async_media_previous_track(self, **kwargs: Any) -> None:
        """Skip to the previous track in history, or delegate to MA if empty."""
        _LOGGER.debug("[%s] Previous track called", self.entity_id)

        # Allow skipping only in "multi" mode
        if self._track_mode == "single":
            _LOGGER.warning(
                "[%s] Previous track ignored: Player is in 'single track' mode",
                self.entity_id,
            )
            return

        # Check the internal history
        if self._history:
            _LOGGER.info(
                "[%s] Playing previous item from internal history", self.entity_id
            )
            # Current title (if available) back to the beginning of the queue
            if self._current_item:
                self._queue.insert(0, self._current_item)

            # Get last title from history and play it
            self._current_item = self._history.pop()
            await self._send_item_to_client(self._current_item)

        # Internal history is empty - delegate to MA
        else:
            _LOGGER.info(
                "[%s] Internal history empty. Delegating previous_track to Music Assistant",
                self.entity_id,
            )
            proxy_entity_id = self._get_mass_proxy_entity_id()
            if not proxy_entity_id:
                _LOGGER.error(
                    "[%s] Cannot skip track: No MA proxy player found", self.entity_id
                )
                return

            await self.hass.services.async_call(
                "media_player",
                "media_previous_track",
                {"entity_id": proxy_entity_id},
                blocking=True,
            )

    async def async_set_volume_level(self, volume: float) -> None:
        """Send a command to the client to set the volume."""
        await self._provider.async_send_json_message(
            self._stream_name,
            {"type": "habitron/set_volume", "payload": {"volume_level": volume}},
        )
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the volume."""
        if mute:
            self._pre_mute_volume = self._attr_volume_level
            await self.async_set_volume_level(0)
        else:
            await self.async_set_volume_level(self._pre_mute_volume or 0.5)

        self._attr_is_volume_muted = mute
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on the media player."""
        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/player_turn_on"}
        )
        if self._attr_state == MediaPlayerState.OFF:
            self._attr_state = MediaPlayerState.IDLE
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn off the media player."""
        _LOGGER.debug("[%s] Turn off command received. Clearing queue", self.entity_id)
        # Clearing internal queue
        self._queue = []
        self._history = []
        self._current_item = None
        self._track_mode = "single"

        await self._provider.async_send_json_message(
            self._stream_name, {"type": "habitron/player_turn_off"}
        )
        self._attr_state = MediaPlayerState.OFF
        self.async_write_ha_state()

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
        image_url = self._attr_media_image_url
        if not image_url:
            return None, None
        return await self._async_fetch_image(image_url)

    @callback
    def update_from_client(
        self, state_str: str, attributes: dict[str, Any] | None = None
    ) -> None:
        """Update the entity's state when a message is received from the client."""

        try:
            new_state = MediaPlayerState(state_str.lower())
        except ValueError:
            # Accept client 'error', but set to 'idle' for HA
            if state_str.lower() == "error":
                _LOGGER.warning(
                    "[%s] Client reported error, setting state to IDLE", self.entity_id
                )
                new_state = MediaPlayerState.IDLE
            else:
                _LOGGER.warning("Received unknown media player state: %s", state_str)
                new_state = MediaPlayerState.IDLE

        # If client reports PLAYING (e.g. after Play/Pause)
        if new_state == MediaPlayerState.PLAYING:
            self._attr_state = MediaPlayerState.PLAYING

        # For all other states
        else:
            self._attr_state = new_state

        # Synchronize attributes from client (volume, mute)
        try:
            if attributes:
                if "volume_level" in attributes:
                    self._attr_volume_level = attributes["volume_level"]
                if "is_volume_muted" in attributes:
                    self._attr_is_volume_muted = attributes["is_volume_muted"]

                # Update metadata only if it comes from the client (ICY)
                if "media_title" in attributes:
                    self._attr_media_title = attributes.get("media_title")
                    self._attr_media_artist = attributes.get("media_artist")
                    self._attr_media_image_url = attributes.get("entity_picture")

        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error updating attributes from client: %s", e)

        self.async_write_ha_state()

    # The TTS and media-source logic is in _process_media_id
    async def process_media_id(self, media_id: str) -> str:
        """Check media_id and convert to url. (Mostly redundant due to _process_media_id)."""
        return await self._process_media_id(media_id)
