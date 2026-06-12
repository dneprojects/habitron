"""Provide device triggers for Habitron integration."""

from typing import Any

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

# Use dynamic string validation instead of hardcoded types
TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required("type"): cv.string,
        vol.Required("entity_id"): cv.entity_id,
    }
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List device triggers for Habitron devices."""
    entity_registry = er.async_get(hass)
    device_entries = er.async_entries_for_device(entity_registry, device_id)

    triggers: list[dict[str, str]] = []

    for entry in device_entries:
        if entry.domain != "event":
            continue

        # Get capabilities securely
        capabilities = entry.capabilities or {}
        event_types = capabilities.get("event_types", [])

        # Create trigger list based on capabilities
        triggers.extend(
            [
                {
                    "platform": "device",
                    "domain": DOMAIN,
                    "device_id": device_id,
                    "entity_id": entry.entity_id,
                    "type": evt_type,
                }
                for evt_type in event_types
                if evt_type not in ("inactive", "finger")
            ]
        )

    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger to the HA event bus."""
    trigger_type = config["type"]
    entity_id = config["entity_id"]

    # Use native state event listener to catch all fast changes
    @callback
    def filter_event_type_action(
        event: Event[EventStateChangedData],
    ) -> None:
        """Filter the state change by event_type attribute."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        # Ignore if entity was removed
        if new_state is None:
            return

        new_event_type = new_state.attributes.get("event_type")
        old_event_type = old_state.attributes.get("event_type") if old_state else None

        # Only execute if the event_type matches our selected UI trigger
        if new_event_type == trigger_type and new_event_type != old_event_type:
            # Build variables payload for automation execution
            trigger_payload: dict[str, Any] = {
                "platform": "device",
                "domain": DOMAIN,
                "device_id": config["device_id"],
                "entity_id": entity_id,
                "type": trigger_type,
                "description": f"habitron event {trigger_type}",
            }

            # Forward the upstream trigger-data identifiers if present.
            trigger_data = trigger_info["trigger_data"]
            trigger_payload["id"] = trigger_data["id"]
            trigger_payload["idx"] = trigger_data["idx"]
            if trigger_data["alias"] is not None:
                trigger_payload["alias"] = trigger_data["alias"]

            variables = {"trigger": trigger_payload}
            hass.async_create_task(action(variables, context=event.context))

    # Attach the state trigger using our filter callback directly on the event bus
    return async_track_state_change_event(hass, [entity_id], filter_event_type_action)


# End of file device triggers
