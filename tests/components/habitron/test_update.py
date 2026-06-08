"""Tests for the Habitron update platform."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.router import HbtnRouter
from custom_components.habitron.update import (
    HbtnModuleUpdate,
    SCTouchAppUpdate,
    async_setup_entry,
)

from .conftest import class_attr


async def test_update_setup(setup_integration: MockConfigEntry) -> None:
    """The update platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_module_update_polls_for_firmware() -> None:
    """HbtnModuleUpdate keeps _attr_should_poll=True (firmware not via coord)."""
    assert class_attr(HbtnModuleUpdate, "_attr_should_poll") is True


def test_sc_touch_app_update_polls() -> None:
    """SCTouchAppUpdate polls for new firmware (no Coordinator binding)."""
    assert class_attr(SCTouchAppUpdate, "_attr_should_poll") is True


# ---------- Helpers ----------


def _make_module(
    uid: str = "MOD-1",
    *,
    typ: bytes = b"\x01\x03",
    name: str = "Touch 1",
    sw_version: str = "1.0.0",
) -> MagicMock:
    mod = MagicMock()
    mod.uid = uid
    mod.name = name
    mod.typ = typ
    mod.sw_version = sw_version
    mod.client_version = "1.0.0"
    mod.mod_addr = 105
    mod.raddr = 5
    mod.stream_name = "touch_1_5"
    mod.comm.handle_firmware = AsyncMock(return_value=b"")
    mod.comm.update_firmware = AsyncMock()
    return mod


def _make_router_module() -> HbtnRouter:
    """Build a real HbtnRouter instance (so ``isinstance`` checks succeed)."""
    rt = HbtnRouter.__new__(HbtnRouter)
    rt.uid = "ROUTER-1"
    rt.name = "Router"
    rt.id = 100
    rt.version = "1.0.0"
    rt.comm = MagicMock()
    rt.comm.handle_firmware = AsyncMock(return_value=b"")
    rt.comm.update_firmware = AsyncMock()
    rt.get_definitions = AsyncMock()
    return rt


def _make_router_with_smhub() -> MagicMock:
    rt = MagicMock()
    rt.uid = "ROUTER-1"
    rt.hass = MagicMock()
    rt.hass.config.path = MagicMock(return_value="/cfg")
    rt.hass.config.internal_url = "http://ha.local"
    rt.hass.async_add_executor_job = AsyncMock()
    rt.smhub.addon_slug = ""
    rt.smhub.ws_provider = MagicMock()
    rt.smhub.ws_provider.active_ws_connections = {}
    rt.smhub.ws_provider.async_send_json_message = AsyncMock()
    return rt


# ---------- async_setup_entry ----------


async def test_async_setup_entry_emits_router_module_and_touch_app(hass) -> None:
    """async_setup_entry adds router + module + SCTouchAppUpdate for Touch."""
    touch = _make_module(typ=b"\x01\x04")
    other = _make_module(uid="MOD-2", typ=b"\x01\x03")
    rt = MagicMock()
    rt.modules = [touch, other]
    rt.coord = MagicMock()
    rt.hass = hass
    rt.smhub.addon_slug = ""
    rt.uid = "ROUTER-1"

    entry = MagicMock()
    entry.runtime_data.router = rt

    added: list = []
    await async_setup_entry(hass, entry, lambda es: added.extend(es))

    # 1 router + 2 modules + 1 SCTouchAppUpdate for the Touch
    assert len(added) == 4
    assert any(isinstance(e, SCTouchAppUpdate) for e in added)


async def test_async_setup_entry_skips_apk_for_non_touch(hass) -> None:
    """A module that isn't a Smart Controller Touch does not get an APK entity."""
    rt = MagicMock()
    rt.modules = [_make_module(typ=b"\x01\x03")]
    rt.coord = MagicMock()
    entry = MagicMock()
    entry.runtime_data.router = rt

    added: list = []
    await async_setup_entry(hass, entry, lambda es: added.extend(es))
    # router + module = 2; no SCTouchAppUpdate
    assert sum(isinstance(e, SCTouchAppUpdate) for e in added) == 0


