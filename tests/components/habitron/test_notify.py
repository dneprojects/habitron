"""Tests for the Habitron notify platform (GSM/SMS, v2 model)."""

from unittest.mock import AsyncMock, MagicMock

from habitron_client import HbtnCommand, Module, Router

from custom_components.habitron.notify import HbtnGSMMessage, async_setup_entry
from homeassistant.core import HomeAssistant


def _gsm_module() -> Module:
    module = Module(uid="MOD-GSM", addr=105, typ=b"\x1e\x03", name="GSM")
    module.messages = [HbtnCommand(name="Alarm", nmbr=3)]
    module.gsm_numbers = [HbtnCommand(name="0170 1234", nmbr=1)]
    return module


def _comm() -> MagicMock:
    comm = MagicMock()
    comm.send_sms = AsyncMock()
    return comm


def test_gsm_message_unique_id() -> None:
    """The SMS entity exposes a stable unique id derived from the number."""
    module = _gsm_module()
    entity = HbtnGSMMessage(module, module.gsm_numbers[0], _comm())
    assert entity.unique_id == "Mod_MOD-GSM_sms01701234"
    assert entity.name == "SMS 0170 1234"


async def test_gsm_message_sends_known_message() -> None:
    """A stored message name is resolved and sent as an SMS."""
    comm = _comm()
    module = _gsm_module()
    entity = HbtnGSMMessage(module, module.gsm_numbers[0], comm)
    await entity.async_send_message("Alarm")
    comm.send_sms.assert_awaited_with(105, 3, 1)


async def test_gsm_message_unknown_text_skipped() -> None:
    """A free-text message that is not a stored entry is skipped."""
    comm = _comm()
    module = _gsm_module()
    entity = HbtnGSMMessage(module, module.gsm_numbers[0], comm)
    await entity.async_send_message("free text")
    comm.send_sms.assert_not_awaited()


async def test_async_setup_entry_builds_sms_entities(hass: HomeAssistant) -> None:
    """async_setup_entry creates one SMS entity per GSM number."""
    module = _gsm_module()
    router = Router(uid="ROUTER-1")
    router.modules = [module]
    entry = MagicMock()
    entry.runtime_data.router = router
    entry.runtime_data.comm = _comm()

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    assert len(added) == 1
    assert isinstance(added[0], HbtnGSMMessage)
