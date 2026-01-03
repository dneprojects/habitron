"""Platform for notification integration."""

from __future__ import annotations

# Import the device class from the component that you want to support
from homeassistant.components.notify import NotifyEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add event entities for Habitron system."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    new_devices = []
    for hbt_module in hbtn_rt.modules:
        if hbt_module.typ in [b"\x01\x02", b"\x01\x03", b"\x32\x01"]:
            new_devices.append(HbtnMessage(hbt_module, len(new_devices)))
        if hbt_module.typ in [b"\x1e\x03"]:
            for sms in hbt_module.gsm_numbers:
                new_devices.append(HbtnGSMMessage(hbt_module, sms, len(new_devices)))

    if new_devices:
        async_add_entities(new_devices)


class HbtnMessage(NotifyEntity):
    """Representation of habitron notification."""

    def __init__(self, module, idx) -> None:
        """Initialize an HbtnEvent, pass coordinator to CoordinatorEntity."""
        super().__init__()
        self.idx = idx
        self._module = module
        self.messages = module.messages
        self._attr_name = f"{module.name} messages"
        self._attr_unique_id = f"Mod_{self._module.uid}_msg"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message."""

        msg_id = None
        for msg in self.messages:
            if message.replace(" ", "") == msg.name.replace(" ", ""):
                msg_id = msg.nmbr
                break
        if msg_id is not None:
            await self._module.comm.send_message(self._module.mod_addr, msg_id)
        else:
            await self._module.comm.send_message(self._module.mod_addr, message)


class HbtnGSMMessage(NotifyEntity):
    """Representation of habitron notification."""

    def __init__(self, module, gsm_number, idx) -> None:
        """Initialize an HbtnEvent, pass coordinator to CoordinatorEntity."""
        super().__init__()
        self.idx = idx
        self._module = module
        self.messages = module.messages
        self.sms_id = gsm_number.nmbr
        self.sms_no = gsm_number.name.replace(" ", "").replace("-", "")
        self._attr_name = f"SMS {gsm_number.name}"
        self._attr_unique_id = f"Mod_{self._module.uid}_sms{self.sms_no}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message."""

        msg_id = None
        for msg in self.messages:
            if message == msg.name:
                msg_id = msg.nmbr
                break
        if msg_id is not None:
            await self._module.comm.send_sms(self._module.mod_addr, msg_id, self.sms_id)
        else:
            await self._module.comm.send_sms(
                self._module.mod_addr, message, self.sms_id
            )
