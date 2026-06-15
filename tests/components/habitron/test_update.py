"""Tests for the Habitron update platform."""

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
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import class_attr


async def test_update_setup(setup_integration: MockConfigEntry) -> None:
    """The update platform sets up cleanly against an empty router."""
    assert setup_integration.runtime_data is not None


def test_module_update_does_not_poll() -> None:
    """HbtnModuleUpdate relies on the firmware coordinator, not platform polling."""
    assert _make_module_update().should_poll is False


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


async def test_async_setup_entry_emits_router_module_and_touch_app(
    hass: HomeAssistant,
) -> None:
    """async_setup_entry adds router + module + SCTouchAppUpdate for Touch."""
    touch = _make_module(typ=b"\x01\x04")
    other = _make_module(uid="MOD-2", typ=b"\x01\x03")
    rt = MagicMock()
    rt.modules = [touch, other]
    rt.hass = hass
    rt.smhub.addon_slug = ""
    rt.uid = "ROUTER-1"

    entry = MagicMock()
    entry.runtime_data.router = rt

    added: list = []
    with patch("custom_components.habitron.update.HbtnFirmwareCoordinator") as fw_cls:
        fw_cls.return_value.async_refresh = AsyncMock()
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry

    # 1 router + 2 modules + 1 SCTouchAppUpdate for the Touch
    assert len(added) == 4
    assert any(isinstance(e, SCTouchAppUpdate) for e in added)


async def test_async_setup_entry_skips_apk_for_non_touch(hass: HomeAssistant) -> None:
    """A module that isn't a Smart Controller Touch does not get an APK entity."""
    rt = MagicMock()
    rt.modules = [_make_module(typ=b"\x01\x03")]
    entry = MagicMock()
    entry.runtime_data.router = rt

    added: list = []
    with patch("custom_components.habitron.update.HbtnFirmwareCoordinator") as fw_cls:
        fw_cls.return_value.async_refresh = AsyncMock()
        await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    # router + module = 2; no SCTouchAppUpdate
    assert sum(isinstance(e, SCTouchAppUpdate) for e in added) == 0


# ---------- SCTouchAppUpdate ----------


