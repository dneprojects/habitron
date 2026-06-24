"""Tests for the Habitron update platform (habitron_client v2 model)."""

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Module, Router
import pytest

from custom_components.habitron.update import (
    HbtnModuleUpdate,
    SCTouchAppUpdate,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


def _fw_coord() -> MagicMock:
    coord = MagicMock()
    coord.data = {}
    coord.comm = MagicMock()
    coord.comm.update_firmware = AsyncMock()
    return coord


def _module() -> Module:
    return Module(
        uid="MOD-1", addr=105, typ=b"\x0a\x01", name="Out", sw_version="1.2.0"
    )


# ---------------------------------------------------------------------------
# HbtnModuleUpdate
# ---------------------------------------------------------------------------


def test_module_update_unique_id_and_installed_version() -> None:
    """The firmware update entity reflects the module's installed version."""
    entity = HbtnModuleUpdate(_module(), _fw_coord(), 0)
    assert entity.unique_id == "Mod_MOD-1_update"
    assert entity.installed_version == "1.2.0"


def test_module_update_reflects_coordinator_versions() -> None:
    """The entity picks up installed/latest from the firmware coordinator."""
    coord = _fw_coord()
    coord.data = {"MOD-1": ("1.2.0", "1.3.0")}
    entity = HbtnModuleUpdate(_module(), coord, 0)
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.installed_version == "1.2.0"
    assert entity.latest_version == "1.3.0"


async def test_module_update_install_module() -> None:
    """Installing a module firmware calls update_firmware with the module addr."""
    coord = _fw_coord()
    entity = HbtnModuleUpdate(_module(), coord, 0)
    entity.async_write_ha_state = MagicMock()
    with patch("custom_components.habitron.update.sleep", new=AsyncMock()):
        await entity.async_install("1.3.0", backup=False)
    coord.comm.update_firmware.assert_awaited_with(105)
    assert entity.installed_version == "1.3.0"


async def test_module_update_install_router() -> None:
    """Installing router firmware targets the router id."""
    coord = _fw_coord()
    router = Router(uid="ROUTER-1", version="2.0.0")
    entity = HbtnModuleUpdate(router, coord, 0)
    entity.async_write_ha_state = MagicMock()
    with patch("custom_components.habitron.update.sleep", new=AsyncMock()):
        await entity.async_install("2.1.0", backup=False)
    coord.comm.update_firmware.assert_awaited_with(router.id)


# ---------------------------------------------------------------------------
# SCTouchAppUpdate
# ---------------------------------------------------------------------------


def _smhub() -> MagicMock:
    smhub = MagicMock()
    smhub.hass = MagicMock()
    smhub.addon_slug = ""
    smhub.ws_provider = None
    return smhub


def test_sctouch_app_update_defaults() -> None:
    """The Touch app update entity exposes a stable id and default version."""
    module = Module(uid="MOD-T", addr=104, typ=b"\x01\x04", name="Touch")
    entity = SCTouchAppUpdate(module, _smhub())
    assert entity.unique_id == "mod_MOD-T_app_update"
    assert entity.installed_version == "0.0.0"
    assert "Latest APK version" in (entity.release_notes() or "")


async def test_sctouch_app_install_without_version_raises() -> None:
    """Install raises when no latest APK version is known."""
    module = Module(uid="MOD-T", addr=104, typ=b"\x01\x04", name="Touch")
    entity = SCTouchAppUpdate(module, _smhub())
    entity._attr_latest_version = None
    with pytest.raises(HomeAssistantError):
        await entity.async_install(None, backup=False)


async def test_sctouch_app_install_sends_absolute_url(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """A successful install sends a fully-qualified URL with a scheme.

    Regression guard: the URL must come from ``get_url`` (always absolute),
    not from ``hass.config.internal_url`` which is ``None`` unless configured
    and would otherwise yield a scheme-less address the Touch app rejects.
    """
    apk = tmp_path / "sctouch_v1.3.0.apk"
    apk.write_bytes(b"payload")
    expected_checksum = hashlib.sha256(b"payload").hexdigest()

    module = Module(uid="MOD-T", addr=104, typ=b"\x01\x04", name="Touch")
    smhub = _smhub()
    smhub.hass = hass
    provider = MagicMock()
    provider.active_ws_connections = {"": True}
    provider.async_send_json_message = AsyncMock()
    smhub.ws_provider = provider

    entity = SCTouchAppUpdate(module, smhub)
    entity.firmware_dir = tmp_path
    entity._attr_latest_version = "1.3.0"
    entity._latest_apk_filename = "sctouch_v1.3.0.apk"

    with patch(
        "custom_components.habitron.update.get_url",
        return_value="http://ha.local:8123",
    ):
        await entity.async_install("1.3.0", backup=False)

    provider.async_send_json_message.assert_awaited_once()
    _stream, message = provider.async_send_json_message.await_args.args
    payload = message["payload"]
    assert payload["url"] == "http://ha.local:8123/habitron-firmware/sctouch_v1.3.0.apk"
    assert payload["checksum"] == expected_checksum


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_async_setup_entry_emits_updates(hass: HomeAssistant) -> None:
    """Setup emits a router + per-module firmware update and a Touch app update."""
    module = _module()
    touch = Module(uid="MOD-T", addr=104, typ=b"\x01\x04", name="Touch")
    router = Router(uid="ROUTER-1", version="2.0.0")
    router.modules = [module, touch]
    smhub = _smhub()
    smhub.router = router
    smhub.comm = MagicMock()
    entry = MagicMock()
    entry.runtime_data = smhub

    added: list = []
    with patch(
        "custom_components.habitron.update.HbtnFirmwareCoordinator"
    ) as coord_cls:
        coord = coord_cls.return_value
        coord.data = {}
        coord.async_refresh = AsyncMock()
        coord.async_add_listener = MagicMock(return_value=lambda: None)
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    assert (
        sum(isinstance(e, HbtnModuleUpdate) for e in added) == 3
    )  # router + 2 modules
    assert any(isinstance(e, SCTouchAppUpdate) for e in added)
