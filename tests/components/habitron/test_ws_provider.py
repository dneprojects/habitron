"""Tests for the Habitron WebRTC / WebSocket provider class.

Focuses on ``custom_components.habitron.ws_provider.provider`` —
the class itself: lifecycle, message-passing API, WebRTC negotiation
and snapshot flow. The websocket-command handlers and the voice
pipeline are exercised in their own dedicated test modules.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.habitron.ws_provider.provider import (
    HabitronWebRTCProvider,
    _filter_ipv6_candidates,
)
from homeassistant.components.camera import WebRTCAnswer, WebRTCError
from homeassistant.exceptions import HomeAssistantError


def _make_provider() -> HabitronWebRTCProvider:
    """Build a provider with ``async_register_webrtc_provider`` mocked out."""
    hass = MagicMock()
    rtr = MagicMock()
    with patch(
        "custom_components.habitron.ws_provider.provider."
        "async_register_webrtc_provider",
        return_value=MagicMock(),
    ):
        return HabitronWebRTCProvider(hass, rtr)


def test_filter_ipv6_candidates_drops_ip6_lines() -> None:
    """The helper strips IPv6 candidate lines from an SDP offer."""
    sdp = (
        "v=0\r\n"
        "a=candidate:1 IP4 192.0.2.1\r\n"
        "a=candidate:2 IP6 2001:db8::1\r\n"
        "m=audio\r\n"
    )
    out = _filter_ipv6_candidates(sdp)
    assert "IP6" not in out
    assert "IP4" in out


def test_filter_ipv6_candidates_returns_input_when_no_ip6() -> None:
    """An SDP without IP6 candidates is passed through unchanged."""
    sdp = "v=0\r\na=candidate:1 IP4 192.0.2.1\r\n"
    assert _filter_ipv6_candidates(sdp) == sdp


def test_init_seeds_state_containers_and_registers_provider() -> None:
    """__init__ wires up the state dicts and registers as a WebRTC provider."""
    provider = _make_provider()
    assert provider.active_ws_connections == {}
    assert provider.webrtc_futures == {}
    assert provider.webrtc_send_message_callbacks == {}
    assert provider.session_to_stream_map == {}
    assert provider.pending_candidates == {}
    assert provider.snapshot_futures == {}
    assert provider.media_players == {}
    assert provider.assist_satellites == {}
    assert provider.voice_pipelines == {}
    assert provider._remove_provider is not None


def test_domain_returns_habitron() -> None:
    """``domain`` returns the package DOMAIN constant."""
    provider = _make_provider()
    assert provider.domain == "habitron"


def test_async_close_unregisters_and_clears_state() -> None:
    """``async_close`` detaches and clears every state container."""
    provider = _make_provider()
    remove_cb = provider._remove_provider
    provider.active_ws_connections["s1"] = MagicMock()
    provider.media_players["s1"] = MagicMock()
    provider.assist_satellites["s1"] = MagicMock()
    provider.voice_pipelines["s1"] = {"task": MagicMock(done=lambda: False)}

    provider.async_close()
    remove_cb.assert_called()
    assert provider._remove_provider is None
    assert provider.voice_pipelines == {}
    assert provider.active_ws_connections == {}
    assert provider.media_players == {}
    assert provider.assist_satellites == {}


def test_async_close_is_idempotent_when_remove_already_none() -> None:
    """``async_close`` is safe to call again — the remove callback is None."""
    provider = _make_provider()
    provider._remove_provider = None
    provider.async_close()  # no exception


def test_async_close_skips_done_pipeline_tasks() -> None:
    """A done pipeline task is left alone, not cancelled."""
    provider = _make_provider()
    done_task = MagicMock(done=lambda: True)
    provider.voice_pipelines["s1"] = {"task": done_task}
    provider.async_close()
    done_task.cancel.assert_not_called()


def test_async_close_handles_pipeline_without_task() -> None:
    """A pipeline entry without a task does not raise on close."""
    provider = _make_provider()
    provider.voice_pipelines["s1"] = {"queue": MagicMock()}
    provider.async_close()  # no KeyError / NoneType crash


def test_register_media_player_stores_by_stream_name() -> None:
    """``register_media_player`` keys the player by its stream_name."""
    provider = _make_provider()
    player = MagicMock()
    player.stream_name = "touch_1"
    provider.register_media_player(player)
    assert provider.media_players["touch_1"] is player


def test_register_assist_satellite_stores_by_stream_name() -> None:
    """``register_assist_satellite`` keys the satellite by its stream_name."""
    provider = _make_provider()
    sat = MagicMock()
    sat.stream_name = "touch_1"
    provider.register_assist_satellite(sat)
    assert provider.assist_satellites["touch_1"] is sat


# ---------- Message-passing API ----------


async def test_async_send_json_message_forwards_to_active_connection() -> None:
    """A message for a known stream is forwarded to the matching connection."""
    provider = _make_provider()
    conn = MagicMock()
    provider.active_ws_connections["touch_1"] = conn
    await provider.async_send_json_message("touch_1", {"type": "habitron/ping"})
    conn.send_message.assert_called_with({"type": "habitron/ping"})


async def test_async_send_json_message_warns_for_unknown_stream() -> None:
    """A message for an unknown stream logs a warning + returns silently."""
    provider = _make_provider()
    await provider.async_send_json_message("ghost", {"type": "habitron/ping"})


async def test_async_broadcast_message_walks_every_connection() -> None:
    """``async_broadcast_message`` sends to every active connection."""
    provider = _make_provider()
    conn_a = MagicMock()
    conn_b = MagicMock()
    provider.active_ws_connections["s1"] = conn_a
    provider.active_ws_connections["s2"] = conn_b
    await provider.async_broadcast_message({"type": "habitron/announce"})
    conn_a.send_message.assert_called()
    conn_b.send_message.assert_called()


async def test_async_send_system_command_sends_payload() -> None:
    """A system command is sent as ``habitron/system_command``."""
    provider = _make_provider()
    conn = MagicMock()
    provider.active_ws_connections["s1"] = conn
    await provider.async_send_system_command("s1", "restart")
    payload = conn.send_message.call_args.args[0]
    assert payload["type"] == "habitron/system_command"
    assert payload["command"] == "restart"
    assert "new_ip" not in payload


async def test_async_send_system_command_includes_new_ip_when_given() -> None:
    """A new_ip kwarg is added to the payload."""
    provider = _make_provider()
    conn = MagicMock()
    provider.active_ws_connections["s1"] = conn
    await provider.async_send_system_command("s1", "change_ip", new_ip="10.0.0.1")
    payload = conn.send_message.call_args.args[0]
    assert payload["new_ip"] == "10.0.0.1"


async def test_async_send_system_command_logs_when_no_connection() -> None:
    """A missing connection logs an error and returns without raising."""
    provider = _make_provider()
    await provider.async_send_system_command("ghost", "restart")


# ---------- async_is_supported ----------


def test_async_is_supported_accepts_habitron_uris() -> None:
    """The provider supports ``habitron://`` stream sources."""
    provider = _make_provider()
    assert provider.async_is_supported("habitron://touch_1") is True
    assert provider.async_is_supported("rtsp://other") is False


