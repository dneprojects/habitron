"""Provide device triggers for Habitron integration."""

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

# Import DOMAIN from your const file
from .const import DOMAIN

# Dynamically generate the supported trigger types including the 10 fingers
FINGER_TYPES = {f"finger_{i}" for i in range(1, 11)}
TRIGGER_TYPES = {
    "single_press",
    "long_press",
    "long_press_end",
    "finger",
} | FINGER_TYPES

# Define the schema for the trigger
TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required("type"): vol.In(TRIGGER_TYPES),
        vol.Required("entity_id"): cv.entity_id,
    }
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List device triggers for Habitron devices."""
    entity_registry = er.async_get(hass)
    device_entries = er.async_entries_for_device(entity_registry, device_id)
    triggers = []

    for entry in device_entries:
        if entry.domain != "event":
            continue

        capabilities = entry.capabilities or {}
        event_types = capabilities.get("event_types", [])

        # Add all supported event types using list comprehension
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
            ]
        )

    return triggers


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a trigger to the Home Assistant event bus."""
    trigger_type = config["type"]
    entity_id = config["entity_id"]

    # Finger events listen to the specific bus event
    if trigger_type.startswith("finger_") or trigger_type == "finger":
        event_name = "habitron_finger_detected"
    else:
        event_name = "habitron_input_pressed"

    event_data = {
        "entity_id": entity_id,
        "event_type": trigger_type,
    }

    event_config = {
        event_trigger.CONF_PLATFORM: "event",
        event_trigger.CONF_EVENT_TYPE: event_name,
        event_trigger.CONF_EVENT_DATA: event_data,
    }

    event_config = event_trigger.TRIGGER_SCHEMA(event_config)

    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )


# End of file device triggers.
