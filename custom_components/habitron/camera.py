from __future__ import annotations

import logging
from typing import Any

from aiohttp.hdrs import CONTENT_TYPE
import async_timeout

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    RTCIceCandidateInit,
    WebRTCClientConfiguration,
    async_get_supported_provider,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.network as network_helper

from .const import DOMAIN
from .module import HbtnModule
from .router import HbtnRouter
from .webrtc_provider import async_setup_provider, HabitronWebRTCProvider

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Habitron cameras from a config entry."""
    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router

    # Provider initialisieren, bevor Entitäten erstellt werden
    provider: HabitronWebRTCProvider = await async_setup_provider(hass)

    new_devices = []
    # Get the authentication object and pass it to the camera entity
    auth = hass.auth

    for hbt_module in hbtn_rt.modules:
        if hbt_module.mod_type == "Smart Controller Touch":
            # Pass the auth object and the provider to the camera constructor
            new_devices.append(
                HbtnCam(hass, hbt_module, auth, len(new_devices), provider)
            )

    if new_devices:
        async_add_entities(new_devices)
        _LOGGER.info("Added %d Habitron WebRTC camera(s)", len(new_devices))

    else:
        _LOGGER.info("No Habitron Smart Controller Touch modules found")
        # Call the provider setup, but indicate that no cameras were found


class HbtnCam(Camera):
    """Habitron Camera entity (the phone publishes media; HA just negotiates)."""

    # We now support both streaming and on/off features.
    _attr_supported_features = CameraEntityFeature.STREAM | CameraEntityFeature.ON_OFF
    _attr_frontend_stream_type = "webrtc"
    _attr_is_on = True

    def __init__(
        self,
        hass: HomeAssistant,
        module: HbtnModule,
        auth: Any,
        idx: int,
        provider: HabitronWebRTCProvider,
    ) -> None:
        """Initialize the camera entity."""
        super().__init__()
        self._stream_name = module.name.lower().replace(" ", "_")
        self.idx: int = idx
        self._module: HbtnModule = module
        self._attr_name = f"HbtnCam {idx + 1} ({module.name})"
        self._attr_unique_id = f"Mod_{self._module.uid}_camera"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}
        self.hass = hass
        self._auth = auth
        self._provider = provider

    async def stream_source(self) -> str:
        """Return the source of the stream."""
        return f"habitron://{self._stream_name}"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of camera image."""
        if not self._attr_is_on:
            _LOGGER.info("Camera is off, cannot fetch image.")
            return None

        _LOGGER.debug(
            "Requesting still image from provider for stream: %s", self._stream_name
        )
        try:
            image_data = await self._provider.async_take_snapshot(
                stream_name=self._stream_name
            )
            return image_data
        except Exception as e:
            _LOGGER.error(
                "Failed to get snapshot for camera '%s': %s", self._stream_name, e
            )
            return None

    async def async_turn_on(self) -> None:
        """Turn on the camera."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.info("Camera turned on: %s", self._attr_name)

    async def async_turn_off(self) -> None:
        """Turn off the camera."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.info("Camera turned off: %s", self._attr_name)

    async def async_handle_async_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message,
    ) -> None:
        """Handle the WebRTC offer coming from the HA frontend."""
        if not self._attr_is_on:
            _LOGGER.warning("Attempted to start stream on a camera that is off.")
            raise RuntimeError("Cannot start stream when the camera is off")

        provider = await async_get_supported_provider(self.hass, self)
        if not provider:
            raise RuntimeError("No WebRTC provider available for this camera")

        await provider.async_handle_async_webrtc_offer(
            camera=self,
            offer_sdp=offer_sdp,
            session_id=session_id,
            send_message=send_message,
        )

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Forward frontend ICE candidates to the provider (which relays to phone)."""
        provider = await async_get_supported_provider(self.hass, self)
        if not provider:
            _LOGGER.debug("No provider for candidate; session=%s", session_id)
            return
        await provider.async_on_webrtc_candidate(session_id, candidate)

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """Called by HA when the WS subscription is closed; notify provider."""
        _LOGGER.debug("WebRTC session %s closed by frontend", session_id)

    def async_get_webrtc_client_configuration(self) -> WebRTCClientConfiguration:
        """Optionally provide client ICE config."""
        return WebRTCClientConfiguration()
