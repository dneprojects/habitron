"""Platform for update integration."""

from __future__ import annotations

from asyncio import sleep
import hashlib
import logging
from pathlib import Path
import shutil

# Third-party library to parse APK files
import apkutils

# Standard library for version comparison
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

from .const import DOMAIN

# Import the custom classes as specified by the user
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
    new_devices.append(HbtnModuleUpdate(hbtn_rt, hbtn_cord, len(new_devices)))
    for hbt_module in hbtn_rt.modules:
        new_devices.append(HbtnModuleUpdate(hbt_module, hbtn_cord, len(new_devices)))
        if hbt_module.typ == b"\x01\x04":  # Smart Controller Touch
            new_devices.append(SCTouchAppUpdate(hbt_module, hbtn_rt))

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        # hbtn_cord.data = new_devices
        async_add_entities(new_devices)


class SCTouchAppUpdate(UpdateEntity):
    """Perform SC Touch Android App update."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_name = "SC Touch App"
    _attr_should_poll = True
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(self, module: HbtnModule, router: HbtnRouter) -> None:
        """Initialize the app update entity for a specific module."""
        self._module = module
        self._router = router
        self._hass = router.hass

        self.firmware_dir: Path

        self._attr_unique_id = f"mod_{self._module.uid}_app_update"
        self._attr_device_info = {"identifiers": {(DOMAIN, module.uid)}}
        self._attr_installed_version = getattr(self._module, "client_version", "0.0.0")
        self._attr_latest_version = None
        self._latest_apk_filename: str | None = None

    # --- Private Helper Methods ---
    def scan_firmware_dir_blocking(self):
        """This function contains all the blocking I/O."""
        if not self.firmware_dir.is_dir():
            _LOGGER.debug("Firmware directory not found: %s", self.firmware_dir)
            return None, None

        latest_version = parse_version("0.0.0")
        latest_filename = None

        try:
            # This is all blocking, so it's fine inside the executor job
            for file_path in self.firmware_dir.iterdir():
                if file_path.name.startswith("sctouch_") and file_path.suffix == ".apk":
                    # --- Suppress 'axml' log spam ---
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

                    if not version_name:
                        _LOGGER.warning(
                            "Could not read version from %s", file_path.name
                        )
                        continue

                    apk_version_obj = parse_version(str(version_name))
                    if apk_version_obj > latest_version:
                        latest_version = apk_version_obj
                        latest_filename = file_path.name

            if latest_filename:
                return str(latest_version), latest_filename

        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Error iterating firmware directory: %s", e)

        return None, None

    async def _find_latest_apk(self) -> tuple[str | None, str | None]:
        """Return latest APK version and filename."""
        if self._router.smhub.addon_slug == "":
            _LOGGER.debug("No addon slug available, try local firmware directory")
            self.firmware_dir = (
                Path(self._hass.config.path())
                / "custom_components"
                / DOMAIN
                / "firmware"
            )
        else:
            self.firmware_dir = (
                Path(self._hass.config.path().replace("config", "addon_configs"))
                / self._router.smhub.addon_slug
                / "firmware"
            )

        # Run the entire blocking function in an executor thread
        return await self._hass.async_add_executor_job(self.scan_firmware_dir_blocking)

    async def _copy_apk_to_www(self, filename: str) -> tuple[str | None, str | None]:
        """Copy APK to /www/ and calculate checksum."""
        config_dir = Path(self._hass.config.path())
        source_file = self.firmware_dir / filename
        public_dir = config_dir / "www" / "firmware"
        public_file = public_dir / filename

        def _copy_and_hash_blocking():
            """This function contains all the blocking I/O."""
            try:
                # Create dir (blocking)
                public_dir.mkdir(parents=True, exist_ok=True)

                # Copy file (blocking)
                shutil.copy2(source_file, public_file)

                # Calculate checksum (blocking)
                sha256 = hashlib.sha256()
                with Path.open(public_file, "rb") as f:
                    while True:
                        data = f.read(65536)  # Read in 64k chunks
                        if not data:
                            break
                        sha256.update(data)
                checksum = sha256.hexdigest()

                # /local/ maps to /config/www/
                public_url = (
                    f"{self._hass.config.internal_url}/local/firmware/{filename}"
                )

                return public_url, checksum  # noqa: TRY300

            except FileNotFoundError:
                _LOGGER.error("APK file not found at source: %s", source_file)
            except Exception:
                _LOGGER.exception("Error preparing update file %s", filename)

            return None, None

        # Run the combined blocking function in an executor thread
        return await self._hass.async_add_executor_job(_copy_and_hash_blocking)

    # --- Home Assistant Entity Methods ---

    async def async_update(self) -> None:
        """Check if update needed."""

        latest_version_str, latest_filename = await self._find_latest_apk()

        # 2. Get the currently installed version from the module
        installed_version_str = getattr(self._module, "client_version", "0.0.0")
        if installed_version_str == "unknown":
            installed_version_str = "0.0.0"

        self._attr_latest_version = latest_version_str
        self._attr_installed_version = installed_version_str
        self._latest_apk_filename = latest_filename

        if latest_version_str and (
            parse_version(latest_version_str) > parse_version(installed_version_str)
        ):
            _LOGGER.info(
                "App update %s available for module %s (has %s). Copying file to /www/",
                latest_version_str,
                getattr(self._module, "name", self._module.uid),
                installed_version_str,
            )
            # Perform the copy (non-blocking)
            if latest_filename:
                await self._copy_apk_to_www(latest_filename)

    async def async_install(self, version: str | None, backup: bool) -> None:
        """Send update available to the module's client."""

        module_name = getattr(self._module, "name", self._module.uid)
        latest_version_from_state = self._attr_latest_version

        _LOGGER.info(
            "Install command triggered for module %s. Target version from HA: %s, Target version from state: %s",
            module_name,
            version,  # This was None
            latest_version_from_state,  # This was "1.1.4"
        )

        if latest_version_from_state is None:
            _LOGGER.error("Install failed: Entity has no latest_version set")
            raise HomeAssistantError("Entity state is missing latest_version.")

        # Check if the client is connected
        stream_name = self._module.stream_name
        provider = self._router.smhub.ws_provider
        # Check if the client is connected *using the provider's dictionary*
        if not provider.active_ws_connections.get(stream_name):
            _LOGGER.error(
                "Cannot install: Client for module '%s' (stream: %s) is not connected",
                module_name,
                stream_name,
            )
            raise HomeAssistantError(f"Client {module_name} is not connected.")

        # Get filename (from cache)
        filename = self._latest_apk_filename
        if not filename:
            # Fallback: Rescan if cache is invalid
            _LOGGER.warning("Filename not in cache or mismatch, rescanning")
            latest_ver, latest_file = await self._find_latest_apk()
            if latest_ver == latest_version_from_state and latest_file:
                filename = latest_file
            else:
                _LOGGER.error(
                    "Cannot find APK file for version %s", latest_version_from_state
                )
                raise HomeAssistantError(
                    f"APK file for {latest_version_from_state} not found."
                )

        # Get URL and checksum (file should already be in /www/)
        public_url, checksum = await self._copy_apk_to_www(filename)

        if not public_url or not checksum:
            _LOGGER.error("Failed to copy or get checksum for %s", filename)
            raise HomeAssistantError("Failed to prepare file for download.")

        # Create payload and send update command to the client
        payload = {
            "version": latest_version_from_state,  # Use our correct state
            "filename": filename,
            "url": public_url,
            "checksum": checksum,
        }

        _LOGGER.info("Sending 'habitron/update_available' command to %s", module_name)
        try:
            # The app receives this and shows the dialog (Step 4)
            stream_name = getattr(self._module, "stream_name", None)
            if stream_name:
                await provider.async_send_json_message(
                    stream_name,
                    {
                        "type": "habitron/update_available",
                        "payload": payload,
                    },
                )
            else:
                raise HomeAssistantError(f"Module {module_name} has no stream_name.")

        except Exception as e:  # noqa: BLE001
            _LOGGER.error(
                "Failed to send update command to module %s: %s", module_name, e
            )
            raise HomeAssistantError(f"Failed to send command to client: {e}")

    @property
    def release_notes(self) -> str | None:
        """Return the release notes."""
        return f"Latest version found in firmware folder: {self.latest_version}"


