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
            # Keep the general finger entity
            new_devices.append(
                FingerDetected(
                    hbt_module.fingers[0], hbt_module, hbtn_cord, len(new_devices)
                )
            )

            # Create one entity per user, removing the German name list here
            for user_obj in hbt_module.ids:
                u_id = user_obj.nmbr if hasattr(user_obj, "nmbr") else user_obj.id
                u_name = user_obj.name

                new_devices.append(
                    EkeyUserEvent(
                        hbt_module.fingers[0],
                        hbt_module,
                        hbtn_cord,
                        len(new_devices),
                        u_id,
                        u_name,
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
            if abs(mod_input.type) == 1:  # pulse switch
                entity_entry = registry.async_get_entity_id(
                    "event", DOMAIN, f"Mod_{hbt_module.uid}_evnt{mod_input.nmbr}"
                )
                if entity_entry:
                    area_index = mod_input.area
                    if area_index in [0, hbt_module.area_member]:
                        registry.async_update_entity(
                            entity_entry, area_id=None
                        )  # default
                    else:
                        registry.async_update_entity(
                            entity_entry, area_id=area_names[area_index].get_name_id()
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

    @callback
    def _async_handle_event(self, event: str) -> None:
        """Handle event."""
        # Call standard trigger for the event entity
        self._trigger_event(event, {"extra_data": 123})

        # Prepare data for the custom event
        event_data = {
            "entity_id": self.entity_id,
            "event_type": event,
            "module_uid": self._module.uid,
        }

        # Fire an explicit event to the HA event bus
        self.hass.bus.async_fire("hbtn_input_pressed", event_data)

        # Update the state of the entity
        self.async_write_ha_state()


class FingerDetected(HbtnEvent):
    """Representation of habitron button short press event."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = ["inactive", "finger"]

    def __init__(self, event_if, module, coord, idx) -> None:
        """Initialize FingerDetected and setup extra attributes."""
        super().__init__(event_if, module, coord, idx)
        # Initialize attributes to be visible in HA UI
        self._attr_extra_state_attributes = {
            "last_user": None,
            "last_finger": None,
        }

    @callback
    def _async_handle_event(self, event: str, user: int, finger: int) -> None:
        """Handle event."""
        if finger > 10:
            # user disabled
            user = user * (-1)
            finger = finger - 128
        self._trigger_event(event, {"user": f"{user}", "finger": f"{finger}"})

        # Update attributes to show in HA frontend directly
        self._attr_extra_state_attributes = {
            "last_user": user,
            "last_finger": finger,
        }

        # Fire an explicit event to the HA event bus
        self.hass.bus.async_fire(
            "hbtn_finger_detected",
            {
                "entity_id": self.entity_id,
                "event_type": event,
                "user": user,
                "finger": finger,
            },
        )

        self.async_write_ha_state()


class EkeyUserEvent(HbtnEvent):
    """Representation of a specific user event."""

    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(self, event_if, module, coord, idx, u_id, u_name) -> None:
        """Initialize specific user event."""
        super().__init__(event_if, module, coord, idx)
        self._u_id = u_id

        # Technical keys for UI mapping
        self._attr_event_types = [f"finger_{i}" for i in range(1, 11)]

        # Name formulation
        self._attr_name = f"{module.name} {u_name}"
        self._attr_unique_id = f"Mod_{self._module.uid}_u{u_id}"

    @callback
    def _async_handle_event(self, event: str, user: int, finger: int) -> None:
        """Handle event and match user ID."""
        if finger > 10:
            # Handle disabled users
            calc_user = user * (-1)
            calc_finger = finger - 128
        else:
            calc_user = user
            calc_finger = finger

        if calc_user == self._u_id:
            if 1 <= calc_finger <= 10:
                # Use technical key for the triggered event
                finger_event_type = f"finger_{calc_finger}"

                self._trigger_event(finger_event_type, {"finger_id": calc_finger})

                # Fire the bus event so device_trigger.py can catch it
                self.hass.bus.async_fire(
                    "habitron_finger_detected",
                    {
                        "entity_id": self.entity_id,
                        "event_type": finger_event_type,
                        "user": calc_user,
                        "finger": calc_finger,
                    },
                )

                self.async_write_ha_state()


# End of file event classes.
