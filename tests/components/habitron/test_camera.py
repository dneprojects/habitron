"""Tests for the Habitron camera platform."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.habitron.camera import HbtnCam, async_setup_entry
from homeassistant.core import HomeAssistant


def _make_touch_module(uid: str = "MOD-T", stream: str = "touch_1") -> MagicMock:
    mod = MagicMock()
    mod.uid = uid
    mod.name = "Touch 1"
    mod.mod_type = "Smart Controller Touch"
    mod.stream_name = stream
    return mod


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.async_take_snapshot = AsyncMock(return_value=b"jpeg-bytes")
    provider.async_handle_async_webrtc_offer = AsyncMock()
    provider.async_on_webrtc_candidate = AsyncMock()
    return provider


def test_hbtn_cam_unique_id_and_device_info() -> None:
    """HbtnCam exposes module-scoped unique id and device identifier."""
    hass = MagicMock()
    mod = _make_touch_module()
    cam = HbtnCam(hass, mod, 0, _make_provider())
    assert cam.unique_id == "Mod_MOD-T_camera"
    assert ("habitron", "MOD-T") in cam._attr_device_info["identifiers"]
    assert cam.name == "HbtnCam 1"
    assert cam.has_entity_name is True


async def test_hbtn_cam_stream_source_returns_habitron_uri() -> None:
    """``stream_source`` returns the habitron:// URL for the stream name."""
    hass = MagicMock()
    mod = _make_touch_module()
    cam = HbtnCam(hass, mod, 0, _make_provider())
    assert await cam.stream_source() == "habitron://touch_1"


async def test_hbtn_cam_async_camera_image_returns_snapshot() -> None:
    """``async_camera_image`` forwards to the provider's snapshot helper."""
    hass = MagicMock()
    mod = _make_touch_module()
    provider = _make_provider()
    cam = HbtnCam(hass, mod, 0, provider)
    img = await cam.async_camera_image()
    assert img == b"jpeg-bytes"
    provider.async_take_snapshot.assert_awaited_with(stream_name="touch_1")


async def test_hbtn_cam_async_camera_image_returns_none_when_off() -> None:
    """When the camera is off, ``async_camera_image`` returns None without calling."""
    hass = MagicMock()
    mod = _make_touch_module()
    provider = _make_provider()
    cam = HbtnCam(hass, mod, 0, provider)
    cam._attr_is_on = False
    img = await cam.async_camera_image()
    assert img is None
    provider.async_take_snapshot.assert_not_awaited()


async def test_hbtn_cam_async_camera_image_propagates_provider_error() -> None:
    """Provider failures propagate so HA can surface them to the user."""
    hass = MagicMock()
    mod = _make_touch_module()
    provider = _make_provider()
    provider.async_take_snapshot = AsyncMock(side_effect=RuntimeError("boom"))
    cam = HbtnCam(hass, mod, 0, provider)
    with pytest.raises(RuntimeError, match="boom"):
        await cam.async_camera_image()


async def test_hbtn_cam_async_turn_on_sets_state() -> None:
    """async_turn_on flips _attr_is_on and writes the state."""
    hass = MagicMock()
    mod = _make_touch_module()
    cam = HbtnCam(hass, mod, 0, _make_provider())
    cam._attr_is_on = False
    cam.async_write_ha_state = MagicMock()
    await cam.async_turn_on()
    assert cam._attr_is_on is True
    cam.async_write_ha_state.assert_called()


async def test_hbtn_cam_async_turn_off_sets_state() -> None:
    """async_turn_off flips _attr_is_on and writes the state."""
    hass = MagicMock()
    mod = _make_touch_module()
    cam = HbtnCam(hass, mod, 0, _make_provider())
    cam.async_write_ha_state = MagicMock()
    await cam.async_turn_off()
    assert cam._attr_is_on is False
    cam.async_write_ha_state.assert_called()