# ---------- WebRTC offer ----------


def _make_camera_with_stream(source: str | None = "habitron://touch_1") -> MagicMock:
    cam = MagicMock()
    cam.stream_source = AsyncMock(return_value=source)
    return cam


async def test_async_handle_webrtc_offer_raises_when_stream_source_missing() -> None:
    """A camera without a stream source raises HomeAssistantError."""

    provider = _make_provider()
    camera = _make_camera_with_stream(source=None)
    send_message = MagicMock()
    with pytest.raises(HomeAssistantError):
        await provider.async_handle_async_webrtc_offer(
            camera, "sdp", "sess-1", send_message
        )


async def test_async_handle_webrtc_offer_sends_empty_answer_when_no_client() -> None:
    """No active client → an empty WebRTCAnswer is sent and the flow returns."""

    provider = _make_provider()
    camera = _make_camera_with_stream()
    send_message = MagicMock()
    await provider.async_handle_async_webrtc_offer(
        camera, "sdp", "sess-1", send_message
    )
    args = send_message.call_args.args
    assert isinstance(args[0], WebRTCAnswer)
    assert args[0].answer == ""


async def test_async_handle_webrtc_offer_negotiates_successfully() -> None:
    """A successful offer/answer roundtrip ends with a WebRTCAnswer for HA."""

    provider = _make_provider()
    conn = MagicMock()
    provider.active_ws_connections["touch_1"] = conn
    camera = _make_camera_with_stream()
    send_message = MagicMock()

    async def _drive():
        # Wait until the future is in the map, then complete it.
        for _ in range(10):
            if "sess-1" in provider.webrtc_futures:
                provider.webrtc_futures["sess-1"].set_result("answer-sdp")
                return
            await asyncio.sleep(0.001)

    driver = asyncio.create_task(_drive())
    await provider.async_handle_async_webrtc_offer(
        camera, "sdp", "sess-1", send_message
    )
    await driver
    # The HA-side send_message got an answer
    final = send_message.call_args.args[0]
    assert isinstance(final, WebRTCAnswer)
    assert final.answer == "answer-sdp"
    # State maps were updated
    assert provider.session_to_stream_map["sess-1"] == "touch_1"
    assert provider.webrtc_send_message_callbacks["sess-1"] is send_message