class HbtnModuleUpdate(UpdateEntity):
    """Representation of habitron event."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )
    _attr_should_poll = True  # for push updates

    def __init__(self, module, coord, idx) -> None:
        """Initialize an HbtnEvent, pass coordinator to CoordinatorEntity."""
        super().__init__()
        self.idx = idx
        self._module = module
        self._attr_name = "Firmware"
        self._state = None
        self._attr_unique_id = f"Mod_{self._module.uid}_update"
        self.flash_in_progress = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str | None:
        """Return the display name of this number."""
        return self._attr_name

    @property
    def in_progress(self) -> bool:
        """Update installation in progress."""
        return self.flash_in_progress

    @property
    def update_percentage(self) -> int | None:
        """Return percentage, if available."""
        return None

    async def async_install(self, version: str | None, backup: bool) -> None:
        """Install an update."""

        self.flash_in_progress = True
        self.async_write_ha_state()
        await sleep(0.1)
        if isinstance(self._module, HbtnRouter):
            await self._module.comm.update_firmware(self._module.id, 0)
            self._module.version = version
        else:
            await self._module.comm.update_firmware(
                int(self._module.mod_addr / 100) * 100, self._module.raddr
            )
            self._module.sw_version = version
        self.flash_in_progress = False
        await self.async_update()

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        await super().async_added_to_hass()
        await self.async_update()

    async def async_update(self) -> None:
        """Update properties."""

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
