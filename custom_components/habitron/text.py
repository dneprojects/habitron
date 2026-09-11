"""Text platform for Habitron module displays."""

import logging
from typing import TYPE_CHECKING

from habitron_client import Module

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._helpers import hbtn_device_info, resolve_stored_message
from .coordinator import HabitronConfigEntry

if TYPE_CHECKING:
    from .communicate import HbtnComm

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# Module types whose display is driven by the bus ``send_message_text``
# command: the Smart Controllers, incl. Smart Touch (b"\x01\x04").
DISPLAY_TYPES = (b"\x01\x02", b"\x01\x03", b"\x01\x04", b"\x32\x01")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a display-text entity for each display-capable module."""
    smhub = entry.runtime_data
    new_devices = [
        HbtnDisplayText(hbt_module, smhub.comm)
        for hbt_module in smhub.router.modules
        if hbt_module.typ in DISPLAY_TYPES
    ]
    if new_devices:
        async_add_entities(new_devices)


class HbtnDisplayText(TextEntity):
    """Free-text message shown on a Habitron module display."""

    _attr_has_entity_name = True
    _attr_translation_key = "message"
    _attr_native_value = ""

    def __init__(self, module: Module, comm: HbtnComm) -> None:
        """Initialize the display-text entity."""
        self._module = module
        self._comm = comm
        self._attr_unique_id = f"{module.uid}_message"
        self._attr_device_info = hbtn_device_info(module.uid)

    async def async_set_value(self, value: str) -> None:
        """Show ``value`` on the module display.

        What is typed is resolved against the module's stored messages first --
        by name, or by the number printed in front of it in the list, spacing
        ignored either way -- and it is that *resolved* text which goes to the
        display and stays in this entity, so typing "3" leaves the message
        behind that id standing here. Anything matching no stored message goes
        out unchanged. An empty value clears the display.

        Everything is sent as display text (``1E 11 01``). Triggering a stored
        message by its id (``1E 11 03``) is not an option: the SmartHub
        acknowledges that command on the bus with ``OK`` but logs "Meldung auf
        Zeit setzen noch nicht implementiert" and never passes it on to the
        module -- with any display time, the id's own text included. Resolving
        here does what the hub would have done anyway.
        """
        _nmbr, label = resolve_stored_message(self._module.messages, value)
        await self._comm.send_message_text(self._module.addr, label)
        self._attr_native_value = label
        self.async_write_ha_state()
