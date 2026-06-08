"""Tests for the Habitron notify platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.notify import (
    HbtnGSMMessage,
    HbtnMessage,
    async_setup_entry,
)


async def test_notify_setup(setup_integration: MockConfigEntry) -> None:
    """The notify platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def _make_message_module() -> MagicMock:
    """Build a module stub with a messages list and comm hooks."""
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    msg = MagicMock()
    msg.name = "Welcome"
    msg.nmbr = 42
    mod.messages = [msg]
    mod.comm.send_message = AsyncMock()
    mod.comm.send_sms = AsyncMock()
    return mod


def test_message_unique_id_pattern() -> None:
    """HbtnMessage builds a stable, module-scoped unique id."""
    mod = _make_message_module()
    entity = HbtnMessage(mod, 0)
    assert entity.unique_id == "Mod_MOD-1_msg"
    assert "messages" in entity._attr_name.lower()


async def test_message_send_known_message_uses_message_number() -> None:
    """A message whose stripped name matches goes out by number."""
    mod = _make_message_module()
    entity = HbtnMessage(mod, 0)
    await entity.async_send_message(message="Welcome")
    mod.comm.send_message.assert_awaited_with(105, 42)


async def test_message_send_unknown_message_logs_and_skips() -> None:
    """An unknown message no longer sends — the lib only accepts stored ids."""
    mod = _make_message_module()
    entity = HbtnMessage(mod, 0)
    await entity.async_send_message(message="freeform text")
    mod.comm.send_message.assert_not_awaited()


def _make_gsm_module() -> MagicMock:
    """Build a module stub with messages + a single GSM number."""
    mod = _make_message_module()
    return mod


def test_gsm_message_unique_id_includes_sms_number() -> None:
    """HbtnGSMMessage namespaces its unique id by the SMS number."""
    mod = _make_gsm_module()
    sms = MagicMock()
    sms.name = "+49-170-1234567"
    sms.nmbr = 3
    entity = HbtnGSMMessage(mod, sms, 0)
    assert entity.unique_id.startswith("Mod_MOD-1_sms")
    assert "+491701234567" in entity.unique_id


async def test_gsm_send_known_message_routes_to_send_sms() -> None:
    """A known message goes out by message-id over send_sms."""
    mod = _make_gsm_module()
    sms = MagicMock()
    sms.name = "+49-170-1234567"
    sms.nmbr = 3
    entity = HbtnGSMMessage(mod, sms, 0)
    await entity.async_send_message(message="Welcome")
    mod.comm.send_sms.assert_awaited_with(105, 42, 3)


async def test_gsm_send_unknown_message_logs_and_skips() -> None:
    """An unknown SMS message no longer sends — only stored ids are accepted."""
    mod = _make_gsm_module()
    sms = MagicMock()
    sms.name = "+49-170-1234567"
    sms.nmbr = 3
    entity = HbtnGSMMessage(mod, sms, 0)
    await entity.async_send_message(message="hello")
    mod.comm.send_sms.assert_not_awaited()


def test_message_device_info_links_module() -> None:
    """HbtnMessage.device_info points at the module uid."""
    mod = _make_message_module()
    entity = HbtnMessage(mod, 0)
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]


def test_gsm_message_device_info_links_module() -> None:
    """HbtnGSMMessage.device_info points at the module uid."""
    mod = _make_gsm_module()
    sms = MagicMock()
    sms.name = "+49-170-1"
    sms.nmbr = 0
    entity = HbtnGSMMessage(mod, sms, 0)
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]


async def test_async_setup_entry_emits_message_for_smart_controllers(hass) -> None:
    """async_setup_entry emits HbtnMessage for typ b"\\x01\\x02" modules."""
    msg = MagicMock()
    msg.name = "Welcome"
    msg.nmbr = 42
    mod = MagicMock()
    mod.uid = "MOD-1"
    mod.mod_addr = 105
    mod.name = "Touch 1"
    mod.typ = b"\x01\x02"
    mod.messages = [msg]
    mod.gsm_numbers = []

    router = MagicMock()
    router.modules = [mod]
    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    await async_setup_entry(hass, entry, lambda es: added.extend(es))
    assert any(isinstance(e, HbtnMessage) for e in added)


async def test_async_setup_entry_emits_gsm_message_for_gsm_module(hass) -> None:
    """async_setup_entry emits one HbtnGSMMessage per SMS number."""
    msg = MagicMock()
    msg.name = "Welcome"
    msg.nmbr = 42
    sms = MagicMock()
    sms.name = "+49-170-1234567"
    sms.nmbr = 3
    mod = MagicMock()
    mod.uid = "MOD-G"
    mod.mod_addr = 105
    mod.name = "GSM 1"
    mod.typ = b"\x1e\x03"
    mod.messages = [msg]
    mod.gsm_numbers = [sms]

    router = MagicMock()
    router.modules = [mod]
    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    await async_setup_entry(hass, entry, lambda es: added.extend(es))
    assert any(isinstance(e, HbtnGSMMessage) for e in added)


async def test_async_setup_entry_skips_other_modules(hass) -> None:
    """A module with an unrecognised typ does not emit any entity."""
    mod = MagicMock()
    mod.uid = "MOD-X"
    mod.typ = b"\x99\x99"
    mod.messages = []
    mod.gsm_numbers = []

    router = MagicMock()
    router.modules = [mod]
    entry = MagicMock()
    entry.runtime_data.router = router

    added: list = []
    await async_setup_entry(hass, entry, lambda es: added.extend(es))
    assert added == []
