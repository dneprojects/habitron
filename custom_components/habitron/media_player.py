"""Media player entity for Habitron integration."""
# custom_components/habitron/media_player.py

import logging
from typing import Any
from urllib import parse

from aiohttp import ClientSession

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .module import HbtnModule
from .router import HbtnRouter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Habitron media player entities."""

    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router
    new_devices = []

    for hbt_module in hbtn_rt.modules:
        if hbt_module.mod_type == "Smart Controller Touch":
            new_devices.append(  # noqa: PERF401
                HbtnMediaPlayer(
                    hass,
                    hbt_module,
                    hbtn_rt.smhub.ws_provider,
                )
            )

    if new_devices:
        async_add_entities(new_devices)
        _LOGGER.info("Added %d Habitron media player(s)", len(new_devices))
    else:
        _LOGGER.info("No Habitron Smart Controller Touch modules found")


class HbtnMediaPlayer(MediaPlayerEntity):
    """Representation of a Habitron client as a media player."""

    _attr_should_poll = False  # State is pushed from the client

    def __init__(
        self,
        hass: HomeAssistant | None,
        module: HbtnModule,
        provider,
    ) -> None:
        """Initialize the media player."""
        self._hass = hass
        self._module: HbtnModule = module
        self._module_name: str = module.name
        self._provider = provider
        self._stream_name: str = module.name.lower().replace(" ", "_")
        self._attr_name = f"Player {module.name}"
        self._attr_unique_id = f"Mod_{self._module.uid}_mediaplayer"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}
        self._attr_state = MediaPlayerState.IDLE
        self._attr_extra_state_attributes = {}
        self._attr_supported_features = (
            MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.VOLUME_SET
        )
        self._internal_auth_token: str | None = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        await super().async_added_to_hass()
        await self.get_token()
        _LOGGER.info("Internal auth token created for %s", self.name)

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
        """Handle HA calling play_media. This is the core logic."""
        _LOGGER.debug("async_play_media called with media_id: %s", media_id)

        if media_id.startswith("media-source://tts/"):
            try:
                parts = media_id.replace("media-source://tts/", "").split("?")
                engine_id = parts[0]
                params = dict(parse.parse_qsl(parts[1]))
                message = params.get("message", "Error: No message found.")

                _LOGGER.info(
                    "Resolving TTS URL via /api/tts_get_url for message: '%s'", message
                )

                # Prepare API call
                session = async_get_clientsession(self.hass)
                url = f"{self.hass.config.internal_url}/api/tts_get_url"
                payload = {"engine_id": engine_id, "message": message}

                resolved_url = await self._async_resolve_tts_url(session, url, payload)

                if resolved_url == 401:
                    _LOGGER.warning(
                        "Token expired or invalid. Getting new token and retrying"
                    )
                    await self.get_token()
                    resolved_url = await self._async_resolve_tts_url(
                        session, url, payload
                    )

                if isinstance(resolved_url, str):
                    full_url = f"{self.hass.config.internal_url}{resolved_url}"
                    await self._provider.async_send_media_command(
                        self._stream_name, "play_media", media_content_id=full_url
                    )
                elif resolved_url is not None:
                    _LOGGER.error(
                        "Failed to resolve TTS URL. Final status was: %s", resolved_url
                    )
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Error while processing TTS request in play_media: %s", e)

        else:
            _LOGGER.info("Forwarding resolved URL to client: %s", media_id)
            await self._provider.async_send_media_command(
                self._stream_name,
                "play_media",
                media_content_id=media_id,
            )

    async def async_media_play(self) -> None:
        """Send a command to the client to resume playback."""
        await self._provider.async_send_media_command(self._stream_name, "play")

    async def async_media_pause(self) -> None:
        """Send a command to the client to pause playback."""
        await self._provider.async_send_media_command(self._stream_name, "pause")

    async def async_media_stop(self) -> None:
        """Send a command to the client to stop media."""
        await self._provider.async_send_media_command(self._stream_name, "stop")

    async def async_set_volume_level(self, volume: float) -> None:
        """Send a command to the client to set the volume."""
        await self._provider.async_send_media_command(
            self._stream_name, "set_volume", volume_level=volume
        )

    @callback
    def update_from_client(
        self, state: str, attributes: dict[str, Any] | None = None
    ) -> None:
        """Update the entity's state when a message is received from the client."""
        try:
            # Convert string state to MediaPlayerState enum
            self._attr_state = MediaPlayerState(state.lower())
        except ValueError:
            _LOGGER.warning("Received unknown media player state: %s", state)
            self._attr_state = MediaPlayerState.IDLE

        if attributes:
            self._attr_extra_state_attributes.update(attributes)

        self.async_write_ha_state()
