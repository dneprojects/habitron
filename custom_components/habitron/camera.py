"""Habitron Camera entity wired to the direct WebRTC provider (phone as camera)."""

from __future__ import annotations

import logging

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    RTCIceCandidateInit,
    WebRTCClientConfiguration,
    async_get_supported_provider,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .module import HbtnModule
from .router import HbtnRouter
from .webrtc_provider import async_setup_provider

_LOGGER = logging.getLogger(__name__)


class HbtnCam(Camera):
    """Habitron Camera entity (the phone publishes media; HA just negotiates)."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_frontend_stream_type = "webrtc"

    def __init__(self, hass: HomeAssistant, module: HbtnModule, idx: int) -> None:
        """Initialize the camera entity."""
        super().__init__()
        self._stream_name = module.name.lower().replace(" ", "_")
        self.idx: int = idx
        self._module: HbtnModule = module
        self._attr_name = f"HbtnCam {idx + 1} ({module.name})"
        self._attr_unique_id = f"Mod_{self._module.uid}_camera"
        self.hass = hass

    async def stream_source(self) -> str | None:
        """Return a logical stream identifier understood by the provider."""
        return f"habitron://{self._stream_name}"

    async def async_handle_async_webrtc_offer(
        self,
        offer_sdp: str,
        session_id: str,
        send_message,
    ) -> None:
        """Handle the WebRTC offer coming from the HA frontend."""
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
        # This part is optional, but it's a good practice to let the provider know
        # if a session is closed, so it can clean up its internal state.
        _LOGGER.debug("WebRTC session %s closed by frontend", session_id)
        # You can add a method to your provider for cleanup if needed.

    def async_get_webrtc_client_configuration(self) -> WebRTCClientConfiguration:
        """Optionally provide client ICE config."""
        return WebRTCClientConfiguration()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a placeholder image for badges etc."""
        try:
            return (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\x0bIDAT\x08\xd7c``\x00\x00\x00\x02\x00\x01"
                b"\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
            )
        except Exception:  # noqa: BLE001
            return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Habitron cameras from a config entry."""
    await async_setup_provider(hass)

    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        if hbt_module.mod_type == "Smart Controller Touch":
            new_devices.append(HbtnCam(hass, hbt_module, len(new_devices)))

    if new_devices:
        async_add_entities(new_devices)
        _LOGGER.info("Added %d Habitron WebRTC camera(s)", len(new_devices))
    else:
        _LOGGER.info("No Habitron Smart Controller Touch modules found")
