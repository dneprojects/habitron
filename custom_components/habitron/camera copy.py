"""Platform for camera integration."""

import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.camera.const import StreamType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .module import HbtnModule
from .router import HbtnRouter
from .utils import ensure_webrtc_streams, normalize_module_name, reload_go2rtc

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add climate units for passed config_entry in HA."""
    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router
    # collect all module names that require WebRTC streams
    modules = [
        m.name for m in hbtn_rt.modules if m.mod_type == "Smart Controller Touch"
    ]
    # ensure go2rtc.yaml has all required streams
    changed = await ensure_webrtc_streams(hass, modules, hbtn_rt.modules[0].comm.com_ip)
    if changed:
        # host could come from entry.data or first module
        host = hbtn_rt.modules[0].comm.com_ip
        await reload_go2rtc(hass, host)

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        if hbt_module.mod_type == "Smart Controller Touch":
            new_devices.append(HbtnCam(hbt_module, len(new_devices)))
    if new_devices:
        async_add_entities(new_devices)


class HbtnCam(Camera):
    """Camera entity for the Habitron WebRTC stream."""

    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        module: HbtnModule,
        idx: int,
    ) -> None:
        """Initialize the camera."""
        super().__init__()
        self._host = "127.0.0.1"  # module.comm.com_ip
        self._stream = normalize_module_name(module.name)
        self.idx: int = idx
        self._module: HbtnModule = module
        self._attr_name = f"HbtnCam {idx + 1} ({module.name})"
        self._attr_unique_id = f"Mod_{self._module.uid}_camera"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str | None:
        """Return the display name of this camera."""
        return self._attr_name

    async def stream_source(self) -> str | None:
        """Return RTSP stream from go2rtc relay."""
        # go2rtc RTSP relay (always on port 8554 inside HA)
        return f"rtsp://{self._host}:8554/{self._stream}"

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        """Return a still image from go2rtc if available, otherwise None."""
        session = async_get_clientsession(self.hass)
        url = f"http://{self._host}:1984/api/frame.jpeg?src={self._stream}"

        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.read()
                _LOGGER.warning(
                    "Could not fetch snapshot for %s, status=%s",
                    self._attr_name,
                    resp.status,
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Error fetching snapshot for %s: %s", self._attr_name, err)

        return None
