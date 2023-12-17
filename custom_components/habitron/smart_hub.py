"""SmartHub class."""
from __future__ import annotations

from enum import Enum

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .communicate import HbtnComm as hbtn_com
from .const import DOMAIN
from .interfaces import IfDescriptor
from .router import HbtnRouter as hbtr


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
        self._hass = hass
        self.config: config
        self._name = config.title
        self.comm = hbtn_com(hass, config)
        self.online = True
        self._mac = self.comm.com_mac
        self.uid = self._mac.replace(":", "")
        self._version = self.comm.com_version
        self._type = self.comm.com_hwtype
        self.router = []

        self._host = self.comm.com_ip
        self._port = self.comm.com_port

        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=config.entry_id,
            configuration_url=f"http://{self.comm.com_ip}:7780/hub",
            connections={(dr.CONNECTION_NETWORK_MAC, self._mac)},
            identifiers={(DOMAIN, self.uid)},
            manufacturer="Habitron GmbH",
            suggested_area="House",
            name=self._name,
            model=self._name,
            sw_version=self._version,
            hw_version=self._type,
        )
        self.sensors: list[IfDescriptor] = []
        self.diags: IfDescriptor = []
        self.loglvl: IfDescriptor = []
        if self._type[:12] == "Raspberry Pi":
            self.diags.append(IfDescriptor("CPU Frequency", 0, 10, 0))
            self.diags.append(IfDescriptor("CPU load", 1, 10, 0))
            self.diags.append(IfDescriptor("CPU Temperature", 2, 10, 0))
            self.sensors.append(IfDescriptor("Memory free", 0, 2, 0))
            self.sensors.append(IfDescriptor("Disk free", 1, 2, 0))
            self.loglvl.append(IfDescriptor("Logging level console", 0, 2, 0))
            self.loglvl.append(IfDescriptor("Logging level file", 1, 2, 0))
            self.update()

    @property
    def smhub_version(self) -> str:
        """Version for SmartHub."""
        return self._version

    def update(self) -> None:
        """Update in a module specific method. Reads and parses status."""
        if self.comm.com_hwtype == "E-5":
            return
        info = self.comm.get_smhub_info()
        if info == "":
            return
        if self._type[:12] == "Raspberry Pi":
            self.diags[0].value = float(
                info["hardware"]["cpu"]["frequency current"].replace("MHz", "")
            )
            self.diags[1].value = float(
                info["hardware"]["cpu"]["load"].replace("%", "")
            )
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

    async def get_version(self) -> str:
        """Test connectivity to SmartHub is OK."""
        resp = await self.comm.get_smhub_version()
        ver_string = resp.decode("iso8859-1")
        if ver_string[0:7] == "SmartIP":
            return ver_string[9 : len(ver_string)]
        return "0.0.0"

    async def initialize(self, hass: HomeAssistant, config: ConfigEntry) -> bool:
        """Initialize SmartHub instance."""
        await self.comm.send_network_info(config.data["websock_token"])
        await self.comm.async_stop_mirror(1)
        self.router = hbtr(hass, config, self)
        await self.router.initialize()

    async def restart(self, rt_id):
        """Restart hub."""
        await self.comm.hub_restart(rt_id)

    async def reboot(self):
        """Reboot hub."""
        await self.comm.hub_reboot()