async def test_async_handle_webrtc_offer_timeout_sends_error() -> None:
    """When the client does not answer in time a WebRTCError is sent."""

    provider = _make_provider()
    provider.active_ws_connections["touch_1"] = MagicMock()
    camera = _make_camera_with_stream()
    send_message = MagicMock()

    real_wait_for = asyncio.wait_for

    async def _fast_timeout(fut, timeout):
        return await real_wait_for(fut, timeout=0.001)

    with patch(
        "custom_components.habitron.ws_provider.provider.asyncio.wait_for",
        new=_fast_timeout,
    ):
        await provider.async_handle_async_webrtc_offer(
            camera, "sdp", "sess-1", send_message
        )

    # The final send_message should be a WebRTCError
    last = send_message.call_args.args[0]
    assert isinstance(last, WebRTCError)
    assert last.code == "timeout"


async def test_async_handle_webrtc_offer_drains_pending_candidates() -> None:
    """ICE candidates that arrived before the answer are flushed after handling."""
    provider = _make_provider()
    provider.active_ws_connections["touch_1"] = MagicMock()
    camera = _make_camera_with_stream()
    send_message = MagicMock()

    candidate = MagicMock()
    provider.pending_candidates["sess-1"] = [candidate]

    async def _resolve():
        for _ in range(10):
            if "sess-1" in provider.webrtc_futures:
                provider.webrtc_futures["sess-1"].set_result("answer-sdp")
                return
            await asyncio.sleep(0.001)

    driver = asyncio.create_task(_resolve())
    await provider.async_handle_async_webrtc_offer(
        camera, "sdp", "sess-1", send_message
    )
    await driver
    # The candidate was forwarded to HA
    send_message.assert_any_call(candidate)


