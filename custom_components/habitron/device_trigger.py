"""Provide device triggers for Habitron integration."""

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import state as state_trigger
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
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

    triggers = []

    for entry in device_entries:
        if entry.domain != "event":
            continue

        # Get capabilities securely
        capabilities = entry.capabilities or {}
        event_types = capabilities.get("event_types", [])

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

    # Use native state trigger to listen to EventEntity timestamp changes
    state_config = {
        state_trigger.CONF_PLATFORM: "state",
        state_trigger.CONF_ENTITY_ID: entity_id,
    }
    state_config = state_trigger.TRIGGER_SCHEMA(state_config)

    @callback
    async def filter_event_type_action(variables, context=None):
        """Filter the state change by event_type attribute."""
        to_state = variables.get("trigger", {}).get("to_state")

        # Only execute if the event_type matches our selected UI trigger
        if to_state and to_state.attributes.get("event_type") == trigger_type:
            await action(variables, context=context)

    # Attach the state trigger using our filter callback
    return await state_trigger.async_attach_trigger(
        hass,
        state_config,
        filter_event_type_action,
        trigger_info,
        platform_type="device",
    )


# End of file device triggers