# ---------- SCTouchAppUpdate ----------


def _make_app(rt: MagicMock | None = None, mod: MagicMock | None = None) -> SCTouchAppUpdate:
    """Build an SCTouchAppUpdate with stubbed router + module."""
    rt = rt if rt is not None else _make_router_with_smhub()
    mod = mod if mod is not None else _make_module(typ=b"\x01\x04")
    app = SCTouchAppUpdate(mod, rt)
    app.hass = rt.hass
    app.entity_id = "update.touch"
    return app


def test_sc_touch_init_seeds_unique_id_and_version() -> None:
    """SCTouchAppUpdate's unique id + initial version come from the module."""
    rt = _make_router_with_smhub()
    mod = _make_module(typ=b"\x01\x04")
    mod.client_version = "1.2.3"
    app = SCTouchAppUpdate(mod, rt)
    assert app.unique_id == "mod_MOD-1_app_update"
    assert app._attr_installed_version == "1.2.3"
    assert ("habitron", "MOD-1") in app._attr_device_info["identifiers"]


def test_sc_touch_init_unknown_falls_back_to_zero() -> None:
    """A module with client_version='unknown' falls back to '0.0.0'."""
    rt = _make_router_with_smhub()
    mod = _make_module(typ=b"\x01\x04")
    mod.client_version = "unknown"
    app = SCTouchAppUpdate(mod, rt)
    assert app._attr_installed_version == "0.0.0"


def test_sc_touch_release_notes_reports_latest_version() -> None:
    """``release_notes`` exposes the cached latest version string."""
    app = _make_app()
    app._attr_latest_version = "2.0.0"
    assert "2.0.0" in app.release_notes()


