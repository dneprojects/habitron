"""Tests for the Habitron text platform."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.habitron.text import HbtnDisplayText, async_setup_entry
from homeassistant.core import HomeAssistant


def _make_display_module(typ: bytes = b"\x01\x04") -> MagicMock:
    """Build a display-capable module stub with a comm hook."""
    mod = MagicMock()
    mod.uid = "MOD-D"
    mod.mod_addr = 105
    mod.typ = typ
    mod.comm.send_message_text = AsyncMock()
    return mod


def test_display_text_unique_id_and_initial_value() -> None:
    """The text entity has a stable id and starts empty."""
    entity = HbtnDisplayText(_make_display_module())
    assert entity.unique_id == "Mod_MOD-D_message"
    assert entity.native_value == ""


async def test_set_value_sends_free_text_to_module() -> None:
    """Setting the value forwards it to the module via send_message_text."""
    mod = _make_display_module()
    entity = HbtnDisplayText(mod)
    entity.async_write_ha_state = MagicMock()
    await entity.async_set_value("Hello")
    mod.comm.send_message_text.assert_awaited_with(105, "Hello")
    assert entity.native_value == "Hello"


async def test_set_empty_value_clears_display() -> None:
    """An empty value clears the module display."""
    mod = _make_display_module()
    entity = HbtnDisplayText(mod)
    entity.async_write_ha_state = MagicMock()
    await entity.async_set_value("")
    mod.comm.send_message_text.assert_awaited_with(105, "")


def test_device_info_links_module() -> None:
    """The text entity links to the module device."""
    entity = HbtnDisplayText(_make_display_module())
    assert ("habitron", "MOD-D") in entity.device_info["identifiers"]


async def test_async_setup_entry_emits_text_for_all_display_types(
    hass: HomeAssistant,
) -> None:
    """One display-text entity is added per display-capable module type."""
    mods = []
    for typ in (b"\x01\x02", b"\x01\x03", b"\x01\x04", b"\x32\x01", b"\x99\x99"):
        m = _make_display_module(typ)
        m.uid = f"MOD-{typ.hex()}"
        mods.append(m)
    router = MagicMock()
    router.modules = mods
    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    # The four display types each get an entity; b"\x99\x99" is skipped.
    assert len(added) == 4
    assert all(isinstance(e, HbtnDisplayText) for e in added)
