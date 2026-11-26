"""Platform for update integration."""

from asyncio import sleep
import hashlib
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from aiohttp import web
from habitron_client import Module, Router
from packaging.version import parse as parse_version

from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.hass_dict import HassKey

from ._axml import read_apk_version_name
from ._helpers import hbtn_device_info
from .const import DOMAIN
from .coordinator import HabitronConfigEntry, HbtnCoordinator, HbtnFirmwareCoordinator

PARALLEL_UPDATES = 1

_LOGGER = logging.getLogger(__name__)


# URL prefix of the APK download route. The Touch panel app downloads the
# APK from ``<prefix>/<module uid>/<filename>``.
_FIRMWARE_URL_PREFIX = "/habitron-firmware"

# Only APKs of the Touch app are served; no path separators, so a request can
# never leave the firmware directory.
_APK_NAME_RE = re.compile(r"sctouch_[A-Za-z0-9._+-]+\.apk")

# Touch app update entities by module uid; the download route resolves each
# request against the entity's current firmware directory.
_TOUCH_APP_ENTITIES: HassKey[dict[str, SCTouchAppUpdate]] = HassKey(
    f"{DOMAIN}_touch_app_entities"
)

# Legacy firmware paths already logged, so the migration nudge appears only once.
_LEGACY_FIRMWARE_LOGGED: set[str] = set()

# Firmware directories that could not be created, so that failure is reported
# once rather than on every poll.
_FIRMWARE_DIR_LOGGED: set[str] = set()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add update entities for Habitron system."""
    coordinator = entry.runtime_data
    hbtn_rt = coordinator.router
    fw_coord = HbtnFirmwareCoordinator(hass, entry, coordinator)

    new_devices: list[UpdateEntity] = []
    # Add router update entity
    new_devices.append(HbtnModuleUpdate(hbtn_rt, fw_coord, len(new_devices)))

    for hbt_module in hbtn_rt.modules:
        # Add standard firmware update entity
        new_devices.append(HbtnModuleUpdate(hbt_module, fw_coord, len(new_devices)))

        # Check for Smart Controller Touch type
        if hbt_module.typ == b"\x01\x04":
            _LOGGER.info("Creating SCTouchAppUpdate for %s", hbt_module.uid)
            new_devices.append(SCTouchAppUpdate(hbt_module, coordinator))

    if any(isinstance(dev, SCTouchAppUpdate) for dev in new_devices):
        _async_register_firmware_view(hass)

    if new_devices:
        # Prime firmware versions with one read before the entities go live.
        # Firmware is non-critical, so a failed read must not abort setup.
        await fw_coord.async_refresh()
        async_add_entities(new_devices)


@callback
def _async_register_firmware_view(hass: HomeAssistant) -> None:
    """Register the APK download route once per HA instance.

    Unlike a static path, the route is not bound to a directory: each request
    is resolved against the firmware directory the entity uses right now, so a
    directory that changes after setup (add-on slug known only later) is
    served correctly without a restart.
    """
    if _TOUCH_APP_ENTITIES in hass.data:
        return
    hass.data[_TOUCH_APP_ENTITIES] = {}
    hass.http.register_view(HbtnFirmwareView())


class HbtnFirmwareView(HomeAssistantView):
    """Serve the Touch app APK to the panel."""

    url = _FIRMWARE_URL_PREFIX + "/{module_uid}/{filename}"
    name = "api:habitron:firmware"
    # The panel downloads with a plain HTTP client, without a HA token.
    requires_auth = False

    async def get(
        self, request: web.Request, module_uid: str, filename: str
    ) -> web.StreamResponse:
        """Return the APK from the firmware directory of the panel's entity."""
        hass: HomeAssistant = request.app[KEY_HASS]
        entity = hass.data.get(_TOUCH_APP_ENTITIES, {}).get(module_uid)
        if entity is None or not _APK_NAME_RE.fullmatch(filename):
            raise web.HTTPNotFound
        file_path = await hass.async_add_executor_job(
            entity.resolve_apk_blocking, filename
        )
        if file_path is None:
            _LOGGER.warning(
                "APK %s requested but not found in %s", filename, entity.firmware_dir
            )
            raise web.HTTPNotFound
        return web.FileResponse(file_path)