async def test_sc_touch_async_added_to_hass_triggers_update() -> None:
    """async_added_to_hass fires an immediate update so the entity has fresh data."""
    app = _make_app()
    app.async_update = AsyncMock()
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ), patch(
        "homeassistant.components.update.UpdateEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await app.async_added_to_hass()
    app.async_update.assert_awaited()


def test_update_path_uses_share_when_addon_slug_set() -> None:
    """An addon installation routes the firmware dir into /share/<slug>/firmware."""
    rt = _make_router_with_smhub()
    rt.smhub.addon_slug = "habitron_addon"
    app = _make_app(rt=rt)
    app._update_path()
    assert str(app.firmware_dir) == "/share/habitron_addon/firmware"


def test_update_path_uses_custom_components_when_not_addon() -> None:
    """A non-addon install routes the firmware dir under custom_components/<domain>."""
    rt = _make_router_with_smhub()
    rt.smhub.addon_slug = ""
    app = _make_app(rt=rt)
    app._update_path()
    assert "custom_components" in str(app.firmware_dir)
    assert "habitron" in str(app.firmware_dir)


# ---------- scan_firmware_dir_blocking ----------


def test_scan_firmware_dir_missing_returns_none_none() -> None:
    """A non-existent firmware directory returns (None, None) + logs a warning."""
    app = _make_app()
    app.firmware_dir = Path("/this/does/not/exist")
    assert app.scan_firmware_dir_blocking() == (None, None)


def test_scan_firmware_dir_no_apks_returns_none_none(tmp_path: Path) -> None:
    """A firmware dir without sctouch APKs returns (None, None)."""
    app = _make_app()
    app.firmware_dir = tmp_path
    # Empty dir → returns (None, None)
    assert app.scan_firmware_dir_blocking() == (None, None)


def test_scan_firmware_dir_finds_latest_apk(tmp_path: Path) -> None:
    """The scanner picks the highest sctouch_*.apk version it can parse."""
    app = _make_app()
    app.firmware_dir = tmp_path
    (tmp_path / "sctouch_1.0.0.apk").touch()
    (tmp_path / "sctouch_2.5.0.apk").touch()
    (tmp_path / "other.apk").touch()  # ignored — doesn't start with sctouch_

    def _fake_apk_factory(file_path):
        apk = MagicMock()
        if "2.5.0" in file_path:
            apk.version_name = "2.5.0"
        else:
            apk.version_name = "1.0.0"
        apk.get_manifest = MagicMock()
        apk.close = MagicMock()
        return apk

    apk_module = MagicMock()
    apk_module.APK.from_file = MagicMock(side_effect=_fake_apk_factory)
    with patch.dict("sys.modules", {"apkutils": apk_module}):
        version, filename = app.scan_firmware_dir_blocking()
    assert version == "2.5.0"
    assert filename == "sctouch_2.5.0.apk"


def test_scan_firmware_dir_handles_parse_failure(tmp_path: Path) -> None:
    """A broken APK is logged + skipped without failing the entire scan."""
    app = _make_app()
    app.firmware_dir = tmp_path
    (tmp_path / "sctouch_1.0.0.apk").touch()

    apk_module = MagicMock()
    apk_module.APK.from_file = MagicMock(side_effect=RuntimeError("bad apk"))
    with patch.dict("sys.modules", {"apkutils": apk_module}):
        version, filename = app.scan_firmware_dir_blocking()
    assert version is None
    assert filename is None


def test_scan_firmware_dir_handles_iter_error(tmp_path: Path) -> None:
    """An iterdir() that raises is caught + reported as (None, None)."""
    app = _make_app()
    app.firmware_dir = MagicMock()
    app.firmware_dir.is_dir = MagicMock(return_value=True)
    app.firmware_dir.iterdir = MagicMock(side_effect=OSError("permission"))
    apk_module = MagicMock()
    with patch.dict("sys.modules", {"apkutils": apk_module}):
        version, filename = app.scan_firmware_dir_blocking()
    assert version is None
    assert filename is None


def test_scan_firmware_dir_restores_axml_logger_level(tmp_path: Path) -> None:
    """The scanner restores axml's original log level even after exceptions."""
    app = _make_app()
    app.firmware_dir = tmp_path
    (tmp_path / "sctouch_1.apk").touch()
    axml = logging.getLogger("axml")
    axml.setLevel(logging.DEBUG)

    apk_module = MagicMock()
    apk_module.APK.from_file = MagicMock(side_effect=RuntimeError("boom"))
    with patch.dict("sys.modules", {"apkutils": apk_module}):
        app.scan_firmware_dir_blocking()
    # The "axml" logger's DEBUG level is restored after the scan.
    assert axml.level == logging.DEBUG


# ---------- async_update ----------


async def test_sc_touch_async_update_no_new_version_does_not_copy() -> None:
    """When no APK is newer than installed, no copy happens."""
    app = _make_app()
    app._attr_installed_version = "5.0.0"
    app._update_path = MagicMock()
    app._copy_apk_to_www = AsyncMock()
    app.hass.async_add_executor_job = AsyncMock(return_value=("1.0.0", "sctouch.apk"))
    app._module.client_version = "5.0.0"
    await app.async_update()
    app._copy_apk_to_www.assert_not_awaited()
    assert app._attr_latest_version == "1.0.0"


async def test_sc_touch_async_update_copies_when_newer_available() -> None:
    """A newer APK triggers _copy_apk_to_www."""
    app = _make_app()
    app._attr_installed_version = "1.0.0"
    app._update_path = MagicMock()
    app._copy_apk_to_www = AsyncMock()
    app.hass.async_add_executor_job = AsyncMock(return_value=("2.0.0", "sctouch.apk"))
    app._module.client_version = "1.0.0"
    await app.async_update()
    app._copy_apk_to_www.assert_awaited_with("sctouch.apk")


async def test_sc_touch_async_update_picks_up_module_version() -> None:
    """A non-unknown module client_version overrides the cached installed_version."""
    app = _make_app()
    app._update_path = MagicMock()
    app._copy_apk_to_www = AsyncMock()
    app._module.client_version = "3.3.3"
    app.hass.async_add_executor_job = AsyncMock(return_value=(None, None))
    await app.async_update()
    assert app._attr_installed_version == "3.3.3"


async def test_sc_touch_async_update_ignores_unknown_module_version() -> None:
    """A 'unknown' client_version is ignored in favour of the cached value."""
    app = _make_app()
    app._update_path = MagicMock()
    app._copy_apk_to_www = AsyncMock()
    app._module.client_version = "unknown"
    app._attr_installed_version = "1.0.0"
    app.hass.async_add_executor_job = AsyncMock(return_value=(None, None))
    await app.async_update()
    assert app._attr_installed_version == "1.0.0"


# ---------- _copy_apk_to_www ----------


async def test_copy_apk_to_www_returns_url_and_checksum(tmp_path: Path) -> None:
    """A successful copy returns the public URL + sha256 hex."""
    rt = _make_router_with_smhub()
    rt.hass.config.path = MagicMock(return_value=str(tmp_path))
    app = _make_app(rt=rt)
    src = tmp_path / "firmware"
    src.mkdir()
    apk = src / "sctouch_1.apk"
    apk.write_bytes(b"apk-contents")
    app.firmware_dir = src

    async def _exec_job(func):
        return func()

    rt.hass.async_add_executor_job = AsyncMock(side_effect=_exec_job)
    url, sha = await app._copy_apk_to_www("sctouch_1.apk")
    assert url == "http://ha.local/local/firmware/sctouch_1.apk"
    assert isinstance(sha, str) and len(sha) == 64


async def test_copy_apk_to_www_returns_none_on_failure() -> None:
    """A copy failure (no source file) returns (None, None) + logs."""
    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)

    async def _exec_job(func):
        return func()

    rt.hass.async_add_executor_job = AsyncMock(side_effect=_exec_job)
    url, sha = await app._copy_apk_to_www("does-not-exist.apk")
    assert url is None
    assert sha is None


