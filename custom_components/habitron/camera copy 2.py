"""Habitron Camera with WebRTC support."""

import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.core import HomeAssistant

from .webrtc_provider import async_setup_provider

_LOGGER = logging.getLogger(__name__)


class HbtnCam(Camera):
    """Habitron Camera entity."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_frontend_stream_type = "webrtc"

    def __init__(self, module, coordinator, index: int) -> None:
        """Initialize the Habitron camera entity."""
        super().__init__()
        self._module = module
        self._coordinator = coordinator
        self._attr_name = f"Habitron Cam {index + 1}"
        self._attr_unique_id = f"habitron_cam_{index + 1}"
        self._index = index

    async def stream_source(self) -> str | None:
        """Return the source for the camera stream.

        This is mapped to a go2rtc stream name via habitron:// scheme.
        """
        # Hier dein Mapping (z.B. Modul-ID → Stream-Name)
        if not self._module:
            return None

        # z.B. habitron://cam1 (muss in go2rtc.yaml als Stream definiert sein)
        return f"habitron://{self._module.uid}"

    async def async_added_to_hass(self) -> None:
        """Handle entity added to hass."""
        await super().async_added_to_hass()
        _LOGGER.debug("Habitron camera %s added", self._attr_unique_id)


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Set up Habitron cameras from config entry."""

    # Provider registrieren (nur einmal)
    await async_setup_provider(hass)

    coordinator = hass.data["habitron"][entry.entry_id]["coordinator"]
    modules = hass.data["habitron"][entry.entry_id]["modules"]

    cams = []
    for idx, mod in enumerate(modules):
        if mod.mod_type == "Smart Controller Touch":
            cams.append(HbtnCam(mod, coordinator, idx))

    if cams:
        async_add_entities(cams)
