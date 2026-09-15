"""Tests for the shared Habitron entity helpers.

These cover the parts of ``_helpers`` that the platform tests only reach
indirectly, if at all: the first-creation area stamp with its propagation to
hidden duplicates, and the two message helpers that resolve an entity through
the registry before touching it.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.habitron._helpers import (
    HbtnAreaMixin,
    async_show_on_display,
    selected_message_id,
)
from custom_components.habitron.const import ATTR_MESSAGE_ID
from homeassistant.exceptions import HomeAssistantError

_HELPERS = "custom_components.habitron._helpers"


class _AreaEntity(HbtnAreaMixin):
    """Minimal entity carrying nothing but the mixin under test."""

    _initial_area_propagate = True


def _entity(*, hidden: bool = True, device_id: str | None = "dev1") -> _AreaEntity:
    """An entity whose registry entry is a hidden switch duplicate."""
    entity = _AreaEntity()
    entity.hass = MagicMock()
    entity.registry_entry = MagicMock(
        entity_id="switch.primary",
        hidden=hidden,
        device_id=device_id,
        original_name="Light",
    )
    return entity


def _duplicates() -> list[MagicMock]:
    """One same-named entity on the device and one unrelated to it."""
    duplicate = MagicMock(entity_id="switch.duplicate", original_name="Light")
    unrelated = MagicMock(entity_id="switch.unrelated", original_name="Other")
    return [duplicate, unrelated]


async def test_initial_area_is_stamped_once() -> None:
    """The stamped area lands on the entity that was just created."""
    entity = _entity(hidden=False)
    entity.set_initial_area("area-2")
    registry = MagicMock()

    with patch(f"{_HELPERS}.er.async_get", return_value=registry):
        await entity.async_added_to_hass()

    registry.async_update_entity.assert_called_once_with(
        "switch.primary", area_id="area-2"
    )


async def test_initial_area_propagates_to_hidden_duplicates() -> None:
    """A hidden entity's area is pushed to same-named duplicates on the device.

    Bus updates leave duplicate hidden entities behind on the switch platform;
    without this, one of them keeps the device area and the entity appears in
    two rooms at once.
    """
    entity = _entity()
    entity.set_initial_area("area-2")
    registry = MagicMock()

    with (
        patch(f"{_HELPERS}.er.async_get", return_value=registry),
        patch(f"{_HELPERS}.er.async_entries_for_device", return_value=_duplicates()),
    ):
        await entity.async_added_to_hass()

    updated = [call.args[0] for call in registry.async_update_entity.call_args_list]
    assert updated == ["switch.primary", "switch.duplicate"]


@pytest.mark.parametrize(
    ("hidden", "device_id"),
    [
        pytest.param(False, "dev1", id="not_hidden"),
        pytest.param(True, None, id="no_device"),
    ],
)
async def test_initial_area_skips_propagation(
    hidden: bool, device_id: str | None
) -> None:
    """Propagation is limited to a hidden entity that belongs to a device."""
    entity = _entity(hidden=hidden, device_id=device_id)
    entity.set_initial_area("area-2")
    registry = MagicMock()

    with (
        patch(f"{_HELPERS}.er.async_get", return_value=registry),
        patch(f"{_HELPERS}.er.async_entries_for_device") as mock_entries,
    ):
        await entity.async_added_to_hass()

    mock_entries.assert_not_called()
    registry.async_update_entity.assert_called_once_with(
        "switch.primary", area_id="area-2"
    )


async def test_no_initial_area_touches_nothing() -> None:
    """Without a stamped area the registry is left alone entirely."""
    entity = _entity()
    registry = MagicMock()

    with patch(f"{_HELPERS}.er.async_get", return_value=registry):
        await entity.async_added_to_hass()

    registry.async_update_entity.assert_not_called()


def test_selected_message_id_reads_the_list_attribute() -> None:
    """The id comes off the select's attribute, not parsed back out of its label."""
    hass = MagicMock()
    hass.states.get.return_value = MagicMock(attributes={ATTR_MESSAGE_ID: 7})
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "select.messages"

    with patch(f"{_HELPERS}.er.async_get", return_value=registry):
        assert selected_message_id(hass, "MOD-1") == 7

    registry.async_get_entity_id.assert_called_once_with(
        "select", "habitron", "MOD-1_stored_message"
    )


@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        pytest.param(None, None, id="no_list_entity"),
        pytest.param("select.messages", None, id="entity_without_state"),
        pytest.param(
            "select.messages", MagicMock(attributes={}), id="state_without_id"
        ),
    ],
)
def test_selected_message_id_without_a_choice_raises(
    entity_id: str | None, state: MagicMock | None
) -> None:
    """Every way of having no selection ends in the same translated error."""
    hass = MagicMock()
    hass.states.get.return_value = state
    registry = MagicMock()
    registry.async_get_entity_id.return_value = entity_id

    with (
        patch(f"{_HELPERS}.er.async_get", return_value=registry),
        pytest.raises(HomeAssistantError) as err,
    ):
        selected_message_id(hass, "MOD-1")

    assert err.value.translation_key == "no_message_selected"


async def test_show_on_display_goes_through_the_text_entity() -> None:
    """The display is written through ``text.set_value``, never past it.

    The text entity is the one place that knows what the display last showed,
    so writing to the bus directly would leave its value standing while the
    display already shows something else.
    """
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    registry = MagicMock()
    registry.async_get_entity_id.return_value = "text.display"

    with patch(f"{_HELPERS}.er.async_get", return_value=registry):
        await async_show_on_display(hass, "MOD-1", "Hello")

    hass.services.async_call.assert_awaited_once_with(
        "text",
        "set_value",
        {"entity_id": "text.display", "value": "Hello"},
        blocking=True,
    )


async def test_show_on_display_without_a_text_entity_raises() -> None:
    """A module with no display entity reports that, rather than failing later."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    registry = MagicMock()
    registry.async_get_entity_id.return_value = None

    with (
        patch(f"{_HELPERS}.er.async_get", return_value=registry),
        pytest.raises(HomeAssistantError) as err,
    ):
        await async_show_on_display(hass, "MOD-1", "Hello")

    assert err.value.translation_key == "no_display_entity"
    hass.services.async_call.assert_not_awaited()
