"""Platform for notification integration."""

import logging

# Import the device class from the component that you want to support
from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._helpers import hbtn_device_info
from .coordinator import HabitronConfigEntry
from .interfaces import IfDescriptor
from .module import HbtnModule

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add event entities for Habitron system."""
    hbtn_rt = entry.runtime_data.router
    new_devices: list[NotifyEntity] = []
    for hbt_module in hbtn_rt.modules:
        if hbt_module.typ in [b"\x01\x02", b"\x01\x03", b"\x32\x01"]:
            new_devices.append(HbtnMessage(hbt_module, len(new_devices)))
        if hbt_module.typ == b"\x1e\x03":
            for sms in hbt_module.gsm_numbers:
                new_devices.append(HbtnGSMMessage(hbt_module, sms, len(new_devices)))

    if new_devices:
        async_add_entities(new_devices)


class HbtnMessage(NotifyEntity):
    """Representation of habitron notification."""

    _attr_has_entity_name = True
    _attr_name = "Messages"

    def __init__(self, module: HbtnModule, idx: int) -> None:
        """Initialize an HbtnEvent, pass coordinator to CoordinatorEntity."""
        super().__init__()
        self.idx = idx
        self._module = module
        self.messages = module.messages
        self._attr_unique_id = f"Mod_{self._module.uid}_msg"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message to the module display.

        If the text matches a stored message name, trigger that stored
        message by its numeric id; otherwise show the text as free text
        (habitron_client 1.0.4+). An empty message clears the display.
        """
        for msg in self.messages:
            if message.replace(" ", "") == msg.name.replace(" ", ""):
                await self._module.comm.send_message(self._module.mod_addr, msg.nmbr)
                return
        await self._module.comm.send_message_text(self._module.mod_addr, message)


class HbtnGSMMessage(NotifyEntity):
    """Representation of habitron notification."""

    _attr_has_entity_name = True

    def __init__(self, module: HbtnModule, gsm_number: IfDescriptor, idx: int) -> None:
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
        return hbtn_device_info(self._module.uid)

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send an SMS via the GSM module.

        Like ``HbtnMessage`` above, free-text payloads are not supported by
        habitron_client 1.0.0; only stored message ids reach the bus. Log
        and skip when the text is not a known entry.
        """
        msg_id = None
        for msg in self.messages:
            if message == msg.name:
                msg_id = msg.nmbr
                break
        if msg_id is None:
            _LOGGER.warning(
                "Cannot send free-text SMS via HbtnGSMMessage: %r is not a"
                " known stored message on module %s",
                message,
                self._module.uid,
            )
            return
        await self._module.comm.send_sms(self._module.mod_addr, msg_id, self.sms_id)
