"""SmartIP class."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .communicate import HbtnComm as hbtn_com

# In a real implementation, this would be in an external library that's on PyPI.
# The PyPI package needs to be included in the `requirements` section of manifest.json
# See https://developers.home-assistant.io/docs/creating_integration_manifest
# for more information.
# This dummy smip always returns 3 rollers.
from .const import DOMAIN
from .router import HbtnRouter as hbtr


class SmartIP:
    """Habitron SmartIP class."""

    manufacturer = "Habitron GmbH"

    def __init__(self, hass: HomeAssistant, config: ConfigEntry) -> None:
        """Init Smart IP."""
        self.uid = 0
        self._hass = hass
        self.config: config
        self._name = "SmartIP"
        self.comm = hbtn_com(hass, config)
        self.online = True
        self._mac = self.comm.com_mac
        self._version = self.comm.com_version
        self._type = self.comm.com_hwtype
        self.router = []

        self._host = self.comm.com_ip
        self._port = self.comm.com_port

        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=config.entry_id,
            connections={(dr.CONNECTION_NETWORK_MAC, self._mac)},
            identifiers={(DOMAIN, self.uid)},
            manufacturer="Habitron GmbH",
            suggested_area="House",
            name=self._name,
            model=self._name,
            sw_version=self._version,
            hw_version=self._type,
        )

    @property
    def smip_version(self) -> str:
        """Version for SmartIP."""
        return self._version

    async def get_version(self) -> str:
        """Test connectivity to SmartIP is OK."""
        resp = await self.comm.get_smip_version()
        ver_string = resp.decode("iso8859-1")
        if ver_string[0:7] == "SmartIP":
            return ver_string[9 : len(ver_string)]
        return "0.0.0"

    async def initialize(self, hass: HomeAssistant, config: ConfigEntry) -> bool:
        """Initialization of SmartIP instance."""
        self._version = await self.get_version()
        # self._mac = self.comm.get_mac()
        self.router = hbtr(hass, config, self.comm)
        await self.router.initialize()
