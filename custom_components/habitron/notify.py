"""Platform for notification integration."""

import logging
from typing import TYPE_CHECKING

from habitron_client import HbtnCommand, Module

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._helpers import (
    async_show_on_display,
    hbtn_device_info,
    resolve_stored_message,
    selected_message_id,
)
from .const import DOMAIN, SERVICE_CLEAR_SENT_MESSAGE, SERVICE_SEND_SELECTED_MESSAGE
from .coordinator import HabitronConfigEntry
from .text import DISPLAY_TYPES

if TYPE_CHECKING:
    from .communicate import HbtnComm
    from .smart_hub import SmartHub

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add notification entities for display and GSM modules."""
    smhub = entry.runtime_data
    new_devices: list[NotifyEntity] = []
    for hbt_module in smhub.router.modules:
        if hbt_module.typ in DISPLAY_TYPES:
            new_devices.append(HbtnDisplayMessage(hbt_module, smhub))
        if hbt_module.typ == b"\x1e\x03":
            new_devices.extend(
                HbtnGSMMessage(hbt_module, sms, smhub.comm)
                for sms in hbt_module.gsm_numbers
            )

    if new_devices:
        async_add_entities(new_devices)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_SELECTED_MESSAGE, None, "async_send_selected_message"
    )
    platform.async_register_entity_service(
        SERVICE_CLEAR_SENT_MESSAGE, None, "async_clear_sent_message"
    )


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
        self._attr_unique_id = f"{self._module.uid}_sms_{self.sms_no}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send an SMS via the GSM module.

        Free-text payloads are not supported; only stored message ids reach the
        bus. Log and skip when the text is not a known stored message.
        """
        msg_id, _label = resolve_stored_message(self.messages, message)
        if msg_id is None:
            _LOGGER.warning(
                "Cannot send free-text SMS via HbtnGSMMessage: %r is not a"
                " known stored message on module %s",
                message,
                self._module.uid,
            )
            return
        await self._comm.send_sms(self._module.addr, msg_id, self.sms_id)

    async def async_clear_sent_message(self) -> None:
        """Refuse: an SMS cannot be taken back once it has been sent."""
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="sms_cannot_be_cleared"
        )

    async def async_send_selected_message(self) -> None:
        """Send whatever is picked in the module's message list to this number.

        The list says *what*, this entity says *to whom* -- which is why the
        action sits here and not on the list: one module's messages can go to
        any of its numbers.
        """
        await self._comm.send_sms(
            self._module.addr,
            selected_message_id(self.hass, self._module.uid),
            self.sms_id,
        )


class HbtnDisplayMessage(NotifyEntity):
    """A message on a module display, as a notify target.

    Sits beside ``text.<module>_message``: the text entity is the field you
    type into, this one is what an automation or a notification group sends
    to. Both take the same payload and end up on the same display.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "display_message"

    def __init__(self, module: Module, smhub: SmartHub) -> None:
        """Initialize the display notify target."""
        super().__init__()
        self._module = module
        self._smhub = smhub
        self._attr_unique_id = f"{module.uid}_message"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Show ``message`` on the display.

        A stored message is resolved to its text; anything else goes out
        unchanged. An empty message clears the display.
        """
        del title
        await async_show_on_display(self.hass, self._module.uid, message)

    async def async_send_selected_message(self) -> None:
        """Show whatever is currently picked in the module's message list."""
        nmbr = selected_message_id(self.hass, self._module.uid)
        name = next(
            (msg.name for msg in self._module.messages if msg.nmbr == nmbr), str(nmbr)
        )
        await async_show_on_display(self.hass, self._module.uid, name)

    async def async_clear_sent_message(self) -> None:
        """Clear the display, and the text entity's value with it."""
        await async_show_on_display(self.hass, self._module.uid, "")