class SCTouchAppUpdate(UpdateEntity):
    """Perform SC Touch Android App update."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_has_entity_name = True
    _attr_name = "SC Touch App"
    _attr_should_poll = True
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, module: Module, coordinator: HbtnCoordinator) -> None:
        """Initialize the app update entity."""
        self._module = module
        self._smhub = coordinator
        self._hass = coordinator.hass
        self.firmware_dir = Path("")

        self._attr_unique_id = f"{self._module.uid}_app_update"
        self._attr_device_info = hbtn_device_info(module.uid)

        # Initial version sync from module property
        current_version = getattr(self._module, "client_version", "0.0.0")
        self._attr_installed_version = (
            current_version if current_version != "unknown" else "0.0.0"
        )
        self._attr_latest_version = None
        self._latest_apk_filename: str | None = None

    async def async_added_to_hass(self) -> None:
        """Handle entity which is added to Home Assistant."""
        await super().async_added_to_hass()
        # Force immediate update to fill latest_version and logs
        _LOGGER.debug(
            "Entity added, triggering immediate update for %s", self._module.uid
        )
        await self.async_update()
        self._hass.data.setdefault(_TOUCH_APP_ENTITIES, {})[self._module.uid] = self

    async def async_will_remove_from_hass(self) -> None:
        """Stop serving this panel's APK when the entity goes away."""
        entities = self._hass.data.get(_TOUCH_APP_ENTITIES, {})
        if entities.get(self._module.uid) is self:
            del entities[self._module.uid]
        await super().async_will_remove_from_hass()

    def resolve_apk_blocking(self, filename: str) -> Path | None:
        """Return the APK file in the current firmware directory, or None."""
        file_path = self.firmware_dir / filename
        if file_path.parent != self.firmware_dir or not file_path.is_file():
            return None
        return file_path

    def scan_firmware_dirs_blocking(
        self, dirs: list[Path]
    ) -> tuple[str | None, str | None, Path | None]:
        """Find the newest ``sctouch_*.apk`` across the firmware directories.

        The last directory is the one the user drops APKs into; it is created
        when missing, so nobody has to guess it from a log line. Returns
        ``(version, filename, directory)`` of the highest version, or
        ``(None, None, None)`` when no directory holds a parseable APK.
        """
        self._ensure_user_dir(dirs[-1])
        latest_version = parse_version("0.0.0")
        latest: tuple[str, Path] | None = None
        for firmware_dir in dirs:
            if not firmware_dir.is_dir():
                continue
            try:
                for file_path in firmware_dir.iterdir():
                    if not _APK_NAME_RE.fullmatch(file_path.name):
                        continue
                    version_name = read_apk_version_name(file_path)
                    if version_name is None:
                        _LOGGER.warning("Could not read version from %s", file_path)
                        continue
                    _LOGGER.debug("Parsed APK %s, version %s", file_path, version_name)
                    apk_version = parse_version(version_name)
                    if apk_version > latest_version:
                        latest_version = apk_version
                        latest = (file_path.name, firmware_dir)
            except OSError as err:
                _LOGGER.error(
                    "Error scanning firmware directory %s: %s", firmware_dir, err
                )
        if latest is None:
            return None, None, None
        return str(latest_version), latest[0], latest[1]

    @staticmethod
    def _ensure_user_dir(firmware_dir: Path) -> None:
        """Create the directory the user drops APKs into, if missing."""
        if firmware_dir.is_dir():
            return
        try:
            firmware_dir.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            # Worth a warning -- but once, not on every poll.
            if str(firmware_dir) not in _FIRMWARE_DIR_LOGGED:
                _FIRMWARE_DIR_LOGGED.add(str(firmware_dir))
                _LOGGER.warning(
                    "Cannot create the firmware directory %s: %s", firmware_dir, err
                )
        else:
            _LOGGER.info(
                "Created the firmware directory %s; place an sctouch_*.apk "
                "there to offer the Touch app update",
                firmware_dir,
            )

    def _hub_coordinators(self) -> list[HbtnCoordinator]:
        """Return this panel's hub and every other loaded hub of this HA."""
        coordinators = [self._smhub]
        for entry in self._hass.config_entries.async_loaded_entries(DOMAIN):
            coordinator = entry.runtime_data
            # SEA entries share the domain; only hubs carry firmware.
            if isinstance(coordinator, HbtnCoordinator) and coordinator not in (
                coordinators
            ):
                coordinators.append(coordinator)
        return coordinators

    def _firmware_dirs(self, coordinators: list[HbtnCoordinator]) -> list[Path]:
        """Return the directories an APK of this HA instance can be in.

        One APK serves every Touch panel of the HA instance, whichever hub it
        is connected to:

        1. ``/share/<addon_slug>/firmware`` of each hub running as HA app; the
           app deposits its bundled APK there.
        2. ``<HA-config>/<DOMAIN>/firmware``, the folder to drop an APK by
           hand; it is the last entry and created when missing.
        3. ``<HA-config>/custom_components/<DOMAIN>/firmware`` instead of 2
           for HACS installs that still keep their APKs there.
        """
        dirs: list[Path] = []
        for coordinator in coordinators:
            # Only an app hub has a real slug; a standalone one may report
            # its host name there.
            if coordinator.is_addon and coordinator.addon_slug:
                app_dir = Path("/share") / coordinator.addon_slug / "firmware"
                if app_dir not in dirs:
                    dirs.append(app_dir)

        base_path = Path(self._hass.config.path())
        new_path = base_path / DOMAIN / "firmware"
        legacy_path = base_path / "custom_components" / DOMAIN / "firmware"
        if new_path.is_dir() or not legacy_path.is_dir():
            dirs.append(new_path)
            return dirs
        dirs.append(legacy_path)
        if str(legacy_path) not in _LEGACY_FIRMWARE_LOGGED:
            _LEGACY_FIRMWARE_LOGGED.add(str(legacy_path))
            _LOGGER.info("Legacy firmware %s, move to %s", legacy_path, new_path)
        return dirs

    async def async_update(self) -> None:
        """Fetch latest state."""
        coordinators = self._hub_coordinators()
        # An app hub may name its slug only after setup; read it on every
        # update search so the firmware directory follows without a reload.
        for coordinator in coordinators:
            if coordinator.is_addon:
                await coordinator.async_refresh_addon_slug()
        dirs = self._firmware_dirs(coordinators)
        _LOGGER.debug("Checking for updates in %s", dirs)

        latest_ver, latest_file, latest_dir = await self._hass.async_add_executor_job(
            self.scan_firmware_dirs_blocking, dirs
        )
        # The download route serves from here, the checksum is computed here.
        self.firmware_dir = latest_dir or dirs[-1]

        # Ensure installed version matches module master value
        module_version = getattr(self._module, "client_version", None)
        if module_version and module_version != "unknown":
            self._attr_installed_version = module_version

        self._attr_latest_version = latest_ver
        self._latest_apk_filename = latest_file

        if latest_ver and self._attr_installed_version:
            if parse_version(latest_ver) > parse_version(self._attr_installed_version):
                _LOGGER.debug(
                    "App update available: %s -> %s",
                    self._attr_installed_version,
                    latest_ver,
                )

    async def _apk_url_and_checksum(
        self, filename: str
    ) -> tuple[str | None, str | None]:
        """Return ``(url, sha256)`` for the firmware file served in place.

        The file is served by :class:`HbtnFirmwareView` from the same
        directory the checksum is computed over, so there is no copy step.
        """
        source_file = self.firmware_dir / filename

        # Resolve a fully-qualified base URL (with scheme) for the client to
        # download from. ``hass.config.internal_url`` is ``None`` unless the
        # user explicitly set one, which would yield a scheme-less URL the
        # Touch app rejects; ``get_url`` always returns an absolute URL.
        try:
            base_url = get_url(self._hass)
        except NoURLAvailableError:
            _LOGGER.error("No Home Assistant URL available to serve firmware")
            return None, None

        def _hash_job() -> tuple[str | None, str | None]:
            try:
                sha256 = hashlib.sha256()
                with source_file.open("rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha256.update(chunk)
                url = (
                    f"{base_url}{_FIRMWARE_URL_PREFIX}/"
                    f"{quote(self._module.uid, safe='')}/{filename}"
                )
                return url, sha256.hexdigest()
            except Exception:
                _LOGGER.exception("Error hashing file %s", filename)
                return None, None

        return await self._hass.async_add_executor_job(_hash_job)

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Trigger update on the mobile client."""
        del version, backup, kwargs
        module_name = getattr(self._module, "name", self._module.uid)

        if not self._attr_latest_version:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="update_no_version_info",
            )

        stream_name = getattr(self._module, "stream_name", "")
        provider = self._smhub.ws_provider
        if provider is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="update_no_webrtc_provider",
            )

        if not provider.active_ws_connections.get(stream_name):
            _LOGGER.error("Client for %s is not connected", module_name)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="update_client_not_connected",
                translation_placeholders={"module_name": str(module_name)},
            )

        if self._latest_apk_filename is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="update_no_apk_filename",
            )

        url, checksum = await self._apk_url_and_checksum(self._latest_apk_filename)
        if not url:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="update_apk_prep_failed",
            )

        payload = {
            "version": self._attr_latest_version,
            "filename": self._latest_apk_filename,
            "url": url,
            "checksum": checksum,
        }

        await provider.async_send_json_message(
            stream_name, {"type": "habitron/update_available", "payload": payload}
        )

    def release_notes(self) -> str | None:
        """Return release notes."""
        return f"Latest APK version: {self._attr_latest_version}"


class HbtnModuleUpdate(CoordinatorEntity[HbtnFirmwareCoordinator], UpdateEntity):
    """Module firmware update entity."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_has_entity_name = True
    _attr_name = "Firmware"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )
    # should_poll stays off (CoordinatorEntity default): firmware versions are
    # read by HbtnFirmwareCoordinator round-robin; this entity only reflects the
    # result for its module, written into coordinator.data keyed by uid.

    def __init__(
        self,
        module: Module | Router,
        coord: HbtnFirmwareCoordinator,
        idx: int,
    ) -> None:
        """Initialize entity."""
        super().__init__(coord)
        self.idx = idx
        self._module: Module | Router = module
        self._attr_unique_id = f"{self._module.uid}_firmware_update"
        self.flash_in_progress = False
        # Installed version is known from setup; latest fills in once polled.
        self._attr_installed_version = getattr(module, "sw_version", None) or getattr(
            module, "version", None
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return hbtn_device_info(self._module.uid)

    @property
    def in_progress(self) -> bool:
        """Return if update is in progress."""
        return self.flash_in_progress

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Start firmware update."""
        del backup, kwargs
        self.flash_in_progress = True
        self.async_write_ha_state()
        await sleep(0.1)
        try:
            if isinstance(self._module, Router):
                # The router answers as address 0, like it does for a
                # firmware read or a restart.
                await self.coordinator.status.update_firmware(0)
                self._module.version = version or ""
            else:
                await self.coordinator.status.update_firmware(self._module.addr)
                self._module.sw_version = version or ""
        finally:
            self.flash_in_progress = False
            if version:
                self._attr_installed_version = version
                self._attr_latest_version = version
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Reflect any firmware version already polled by the coordinator."""
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Reflect the firmware versions read for this module by the coordinator."""
        versions = self.coordinator.data.get(self._module.uid)
        if versions is None:
            return
        installed, latest = versions
        if (installed, latest) == (
            self._attr_installed_version,
            self._attr_latest_version,
        ):
            return
        self._attr_installed_version = installed
        self._attr_latest_version = latest
        self.async_write_ha_state()
