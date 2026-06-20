"""SmartHub class — the integration's thin binding to the habitron_client model."""

from enum import Enum
from pathlib import Path

from habitron_client import (
    Diagnostic,
    Router,
    Sensor,
    SmartController,
    async_build_system,
)

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.util import slugify

from .communicate import HbtnComm as hbtn_com
from .const import DOMAIN
from .coordinator import HbtnCoordinator
from .ws_provider import HabitronWebRTCProvider


class LoggingLevels(Enum):
    """Definition of logging levels for selector."""

    notset = 0
    debug = 1
    info = 2
    warning = 3
    error = 4
    critical = 5


def _area_name(router: Router, area_no: int) -> str:
    """Return the bus area name for ``area_no`` (or ``House``)."""
    for area in router.areas:
        if area.nmbr == area_no:
            return area.name
    return "House"


class SmartHub:
    """Habitron SmartHub: connects, builds the device model, owns the coordinator."""

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
        # Empty model until async_setup builds it from the bus.
        self.router: Router = Router()
        self.coordinator: HbtnCoordinator = HbtnCoordinator(hass, config, self.comm)
        self.addon_slug: str = ""
        self.base_url: str = ""
        self.host = self.comm.com_ip
        self._port = self.comm.com_port

        # Hub-level (SmartHub host) diagnostics — separate from the bus model.
        self.sensors: list[Sensor] = []
        self.diags: list[Diagnostic] = []
        self.loglvl: list[Sensor] = []
        self.ws_provider: HabitronWebRTCProvider | None = None

    @property
    def smhub_version(self) -> str:
        """Version for SmartHub."""
        return self._version

    async def async_setup(self) -> None:
        """Connect, register the hub device and build the bus model."""
        # 1. Open the client connection and fetch hub info (mac/version/host).
        await self.comm.async_setup()
        await self.comm.get_smhub_info()

        self._mac = self.comm.com_mac
        self.uid = self._mac.replace(":", "")
        self._version = self.comm.com_version
        self._type = self.comm.com_hwtype
        self.host = self.comm.com_ip
        self.addon_slug = self.comm.slugname

        if self.comm.is_addon:
            self.base_url = f"http://{self.host}:8123/{self.addon_slug}/ingress?index="
        else:
            self.base_url = f"http://{self.host}:7780"
        conf_url = f"{self.base_url}/hub" if self.host else None

        # 2. Register the hub device.
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
        self._register_iconset()

        # 3. Hub diagnostics (depends on the platform type).
        if self._type[:12] == "Raspberry Pi":
            self.diags = [
                Diagnostic(name="CPU Frequency", nmbr=0, type=10),
                Diagnostic(name="CPU load", nmbr=1, type=10),
                Diagnostic(name="CPU Temperature", nmbr=2, type=10),
            ]
            self.sensors = [
                Sensor(name="Memory free", nmbr=0, type=2, value=0),
                Sensor(name="Disk free", nmbr=1, type=2, value=0),
            ]
            self.loglvl = [
                Sensor(name="Logging level console", nmbr=0, type=2, value=0),
                Sensor(name="Logging level file", nmbr=1, type=2, value=0),
            ]

        # 4. Build the bus model (router + modules), register their devices.
        await self.comm.reinit_hub(0)
        await self.comm.send_network_info(self.config.data["websock_token"])
        self.router = await async_build_system(self.comm.client, b_uid=self.uid)
        self.comm.set_router(self.router)
        # Seed the WebRTC stream name for Touch modules (used by camera /
        # media_player / assist / voice button to address the Flutter client).
        for module in self.router.modules:
            if isinstance(module, SmartController):
                raddr = module.addr - self.router.id
                module.stream_name = f"{slugify(module.name)}_{raddr}"
        await self._register_bus_devices()
        await self.comm.reinit_hub(1)

        # 5. First hub-diagnostics update.
        await self.update()

    def _register_iconset(self) -> None:
        """Register the Habitron frontend iconset (HACS only, best effort)."""
        files_path = Path(__file__).parent / "logos"
        path_config = StaticPathConfig(
            "/habitronfiles/hbt-icons.js",
            str(files_path / "hbt-icons.js"),
            False,
        )
        try:
            self.hass.async_create_task(
                self.hass.http.async_register_static_paths([path_config])
            )
            add_extra_js_url(self.hass, "/habitronfiles/hbt-icons.js")
        except Exception:  # noqa: BLE001
            # Per-process registration; the second call on reload raises but the
            # path stays wired from the first. Swallow and continue.
            pass

    async def _register_bus_devices(self) -> None:
        """Register the router + module devices and push their registry ids."""
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        router = self.router

        dev_reg.async_get_or_create(
            config_entry_id=self.config.entry_id,
            configuration_url=f"{self.base_url}/router" if self.host else None,
            identifiers={(DOMAIN, router.uid)},
            manufacturer="Habitron GmbH",
            name=router.name,
            model="Smart Router",
            sw_version=router.version,
            hw_version=router.serial,
            via_device=(DOMAIN, self.uid),
        )
        rt_dev = dev_reg.async_get_device(identifiers={(DOMAIN, router.uid)})
        if rt_dev is not None:
            await self.comm.send_devregid(0, rt_dev.id)

        for module in router.modules:
            raddr = module.addr - router.id
            area_name = _area_name(router, module.area)
            dev_reg.async_get_or_create(
                config_entry_id=self.config.entry_id,
                configuration_url=(
                    f"{self.base_url}/module-{raddr}" if self.host else None
                ),
                identifiers={(DOMAIN, module.uid)},
                manufacturer="Habitron GmbH",
                suggested_area=area_name,
                name=module.name,
                model=module.mod_type,
                sw_version=module.sw_version,
                hw_version=module.hw_version,
                via_device=(DOMAIN, router.uid),
            )
            dev = dev_reg.async_get_device(identifiers={(DOMAIN, module.uid)})
            area = area_reg.async_get_or_create(area_name)
            if dev is not None:
                await self.comm.send_devregid(raddr, dev.id)
                dev_reg.async_update_device(dev.id, area_id=area.id)

    async def update(self) -> None:
        """Refresh the hub-level diagnostics from the SmartHub info query."""
        info = await self.comm.get_smhub_update()
        if not info or not self.diags:
            return
        hardware = info["hardware"]
        software = info["software"]
        self._set(
            self.diags[0], float(hardware["cpu"]["frequency current"].rstrip("MHz"))
        )
        self._set(self.diags[1], float(hardware["cpu"]["load"].rstrip("%")))
        self._set(self.diags[2], float(hardware["cpu"]["temperature"].rstrip("°C")))
        self._set(self.sensors[0], float(hardware["memory"]["percent"].rstrip("%")))
        self._set(self.sensors[1], float(hardware["disk"]["percent"].rstrip("%")))
        self._set(self.loglvl[0], int(software["loglevel"]["console"]))
        self._set(self.loglvl[1], int(software["loglevel"]["file"]))

    @staticmethod
    def _set(member: Diagnostic | Sensor, value: float) -> None:
        """Set a hub member's value and notify listeners on a change."""
        if member.value != value:
            member.value = value
            member.notify()

    async def async_update(self) -> None:
        """Async wrapper retained for callers expecting the old API."""
        await self.update()

    async def async_close(self) -> None:
        """Close the underlying client connection on entry unload."""
        await self.comm.async_close()

    async def get_version(self) -> str:
        """Test connectivity to SmartHub is OK."""
        resp = await self.comm.get_smhub_version()
        ver_string = resp.decode("iso8859-1")
        return ver_string[9:] if ver_string.startswith("SmartIP") else "0.0.0"

    async def restart(self, rt_id: int) -> None:
        """Restart hub.

        ``rt_id`` is accepted for forward compatibility with multi-router
        setups but is unused today — the bus protocol exposes a single
        ``hub_restart`` command without a target selector.
        """
        del rt_id
        await self.comm.hub_restart()

    async def reboot(self) -> None:
        """Reboot hub."""
        await self.comm.hub_reboot()
