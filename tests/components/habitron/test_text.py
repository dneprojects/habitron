"""Tests for the Habitron text platform (habitron_client v2 model)."""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock

from habitron_client import HbtnCommand, Module, Router
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.const import DOMAIN
from custom_components.habitron.text import HbtnDisplayText, async_setup_entry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def _module(typ: bytes = b"\x01\x02") -> Module:
    return Module(uid="MOD-1", addr=105, typ=typ, name="SC")


def _comm() -> MagicMock:
    comm = MagicMock()
    comm.send_message_text = AsyncMock()
    comm.send_message = AsyncMock()
    return comm


def test_display_text_unique_id() -> None:
    """The display-text entity exposes a stable unique id and starts empty."""
    entity = HbtnDisplayText(_module(), _comm())
    assert entity.unique_id == "MOD-1_message"
    assert entity.native_value == ""


async def test_display_text_set_value_forwards_to_bus() -> None:
    """Setting a value forwards it to the module display."""
    comm = _comm()
    entity = HbtnDisplayText(_module(), comm)
    entity.async_write_ha_state = MagicMock()
    await entity.async_set_value("Hello")
    comm.send_message_text.assert_awaited_with(105, "Hello")
    assert entity.native_value == "Hello"


async def test_async_setup_entry_only_for_display_modules(hass: HomeAssistant) -> None:
    """A display entity is created for display-capable modules only."""
    display = _module(typ=b"\x01\x02")
    plain = _module(typ=b"\x0a\x01")
    router = Router(uid="ROUTER-1")
    router.modules = [display, plain]
    entry = MagicMock()
    entry.runtime_data.router = router
    entry.runtime_data.comm = _comm()

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    assert len(added) == 1
    assert isinstance(added[0], HbtnDisplayText)


async def test_set_value_service_reaches_bus_and_updates_state(
    hass: HomeAssistant,
    real_setup: Callable[..., Awaitable[tuple[MockConfigEntry, AsyncMock]]],
) -> None:
    """``text.set_value`` forwards to the module display and reflects in state.

    Public path: full setup creates the display-text entity for a display
    module, then a real service call writes the value to the bus client and the
    entity state mirrors it.
    """
    router = Router(uid="rt_1", id=100)
    router.modules = [_module()]
    _entry, client = await real_setup(router)

    entity_id = er.async_get(hass).async_get_entity_id("text", DOMAIN, "MOD-1_message")
    assert entity_id is not None

    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": entity_id, "value": "Hello"},
        blocking=True,
    )
    # comm converts the absolute addr (105) to the bus id (addr - 100 = 5).
    client.send_message_text.assert_awaited_once_with(5, "Hello")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Hello"


def _module_with_messages() -> Module:
    """A display module carrying two stored messages."""
    module = _module()
    module.messages = [
        HbtnCommand(name="Tor offen", nmbr=3),
        HbtnCommand(name="Besuch", nmbr=5),
    ]
    return module


@pytest.mark.parametrize(
    ("typed", "shown"),
    [
        # The stored message by name, spacing ignored on both sides.
        ("Tor offen", "Tor offen"),
        ("  Toroffen ", "Tor offen"),
        # ... and by the id printed in front of it in the messages list.
        ("5", "Besuch"),
        # Anything else is taken as it stands.
        ("Paket abgegeben", "Paket abgegeben"),
        ("", ""),
    ],
)
async def test_set_value_resolves_and_echoes(typed: str, shown: str) -> None:
    """What is typed is resolved first, and the resolved text is what is sent.

    Typing an id leaves the message behind it standing in the entity -- which
    is the confirmation that it was read as an id and not sent as that text.
    Everything reaches the display as text: the id command the stored message
    would otherwise use is not carried out by the SmartHub.
    """
    comm = _comm()
    entity = HbtnDisplayText(_module_with_messages(), comm)
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_value(typed)

    comm.send_message_text.assert_awaited_once_with(105, shown)
    comm.send_message.assert_not_awaited()
    assert entity.native_value == shown


async def test_a_message_named_like_a_number_wins_over_that_id() -> None:
    """A stored message called "5" is what "5" means, not the message with id 5.

    Reading the number first would hide such a message behind another one, and
    the user would have no way to reach it at all.
    """
    module = _module()
    module.messages = [
        HbtnCommand(name="5", nmbr=9),
        HbtnCommand(name="Besuch", nmbr=5),
    ]
    comm = _comm()
    entity = HbtnDisplayText(module, comm)
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_value("5")

    comm.send_message_text.assert_awaited_once_with(105, "5")
    assert entity.native_value == "5"
