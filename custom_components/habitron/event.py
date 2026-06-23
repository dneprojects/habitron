"""Platform for events integration."""

from habitron_client import BusMember, Finger, Input, Module

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._helpers import async_assign_entity_area, hbtn_device_info
from .coordinator import HabitronConfigEntry

PARALLEL_UPDATES = 1

# Input press codes carried on the member value by ``apply_event``.
INP_EVENT_TYPES = ["inactive", "single_press", "long_press", "long_press_end"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add event entities for Habitron system."""
    smhub = entry.runtime_data
    hbtn_rt = smhub.router

    new_devices: list[EventEntity] = []
    for hbt_module in hbtn_rt.modules:
        for mod_input in hbt_module.inputs:
            if abs(mod_input.type) == 1:  # pulse switch
                new_devices.append(
                    InputPressed(mod_input, hbt_module, len(new_devices))
                )
        if hbt_module.mod_type == "Fanekey":
            new_devices.append(
                FingerDetected(hbt_module.fingers[0], hbt_module, len(new_devices))
            )
            for user_obj in hbt_module.ids:
                new_devices.append(
                    EkeyUserEvent(
                        hbt_module.fingers[0],
                        hbt_module,
                        len(new_devices),
                        user_obj.nmbr,
                        user_obj.name,
                    )
                )

    if new_devices:
        async_add_entities(new_devices)

    registry: er.EntityRegistry = er.async_get(hass)
    area_reg = ar.async_get(hass)
    area_ids = {
        area.nmbr: area_reg.async_get_or_create(area.name).id for area in hbtn_rt.areas
    }

    for hbt_module in hbtn_rt.modules:
        for mod_input in hbt_module.inputs:
            if abs(mod_input.type) == 1:  # pulse switch
                async_assign_entity_area(
                    registry,
                    domain="event",
                    unique_id=f"Mod_{hbt_module.uid}_evnt{mod_input.nmbr}",
                    area_index=mod_input.area,
                    area_member=hbt_module.area,
                    area_ids=area_ids,
                )


class HbtnEvent(EventEntity):
    """Base representation of a Habitron event entity."""

    _attr_translation_key = "hbtn_event"

    def __init__(self, event_if: BusMember, module: Module, idx: int) -> None:
        """Initialize an HbtnEvent bound to a model member."""
        super().__init__()
        self.idx = idx
        self._if = event_if
        self._module = module
        self._attr_name = f"{event_if.name}"
        self._nmbr = event_if.nmbr
        self._attr_unique_id = f"Mod_{module.uid}_evnt{event_if.nmbr}"
        if event_if.type < 0:
            self._attr_entity_registry_enabled_default = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @callback
    def _handle_member_update(self) -> None:
        """React to a member change (overridden per event kind)."""

    async def async_added_to_hass(self) -> None:
        """Subscribe to the member's change notifications."""
        await super().async_added_to_hass()
        self._if.add_listener(self._handle_member_update)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe the member listener."""
        self._if.remove_listener(self._handle_member_update)


class InputPressed(HbtnEvent):
    """A Habitron button (short/long) press event."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_has_entity_name = True
    _attr_event_types = ["single_press", "long_press", "long_press_end"]

    def __init__(self, event_if: Input, module: Module, idx: int) -> None:
        """Initialize the button-press event."""
        super().__init__(event_if, module, idx)
        self._input = event_if

    @callback
    def _handle_member_update(self) -> None:
        """Translate the input press code into a button event."""
        code = int(self._input.value)
        if not 0 <= code < len(INP_EVENT_TYPES):
            return
        event = INP_EVENT_TYPES[code]
        # The "inactive" reset (code 0) is a state reset, not a button event.
        if event not in self.event_types:
            return
        self._trigger_event(event)
        self.async_write_ha_state()


class FingerDetected(HbtnEvent):
    """A Fanekey finger-detected event (with user/finger attributes)."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_has_entity_name = True
    _attr_event_types = ["finger"]

    def __init__(self, event_if: Finger, module: Module, idx: int) -> None:
        """Initialize the finger-detected event."""
        super().__init__(event_if, module, idx)
        self._finger = event_if
        self._attr_extra_state_attributes = {"last_user": None, "last_finger": None}

    @callback
    def _handle_member_update(self) -> None:
        """Fire the finger event from the member's raw user/finger values."""
        user = self._finger.user
        finger = self._finger.value
        if not 1 <= finger <= 138:  # 0 is the inactive reset
            return
        if finger > 10:  # disabled user
            user = user * -1
            finger = finger - 128
        self._trigger_event("finger", {"user": f"{user}", "finger": f"{finger}"})
        self._attr_extra_state_attributes = {"last_user": user, "last_finger": finger}
        self.async_write_ha_state()


class EkeyUserEvent(HbtnEvent):
    """A per-user Fanekey event firing a finger-specific event type."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_has_entity_name = True

    _FINGER_NAMES = {
        1: "left_pinky",
        2: "left_ring",
        3: "left_middle",
        4: "left_index",
        5: "left_thumb",
        6: "right_thumb",
        7: "right_index",
        8: "right_middle",
        9: "right_ring",
        10: "right_pinky",
    }

    def __init__(
        self, event_if: Finger, module: Module, idx: int, u_id: int, u_name: str
    ) -> None:
        """Initialize a per-user finger event."""
        super().__init__(event_if, module, idx)
        self._finger = event_if
        self._u_id = u_id
        self._attr_event_types = list(self._FINGER_NAMES.values())
        self._attr_name = f"{u_name}"
        self._attr_unique_id = f"Mod_{module.uid}_u{u_id}"

    @callback
    def _handle_member_update(self) -> None:
        """Fire a finger-named event when the matching user is detected."""
        user = self._finger.user
        finger = self._finger.value
        if finger > 10:  # disabled user
            user = user * -1
            finger = finger - 128
        if user == self._u_id and 1 <= finger <= 10:
            self._trigger_event(self._FINGER_NAMES[finger], {"finger_id": finger})
            self.async_write_ha_state()