# ---------- async_install ----------


async def test_sc_touch_async_install_sends_ws_payload() -> None:
    """async_install pushes a habitron/update_available message via the WS provider."""
    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    app._attr_latest_version = "2.0.0"
    app._latest_apk_filename = "sctouch_2.0.0.apk"
    app._copy_apk_to_www = AsyncMock(return_value=("http://x", "abc"))
    rt.smhub.ws_provider.active_ws_connections[app._module.stream_name] = MagicMock()
    await app.async_install(version=None, backup=False)
    rt.smhub.ws_provider.async_send_json_message.assert_awaited()
    sent = rt.smhub.ws_provider.async_send_json_message.call_args.args[1]
    assert sent["type"] == "habitron/update_available"
    assert sent["payload"]["version"] == "2.0.0"


async def test_sc_touch_async_install_raises_without_version() -> None:
    """Calling install before a latest version is known raises HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415

    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    app._attr_latest_version = None
    with pytest.raises(HomeAssistantError):
        await app.async_install(version=None, backup=False)


async def test_sc_touch_async_install_raises_when_client_not_connected() -> None:
    """No connected client → HomeAssistantError before any copy happens."""
    from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415

    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    app._attr_latest_version = "2.0.0"
    app._copy_apk_to_www = AsyncMock()
    # active_ws_connections is empty by default
    with pytest.raises(HomeAssistantError):
        await app.async_install(version=None, backup=False)
    app._copy_apk_to_www.assert_not_awaited()


async def test_sc_touch_async_install_raises_when_copy_fails() -> None:
    """A copy that returns (None, None) raises HomeAssistantError."""
    from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415

    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    app._attr_latest_version = "2.0.0"
    app._latest_apk_filename = "sctouch_2.0.0.apk"
    rt.smhub.ws_provider.active_ws_connections[app._module.stream_name] = MagicMock()
    app._copy_apk_to_www = AsyncMock(return_value=(None, None))
    with pytest.raises(HomeAssistantError):
        await app.async_install(version=None, backup=False)


# ---------- HbtnModuleUpdate ----------


def _make_module_update(mod: MagicMock | None = None) -> HbtnModuleUpdate:
    """Build an HbtnModuleUpdate around a stub module / coordinator."""
    coord = MagicMock()
    coord.last_update_success = True
    mod = mod if mod is not None else _make_module()
    return HbtnModuleUpdate(mod, coord, 0)


def test_hbtn_module_update_device_info_and_progress() -> None:
    """The entity advertises its module uid and the in_progress property."""
    entity = _make_module_update()
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]
    assert entity.in_progress is False
    entity.flash_in_progress = True
    assert entity.in_progress is True


async def test_hbtn_module_update_async_added_to_hass_runs_update() -> None:
    """async_added_to_hass calls into async_update to seed the version state."""
    entity = _make_module_update()
    entity.async_update = AsyncMock()
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    entity.async_update.assert_awaited()


async def test_hbtn_module_update_install_for_module() -> None:
    """Module install routes through ``comm.update_firmware(addr, raddr)``."""
    entity = _make_module_update()
    entity.async_write_ha_state = MagicMock()
    entity.async_update = AsyncMock()
    with patch(
        "custom_components.habitron.update.sleep", new=AsyncMock()
    ):
        await entity.async_install(version="9.9.9", backup=False)
    entity._module.comm.update_firmware.assert_awaited_with(105)
    assert entity._module.sw_version == "9.9.9"
    assert entity.flash_in_progress is False


async def test_hbtn_module_update_install_for_router() -> None:
    """Router install routes through ``comm.update_firmware(router.id, 0)``."""
    rt = _make_router_module()
    entity = _make_module_update(mod=rt)
    entity.async_write_ha_state = MagicMock()
    entity.async_update = AsyncMock()
    with patch(
        "custom_components.habitron.update.sleep", new=AsyncMock()
    ):
        await entity.async_install(version="9.9.9", backup=False)
    rt.comm.update_firmware.assert_awaited_with(rt.id)
    assert rt.version == "9.9.9"


async def test_hbtn_module_update_install_resets_flag_even_on_failure() -> None:
    """A bus exception still resets ``flash_in_progress`` via finally."""
    entity = _make_module_update()
    entity.async_write_ha_state = MagicMock()
    entity.async_update = AsyncMock()
    entity._module.comm.update_firmware = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("custom_components.habitron.update.sleep", new=AsyncMock()):
        with pytest.raises(RuntimeError):
            await entity.async_install(version="x", backup=False)
    assert entity.flash_in_progress is False


async def test_hbtn_module_update_async_update_parses_versions() -> None:
    """A two-line firmware response sets installed + latest version."""
    entity = _make_module_update()
    entity.async_write_ha_state = MagicMock()
    entity._module.comm.handle_firmware = AsyncMock(return_value=b"1.0.0\n2.0.0")
    await entity.async_update()
    assert entity._attr_installed_version == "1.0.0"
    assert entity._attr_latest_version == "2.0.0"


async def test_hbtn_module_update_async_update_router_branch_calls_get_definitions() -> None:
    """For a router target, async_update first reloads its definitions."""
    rt = _make_router_module()
    entity = _make_module_update(mod=rt)
    entity.async_write_ha_state = MagicMock()
    rt.comm.handle_firmware = AsyncMock(return_value=b"1.0.0\n2.0.0")
    await entity.async_update()
    rt.get_definitions.assert_awaited()
    assert entity._attr_latest_version == "2.0.0"


async def test_hbtn_module_update_async_update_empty_response_warns() -> None:
    """An empty firmware response logs a CRC warning and returns."""
    entity = _make_module_update()
    entity.async_write_ha_state = MagicMock()
    entity._module.comm.handle_firmware = AsyncMock(return_value=b"")
    await entity.async_update()
    entity.async_write_ha_state.assert_not_called()


async def test_hbtn_module_update_async_update_handles_exception() -> None:
    """A bus exception in async_update is caught and logged."""
    entity = _make_module_update()
    entity._module.comm.handle_firmware = AsyncMock(side_effect=RuntimeError("boom"))
    # Should not raise
    await entity.async_update()


async def test_hbtn_module_update_async_update_single_line_response() -> None:
    """A single-line response leaves attr_latest_version untouched."""
    entity = _make_module_update()
    entity.async_write_ha_state = MagicMock()
    entity._module.comm.handle_firmware = AsyncMock(return_value=b"only-one-line")
    # async_update parses two lines via "\n".split — single line yields len 1
    await entity.async_update()
    # _attr_latest_version unset (no attribute) — not written
    entity.async_write_ha_state.assert_not_called()
