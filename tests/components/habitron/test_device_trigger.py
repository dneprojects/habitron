"""Tests for the Habitron device triggers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.habitron.device_trigger import (
    async_attach_trigger,
    async_get_triggers,
)


async def test_get_triggers_no_event_entities(
    hass: HomeAssistant, setup_integration
) -> None:
    """A device with no event entities yields zero triggers."""
    reg = er.async_get(hass)
    # No event entities are created for the unknown device id used here.
    triggers = await async_get_triggers(hass, "unknown-device-id")
    assert triggers == []
    # Touch the registry just to make ruff happy about the unused import.
    assert reg is not None


async def test_get_triggers_filters_inactive_and_finger(
    hass: HomeAssistant, setup_integration
) -> None:
    """``inactive`` and ``finger`` event types are excluded from triggers."""
    reg = er.async_get(hass)
    # Register a fake event entity for an existing device id.
    entry = setup_integration
    smhub = entry.runtime_data
    from homeassistant.helpers import device_registry as dr  # noqa: PLC0415
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("habitron", smhub.uid)},
        name="Test device",
    )
    reg.async_get_or_create(
        domain="event",
        platform="habitron",
        unique_id="test-event-1",
        device_id=device.id,
        capabilities={"event_types": ["single_press", "long_press", "inactive", "finger"]},
    )

    triggers = await async_get_triggers(hass, device.id)
    types = sorted(t["type"] for t in triggers)
    assert types == ["long_press", "single_press"]


async def test_attach_trigger_fires_on_matching_state_change(
    hass: HomeAssistant,
) -> None:
    """The attached trigger fires when the event_type attribute matches."""
    action = AsyncMock()
    config = {
        "platform": "device",
        "domain": "habitron",
        "device_id": "dev-1",
        "entity_id": "event.test",
        "type": "single_press",
    }
    trigger_info = {"id": "trig-1", "idx": "0", "alias": "test-trigger"}

    unsub = await async_attach_trigger(hass, config, action, trigger_info)
    assert callable(unsub)

    # Drive a synthetic state change event into the bus with the
    # expected new_state.attributes.event_type.
    new_state = MagicMock()
    new_state.attributes = {"event_type": "single_press"}
    old_state = MagicMock()
    old_state.attributes = {"event_type": "inactive"}
    hass.states.async_set(
        "event.test",
        "single_press",
        attributes={"event_type": "single_press"},
        context=Context(),
    )
    await hass.async_block_till_done()
    # at least one call must have happened
    assert action.await_count >= 1
    unsub()


async def test_attach_trigger_ignores_non_matching_event(
    hass: HomeAssistant,
) -> None:
    """An event_type other than the configured one is silently dropped."""
    action = AsyncMock()
    config = {
        "platform": "device",
        "domain": "habitron",
        "device_id": "dev-1",
        "entity_id": "event.test2",
        "type": "long_press",
    }
    unsub = await async_attach_trigger(hass, config, action, {})

    hass.states.async_set(
        "event.test2",
        "single_press",
        attributes={"event_type": "single_press"},
    )
    await hass.async_block_till_done()
    assert action.await_count == 0
    unsub()
