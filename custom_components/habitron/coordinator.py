"""Habitron integration using DataUpdateCoordinator."""

import asyncio
from datetime import timedelta
from enum import Enum
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

from habitron_client import (
    Diagnostic,
    HabitronError,
    HabitronTimeoutError,
    Module,
    Router,
    Sensor,
    SmartController,
    SmartHub,
    async_build_hub,
    async_build_system,
    async_refresh_hub,
)

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from .communicate import HbtnComm
from .const import DOMAIN, KEY_TOKEN, SCAN_INTERVAL

if TYPE_CHECKING:
    from .ws_provider import HabitronWebRTCProvider

# Firmware is quasi-static and the bus read is comparatively slow, so it is
# polled round-robin (one module per tick) on a slow, separate coordinator.
FW_POLL_INTERVAL = timedelta(seconds=60)

type HabitronConfigEntry = ConfigEntry["HbtnCoordinator"]
"""Typed config entry alias. ``entry.runtime_data`` holds the HbtnCoordinator,
which owns the connection, the hub and the bus model.
"""

_LOGGER = logging.getLogger(__name__)

MANUFACTURER = "Habitron GmbH"

# Port the standalone hub serves its own web UI on.
_WEB_PORT = 7780


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


class HbtnCoordinator(DataUpdateCoordinator[int]):
    """Habitron data update coordinator.

    Owns the connection and the whole model: the ``SmartHub`` (the hub's own
    data and host readings) and the ``Router`` (everything behind it).

    ``async_system_update`` writes the bus status directly into the
    module/input/output objects, and the entities read from those object
    attributes via their ``_handle_coordinator_update`` callbacks. The
    coordinator acts as a heartbeat that fans out update events.

    It returns the compact-status CRC, which serves as the change-detection
    key. With ``always_update=False`` the coordinator only fans out to the
    entities when the bus status actually changed between ticks, avoiding a
    needless write of every entity on every tick.
    """

    manufacturer = MANUFACTURER

    def __init__(self, hass: HomeAssistant, entry: HabitronConfigEntry) -> None:
        """Initialize Habitron update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Habitron updates",
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self.entry = entry
        self.config = entry
        self.comm = HbtnComm(hass, entry, self)

        # Empty models until ``async_setup`` builds them from the bus, so
        # nothing has to guard against ``None``.
        self.hub = SmartHub()
        self.router = Router()

        self.online: bool = True
        self.base_url: str = ""
        self.host = self.comm.com_ip
        self._port = self.comm.com_port
        self.ws_provider: HabitronWebRTCProvider | None = None

        self.rtr_id = 1
        self.previous_devices: set[str] = set()

    @property
    def uid(self) -> str:
        """The identity every device and entity of this entry is keyed by.

        Kept on the hub model rather than beside it: the hub's own entities
        read their device identifier off that same object, so a second copy
        here could disagree with the one they use.
        """
        return self.hub.uid

    @property
    def addon_slug(self) -> str:
        """Ingress slug of the hub's add-on, empty when it is not one."""
        return self.hub.slug

    @property
    def smhub_version(self) -> str:
        """Version for SmartHub."""
        return self.hub.version

    @property
    def smhub_type(self) -> str:
        """Hardware platform type of the SmartHub."""
        return self.hub.platform

    @property
    def smhub_name(self) -> str:
        """Configured name of the SmartHub (the config entry title)."""
        return self.entry.title

    @property
    def sensors(self) -> list[Sensor]:
        """Hub host readings exposed as percentages."""
        return self.hub.sensors

    @property
    def diags(self) -> list[Diagnostic]:
        """Hub host diagnostics (CPU frequency, load, temperature)."""
        return self.hub.diags

    @property
    def loglvl(self) -> list[Sensor]:
        """Hub logging levels (console, file)."""
        return self.hub.loglevels

    @property
    def host_diags_valid(self) -> bool:
        """Whether a host poll has ever succeeded.

        The readings start at their dataclass defaults, and ``0`` is a
        plausible CPU load rather than an obvious placeholder, so the entities
        must report ``unknown`` until this turns true.
        """
        return self.hub.host_valid

    def _conf_url(self, path: str) -> str | None:
        """Return the link to ``path`` in the hub's own web UI.

        An add-on hub is reached through Home Assistant, so the link is stored
        with the ``homeassistant://`` scheme: the frontend rewrites that to a
        plain ``/`` against whatever base the viewer is currently on. One
        stored value then works on the LAN and through a remote (Nabu Casa)
        URL alike -- a hard-coded ``http://<hub ip>:8123`` only ever matches
        the first, and breaks under HTTPS, a reverse proxy or a changed port.
        The page inside the app travels as the ``index`` query, encoded.

        A standalone hub serves its own UI, so that one keeps an absolute URL.
        """
        if not self.host:
            return None
        if self.comm.is_addon:
            # ``safe=""``: the default leaves "/" alone, and the page is a
            # query *value* -- the app's own links carry it encoded.
            return f"{self.base_url}?index={quote(path, safe='')}"
        return f"{self.base_url}{path}"

    async def async_setup(self) -> None:
        """Connect, register the hub device and build the bus model."""
        # 1. Open the client connection and fetch hub info (mac/version/host).
        await self.comm.async_setup()
        await self.comm.get_smhub_info()
        self.hub = await async_build_hub(self.comm.client)
        self._resolve_uid()
        self.host = self.comm.com_ip

        if self.comm.is_addon:
            self.base_url = f"homeassistant://{self.addon_slug}/ingress"
        else:
            self.base_url = f"http://{self.host}:{_WEB_PORT}"

        # 2. Register the hub device.
        dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            configuration_url=self._conf_url("/hub"),
            connections={(dr.CONNECTION_NETWORK_MAC, self.comm.com_mac)},
            identifiers={(DOMAIN, self.uid)},
            manufacturer=MANUFACTURER,
            suggested_area="House",
            name=self.smhub_name,
            model=self.smhub_name,
            sw_version=self.smhub_version,
            hw_version=self.smhub_type,
        )
        await self._register_iconset()

        # 3. Build the bus model (router + modules), register their devices.
        await self.comm.reinit_hub(0)
        # ``.get``, not a subscript: an entry created by the core integration
        # carries no token -- it does not offer the field yet -- and would
        # otherwise raise here the moment someone switches over. Empty is the
        # right default anyway; only a hub on its own machine needs a token,
        # one sharing the machine with Home Assistant uses the supervisor's.
        await self.comm.send_network_info(self.entry.data.get(KEY_TOKEN, ""))
        self.router = await async_build_system(self.comm.client, b_uid=self.uid)
        self.comm.set_router(self.router)
        # Seed the WebRTC stream name for Touch modules (used by camera /
        # media_player / assist / voice button to address the Flutter client).
        for module in self.router.modules:
            if isinstance(module, SmartController):
                module.stream_name = f"{slugify(module.name)}_{module.addr}"
        await self._register_bus_devices()
        await self.comm.reinit_hub(1)

        # 4. First hub host-readings update.
        await self.update()

    def _resolve_uid(self) -> None:
        """Settle the identity every device and entity of this entry is keyed by.

        The hub derives its own from its LAN address; this adds only what the
        library cannot know -- the fallback for a hub that reports no usable
        address. Carrying an empty uid on would give every device of every such
        installation the same blank identifier.
        """
        if self.hub.uid:
            return
        self.hub.uid = self.entry.unique_id or self.entry.entry_id
        _LOGGER.debug("Hub reported no usable MAC; using %s as uid", self.hub.uid)

    async def _register_iconset(self) -> None:
        """Register the Habitron frontend iconset (HACS only, best effort)."""
        files_path = Path(__file__).parent / "logos"
        path_config = StaticPathConfig(
            "/habitronfiles/hbt-icons.js",
            str(files_path / "hbt-icons.js"),
            False,
        )
        try:
            await self.hass.http.async_register_static_paths([path_config])
            add_extra_js_url(self.hass, "/habitronfiles/hbt-icons.js")
        except RuntimeError:
            # Static paths are registered per process: a second setup of this
            # entry (a retry after ConfigEntryNotReady, or a reload) re-adds the
            # same GET route and raises. The path stays wired from the first
            # registration, so this is safe to ignore. Awaiting (rather than
            # firing a background task) keeps the error catchable instead of
            # surfacing as an un-retrieved task exception.
            pass

    async def _register_bus_devices(self) -> None:
        """Register the router + module devices and push their registry ids."""
        dev_reg = dr.async_get(self.hass)
        router = self.router
        # ``via_device_id`` wants the parent's registry id, so the hub device
        # (registered in async_setup) has to be looked up once here. Scoped to
        # our own entry: identifiers are only unique within a config entry.
        hub_dev = dev_reg.async_get_device_by_identifier(
            (DOMAIN, self.uid), self.entry.entry_id
        )

        rt_dev = dev_reg.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            configuration_url=self._conf_url("/router"),
            identifiers={(DOMAIN, router.uid)},
            manufacturer=MANUFACTURER,
            name=router.name,
            model="Smart Router",
            sw_version=router.version,
            hw_version=router.serial,
            via_device_id=hub_dev.id if hub_dev else None,
        )
        await self.comm.send_devregid(0, rt_dev.id)

        for module in router.modules:
            # The bus area is only ever *suggested*, never written: HA applies
            # ``suggested_area`` when it first creates the device and ignores it
            # afterwards, so a user's own area assignment survives every reload.
            # Do not "fix this up" with async_update_device(area_id=...) -- that
            # re-applied the bus area on every setup and silently reassigned all
            # modules whenever the router's area list came back empty or changed
            # (``_area_name`` then falls back to "House" for every module).
            area_name = _area_name(router, module.area)
            dev = dev_reg.async_get_or_create(
                config_entry_id=self.entry.entry_id,
                configuration_url=self._conf_url(f"/module-{module.addr}"),
                identifiers={(DOMAIN, module.uid)},
                manufacturer=MANUFACTURER,
                suggested_area=area_name,
                name=module.name,
                model=module.mod_type,
                sw_version=module.sw_version,
                hw_version=module.hw_version,
                via_device_id=rt_dev.id,
            )
            await self.comm.send_devregid(module.addr, dev.id)

    async def update(self) -> None:
        """Refresh the hub's own host readings.

        These are non-essential (CPU/memory/disk/log levels) and decoupled from
        the bus status: a transient bad or dropped response must not fail the
        coordinator tick, which would mark *every* entity unavailable, or abort
        entry setup. Swallow the library's protocol/connection errors and keep
        the last values; the next tick refreshes them. Genuine connectivity loss
        still surfaces through the bus refresh.

        A hub platform that reports no host readings is skipped inside
        ``async_refresh_hub`` without a wire round trip.
        """
        try:
            await async_refresh_hub(
                self.comm.client, self.hub, hbtn_version=self.comm.hbtn_version
            )
        except (HabitronError, OSError, TimeoutError) as err:
            # Covers an unreadable reading too: the library raises a protocol
            # error rather than handing out a string that would blow up here.
            _LOGGER.debug("SmartHub host readings skipped: %s", err)

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

    async def restart(self) -> None:
        """Restart hub."""
        await self.comm.hub_restart()

    async def reboot(self) -> None:
        """Reboot hub."""
        await self.comm.hub_reboot()

    async def _async_setup(self) -> None:
        """Run a first fetch during ``async_config_entry_first_refresh``."""
        await self._async_update_data()

    async def _async_update_data(self) -> int:
        """Fetch the current Habitron status.

        Returns the compact-status CRC used for change detection;
        ``async_system_update`` also updates the model in place and fires the
        per-member listeners. Connection-level failures (timeouts, network
        errors, refused connections) are converted to ``UpdateFailed`` so the
        coordinator flips ``last_update_success`` to False and every
        ``CoordinatorEntity`` is automatically marked unavailable.
        """
        try:
            async with asyncio.timeout(20):
                crc = await self.comm.async_system_update()
        except (TimeoutError, HabitronTimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_timeout",
            ) from err
        except (OSError, ConnectionError, HabitronError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_network_error",
                translation_placeholders={"error": str(err)},
            ) from err
        # Outside the try: the host readings swallow their own errors, so a
        # hub-diag hiccup must not mark every entity unavailable.
        await self.update()
        return crc