async def test_hbtn_cam_handle_webrtc_offer_forwards_to_provider() -> None:
    """A WebRTC offer is forwarded to the provider with all positional args."""
    hass = MagicMock()
    mod = _make_touch_module()
    provider = _make_provider()
    cam = HbtnCam(hass, mod, 0, provider)
    send_message = MagicMock()
    await cam.async_handle_async_webrtc_offer("sdp", "sess-1", send_message)
    provider.async_handle_async_webrtc_offer.assert_awaited_with(
        camera=cam,
        offer_sdp="sdp",
        session_id="sess-1",
        send_message=send_message,
    )


async def test_hbtn_cam_handle_webrtc_offer_raises_when_off() -> None:
    """A WebRTC offer on an off camera raises a RuntimeError."""
    hass = MagicMock()
    mod = _make_touch_module()
    cam = HbtnCam(hass, mod, 0, _make_provider())
    cam._attr_is_on = False
    with pytest.raises(RuntimeError):
        await cam.async_handle_async_webrtc_offer("sdp", "sess-1", MagicMock())


async def test_hbtn_cam_handle_webrtc_offer_raises_when_no_provider() -> None:
    """A WebRTC offer without a provider raises a RuntimeError."""
    hass = MagicMock()
    mod = _make_touch_module()
    cam = HbtnCam(hass, mod, 0, _make_provider())
    cam._provider = None
    with pytest.raises(RuntimeError):
        await cam.async_handle_async_webrtc_offer("sdp", "sess-1", MagicMock())


async def test_hbtn_cam_async_on_webrtc_candidate_forwards() -> None:
    """ICE candidates are forwarded to the provider."""
    hass = MagicMock()
    mod = _make_touch_module()
    provider = _make_provider()
    cam = HbtnCam(hass, mod, 0, provider)
    candidate = MagicMock()
    await cam.async_on_webrtc_candidate("sess-1", candidate)
    provider.async_on_webrtc_candidate.assert_awaited_with("sess-1", candidate)


async def test_hbtn_cam_async_on_webrtc_candidate_skips_when_no_provider() -> None:
    """When no provider is set, ICE candidates are silently dropped."""
    hass = MagicMock()
    mod = _make_touch_module()
    cam = HbtnCam(hass, mod, 0, _make_provider())
    cam._provider = None
    await cam.async_on_webrtc_candidate("sess-1", MagicMock())  # no raise


async def test_async_setup_entry_adds_camera_for_touch_module(
    hass: HomeAssistant,
) -> None:
    """async_setup_entry adds one HbtnCam per Smart Controller Touch."""
    touch = _make_touch_module()
    other = MagicMock()
    other.mod_type = "Smart Controller"
    smhub = MagicMock()
    smhub.router.modules = [touch, other]
    smhub.ws_provider = _make_provider()

    entry = MagicMock()
    entry.runtime_data = smhub

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    assert len(added) == 1
    assert isinstance(added[0], HbtnCam)


async def test_async_setup_entry_short_circuits_without_provider(
    hass: HomeAssistant,
) -> None:
    """Without a WebRTC provider, async_setup_entry logs and returns."""
    touch = _make_touch_module()
    smhub = MagicMock()
    smhub.router.modules = [touch]
    smhub.ws_provider = None

    entry = MagicMock()
    entry.runtime_data = smhub

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    assert added == []


async def test_async_setup_entry_logs_when_no_touch_modules(
    hass: HomeAssistant,
) -> None:
    """When no Touch modules are present, no entities are added."""
    other = MagicMock()
    other.mod_type = "Smart Output"
    smhub = MagicMock()
    smhub.router.modules = [other]
    smhub.ws_provider = _make_provider()

    entry = MagicMock()
    entry.runtime_data = smhub

    added: list = []
    await async_setup_entry(hass, entry, added.extend)  # pylint: disable=home-assistant-tests-direct-platform-async-setup-entry
    assert added == []
