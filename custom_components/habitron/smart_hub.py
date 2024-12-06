"""SmartHub class."""

from __future__ import annotations

import contextlib
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
        self.comm = hbtn_com(hass, config)
        self.online: bool = True
        self._mac: str = self.comm.com_mac
        self.uid: str = self._mac.replace(":", "")
        self._version: str = self.comm.com_version
        self._type: str = self.comm.com_hwtype
        self.router: hbtr

        self.host = self.comm.com_ip
        self._port = self.comm.com_port
        if len(self.host) == 0:
            conf_url = None
        else:
            conf_url = f"http://{self.comm.com_ip}:7780/hub"

        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=config.entry_id,
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
        self.sensors: list[IfDescriptor] = []
        self.diags: list[IfDescriptor] = []
        self.loglvl: list[IfDescriptor] = []
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
        info = self.comm.get_smhub_update()
        if info == "":
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

    async def get_version(self) -> str:
        """Test connectivity to SmartHub is OK."""
        resp = await self.comm.get_smhub_version()
        ver_string = resp.decode("iso8859-1")
        if ver_string[0:7] == "SmartIP":
            return ver_string[9 : len(ver_string)]
        return "0.0.0"

    async def async_setup(self) -> None:
        """Initialize SmartHub instance."""
        await self.comm.reinit_hub(100, 0)  # force Opr mode to stop
        await self.comm.send_network_info(self.config.data["websock_token"])
        with contextlib.suppress(Exception):
            # if multiple hub instances or restart
            files_path = Path(__file__).parent / "logos"
            await self.hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        "/habitronfiles/hbt-icons.js",
                        str(files_path / "hbt-icons.js"),
                        False,
                    )
                ]
            )
            add_extra_js_url(self.hass, "/habitronfiles/hbt-icons.js")
        self.router = hbtr(self.hass, self.config, self)
        await self.router.initialize()

        await self.comm.reinit_hub(100, 1)  # restart event server

    async def restart(self, rt_id) -> None:
        """Restart hub."""
        await self.comm.hub_restart(rt_id)

    async def reboot(self) -> None:
        """Reboot hub."""
        await self.comm.hub_reboot()
