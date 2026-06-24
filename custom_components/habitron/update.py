"""Platform for update integration."""

from asyncio import sleep
import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from habitron_client import Module, Router
from packaging.version import parse as parse_version

from homeassistant.components.http import StaticPathConfig
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

from ._axml import read_apk_version_name
from ._helpers import hbtn_device_info
from .const import DOMAIN
from .coordinator import HabitronConfigEntry, HbtnFirmwareCoordinator

if TYPE_CHECKING:
    from .smart_hub import SmartHub

PARALLEL_UPDATES = 1

_LOGGER = logging.getLogger(__name__)


# URL prefix under which we expose the firmware directory via HA's
# static-path serving. The Touch panel app downloads APKs from there
# directly — no copy into ``<config>/www/`` necessary.
_FIRMWARE_URL_PREFIX = "/habitron-firmware"

# Legacy firmware paths already logged, so the migration nudge appears only once.
_LEGACY_FIRMWARE_LOGGED: set[str] = set()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add update entities for Habitron system."""
    smhub = entry.runtime_data
    hbtn_rt = smhub.router
    fw_coord = HbtnFirmwareCoordinator(hass, entry, smhub.comm)

    new_devices: list[UpdateEntity] = []
    # Add router update entity
    new_devices.append(HbtnModuleUpdate(hbtn_rt, fw_coord, len(new_devices)))

    for hbt_module in hbtn_rt.modules:
        # Add standard firmware update entity
        new_devices.append(HbtnModuleUpdate(hbt_module, fw_coord, len(new_devices)))

        # Check for Smart Controller Touch type
        if hbt_module.typ == b"\x01\x04":
            _LOGGER.info("Creating SCTouchAppUpdate for %s", hbt_module.uid)
            new_devices.append(SCTouchAppUpdate(hbt_module, smhub))

    if new_devices:
        # Prime firmware versions with one read before the entities go live.
        # Firmware is non-critical, so a failed read must not abort setup.
        await fw_coord.async_refresh()
        async_add_entities(new_devices)


class SCTouchAppUpdate(UpdateEntity):
    """Perform SC Touch Android App update."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_has_entity_name = True
    _attr_name = "SC Touch App"
    _attr_should_poll = True
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, module: Module, smhub: SmartHub) -> None:
        """Initialize the app update entity."""
        self._module = module
        self._smhub = smhub
        self._hass = smhub.hass
        self.firmware_dir = Path("")

        self._attr_unique_id = f"mod_{self._module.uid}_app_update"
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
        await self._register_firmware_static_path()

    async def _register_firmware_static_path(self) -> None:
        """Expose the firmware directory under ``_FIRMWARE_URL_PREFIX``.

        The registration is per-HA-instance; trying to register the same
        path a second time (e.g. on entry reload or with a second Touch
        panel) raises — caught and logged at debug level.
        """
        if not self.firmware_dir.is_dir():
            return
        path_config = StaticPathConfig(
            _FIRMWARE_URL_PREFIX, str(self.firmware_dir), False
        )
        try:
            await self._hass.http.async_register_static_paths([path_config])
        except Exception:  # noqa: BLE001
            # Already registered (second Touch panel, entry reload, …).
            _LOGGER.debug(
                "Static path %s already registered for %s",
                _FIRMWARE_URL_PREFIX,
                self.firmware_dir,
            )

    def scan_firmware_dir_blocking(self) -> tuple[str | None, str | None]:
        """Find the newest ``sctouch_*.apk`` in the firmware directory.

        Returns ``(version, filename)`` of the highest version, or
        ``(None, None)`` if the directory is missing, empty, or
        contains no parseable APKs.
        """
        if not self.firmware_dir.is_dir():
            _LOGGER.warning("Firmware directory not found: %s", self.firmware_dir)
            return None, None

        latest_version = parse_version("0.0.0")
        latest_filename: str | None = None

        try:
            for file_path in self.firmware_dir.iterdir():
                if not (
                    file_path.name.startswith("sctouch_") and file_path.suffix == ".apk"
                ):
                    continue
                version_name = read_apk_version_name(file_path)
                if version_name is None:
                    _LOGGER.warning("Could not read version from %s", file_path.name)
                    continue
                _LOGGER.debug(
                    "Parsed APK %s, found version %s", file_path.name, version_name
                )
                apk_version_obj = parse_version(version_name)
                if apk_version_obj > latest_version:
                    latest_version = apk_version_obj
                    latest_filename = file_path.name
        except OSError as e:
            _LOGGER.error("Error scanning firmware directory: %s", e)
            return None, None

        if latest_filename is None:
            return None, None
        return str(latest_version), latest_filename

    def _update_path(self) -> None:
        """Determine firmware path based on environment.

        Resolves to one of (in priority order):

        1. ``/share/<addon_slug>/firmware`` when SmartHub runs as a HA OS
           add-on. The add-on deposits APKs into ``/share`` by design.
        2. ``<HA-config>/<DOMAIN>/firmware`` for any other install. This is
           the path that works in Home Assistant Core; HACS users should
           migrate to it by moving their existing firmware directory up
           one level (out of ``custom_components/<DOMAIN>/``).
        3. ``<HA-config>/custom_components/<DOMAIN>/firmware`` as a
           backward-compatible fallback for HACS installs that still have
           their APKs in the old location. Logs a deprecation warning
           when this path is used.
        """
        base_path = Path(self._hass.config.path())
        if self._smhub.addon_slug:
            self.firmware_dir = Path("/share") / self._smhub.addon_slug / "firmware"
            return

        new_path = base_path / DOMAIN / "firmware"
        legacy_path = base_path / "custom_components" / DOMAIN / "firmware"
        if new_path.is_dir() or not legacy_path.is_dir():
            self.firmware_dir = new_path
            return
        self.firmware_dir = legacy_path
        if str(legacy_path) not in _LEGACY_FIRMWARE_LOGGED:
            _LEGACY_FIRMWARE_LOGGED.add(str(legacy_path))
            _LOGGER.info("Legacy firmware %s, move to %s", legacy_path, new_path)

    async def async_update(self) -> None:
        """Fetch latest state."""
        self._update_path()
        _LOGGER.debug("Checking for updates in %s", self.firmware_dir)

        # Scan for APKs in executor
        latest_ver, latest_file = await self._hass.async_add_executor_job(
            self.scan_firmware_dir_blocking
        )

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

        The firmware directory is exposed via ``async_register_static_paths``
        in :meth:`async_added_to_hass`, so there is no copy step — we just
        compute the SHA256 over the source file and build the URL from the
        registered prefix.
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
                url = f"{base_url}{_FIRMWARE_URL_PREFIX}/{filename}"
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
        self._attr_unique_id = f"Mod_{self._module.uid}_update"
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
                await self.coordinator.comm.update_firmware(self._module.id)
                self._module.version = version or ""
            else:
                await self.coordinator.comm.update_firmware(self._module.addr)
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