def _make_app(
    rt: MagicMock | None = None, mod: MagicMock | None = None
) -> SCTouchAppUpdate:
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
    with (
        patch(
            "homeassistant.helpers.update_coordinator."
            "CoordinatorEntity.async_added_to_hass",
            new=AsyncMock(),
        ),
        patch(
            "homeassistant.components.update.UpdateEntity.async_added_to_hass",
            new=AsyncMock(),
        ),
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


def test_update_path_uses_config_habitron_when_not_addon(tmp_path: Path) -> None:
    """A non-addon install routes the firmware dir to <config>/<DOMAIN>/firmware."""
    rt = _make_router_with_smhub()
    rt.smhub.addon_slug = ""
    rt.hass.config.path = MagicMock(return_value=str(tmp_path))
    app = _make_app(rt=rt)
    app._update_path()
    assert str(app.firmware_dir) == str(tmp_path / "habitron" / "firmware")


def test_update_path_falls_back_to_legacy_custom_components(tmp_path: Path) -> None:
    """If only the legacy custom_components/<DOMAIN>/firmware exists, use it."""
    rt = _make_router_with_smhub()
    rt.smhub.addon_slug = ""
    rt.hass.config.path = MagicMock(return_value=str(tmp_path))
    # Create only the legacy path; the new <config>/<DOMAIN>/firmware is absent.
    legacy = tmp_path / "custom_components" / "habitron" / "firmware"
    legacy.mkdir(parents=True)
    app = _make_app(rt=rt)
    app._update_path()
    assert app.firmware_dir == legacy


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
    (tmp_path / "sctouch_v1.0.0.apk").touch()
    (tmp_path / "sctouch_v2.5.0.apk").touch()
    (tmp_path / "other.apk").touch()  # ignored — doesn't start with sctouch_

    def _fake_version(path: Path) -> str:
        return "2.5.0" if "2.5.0" in path.name else "1.0.0"

    with patch(
        "custom_components.habitron.update.read_apk_version_name",
        side_effect=_fake_version,
    ):
        version, filename = app.scan_firmware_dir_blocking()
    assert version == "2.5.0"
    assert filename == "sctouch_v2.5.0.apk"


def test_scan_firmware_dir_handles_unreadable_apk(tmp_path: Path) -> None:
    """An APK whose version can't be read is logged + skipped."""
    app = _make_app()
    app.firmware_dir = tmp_path
    (tmp_path / "sctouch_v1.0.0.apk").touch()

    with patch(
        "custom_components.habitron.update.read_apk_version_name",
        return_value=None,
    ):
        version, filename = app.scan_firmware_dir_blocking()
    assert version is None
    assert filename is None


def test_scan_firmware_dir_handles_iter_error(tmp_path: Path) -> None:
    """An iterdir() that raises is caught + reported as (None, None)."""
    app = _make_app()
    app.firmware_dir = MagicMock()
    app.firmware_dir.is_dir = MagicMock(return_value=True)
    app.firmware_dir.iterdir = MagicMock(side_effect=OSError("permission"))
    version, filename = app.scan_firmware_dir_blocking()
    assert version is None
    assert filename is None


# ---------- async_update ----------


async def test_sc_touch_async_update_records_latest_version() -> None:
    """async_update records the latest version + filename without touching files."""
    app = _make_app()
    app._attr_installed_version = "1.0.0"
    app._update_path = MagicMock()
    app.hass.async_add_executor_job = AsyncMock(return_value=("2.0.0", "sctouch.apk"))
    app._module.client_version = "1.0.0"
    await app.async_update()
    assert app._attr_latest_version == "2.0.0"
    assert app._latest_apk_filename == "sctouch.apk"


async def test_sc_touch_async_update_picks_up_module_version() -> None:
    """A non-unknown module client_version overrides the cached installed_version."""
    app = _make_app()
    app._update_path = MagicMock()
    app._module.client_version = "3.3.3"
    app.hass.async_add_executor_job = AsyncMock(return_value=(None, None))
    await app.async_update()
    assert app._attr_installed_version == "3.3.3"


async def test_sc_touch_async_update_ignores_unknown_module_version() -> None:
    """A 'unknown' client_version is ignored in favour of the cached value."""
    app = _make_app()
    app._update_path = MagicMock()
    app._module.client_version = "unknown"
    app._attr_installed_version = "1.0.0"
    app.hass.async_add_executor_job = AsyncMock(return_value=(None, None))
    await app.async_update()
    assert app._attr_installed_version == "1.0.0"


# ---------- _apk_url_and_checksum ----------


async def test_apk_url_and_checksum_returns_static_url_and_sha(tmp_path: Path) -> None:
    """Reads the source file, returns the static-path URL + sha256 hex."""
    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    apk = tmp_path / "sctouch_1.apk"
    apk.write_bytes(b"apk-contents")
    app.firmware_dir = tmp_path

    async def _exec_job(func):
        return func()

    rt.hass.async_add_executor_job = AsyncMock(side_effect=_exec_job)
    url, sha = await app._apk_url_and_checksum("sctouch_1.apk")
    assert url == "http://ha.local/habitron-firmware/sctouch_1.apk"
    assert isinstance(sha, str) and len(sha) == 64


async def test_apk_url_and_checksum_returns_none_on_failure() -> None:
    """A missing source file yields (None, None) + a logged exception."""
    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    app.firmware_dir = Path("/does/not/exist")

    async def _exec_job(func):
        return func()

    rt.hass.async_add_executor_job = AsyncMock(side_effect=_exec_job)
    url, sha = await app._apk_url_and_checksum("missing.apk")
    assert url is None
    assert sha is None


# ---------- async_install ----------


async def test_sc_touch_async_install_sends_ws_payload() -> None:
    """async_install pushes a habitron/update_available message via the WS provider."""
    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    app._attr_latest_version = "2.0.0"
    app._latest_apk_filename = "sctouch_2.0.0.apk"
    app._apk_url_and_checksum = AsyncMock(return_value=("http://x", "abc"))
    rt.smhub.ws_provider.active_ws_connections[app._module.stream_name] = MagicMock()
    await app.async_install(version=None, backup=False)
    rt.smhub.ws_provider.async_send_json_message.assert_awaited()
    sent = rt.smhub.ws_provider.async_send_json_message.call_args.args[1]
    assert sent["type"] == "habitron/update_available"
    assert sent["payload"]["version"] == "2.0.0"


async def test_sc_touch_async_install_raises_without_version() -> None:
    """Calling install before a latest version is known raises HomeAssistantError."""

    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    app._attr_latest_version = None
    with pytest.raises(HomeAssistantError):
        await app.async_install(version=None, backup=False)


async def test_sc_touch_async_install_raises_when_client_not_connected() -> None:
    """No connected client → HomeAssistantError before any file work happens."""

    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    app._attr_latest_version = "2.0.0"
    app._apk_url_and_checksum = AsyncMock()
    # active_ws_connections is empty by default
    with pytest.raises(HomeAssistantError):
        await app.async_install(version=None, backup=False)
    app._apk_url_and_checksum.assert_not_awaited()


async def test_sc_touch_async_install_raises_when_hash_fails() -> None:
    """A hash helper that returns (None, None) raises HomeAssistantError."""

    rt = _make_router_with_smhub()
    app = _make_app(rt=rt)
    app._attr_latest_version = "2.0.0"
    app._latest_apk_filename = "sctouch_2.0.0.apk"
    rt.smhub.ws_provider.active_ws_connections[app._module.stream_name] = MagicMock()
    app._apk_url_and_checksum = AsyncMock(return_value=(None, None))
    with pytest.raises(HomeAssistantError):
        await app.async_install(version=None, backup=False)


# ---------- HbtnModuleUpdate ----------


def _make_module_update(
    mod: MagicMock | None = None, data: dict | None = None
) -> HbtnModuleUpdate:
    """Build an HbtnModuleUpdate around a stub module / firmware coordinator."""
    coord = MagicMock()
    coord.last_update_success = True
    coord.data = data if data is not None else {}
    mod = mod if mod is not None else _make_module()
    return HbtnModuleUpdate(mod, coord, 0)


def test_hbtn_module_update_device_info_and_progress() -> None:
    """The entity advertises its module uid and the in_progress property."""
    entity = _make_module_update()
    assert ("habitron", "MOD-1") in entity.device_info["identifiers"]
    assert entity.in_progress is False
    entity.flash_in_progress = True
    assert entity.in_progress is True


def test_hbtn_module_update_seeds_installed_version_from_module() -> None:
    """The installed version is taken from the module at construction time."""
    assert _make_module_update().installed_version == "1.0.0"


async def test_hbtn_module_update_async_added_to_hass_reflects_data() -> None:
    """async_added_to_hass reflects firmware versions already in coordinator.data."""
    entity = _make_module_update(data={"MOD-1": ("1.0.0", "2.0.0")})
    entity.async_write_ha_state = MagicMock()
    with patch(
        "homeassistant.helpers.update_coordinator."
        "CoordinatorEntity.async_added_to_hass",
        new=AsyncMock(),
    ):
        await entity.async_added_to_hass()
    assert entity.installed_version == "1.0.0"
    assert entity.latest_version == "2.0.0"


async def test_hbtn_module_update_install_for_module() -> None:
    """Module install routes through ``comm.update_firmware(addr, raddr)``."""
    entity = _make_module_update()
    entity.async_write_ha_state = MagicMock()
    with patch("custom_components.habitron.update.sleep", new=AsyncMock()):
        await entity.async_install(version="9.9.9", backup=False)
    entity._module.comm.update_firmware.assert_awaited_with(105)
    assert entity._module.sw_version == "9.9.9"
    assert entity.installed_version == "9.9.9"
    assert entity.flash_in_progress is False


async def test_hbtn_module_update_install_for_router() -> None:
    """Router install routes through ``comm.update_firmware(router.id, 0)``."""
    rt = _make_router_module()
    entity = _make_module_update(mod=rt)
    entity.async_write_ha_state = MagicMock()
    with patch("custom_components.habitron.update.sleep", new=AsyncMock()):
        await entity.async_install(version="9.9.9", backup=False)
    rt.comm.update_firmware.assert_awaited_with(rt.id)
    assert rt.version == "9.9.9"


async def test_hbtn_module_update_install_resets_flag_even_on_failure() -> None:
    """A bus exception still resets ``flash_in_progress`` via finally."""
    entity = _make_module_update()
    entity.async_write_ha_state = MagicMock()
    entity._module.comm.update_firmware = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("custom_components.habitron.update.sleep", new=AsyncMock()):  # noqa: SIM117
        with pytest.raises(RuntimeError):
            await entity.async_install(version="x", backup=False)
    assert entity.flash_in_progress is False


async def test_hbtn_module_update_reflects_coordinator_data() -> None:
    """_handle_coordinator_update copies the polled versions onto the entity."""
    entity = _make_module_update(data={"MOD-1": ("1.0.0", "2.0.0")})
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity.installed_version == "1.0.0"
    assert entity.latest_version == "2.0.0"
    entity.async_write_ha_state.assert_called_once()


async def test_hbtn_module_update_no_data_keeps_state() -> None:
    """Without a firmware entry yet, the callback writes nothing."""
    entity = _make_module_update(data={})
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    entity.async_write_ha_state.assert_not_called()


async def test_hbtn_module_update_unchanged_data_skips_write() -> None:
    """Unchanged versions do not trigger a redundant state write."""
    entity = _make_module_update(data={"MOD-1": ("1.0.0", "2.0.0")})
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()  # first apply writes
    entity.async_write_ha_state.reset_mock()
    entity._handle_coordinator_update()  # unchanged, no write
    entity.async_write_ha_state.assert_not_called()
