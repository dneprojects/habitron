"""Tests for the Habitron text platform (habitron_client v2 model)."""

from unittest.mock import AsyncMock, MagicMock

from habitron_client import Module, Router

from custom_components.habitron.text import HbtnDisplayText, async_setup_entry
from homeassistant.core import HomeAssistant


def _module(typ: bytes = b"\x01\x02") -> Module:
    return Module(uid="MOD-1", addr=105, typ=typ, name="SC")


def _comm() -> MagicMock:
    comm = MagicMock()
    comm.send_message_text = AsyncMock()
    return comm


def test_display_text_unique_id() -> None:
    """The display-text entity exposes a stable unique id and starts empty."""
    entity = HbtnDisplayText(_module(), _comm())
    assert entity.unique_id == "Mod_MOD-1_message"
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
