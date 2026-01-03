"""Platform for events integration."""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

# Import the device class from the component that you want to support
from .interfaces import AreaDescriptor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add event entities for Habitron system."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for mod_input in hbt_module.inputs:
            if abs(mod_input.type) == 1:  # pulse switch
                new_devices.append(
                    InputPressed(mod_input, hbt_module, hbtn_cord, len(new_devices))
                )
        if hbt_module.mod_type == "Fanekey":
            new_devices.append(
                FingerDetected(
                    hbt_module.fingers[0], hbt_module, hbtn_cord, len(new_devices)
                )
            )

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices
        async_add_entities(new_devices)

    registry: er.EntityRegistry = er.async_get(hass)
    area_names: dict[int, AreaDescriptor] = hbtn_rt.areas

    for hbt_module in hbtn_rt.modules:
        for mod_input in hbt_module.inputs:
            if (
                abs(mod_input.type) == 1
                and mod_input.area > 0
                and mod_input.area != hbt_module.area_member
            ):  # pulse switch
                entity_entry = registry.async_get_entity_id(
                    "event", DOMAIN, f"Mod_{hbt_module.uid}_evnt{mod_input.nmbr}"
                )
                if entity_entry:
                    registry.async_update_entity(
                        entity_entry, area_id=area_names[mod_input.area].get_name_id()
                    )


class HbtnEvent(EventEntity):
    """Representation of habitron event."""

    def __init__(self, event_if, module, coord, idx) -> None:
        """Initialize an HbtnEvent, pass coordinator to CoordinatorEntity."""
        super().__init__()
        self.idx = idx
        self._if = event_if
        self._module = module
        self._attr_name = f"{module.name} {event_if.name}"
        self._nmbr = event_if.nmbr
        self._state = None
        self._brightness = None
        self._attr_unique_id = f"Mod_{self._module.uid}_evnt{event_if.nmbr}"
        if event_if.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @callback
    def _async_handle_event(self, event: str) -> None:
        """Handle event."""
        self._trigger_event(event, {"extra_data": 123})
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register callbacks for input update."""
        self._if.register_callback(self._async_handle_event)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._if.remove_callback(self._async_handle_event)


class InputPressed(HbtnEvent):
    """Representation of habitron button short press event."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = ["inactive", "single_press", "long_press", "long_press_end"]


class FingerDetected(HbtnEvent):
    """Representation of habitron button short press event."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = ["inactive", "finger"]

    @callback
    def _async_handle_event(self, event: str, user: int, finger: int) -> None:
        """Handle event."""
        if finger > 10:
            # user disabled
            self._trigger_event(
                event, {"user": f"{user * (-1)}", "finger": f"{finger - 128}"}
            )
        else:
            self._trigger_event(event, {"user": f"{user}", "finger": f"{finger}"})
        self.async_write_ha_state()