class HbtnFirmwareCoordinator(DataUpdateCoordinator[dict[str, tuple[str, str]]]):
    """Poll module firmware versions round-robin, one module per refresh.

    Firmware versions are quasi-static and the bus read is comparatively slow,
    so they are kept off the fast status coordinator. Each refresh reads a
    single target (rotating through router + modules), keeping every cycle to at
    most one serial bus read. Results are stored as ``{uid: (installed, latest)}``
    and the firmware update entities reflect them in their coordinator callback.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HabitronConfigEntry,
        hbtn_comm: HbtnComm,
    ) -> None:
        """Initialize the firmware coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Habitron firmware",
            config_entry=entry,
            update_interval=FW_POLL_INTERVAL,
        )
        self.comm = hbtn_comm
        self._index = 0
        self.data = {}

    async def _async_update_data(self) -> dict[str, tuple[str, str]]:
        """Read one target's firmware (round-robin) and merge it into data."""
        targets: list[Router | Module] = [
            self.comm.router,
            *self.comm.router.modules,
        ]
        if targets:
            target = targets[self._index % len(targets)]
            self._index += 1
            await self._read_target(target)
        return self.data

    async def _read_target(self, target: Router | Module) -> None:
        """Read installed/latest firmware for a single target into data."""
        # The router answers as address 0; a module by its own bus address.
        addr = target.addr if isinstance(target, Module) else 0
        try:
            resp = await self.comm.handle_firmware(addr)
        except (OSError, ConnectionError, HabitronError) as err:
            _LOGGER.debug("Firmware read failed for %s: %s", target.name, err)
            return
        if not resp:
            return  # unchanged (crc match) or read error
        versions = resp.decode("iso8859-1").split("\n")
        if len(versions) != 2:
            return
        installed, latest = versions[0], versions[1]
        if self.data.get(target.uid) == (installed, latest):
            return
        self.data[target.uid] = (installed, latest)
        if latest != installed:
            _LOGGER.info("Firmware %s: %s -> %s", target.name, installed, latest)
