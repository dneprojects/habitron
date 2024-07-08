"""Platform for update integration."""

from __future__ import annotations

from asyncio import sleep

# Import the device class from the component that you want to support
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .router import HbtnRouter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add update entities for Habitron system."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    if hbtn_rt.smhub.is_smhub:
        # Update support restricted to SmartHub
        new_devices.append(HbtnModuleUpdate(hbtn_rt, hbtn_cord, len(new_devices)))
        for hbt_module in hbtn_rt.modules:
            new_devices.append(
                HbtnModuleUpdate(hbt_module, hbtn_cord, len(new_devices))
            )
    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices
        async_add_entities(new_devices)


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
    def in_progress(self) -> bool | int:
        """Update installation in progress."""
        return self.flash_in_progress

    async def async_install(self, version: str | None, backup: bool) -> None:
        """Install an update."""

        self.flash_in_progress = True
        self.async_write_ha_state()
        await sleep(0.1)
        if isinstance(self._module, HbtnRouter):
            resp = await self._module.comm.update_firmware(self._module.id, 0)
            self._module.version = version
        else:
            resp = await self._module.comm.update_firmware(
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
        versions = resp.decode("iso8859-1").split("\n")
        if len(versions) == 2:
            self._attr_latest_version = versions[1]
            self._attr_installed_version = versions[0]
            self.async_write_ha_state()
