"""Text platform for Habitron module displays."""

import logging

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._helpers import hbtn_device_info
from .coordinator import HabitronConfigEntry
from .module import HbtnModule

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
    hbtn_rt = entry.runtime_data.router
    new_devices = [
        HbtnDisplayText(hbt_module)
        for hbt_module in hbtn_rt.modules
        if hbt_module.typ in DISPLAY_TYPES
    ]
    if new_devices:
        async_add_entities(new_devices)


class HbtnDisplayText(TextEntity):
    """Free-text message shown on a Habitron module display."""

    _attr_has_entity_name = True
    _attr_translation_key = "message"
    _attr_native_value = ""

    def __init__(self, module: HbtnModule) -> None:
        """Initialize the display-text entity."""
        self._module = module
        self._attr_unique_id = f"Mod_{module.uid}_message"
        self._attr_device_info = hbtn_device_info(module.uid)

    async def async_set_value(self, value: str) -> None:
        """Show ``value`` on the module display (an empty string clears it)."""
        await self._module.comm.send_message_text(self._module.mod_addr, value)
        self._attr_native_value = value
        self.async_write_ha_state()
