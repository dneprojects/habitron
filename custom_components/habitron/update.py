"""Platform for update integration."""

from __future__ import annotations

from asyncio import sleep
import hashlib
import logging
from pathlib import Path
import shutil

import apkutils
from packaging.version import parse as parse_version

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .router import HbtnModule, HbtnRouter

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add update entities for Habitron system."""
    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    # Add router update entity
    new_devices.append(HbtnModuleUpdate(hbtn_rt, hbtn_cord, len(new_devices)))

    for hbt_module in hbtn_rt.modules:
        # Add standard firmware update entity
        new_devices.append(HbtnModuleUpdate(hbt_module, hbtn_cord, len(new_devices)))

        # Check for Smart Controller Touch type
        if hbt_module.typ == b"\x01\x04":
            _LOGGER.info("Creating SCTouchAppUpdate for %s", hbt_module.uid)
            new_devices.append(SCTouchAppUpdate(hbt_module, hbtn_rt))

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        async_add_entities(new_devices)


class SCTouchAppUpdate(UpdateEntity):
    """Perform SC Touch Android App update."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_name = "SC Touch App"
    _attr_should_poll = True
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, module: HbtnModule, router: HbtnRouter) -> None:
        """Initialize the app update entity."""
        self._module = module
        self._router = router
        self._hass = router.hass
        self.firmware_dir = Path("")

        self._attr_unique_id = f"mod_{self._module.uid}_app_update"
        self._attr_device_info = {"identifiers": {(DOMAIN, module.uid)}}

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

    def scan_firmware_dir_blocking(self):
        """Blocking job to scan for APK files."""
        if not self.firmware_dir.is_dir():
            _LOGGER.warning("Firmware directory not found: %s", self.firmware_dir)
            return None, None

        latest_version = parse_version("0.0.0")
        latest_filename = None

        try:
            for file_path in self.firmware_dir.iterdir():
                if file_path.name.startswith("sctouch_") and file_path.suffix == ".apk":
                    # Mute axml log noise
                    axml_logger = logging.getLogger("axml")
                    original_level = axml_logger.level
                    axml_logger.setLevel(logging.WARNING)

                    version_name = None
                    apk = None
                    try:
                        apk = apkutils.APK.from_file(str(file_path))
                        apk.get_manifest()
                        version_name = apk.version_name
                        _LOGGER.warning(
                            "Parsed APK %s, found version %s",
                            file_path.name,
                            version_name,
                        )
                    except Exception as e:  # noqa: BLE001
                        _LOGGER.warning("Failed to parse APK %s: %s", file_path.name, e)
                    finally:
                        if apk:
                            apk.close()
                        axml_logger.setLevel(original_level)
                    # --- End of suppression ---

                    if version_name:
                        apk_version_obj = parse_version(str(version_name))
                        if apk_version_obj > latest_version:
                            latest_version = apk_version_obj
                            latest_filename = file_path.name

            if latest_filename:
                return str(latest_version), latest_filename

        except Exception as e:
            _LOGGER.error("Error scanning firmware directory: %s", e)

        return None, None

    def _update_path(self):
        """Determine firmware path based on environment."""
        base_path = Path(self._hass.config.path())
        if self._router.smhub.addon_slug:
            # Path for Home Assistant Add-ons
            self.firmware_dir = (
                Path("/share") / self._router.smhub.addon_slug / "firmware"
            )
        else:
            # Default local path
            self.firmware_dir = base_path / "custom_components" / DOMAIN / "firmware"

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
                _LOGGER.warning(
                    "App update available: %s -> %s",
                    self._attr_installed_version,
                    latest_ver,
                )
                if latest_file:
                    await self._copy_apk_to_www(latest_file)

    async def _copy_apk_to_www(self, filename: str) -> tuple[str | None, str | None]:
        """Copy file to accessible www folder and return URL/hash."""
        config_dir = Path(self._hass.config.path())
        source_file = self.firmware_dir / filename
        public_dir = config_dir / "www" / "firmware"
        public_file = public_dir / filename

        def _copy_job():
            try:
                public_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, public_file)

                sha256 = hashlib.sha256()
                with open(public_file, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha256.update(chunk)

                url = f"{self._hass.config.internal_url}/local/firmware/{filename}"
                return url, sha256.hexdigest()
            except Exception:
                _LOGGER.exception("Error preparing file %s", filename)
                return None, None

        return await self._hass.async_add_executor_job(_copy_job)

    async def async_install(self, version: str | None, backup: bool) -> None:
        """Trigger update on the mobile client."""
        module_name = getattr(self._module, "name", self._module.uid)

        if not self._attr_latest_version:
            raise HomeAssistantError("No version info available")

        stream_name = self._module.stream_name
        provider = self._router.smhub.ws_provider

        if not provider.active_ws_connections.get(stream_name):
            _LOGGER.error("Client for %s is not connected", module_name)
            raise HomeAssistantError(f"Client {module_name} not connected")

        url, checksum = await self._copy_apk_to_www(self._latest_apk_filename)
        if not url:
            raise HomeAssistantError("Failed to prepare update file")

        payload = {
            "version": self._attr_latest_version,
            "filename": self._latest_apk_filename,
            "url": url,
            "checksum": checksum,
        }

        await provider.async_send_json_message(
            stream_name, {"type": "habitron/update_available", "payload": payload}
        )

    @property
    def release_notes(self) -> str | None:
        """Return release notes."""
        return f"Latest APK version: {self._attr_latest_version}"


class HbtnModuleUpdate(CoordinatorEntity, UpdateEntity):
    """Module firmware update entity."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )
    _attr_should_poll = True

    def __init__(self, module, coord, idx) -> None:
        """Initialize entity."""
        super().__init__(coord)
        self.idx = idx
        self._module = module
        self._attr_name = "Firmware"
        self._attr_unique_id = f"Mod_{self._module.uid}_update"
        self.flash_in_progress = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def in_progress(self) -> bool:
        """Return if update is in progress."""
        return self.flash_in_progress

    async def async_install(self, version: str | None, backup: bool) -> None:
        """Start firmware update."""
        self.flash_in_progress = True
        self.async_write_ha_state()
        await sleep(0.1)
        try:
            if isinstance(self._module, HbtnRouter):
                await self._module.comm.update_firmware(self._module.id, 0)
                self._module.version = version
            else:
                addr = int(self._module.mod_addr / 100) * 100
                await self._module.comm.update_firmware(addr, self._module.raddr)
                self._module.sw_version = version
        finally:
            self.flash_in_progress = False
            await self.async_update()

    async def async_added_to_hass(self) -> None:
        """Initialize state."""
        await super().async_added_to_hass()
        await self.async_update()

    async def async_update(self) -> None:
        """Update version data from bus."""
        try:
            if isinstance(self._module, HbtnRouter):
                await self._module.get_definitions()
                self._attr_installed_version = self._module.version
                resp = await self._module.comm.handle_firmware(self._module.id, 0)
            else:
                self._attr_installed_version = self._module.sw_version
                resp = await self._module.comm.handle_firmware(
                    int(self._module.mod_addr / 100) * 100, self._module.raddr
                )
            if len(resp) == 0:
                _LOGGER.warning("No response for firmware version check, crc error")
                return
            versions = resp.decode("iso8859-1").split("\n")
            if len(versions) == 2:
                self._attr_latest_version = versions[1]
                self._attr_installed_version = versions[0]
                if self._attr_latest_version != self._attr_installed_version:
                    _LOGGER.warning(
                        "Firmware update available for module %s: %s -> %s",
                        self._module.name,
                        self._attr_installed_version,
                        self._attr_latest_version,
                    )
                self.async_write_ha_state()
        except Exception as e:  # noqa: BLE001
            _LOGGER.error(
                "Error checking firmware version for module %s: %s",
                self._module.name,
                e,
            )