async def test_async_handle_webrtc_offer_wraps_inner_exception() -> None:
    """Any other exception during negotiation is wrapped in HomeAssistantError."""

    provider = _make_provider()
    provider.active_ws_connections["touch_1"] = MagicMock()
    camera = _make_camera_with_stream()
    send_message = MagicMock()

    with (
        patch(
            "custom_components.habitron.ws_provider.provider._filter_ipv6_candidates",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(HomeAssistantError),
    ):
        await provider.async_handle_async_webrtc_offer(
            camera, "sdp", "sess-1", send_message
        )
    # A WebRTCError was sent before the wrap
    last = send_message.call_args.args[0]
    assert isinstance(last, WebRTCError)
    assert last.code == "negotiation_failed"


# ---------- ICE candidate ----------


async def test_async_on_webrtc_candidate_forwards_for_known_session() -> None:
    """A known session forwards the candidate via async_send_json_message."""
    provider = _make_provider()
    provider.session_to_stream_map["sess-1"] = "touch_1"
    provider.active_ws_connections["touch_1"] = MagicMock()
    candidate = MagicMock()
    candidate.candidate = "candidate-string"
    candidate.sdp_mid = "mid"
    candidate.sdp_m_line_index = 0
    await provider.async_on_webrtc_candidate("sess-1", candidate)
    sent = provider.active_ws_connections["touch_1"].send_message.call_args.args[0]
    assert sent["type"] == "habitron/webrtc_candidate"
    assert sent["candidate"] == "candidate-string"


async def test_async_on_webrtc_candidate_ignores_unknown_session() -> None:
    """An unknown session is logged but does not raise."""
    provider = _make_provider()
    await provider.async_on_webrtc_candidate("ghost", MagicMock())


# ---------- Snapshot ----------


async def test_async_take_snapshot_returns_decoded_bytes() -> None:
    """A successful snapshot future is awaited and its payload returned."""
    provider = _make_provider()
    conn = MagicMock()
    provider.active_ws_connections["touch_1"] = conn

    async def _complete():
        for _ in range(10):
            futs = list(provider.snapshot_futures.values())
            if futs:
                futs[0]["future"].set_result(b"png-bytes")
                return
            await asyncio.sleep(0.001)

    driver = asyncio.create_task(_complete())
    result = await provider.async_take_snapshot("touch_1")
    await driver
    assert result == b"png-bytes"
    # Future was cleaned up
    assert provider.snapshot_futures == {}


async def test_async_take_snapshot_raises_when_no_client() -> None:
    """No active client → ``async_take_snapshot`` raises HomeAssistantError."""

    provider = _make_provider()
    with pytest.raises(HomeAssistantError):
        await provider.async_take_snapshot("touch_1")


async def test_async_take_snapshot_raises_on_timeout() -> None:
    """A timeout while waiting for the client raises HomeAssistantError."""

    provider = _make_provider()
    provider.active_ws_connections["touch_1"] = MagicMock()

    real_wait_for = asyncio.wait_for

    async def _fast_timeout(fut, timeout):
        return await real_wait_for(fut, timeout=0.001)

    with (
        patch(
            "custom_components.habitron.ws_provider.provider.asyncio.wait_for",
            new=_fast_timeout,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await provider.async_take_snapshot("touch_1")
    # The future was cleaned up via the finally
    assert provider.snapshot_futures == {}


# ---------- Stream lookup helper ----------


def testget_stream_or_send_error_returns_matching_stream_name() -> None:
    """When the connection matches an entry the stream name is returned."""
    provider = _make_provider()
    conn = MagicMock()
    provider.active_ws_connections["touch_1"] = conn
    assert provider.get_stream_or_send_error(conn, {"id": 5}) == "touch_1"


def testget_stream_or_send_error_sends_error_for_unknown_connection() -> None:
    """An unknown connection sends an "unregistered" error back to the client."""
    provider = _make_provider()
    conn = MagicMock()
    result = provider.get_stream_or_send_error(
        conn, {"id": 5, "type": "habitron/whatever"}
    )
    assert result is None
    conn.send_error.assert_called()


def test_async_register_websocket_handlers_delegates_to_register_handlers() -> None:
    """The method is a thin wrapper around ``handlers.register_handlers``."""
    provider = _make_provider()
    with patch(
        "custom_components.habitron.ws_provider.handlers.register_handlers"
    ) as mock_register:
        provider.async_register_websocket_handlers()
    mock_register.assert_called_with(provider)
