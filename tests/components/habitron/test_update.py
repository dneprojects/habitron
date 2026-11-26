"""Tests for the Habitron update platform (habitron_client v2 model)."""

import hashlib
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from habitron_client import Module, Router
import pytest
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.habitron.update import (
    _TOUCH_APP_ENTITIES,
    HbtnFirmwareView,
    HbtnModuleUpdate,
    SCTouchAppUpdate,
    _async_register_firmware_view,
    async_setup_entry,
)
from homeassistant.components.http import KEY_HASS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component


def _fw_coord() -> MagicMock:
    coord = MagicMock()
    coord.data = {}
    coord.client = AsyncMock()
    # The firmware coordinator reaches the bus through its status parent.
    coord.status = MagicMock()
    coord.status.update_firmware = AsyncMock()
    return coord


def _module() -> Module:
    return Module(uid="MOD-1", addr=5, typ=b"\x0a\x01", name="Out", sw_version="1.2.0")


# ---------------------------------------------------------------------------
# HbtnModuleUpdate
# ---------------------------------------------------------------------------


def test_module_update_unique_id_and_installed_version() -> None:
    """The firmware update entity reflects the module's installed version."""
    entity = HbtnModuleUpdate(_module(), _fw_coord(), 0)
    assert entity.unique_id == "MOD-1_firmware_update"
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
    coord.status.update_firmware.assert_awaited_with(5)
    assert entity.installed_version == "1.3.0"


async def test_module_update_install_router() -> None:
    """Installing router firmware targets the router id."""
    coord = _fw_coord()
    router = Router(uid="ROUTER-1", version="2.0.0")
    entity = HbtnModuleUpdate(router, coord, 0)
    entity.async_write_ha_state = MagicMock()
    with patch("custom_components.habitron.update.sleep", new=AsyncMock()):
        await entity.async_install("2.1.0", backup=False)
    coord.status.update_firmware.assert_awaited_with(0)


# ---------------------------------------------------------------------------
# SCTouchAppUpdate
# ---------------------------------------------------------------------------


def _hub_coord() -> MagicMock:
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.addon_slug = ""
    coordinator.ws_provider = None
    return coordinator


def test_sctouch_app_update_defaults() -> None:
    """The Touch app update entity exposes a stable id and default version."""
    module = Module(uid="MOD-T", addr=4, typ=b"\x01\x04", name="Touch")
    entity = SCTouchAppUpdate(module, _hub_coord())
    assert entity.unique_id == "MOD-T_app_update"
    assert entity.installed_version == "0.0.0"
    assert "Latest APK version" in (entity.release_notes() or "")


async def test_sctouch_app_install_without_version_raises() -> None:
    """Install raises when no latest APK version is known."""
    module = Module(uid="MOD-T", addr=4, typ=b"\x01\x04", name="Touch")
    entity = SCTouchAppUpdate(module, _hub_coord())
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

    module = Module(uid="MOD-T", addr=4, typ=b"\x01\x04", name="Touch")
    coordinator = _hub_coord()
    coordinator.hass = hass
    provider = MagicMock()
    provider.active_ws_connections = {"": True}
    provider.async_send_json_message = AsyncMock()
    coordinator.ws_provider = provider

    entity = SCTouchAppUpdate(module, coordinator)
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
    assert (
        payload["url"]
        == "http://ha.local:8123/habitron-firmware/MOD-T/sctouch_v1.3.0.apk"
    )
    assert payload["checksum"] == expected_checksum


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_async_setup_entry_emits_updates(hass: HomeAssistant) -> None:
    """Setup emits a router + per-module firmware update and a Touch app update."""
    assert await async_setup_component(hass, "http", {})
    module = _module()
    touch = Module(uid="MOD-T", addr=4, typ=b"\x01\x04", name="Touch")
    router = Router(uid="ROUTER-1", version="2.0.0")
    router.modules = [module, touch]
    coordinator = _hub_coord()
    coordinator.router = router
    coordinator.client = AsyncMock()
    entry = MagicMock()
    entry.runtime_data = coordinator

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
    # A Touch panel needs the APK download route.
    assert _TOUCH_APP_ENTITIES in hass.data


def _touch_app_entity() -> SCTouchAppUpdate:
    """A Touch app update entity, detached from any hub."""
    module = Module(uid="MOD-T", addr=4, typ=b"\x01\x04", name="Touch")
    return SCTouchAppUpdate(module, _hub_coord())


def test_scan_creates_the_firmware_directory(tmp_path: Path) -> None:
    """A missing firmware directory is created, not complained about.

    This is where the user drops the APK; making them create it by hand first
    is a step no log line can convey. Empty is a valid state -- the entity then
    simply offers nothing to install.
    """
    entity = _touch_app_entity()
    entity.firmware_dir = tmp_path / "habitron" / "firmware"

    assert entity.scan_firmware_dir_blocking() == (None, None)

    assert entity.firmware_dir.is_dir()


