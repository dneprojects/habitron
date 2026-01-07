"""SmartHub class."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .communicate import HbtnComm as hbtn_com
from .const import DOMAIN
from .interfaces import IfDescriptor
from .router import HbtnRouter as hbtr
from .ws_provider import HabitronWebRTCProvider


class LoggingLevels(Enum):
    """Definition of logging levels for selector."""

    notset = 0
    debug = 1
    info = 2
    warning = 3
    error = 4
    critical = 5


class SmartHub:
    """Habitron SmartHub class."""

    manufacturer = "Habitron GmbH"

    def __init__(self, hass: HomeAssistant, config: ConfigEntry) -> None:
        """Init SmartHub."""

        self.hass: HomeAssistant = hass
        self.config: ConfigEntry = config
        self._name: str = config.title
        self.comm = hbtn_com(hass, config, self)

        # Temporary placeholders until async_setup runs
        self._mac = "00:00:00:00:00:00"
        self.uid = "pending"
        self._version = "0.0.0"
        self._type = "Unknown"

        self.online: bool = True
        self.router = hbtr(self.hass, self.config, self)
        self.addon_slug: str = ""
        self.base_url: str = ""
        self.host = self.comm.com_ip
        self._port = self.comm.com_port
        conf_url = ""

        self.sensors: list[IfDescriptor] = []
        self.diags: list[IfDescriptor] = []
        self.loglvl: list[IfDescriptor] = []
        self.ws_provider: HabitronWebRTCProvider | None = None

    @property
    def smhub_version(self) -> str:
        """Version for SmartHub."""
        return self._version

    async def async_setup(self) -> None:
        """Initialize SmartHub instance and register device."""

        # 1. Fetch info from Hub (Offload blocking socket to executor)
        # This populates self.comm.info
        await self.hass.async_add_executor_job(self.comm.get_smhub_info)

        # 2. Update local variables with real data
        self._mac = self.comm.com_mac
        self.uid = self._mac.replace(":", "")
        self._version = self.comm.com_version
        self._type = self.comm.com_hwtype
        self.host = self.comm.com_ip
        self.addon_slug = self.comm.slugname
        self.router.b_uid = self.uid

        if self.comm.is_addon:
            self.base_url: str = (
                f"http://{self.host}:8123/{self.addon_slug}/ingress?index="
            )
        else:
            self.base_url: str = f"http://{self.host}:7780"

        conf_url = f"{self.base_url}/hub" if self.host else None

        # 3. Register device in HA with MAC and UID, iconset
        device_registry = dr.async_get(self.hass)
        device_registry.async_get_or_create(
            config_entry_id=self.config.entry_id,
            configuration_url=conf_url,
            connections={(dr.CONNECTION_NETWORK_MAC, self._mac)},
            identifiers={(DOMAIN, self.uid)},
            manufacturer="Habitron GmbH",
            suggested_area="House",
            name=self._name,
            model=self._name,
            sw_version=self._version,
            hw_version=self._type,
        )

        # Habitron iconset
        files_path = Path(__file__).parent / "logos"
        path_config = StaticPathConfig(
            "/habitronfiles/hbt-icons.js",
            str(files_path / "hbt-icons.js"),
            False,
        )
        try:
            await self.hass.http.async_register_static_paths(
                [path_config],
            )
            add_extra_js_url(self.hass, "/habitronfiles/hbt-icons.js")
        except Exception:  # noqa: BLE001
            # install only once
            pass

        # 4. Initialize Diagnostics (Logic depends on self._type)
        if self._type[:12] == "Raspberry Pi":
            self.diags.append(IfDescriptor("CPU Frequency", 0, 10, 0))
            self.diags.append(IfDescriptor("CPU load", 1, 10, 0))
            self.diags.append(IfDescriptor("CPU Temperature", 2, 10, 0))
            self.sensors.append(IfDescriptor("Memory free", 0, 2, 0))
            self.sensors.append(IfDescriptor("Disk free", 1, 2, 0))
            self.loglvl.append(IfDescriptor("Logging level console", 0, 2, 0))
            self.loglvl.append(IfDescriptor("Logging level file", 1, 2, 0))

        # 5. Rest of setup
        await self.comm.reinit_hub(100, 0)
        await self.comm.send_network_info(self.config.data["websock_token"])
        await self.router.initialize()
        await self.comm.reinit_hub(100, 1)

        # 6. First data update
        await self.hass.async_add_executor_job(self.update)

    def update(self) -> None:
        """Update in a module specific method. Reads and parses status."""
        info = self.comm.get_smhub_update()
        if not info or not self.diags:
            return
        self.diags[0].value = float(
            info["hardware"]["cpu"]["frequency current"].replace("MHz", "")
        )
        self.diags[1].value = float(info["hardware"]["cpu"]["load"].replace("%", ""))
        self.diags[2].value = float(
            info["hardware"]["cpu"]["temperature"].replace("°C", "")
        )
        self.sensors[0].value = float(
            info["hardware"]["memory"]["percent"].replace("%", "")
        )
        self.sensors[1].value = float(
            info["hardware"]["disk"]["percent"].replace("%", "")
        )
        self.loglvl[0].value = int(info["software"]["loglevel"]["console"])
        self.loglvl[1].value = int(info["software"]["loglevel"]["file"])

    async def async_update(self) -> None:
        """Async wrapper for the update method."""
        # This offloads the blocking 'update' call to a thread pool
        await self.hass.async_add_executor_job(self.update)

    async def get_version(self) -> str:
        """Test connectivity to SmartHub is OK."""
        resp = await self.comm.get_smhub_version()
        ver_string = resp.decode("iso8859-1")
        return ver_string[9:] if ver_string.startswith("SmartIP") else "0.0.0"

    async def restart(self, rt_id) -> None:
        """Restart hub."""
        await self.comm.hub_restart(rt_id)

    async def reboot(self) -> None:
        """Reboot hub."""
        await self.comm.hub_reboot()
