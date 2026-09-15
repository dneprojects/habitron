"""Habitron integration using DataUpdateCoordinator."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from ipaddress import IPv4Address
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from habitron_client import (
    Diagnostic,
    HabitronClient,
    HabitronError,
    HabitronTimeoutError,
    Module,
    Router,
    Sensor,
    SmartController,
    SmartHub,
    apply_event,
    async_build_hub,
    async_build_system,
    async_refresh_hub,
    async_refresh_system,
    get_host_ip,
    get_own_ip,
)

from homeassistant.components import network
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from .const import CONF_DEFAULT_HOST, DOMAIN, KEY_TOKEN, SCAN_INTERVAL

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

# Bus port of the SmartHub, and the port its standalone web UI answers on.
_BUS_PORT = 7777
_WEB_PORT = 7780


class LoggingLevels(Enum):
    """Definition of logging levels for selector."""

    notset = 0
    debug = 1
    info = 2
    warning = 3
    error = 4
    critical = 5


def _is_ipv4(value: str) -> bool:
    """Whether ``value`` is already a literal IPv4 address."""
    try:
        IPv4Address(value)
    except ValueError:
        return False
    return True


def _area_name(router: Router, area_no: int) -> str:
    """Return the bus area name for ``area_no`` (or ``House``)."""
    for area in router.areas:
        if area.nmbr == area_no:
            return area.name
    return "House"


@dataclass(frozen=True, slots=True)
class HbtnData:
    """What one poll found, and the coordinator's change-detection key.

    Most entities do not wait for this: they subscribe to the model member they
    render and the library notifies them as soon as its value moves. The
    coordinator fan-out covers what no member notification carries -- and with
    ``always_update=False`` it happens only when this value differs from the
    previous tick.

    Hence both fields. The CRC moves when the bus status does. The host state
    belongs here because it is not a member value at all: the hub's readings
    are polled apart from the bus, and their failure is something the entities
    show rather than something a member reports.
    """

    crc: int
    host_readings_ok: bool


class HbtnCoordinator(DataUpdateCoordinator[HbtnData]):
    """Habitron data update coordinator.

    Owns the connection and the whole model: the ``SmartHub`` (the hub's own
    data and host readings) and the ``Router`` (everything behind it).

    ``async_system_update`` writes the bus status directly into the
    module/input/output objects, and the entities read from those object
    attributes via their ``_handle_coordinator_update`` callbacks. The
    coordinator acts as a heartbeat that fans out update events.

    It returns an :class:`HbtnData`, which serves as the change-detection key.
    With ``always_update=False`` the coordinator only fans out to the entities
    when something they show actually changed between ticks, avoiding a
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

        # Empty models until ``async_setup`` builds them from the bus, so
        # nothing has to guard against ``None``.
        self.hub = SmartHub()
        self.router = Router()

        # Connection. A literal address is usable straight away; a host name or
        # the ``local`` sentinel is resolved in ``async_setup``, where the
        # blocking lookup can stay off the event loop. The client follows once
        # the address is known.
        self._host_conf: str = entry.data[CONF_HOST]
        self._host: str = self._host_conf if _is_ipv4(self._host_conf) else ""
        self._client: HabitronClient | None = None
        self._network_ip: str = ""

        # The address Home Assistant actually reached the hub at. Device links
        # are built from it, so it has to be one that works from here -- not
        # what the hub says about itself, which is ``0.0.0.0`` whenever its
        # interface is unnumbered from its own point of view.
        self.host: str = self._host
        # What the hub does say about itself. Only used to recognise its pushed
        # events, which it stamps with an address of its own choosing.
        self.reported_ip: str = ""
        self._mac: str = ""
        self.is_addon: bool = True  # settled by the hub's own info

        self.online: bool = True
        self.base_url: str = ""
        self.ws_provider: HabitronWebRTCProvider | None = None

        # Change-detection key for the bus status stream. The firmware reads
        # keep their own per-target CRC so they cannot clobber this one --
        # sharing one field made unrelated reads invalidate each other's dedupe.
        self.crc: int = 0

        # Whether the last host poll answered. The hub's own readings are
        # refreshed separately and their errors are swallowed (see ``update``),
        # so without this they would keep reporting their last value
        # indefinitely, indistinguishable from a live one.
        # ``host_diags_valid`` cannot say this: it means "a host poll has ever
        # succeeded" and never goes back to false.
        self.host_readings_ok: bool = True
        self._stream_crc: dict[str, int] = {}

        # ``version`` is a HACS-only manifest field; core strips it, so fall
        # back to a sentinel to keep entry setup working in both layouts.
        self._hbtn_version: str = hass.data["integrations"]["habitron"].manifest.get(
            "version", "0.0.0"
        )

        self.rtr_id = 1
        self.previous_devices: set[str] = set()

    @property
    def client(self) -> HabitronClient:
        """The bus client, for platforms that send commands.

        Commands go straight to the library: since a module's ``addr`` is its
        bus address and the wire semantics live there, there is nothing for the
        integration to adapt on the way out.

        ``async_setup`` constructs and connects it; reaching for it before then
        is a programming error rather than a state to handle.
        """
        if self._client is None:
            raise RuntimeError("HabitronClient is not connected; setup has not run")
        return self._client

    @property
    def uid(self) -> str:
        """The identity every device and entity of this entry is keyed by.

        Kept on the hub model rather than beside it: the hub's own entities
        read their device identifier off that same object, so a second copy
        here could disagree with the one they use.
        """
        return self.hub.uid

    def owns_event_from(self, hub_id: str) -> bool:
        """Whether a pushed event stamped ``hub_id`` belongs to this hub.

        The hub picks that stamp itself and the service documents it as "host
        name or IP", so all three spellings that legitimately name this hub are
        accepted: the address we reached it at, the one it reports for itself,
        and whatever the entry was configured with. They coincide in every
        normal setup and only drift apart when the hub answers with a different
        interface -- guessing which one it would use would cost the events
        silently, since an unmatched push is dropped with a debug line.
        """
        return hub_id in (self.host, self.reported_ip, self._host_conf)

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
        if self.is_addon:
            # ``safe=""``: the default leaves "/" alone, and the page is a
            # query *value* -- the app's own links carry it encoded.
            return f"{self.base_url}?index={quote(path, safe='')}"
        return f"{self.base_url}{path}"

    async def _async_connect(self) -> None:
        """Resolve the hub address and open the client.

        The client uses a fresh socket per command, so ``connect()`` only opens
        and closes a probe socket to fail fast on an unreachable host; no
        connection is kept open afterwards.
        """
        if not self._host:
            if self._host_conf == CONF_DEFAULT_HOST:
                # get_own_ip is a plain blocking socket call, so it runs in the
                # executor. get_host_ip resolves the name itself with async DNS
                # and must be awaited directly -- handing it to the executor
                # would only build the coroutine and assign that, unrun.
                self._host = await self.hass.async_add_executor_job(get_own_ip)
            else:
                self._host = await get_host_ip(self._host_conf)
        self._network_ip = await network.async_get_source_ip(
            self.hass, target_ip=self._host
        )
        _LOGGER.info("Resolved network ip: %s", self._network_ip)
        self._client = HabitronClient(self._host, _BUS_PORT)
        await self._client.connect()

    async def async_setup(self) -> None:
        """Connect, register the hub device and build the bus model."""
        # 1. Open the client connection and fetch hub info (mac/version/host).
        await self._async_connect()
        await self._async_read_hub_info()
        self.hub = await async_build_hub(self.client)
        self._resolve_uid()

        if self.is_addon:
            self.base_url = f"homeassistant://{self.addon_slug}/ingress"
        else:
            self.base_url = f"http://{self.host}:{_WEB_PORT}"

        # 2. Register the hub device.
        dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            configuration_url=self._conf_url("/hub"),
            connections={(dr.CONNECTION_NETWORK_MAC, self._mac)},
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
        await self.reinit_hub(0)
        # ``.get``, not a subscript: an entry created by the core integration
        # carries no token -- it does not offer the field yet -- and would
        # otherwise raise here the moment someone switches over. Empty is the
        # right default anyway; only a hub on its own machine needs a token,
        # one sharing the machine with Home Assistant uses the supervisor's.
        await self.send_network_info(self.entry.data.get(KEY_TOKEN, ""))
        self.router = await async_build_system(self.client, b_uid=self.uid)
        # Seed the WebRTC stream name for Touch modules (used by camera /
        # media_player / assist / voice button to address the Flutter client).
        for module in self.router.modules:
            if isinstance(module, SmartController):
                module.stream_name = f"{slugify(module.name)}_{module.addr}"
        await self._register_bus_devices()
        await self.reinit_hub(1)

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
        await self.client.send_devregid(0, rt_dev.id)

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
            await self.client.send_devregid(module.addr, dev.id)

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
                self.client, self.hub, hbtn_version=self._hbtn_version
            )
        except (HabitronError, OSError, TimeoutError) as err:
            # Covers an unreadable reading too: the library raises a protocol
            # error rather than handing out a string that would blow up here.
            _LOGGER.debug("SmartHub host readings skipped: %s", err)
            self.host_readings_ok = False
        else:
            self.host_readings_ok = True

    async def async_update(self) -> None:
        """Async wrapper retained for callers expecting the old API."""
        await self.update()

    async def async_close(self) -> None:
        """Release the bus client on entry unload.

        With per-command sockets there is no long-lived connection to tear
        down; this drops the client reference and lets it close any probe
        socket it may still hold.
        """
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def get_version(self) -> str:
        """Test connectivity to SmartHub is OK."""
        resp = await self.client.get_smhub_version()
        ver_string = resp.decode("iso8859-1")
        return ver_string[9:] if ver_string.startswith("SmartIP") else "0.0.0"

    async def restart(self) -> None:
        """Restart hub."""
        await self.client.hub_restart()

    async def reboot(self) -> None:
        """Reboot hub."""
        await self.client.hub_reboot()

    async def _async_setup(self) -> None:
        """Run a first fetch during ``async_config_entry_first_refresh``."""
        await self._async_update_data()

    async def _async_update_data(self) -> HbtnData:
        """Fetch the current Habitron status.

        Returns the change-detection key (see :class:`HbtnData`);
        ``async_system_update`` also updates the model in place and fires the
        per-member listeners. Connection-level failures (timeouts, network
        errors, refused connections) are converted to ``UpdateFailed`` so the
        coordinator flips ``last_update_success`` to False and every
        ``CoordinatorEntity`` is automatically marked unavailable.
        """
        try:
            async with asyncio.timeout(20):
                crc = await self.async_system_update()
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
        return HbtnData(crc=crc, host_readings_ok=self.host_readings_ok)

    async def _async_read_hub_info(self) -> None:
        """Read what the hub reports about itself.

        Kept apart from the library's ``async_build_hub``: these are the fields
        the *connection* needs -- the address the event server stamps its
        pushes with, the MAC the network handshake scrambles a token against,
        and whether the hub is the add-on variant.
        """
        try:
            info = await self.client.get_smhub_info()
            network_info = info["hardware"]["network"]
            self.reported_ip = network_info["ip"]
            self._mac = network_info["lan mac"]
            software = cast("dict[str, Any]", info["software"])
            # Whether the *hub* runs as an add-on is the hub's own property, so
            # it has to come from its info ("Smart Hub App" vs "Smart Hub").
            # Reading SUPERVISOR_TOKEN here asked the wrong machine: it is set
            # in every supervised Home Assistant, so a standalone hub talking
            # to an HA OS instance was taken for an add-on. The token was then
            # sent unscrambled while the hub descrambled it, which destroyed it.
            self.is_addon = "App" in str(software.get("type", ""))
        except HabitronTimeoutError as exc:
            _LOGGER.error("Timeout connecting to SmartHub at %s", self._host)
            raise HabitronTimeoutError(f"Hub at {self._host} not responding") from exc
        except Exception as exc:
            _LOGGER.error("Error during SmartHub info fetch: %s", exc)
            raise

    async def send_network_info(self, tok: str) -> None:
        """Tell the hub how to reach Home Assistant."""
        await self.client.send_network_info(
            self._network_ip,
            tok.encode("utf-8"),
            bytes.fromhex(self._mac.replace(":", "").replace("-", "")),
            is_addon=self.is_addon,
            version=self._hbtn_version,
        )
        _LOGGER.debug("Sent network info to hub - ip: %s", self._network_ip)

    async def reinit_hub(self, mode: int) -> bytes:
        """Restart the event server on the hub."""
        resp = await self.client.reinit_hub(mode)
        _LOGGER.info("Re-initialized hub with mode %s", mode)
        return resp

    async def async_system_update(self) -> int:
        """Poll the bus and update the model in place via the library.

        Delegates to ``async_refresh_system``, which fetches the compact status
        and -- on a CRC change -- applies the router status and distributes it
        to the modules, firing the per-member listeners. Returns the status CRC,
        which is this coordinator's change-detection key.
        """
        self.crc = await async_refresh_system(
            self.client, self.router, last_crc=self.crc
        )
        return self.crc

    async def handle_firmware(self, mod_nmbr: int) -> bytes:
        """Read a target's firmware status, or ``b""`` if it has not changed."""
        return await self._read_deduped("fw", mod_nmbr, self.client.handle_firmware)

    async def update_firmware(self, mod_nmbr: int) -> bytes:
        """Start a router/module firmware update."""
        return await self._read_deduped("fwupd", mod_nmbr, self.client.update_firmware)

    async def _read_deduped(
        self,
        stream: str,
        target: int,
        read: Callable[[int], Awaitable[tuple[bytes, int]]],
    ) -> bytes:
        """Return a stream's payload, or ``b""`` when its CRC has not moved.

        Each stream and target keeps its own CRC: one shared field made
        unrelated reads invalidate each other's dedupe, costing extra reads and
        occasionally swallowing a change.
        """
        payload, crc = await read(target)
        key = f"{stream}:{target}"
        if crc == self._stream_crc.get(key):
            return b""
        self._stream_crc[key] = crc
        return payload

    async def update_entity(
        self,
        hub_id: str,
        mod_id: int,
        evnt: int,
        arg1: int,
        arg2: int,
        arg3: int = 0,
        arg4: int = 0,
        arg5: int = 0,
    ) -> None:
        """Event-server handler: feed a SmartHub push event into the model.

        The library's ``apply_event`` updates the matching member and fires its
        listeners (entities write HA state). Event-only behaviour that needs HA
        timing -- the finger reset pulse, button device triggers -- lives in the
        event platform, which reacts to the member notifications.
        """
        if not self.owns_event_from(hub_id):
            return
        apply_event(self.router, mod_id, evnt, arg1, arg2, arg3, arg4, arg5)


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
        status: HbtnCoordinator,
    ) -> None:
        """Initialize the firmware coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Habitron firmware",
            config_entry=entry,
            update_interval=FW_POLL_INTERVAL,
        )
        self.status = status
        self._index = 0
        self.data = {}

    async def _async_update_data(self) -> dict[str, tuple[str, str]]:
        """Read one target's firmware (round-robin) and merge it into data."""
        targets: list[Router | Module] = [
            self.status.router,
            *self.status.router.modules,
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
            resp = await self.status.handle_firmware(addr)
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