def test_scan_reports_a_directory_it_cannot_create_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A directory that cannot be created is worth saying -- once.

    Unlike the missing directory, this one is a real fault, but the scan runs
    on every poll, so repeating it would fill the log.
    """
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("")
    entity = _touch_app_entity()
    entity.firmware_dir = blocked / "firmware"

    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            assert entity.scan_firmware_dir_blocking() == (None, None)

    assert (
        sum("Cannot create the firmware directory" in r.message for r in caplog.records)
        == 1
    )


# ---------------------------------------------------------------------------
# APK download route
# ---------------------------------------------------------------------------


async def _serving_entity(hass: HomeAssistant, firmware_dir: Path) -> SCTouchAppUpdate:
    """A Touch app entity whose APKs the download route serves."""
    assert await async_setup_component(hass, "http", {})
    _async_register_firmware_view(hass)
    module = Module(uid="MOD-T", addr=4, typ=b"", name="Touch")
    coordinator = _hub_coord()
    coordinator.hass = hass
    entity = SCTouchAppUpdate(module, coordinator)
    entity.firmware_dir = firmware_dir
    hass.data[_TOUCH_APP_ENTITIES]["MOD-T"] = entity
    return entity


async def test_download_follows_a_changed_firmware_directory(
    hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator, tmp_path: Path
) -> None:
    """The APK comes from the directory the entity uses now, not at setup.

    Regression: the directory used to be bound once per HA run. When the
    add-on slug became known only after a reload, update and checksum came
    from ``/share/<slug>/firmware`` while the download still pointed to the
    old directory -- the panel got a 404.
    """
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    new_dir = tmp_path / "new"
    new_dir.mkdir()
    (new_dir / "sctouch_v1.4.8.apk").write_bytes(b"apk-1.4.8")
    entity = await _serving_entity(hass, old_dir)
    entity.firmware_dir = new_dir

    client = await hass_client_no_auth()
    resp = await client.get("/habitron-firmware/MOD-T/sctouch_v1.4.8.apk")

    assert resp.status == 200
    assert await resp.read() == b"apk-1.4.8"


@pytest.mark.parametrize(
    "path",
    [
        "/habitron-firmware/OTHER/sctouch_v1.4.8.apk",  # unknown panel
        "/habitron-firmware/MOD-T/sctouch_v9.9.9.apk",  # missing file
        "/habitron-firmware/MOD-T/notes.txt",  # not a Touch APK
    ],
)
async def test_download_serves_only_touch_apks_of_known_panels(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    tmp_path: Path,
    path: str,
) -> None:
    """Anything but an existing Touch APK of a known panel is a 404."""
    firmware_dir = tmp_path / "firmware"
    firmware_dir.mkdir()
    (firmware_dir / "sctouch_v1.4.8.apk").write_bytes(b"apk")
    (firmware_dir / "notes.txt").write_text("x")
    (tmp_path / "secret.apk").write_text("secret")
    await _serving_entity(hass, firmware_dir)

    client = await hass_client_no_auth()
    resp = await client.get(path)

    assert resp.status == 404


@pytest.mark.parametrize(
    "path",
    [
        "/habitron-firmware/MOD-T/sctouch_%2E%2E%2Fsecret.apk",
        "/habitron-firmware/MOD-T/..%2Fsecret.apk",
    ],
)
async def test_download_never_leaves_the_firmware_directory(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    tmp_path: Path,
    path: str,
) -> None:
    """An encoded path escape is refused (by HA's filter or by the route)."""
    firmware_dir = tmp_path / "firmware"
    firmware_dir.mkdir()
    (tmp_path / "secret.apk").write_text("secret")
    await _serving_entity(hass, firmware_dir)

    client = await hass_client_no_auth()
    resp = await client.get(path)

    assert resp.status in (400, 404)


@pytest.mark.parametrize(
    "filename", ["sctouch_../secret.apk", "../sctouch_v1.apk", "sctouch_v1.apk/x"]
)
async def test_firmware_view_rejects_names_with_separators(
    hass: HomeAssistant, tmp_path: Path, filename: str
) -> None:
    """The route itself refuses a name that could leave the directory.

    HA's request filter catches most escapes first; this guard must hold on
    its own.
    """
    firmware_dir = tmp_path / "firmware"
    firmware_dir.mkdir()
    (tmp_path / "secret.apk").write_text("secret")
    await _serving_entity(hass, firmware_dir)
    request = MagicMock()
    request.app = {KEY_HASS: hass}

    with pytest.raises(web.HTTPNotFound):
        await HbtnFirmwareView().get(request, "MOD-T", filename)


async def test_removed_entity_is_no_longer_served(
    hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator, tmp_path: Path
) -> None:
    """A removed Touch app entity takes its download with it."""
    (tmp_path / "sctouch_v1.4.8.apk").write_bytes(b"apk")
    entity = await _serving_entity(hass, tmp_path)
    entity.hass = hass

    await entity.async_will_remove_from_hass()

    client = await hass_client_no_auth()
    resp = await client.get("/habitron-firmware/MOD-T/sctouch_v1.4.8.apk")
    assert resp.status == 404
    assert "MOD-T" not in hass.data[_TOUCH_APP_ENTITIES]


async def test_firmware_view_is_registered_once(hass: HomeAssistant) -> None:
    """A second Touch panel or a reload must not register the route twice."""
    assert await async_setup_component(hass, "http", {})
    with patch.object(hass.http, "register_view") as register:
        _async_register_firmware_view(hass)
        _async_register_firmware_view(hass)
    register.assert_called_once()
