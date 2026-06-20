"""Platform for notification integration."""

import logging
from typing import TYPE_CHECKING

from habitron_client import HbtnCommand, Module

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._helpers import hbtn_device_info
from .coordinator import HabitronConfigEntry

if TYPE_CHECKING:
    from .communicate import HbtnComm

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add notification entities for Habitron GSM modules."""
    smhub = entry.runtime_data
    new_devices: list[NotifyEntity] = []
    for hbt_module in smhub.router.modules:
        if hbt_module.typ == b"\x1e\x03":
            new_devices.extend(
                HbtnGSMMessage(hbt_module, sms, smhub.comm)
                for sms in hbt_module.gsm_numbers
            )

    if new_devices:
        async_add_entities(new_devices)


class HbtnGSMMessage(NotifyEntity):
    """Representation of a Habitron GSM SMS target."""

    _attr_has_entity_name = True

    def __init__(self, module: Module, gsm_number: HbtnCommand, comm: HbtnComm) -> None:
        """Initialize a GSM SMS notify entity."""
        super().__init__()
        self._module = module
        self._comm = comm
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

        Free-text payloads are not supported; only stored message ids reach the
        bus. Log and skip when the text is not a known stored message.
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
        await self._comm.send_sms(self._module.addr, msg_id, self.sms_id)
