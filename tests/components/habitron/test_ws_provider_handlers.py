"""Tests for the Habitron WebSocket command handlers.

Drives each ``habitron/*`` handler closure directly by:

1. Registering the handlers with a stubbed provider so they end up in
   ``hass.data['websocket_api']``.
2. Pulling the underlying coroutine out via ``handler.__wrapped__``
   (the ``@websocket_api.async_response`` decorator wraps the actual
   async body and exposes it as ``__wrapped__``).
3. Invoking it with a mock ``connection`` and a hand-crafted ``msg``.

This is enough to exercise the closure bodies without spinning up an
actual WebSocket connection.
"""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.habitron.ws_provider.handlers import register_handlers
from custom_components.habitron.ws_provider.provider import HabitronWebRTCProvider


def _make_provider() -> HabitronWebRTCProvider:
    hass = MagicMock()
    hass.data = {}
    hass.bus = MagicMock()
    hass.async_create_background_task = MagicMock()
    rtr = MagicMock()
    with patch(
        "custom_components.habitron.ws_provider.provider."
        "async_register_webrtc_provider"
    ):
        return HabitronWebRTCProvider(hass, rtr)


def _registered_handlers(provider: HabitronWebRTCProvider) -> dict[str, object]:
    """Register handlers and return the wrapped-unwrapped pair indexed by name."""
    register_handlers(provider)
    out: dict[str, object] = {}
    for ws_type, (wrapped, _schema) in provider.hass.data["websocket_api"].items():
        # The decorator chain stores the original async function as ``__wrapped__``.
        # Strip the "habitron/" prefix for readability in tests.
        if ws_type.startswith("habitron/"):
            out[ws_type[len("habitron/") :]] = wrapped.__wrapped__
    return out


def _make_connection(stream_name: str | None = None) -> MagicMock:
    """Build a mock WS connection. ``stream_name`` is what the provider treats it as."""
    conn = MagicMock()
    conn.subscriptions = {}
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    conn.send_message = MagicMock()
    conn.context = MagicMock(return_value=MagicMock())
    conn._stream_name = stream_name  # diagnostic only
    return conn


# ---------- register_handlers smoke ----------


def test_register_handlers_registers_15_commands() -> None:
    """15 habitron/* command handlers (now including the abort) are registered."""
    provider = _make_provider()
    register_handlers(provider)
    cmds = [
        k
        for k in provider.hass.data["websocket_api"]
        if k.startswith("habitron/")
    ]
    assert len(cmds) == 15
    assert "habitron/voice_pipeline_abort" in cmds


def test_register_handlers_registers_all_expected_commands() -> None:
    """Each documented habitron command name is registered."""
    provider = _make_provider()
    register_handlers(provider)
    cmds = set(provider.hass.data["websocket_api"])
    for name in (
        "habitron/register_stream",
        "habitron/webrtc_answer",
        "habitron/webrtc_candidate",
        "habitron/snapshot_result",
        "habitron/call_announcement",
        "habitron/update_media_state",
        "habitron/voice_pipeline_status",
        "habitron/voice_pipeline_start",
        "habitron/voice_pipeline_abort",
        "habitron/voice_audio_chunk",
        "habitron/voice_pipeline_end",
        "habitron/tts_playback_finished",
        "habitron/media_next_track",
        "habitron/media_previous_track",
        "habitron/report_state",
    ):
        assert name in cmds


# ---------- register_stream + disconnect cleanup ----------


async def test_register_stream_stores_connection_and_runs_disconnect() -> None:
    """register_stream records the connection and the disconnect callback cleans state."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()

    mod = MagicMock()
    provider.rtr.get_module_by_stream = MagicMock(return_value=mod)

    await handlers["register_stream"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/register_stream",
         "stream_name": "touch_1", "version": "1.0"},
    )
    # Connection stored and ack sent
    assert provider.active_ws_connections["touch_1"] is conn
    conn.send_result.assert_called_with(1)
    assert mod.client_version == "1.0"

    # Now exercise the disconnect callback by calling subscriptions[1]()
    pending = MagicMock()
    pipeline_task = MagicMock(done=lambda: False)
    pipeline_data = {"task": pipeline_task}
    provider.voice_pipelines["touch_1"] = pipeline_data
    fut = asyncio.Future()
    provider.webrtc_futures["sess-A"] = fut
    provider.session_to_stream_map["sess-A"] = "touch_1"
    provider.pending_candidates["sess-A"] = [pending]
    provider.webrtc_send_message_callbacks["sess-A"] = MagicMock()
    conn.subscriptions[1]()
    assert "touch_1" not in provider.active_ws_connections
    pipeline_task.cancel.assert_called()
    # The future was abandoned with a HomeAssistantError
    assert fut.done() and fut.exception() is not None
    assert provider.session_to_stream_map == {}


async def test_register_stream_warns_when_existing_connection_replaced() -> None:
    """A second register for the same stream warns about the old connection."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    old = _make_connection()
    new = _make_connection()
    provider.active_ws_connections["touch_1"] = old
    provider.rtr.get_module_by_stream = MagicMock(return_value=None)
    await handlers["register_stream"](
        provider.hass,
        new,
        {"id": 2, "type": "habitron/register_stream",
         "stream_name": "touch_1", "version": "1.0"},
    )
    assert provider.active_ws_connections["touch_1"] is new


async def test_register_stream_disconnect_skips_done_future() -> None:
    """A disconnect that finds an already-done future leaves it alone."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.rtr.get_module_by_stream = MagicMock(return_value=None)
    await handlers["register_stream"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/register_stream",
         "stream_name": "touch_1", "version": "1.0"},
    )
    fut = asyncio.Future()
    fut.set_result("ans")  # already done
    provider.webrtc_futures["sess-X"] = fut
    provider.session_to_stream_map["sess-X"] = "touch_1"
    conn.subscriptions[1]()  # disconnect


async def test_register_stream_disconnect_skips_done_task() -> None:
    """A disconnect that finds a done pipeline task does not cancel it."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.rtr.get_module_by_stream = MagicMock(return_value=None)
    await handlers["register_stream"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/register_stream",
         "stream_name": "touch_1", "version": "1.0"},
    )
    done = MagicMock(done=lambda: True)
    provider.voice_pipelines["touch_1"] = {"task": done}
    conn.subscriptions[1]()
    done.cancel.assert_not_called()


# ---------- voice_pipeline_status ----------


async def test_voice_pipeline_status_sends_error_for_unknown_stream() -> None:
    """A status request from an unregistered client gets an unregistered error."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    await handlers["voice_pipeline_status"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/voice_pipeline_status", "disabled": True},
    )
    conn.send_error.assert_called()


async def test_voice_pipeline_status_acks_when_already_running() -> None:
    """A status request while a pipeline is running just acks and returns."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    provider.voice_pipelines["touch_1"] = {"task": MagicMock()}
    await handlers["voice_pipeline_status"](
        provider.hass,
        conn,
        {"id": 5, "type": "habitron/voice_pipeline_status", "disabled": True},
    )
    conn.send_result.assert_called_with(5)


async def test_voice_pipeline_status_updates_satellite() -> None:
    """A satellite registered for this stream has its disabled flag updated."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    sat = MagicMock()
    sat.set_idle = MagicMock()
    provider.assist_satellites["touch_1"] = sat
    await handlers["voice_pipeline_status"](
        provider.hass,
        conn,
        {"id": 5, "type": "habitron/voice_pipeline_status", "disabled": True},
    )
    assert sat.recognition_disabled is True
    sat.set_idle.assert_called()


async def test_voice_pipeline_status_logs_when_no_satellite() -> None:
    """Without a satellite, the status request still acks with a warning."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["voice_pipeline_status"](
        provider.hass,
        conn,
        {"id": 5, "type": "habitron/voice_pipeline_status", "disabled": False},
    )
    conn.send_result.assert_called_with(5)


# ---------- voice_pipeline_start ----------


async def test_voice_pipeline_start_seeds_voice_pipelines_entry() -> None:
    """A pipeline start spawns a background task and stores the queue + event."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn

    # Satellite is optional — we add one so the configuration branch fires.
    sat = MagicMock()
    sat.entity_id = "assist_satellite.touch_1"
    reg = MagicMock()
    reg.device_id = "dev-1"
    reg.options = {"pipeline": "pipe-a", "tts_voice": "voice-x"}
    sat.registry_entry = reg
    provider.assist_satellites["touch_1"] = sat

    # Swallow the spawned ``run_voice_pipeline`` coroutine — the handler
    # tests verify only that the call happens; the pipeline itself has
    # its own dedicated test module.
    def _swallow_coroutine(coro, name=None):  # noqa: ARG001
        coro.close()
        return MagicMock()
    provider.hass.async_create_background_task = MagicMock(side_effect=_swallow_coroutine)

    await handlers["voice_pipeline_start"](
        provider.hass,
        conn,
        {"id": 10, "type": "habitron/voice_pipeline_start", "payload": {}},
    )
    provider.hass.async_create_background_task.assert_called()
    assert "touch_1" in provider.voice_pipelines
    conn.send_result.assert_called_with(10)


async def test_voice_pipeline_start_acks_when_already_running() -> None:
    """A start request while a pipeline is running short-circuits."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    provider.voice_pipelines["touch_1"] = {"task": MagicMock()}
    await handlers["voice_pipeline_start"](
        provider.hass,
        conn,
        {"id": 7, "type": "habitron/voice_pipeline_start", "payload": {}},
    )
    conn.send_result.assert_called_with(7)


async def test_voice_pipeline_start_falls_back_without_satellite() -> None:
    """Without a satellite the pipeline still starts (uses default config)."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    # Swallow the spawned ``run_voice_pipeline`` coroutine — the handler
    # tests verify only that the call happens; the pipeline itself has
    # its own dedicated test module.
    def _swallow_coroutine(coro, name=None):  # noqa: ARG001
        coro.close()
        return MagicMock()
    provider.hass.async_create_background_task = MagicMock(side_effect=_swallow_coroutine)
    await handlers["voice_pipeline_start"](
        provider.hass,
        conn,
        {"id": 11, "type": "habitron/voice_pipeline_start", "payload": {}},
    )
    assert "touch_1" in provider.voice_pipelines


async def test_voice_pipeline_start_with_satellite_no_registry_entry() -> None:
    """A satellite without a registry_entry uses the default device_id branch."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    sat = MagicMock()
    sat.entity_id = "assist_satellite.touch_1"
    sat.registry_entry = None
    provider.assist_satellites["touch_1"] = sat
    # Swallow the spawned ``run_voice_pipeline`` coroutine — the handler
    # tests verify only that the call happens; the pipeline itself has
    # its own dedicated test module.
    def _swallow_coroutine(coro, name=None):  # noqa: ARG001
        coro.close()
        return MagicMock()
    provider.hass.async_create_background_task = MagicMock(side_effect=_swallow_coroutine)
    await handlers["voice_pipeline_start"](
        provider.hass,
        conn,
        {"id": 12, "type": "habitron/voice_pipeline_start", "payload": {}},
    )
    assert "touch_1" in provider.voice_pipelines


async def test_voice_pipeline_start_with_non_string_pipeline_option() -> None:
    """A non-string ``pipeline`` option falls back to the default (no use)."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    sat = MagicMock()
    sat.entity_id = "assist_satellite.touch_1"
    reg = MagicMock()
    reg.device_id = "dev-1"
    # Both options are non-strings so the isinstance checks fail.
    reg.options = {"pipeline": 7, "tts_voice": 7}
    sat.registry_entry = reg
    provider.assist_satellites["touch_1"] = sat
    # Swallow the spawned ``run_voice_pipeline`` coroutine — the handler
    # tests verify only that the call happens; the pipeline itself has
    # its own dedicated test module.
    def _swallow_coroutine(coro, name=None):  # noqa: ARG001
        coro.close()
        return MagicMock()
    provider.hass.async_create_background_task = MagicMock(side_effect=_swallow_coroutine)
    await handlers["voice_pipeline_start"](
        provider.hass,
        conn,
        {"id": 13, "type": "habitron/voice_pipeline_start", "payload": {}},
    )
    assert "touch_1" in provider.voice_pipelines


# ---------- voice_audio_chunk ----------


async def test_voice_audio_chunk_returns_when_no_pipeline() -> None:
    """Chunks for a non-running pipeline are silently dropped."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["voice_audio_chunk"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/voice_audio_chunk",
         "payload": base64.b64encode(b"chunk").decode("ascii")},
    )


async def test_voice_audio_chunk_puts_to_queue() -> None:
    """A valid base64-encoded chunk is put on the pipeline's audio queue."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    provider.voice_pipelines["touch_1"] = {"queue": queue}
    await handlers["voice_audio_chunk"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/voice_audio_chunk",
         "payload": base64.b64encode(b"chunk").decode("ascii")},
    )
    assert await queue.get() == b"chunk"


async def test_voice_audio_chunk_logs_on_decode_error() -> None:
    """A malformed base64 payload is caught and logged."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    provider.voice_pipelines["touch_1"] = {"queue": queue}
    with patch(
        "custom_components.habitron.ws_provider.handlers.base64.b64decode",
        side_effect=TypeError("bad"),
    ):
        await handlers["voice_audio_chunk"](
            provider.hass,
            conn,
            {"id": 1, "type": "habitron/voice_audio_chunk", "payload": "x"},
        )


async def test_voice_audio_chunk_handles_queue_full() -> None:
    """A full queue is logged but does not raise."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn

    full_queue = MagicMock()
    full_queue.put = AsyncMock(side_effect=asyncio.QueueFull())
    provider.voice_pipelines["touch_1"] = {"queue": full_queue}
    await handlers["voice_audio_chunk"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/voice_audio_chunk",
         "payload": base64.b64encode(b"chunk").decode("ascii")},
    )


# ---------- voice_pipeline_abort ----------


async def test_voice_pipeline_abort_cancels_task_and_sets_idle() -> None:
    """An abort cancels the pipeline task and sets the satellite IDLE."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    task = MagicMock(done=lambda: False)
    provider.voice_pipelines["touch_1"] = {"task": task}
    sat = MagicMock()
    provider.assist_satellites["touch_1"] = sat
    await handlers["voice_pipeline_abort"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/voice_pipeline_abort"},
    )
    task.cancel.assert_called()
    sat.set_idle.assert_called()
    assert "touch_1" not in provider.voice_pipelines


async def test_voice_pipeline_abort_skips_done_task() -> None:
    """A done task is not re-cancelled."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    task = MagicMock(done=lambda: True)
    provider.voice_pipelines["touch_1"] = {"task": task}
    await handlers["voice_pipeline_abort"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/voice_pipeline_abort"},
    )
    task.cancel.assert_not_called()


# ---------- voice_pipeline_end ----------


async def test_voice_pipeline_end_puts_none_on_queue() -> None:
    """An end signal puts None on the audio queue to terminate the stream."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    provider.voice_pipelines["touch_1"] = {"queue": queue}
    await handlers["voice_pipeline_end"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/voice_pipeline_end"},
    )
    assert await queue.get() is None


async def test_voice_pipeline_end_acks_for_inactive_pipeline() -> None:
    """An end signal for an inactive pipeline acks and returns."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["voice_pipeline_end"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/voice_pipeline_end"},
    )
    conn.send_result.assert_called_with(1)


# ---------- tts_playback_finished ----------


async def test_tts_playback_finished_sets_event_and_idles_satellite() -> None:
    """playback_finished sets the asyncio.Event and IDLEs the satellite."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    event = asyncio.Event()
    provider.voice_pipelines["touch_1"] = {"playback_event": event}
    sat = MagicMock()
    sat.entity_id = "assist_satellite.touch_1"
    provider.assist_satellites["touch_1"] = sat
    await handlers["tts_playback_finished"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/tts_playback_finished"},
    )
    assert event.is_set()
    sat.set_idle.assert_called()


# ---------- webrtc_answer ----------


async def test_webrtc_answer_sets_future_result() -> None:
    """A webrtc answer resolves the pending future with the answer SDP."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    fut: asyncio.Future = asyncio.Future()
    provider.webrtc_futures["sess-1"] = fut
    await handlers["webrtc_answer"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/webrtc_answer",
         "session_id": "sess-1", "sdp": "answer-sdp", "stream_name": "touch_1"},
    )
    assert fut.result() == "answer-sdp"


async def test_webrtc_answer_unknown_session_is_logged_not_raised() -> None:
    """An answer for an unknown session is logged but does not raise."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["webrtc_answer"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/webrtc_answer",
         "session_id": "ghost", "sdp": "x", "stream_name": "touch_1"},
    )
    conn.send_result.assert_called()


# ---------- webrtc_candidate ----------


async def test_webrtc_candidate_forwards_to_send_message_when_callback_known() -> None:
    """A candidate with a registered send_message callback is forwarded immediately."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    sent = MagicMock()
    provider.webrtc_send_message_callbacks["sess-1"] = sent
    await handlers["webrtc_candidate"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/webrtc_candidate",
         "session_id": "sess-1", "candidate": "c-str",
         "sdp_mid": "mid", "sdp_m_line_index": 0},
    )
    sent.assert_called()


async def test_webrtc_candidate_queues_when_no_callback() -> None:
    """A candidate without a callback is queued for later draining."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["webrtc_candidate"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/webrtc_candidate",
         "session_id": "sess-1", "candidate": "c-str",
         "sdp_mid": "mid", "sdp_m_line_index": 0},
    )
    assert "sess-1" in provider.pending_candidates


# ---------- snapshot_result ----------


async def test_snapshot_result_resolves_future_with_bytes() -> None:
    """A snapshot with base64 data resolves the future with decoded bytes."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    fut = asyncio.Future()
    provider.snapshot_futures["req-1"] = {"future": fut}
    await handlers["snapshot_result"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/snapshot_result",
         "request_id": "req-1",
         "data": base64.b64encode(b"png").decode("ascii")},
    )
    assert fut.result() == b"png"


async def test_snapshot_result_error_sets_exception() -> None:
    """A snapshot result with an error sets the future exception."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    fut = asyncio.Future()
    provider.snapshot_futures["req-1"] = {"future": fut}
    await handlers["snapshot_result"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/snapshot_result",
         "request_id": "req-1", "error": "client failed"},
    )
    assert fut.exception() is not None


async def test_snapshot_result_bad_base64_sets_exception() -> None:
    """A malformed base64 payload sets a HomeAssistantError on the future."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    fut = asyncio.Future()
    provider.snapshot_futures["req-1"] = {"future": fut}
    with patch(
        "custom_components.habitron.ws_provider.handlers.base64.b64decode",
        side_effect=ValueError("bad"),
    ):
        await handlers["snapshot_result"](
            provider.hass,
            conn,
            {"id": 1, "type": "habitron/snapshot_result",
             "request_id": "req-1", "data": "garbage"},
        )
    assert fut.exception() is not None


async def test_snapshot_result_missing_data_sets_exception() -> None:
    """A snapshot result with no data and no error is treated as failure."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    fut = asyncio.Future()
    provider.snapshot_futures["req-1"] = {"future": fut}
    await handlers["snapshot_result"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/snapshot_result", "request_id": "req-1"},
    )
    assert fut.exception() is not None


async def test_snapshot_result_unknown_request_logs() -> None:
    """A snapshot for an unknown / completed request is logged and acked."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["snapshot_result"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/snapshot_result",
         "request_id": "ghost", "data": "x"},
    )
    conn.send_result.assert_called()


# ---------- call_announcement ----------


async def test_call_announcement_missing_text_sends_failure() -> None:
    """An announcement with no message text returns a failure result."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["call_announcement"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/call_announcement", "message": ""},
    )
    result = conn.send_result.call_args.args
    assert result[1]["success"] is False


async def test_call_announcement_no_satellite_sends_failure() -> None:
    """An announcement without a registered satellite returns a failure result."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["call_announcement"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/call_announcement", "message": "hello"},
    )
    result = conn.send_result.call_args.args
    assert result[1]["success"] is False


async def test_call_announcement_forwards_to_satellite() -> None:
    """A valid announcement calls async_internal_announce on the satellite."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    sat = MagicMock()
    sat.async_internal_announce = AsyncMock()
    provider.assist_satellites["touch_1"] = sat
    await handlers["call_announcement"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/call_announcement", "message": "hello"},
    )
    sat.async_internal_announce.assert_awaited()
    conn.send_result.assert_called_with(1)


async def test_call_announcement_satellite_error_returned() -> None:
    """A satellite exception is caught and surfaced in the result."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    sat = MagicMock()
    sat.async_internal_announce = AsyncMock(side_effect=RuntimeError("oops"))
    provider.assist_satellites["touch_1"] = sat
    await handlers["call_announcement"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/call_announcement", "message": "hi"},
    )
    result = conn.send_result.call_args.args
    assert result[1]["success"] is False


# ---------- update_media_state ----------


async def test_update_media_state_forwards_to_player() -> None:
    """A state update forwards to the registered media player."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    player = MagicMock()
    provider.media_players["touch_1"] = player
    await handlers["update_media_state"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/update_media_state",
         "state": "playing", "attributes": {"volume_level": 0.5}},
    )
    player.update_from_client.assert_called_with(
        "playing", {"volume_level": 0.5}
    )


async def test_update_media_state_returns_failure_when_no_player() -> None:
    """Without a registered player the response is a failure."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["update_media_state"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/update_media_state",
         "state": "playing", "attributes": {}},
    )
    result = conn.send_result.call_args.args
    assert result[1]["success"] is False


# ---------- media_next_track / media_previous_track ----------


async def test_media_next_track_forwards_to_player() -> None:
    """A next_track command delegates to the player."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    player = MagicMock()
    player.async_media_next_track = AsyncMock()
    provider.media_players["touch_1"] = player
    await handlers["media_next_track"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/media_next_track"},
    )
    player.async_media_next_track.assert_awaited()
    result = conn.send_result.call_args.args
    assert result[1]["success"] is True


async def test_media_next_track_player_exception_returns_failure() -> None:
    """A failing next_track delegation reports success=False."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    player = MagicMock()
    player.async_media_next_track = AsyncMock(side_effect=RuntimeError("boom"))
    provider.media_players["touch_1"] = player
    await handlers["media_next_track"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/media_next_track"},
    )
    result = conn.send_result.call_args.args
    assert result[1]["success"] is False


async def test_media_next_track_no_player_reports_false() -> None:
    """Without a player, next_track reports success=False."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    await handlers["media_next_track"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/media_next_track"},
    )
    result = conn.send_result.call_args.args
    assert result[1]["success"] is False


async def test_media_previous_track_forwards_to_player() -> None:
    """A previous_track command delegates to the player."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    player = MagicMock()
    player.async_media_previous_track = AsyncMock()
    provider.media_players["touch_1"] = player
    await handlers["media_previous_track"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/media_previous_track"},
    )
    player.async_media_previous_track.assert_awaited()
    result = conn.send_result.call_args.args
    assert result[1]["success"] is True


async def test_media_previous_track_player_exception_returns_failure() -> None:
    """A failing previous_track delegation reports success=False."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    player = MagicMock()
    player.async_media_previous_track = AsyncMock(side_effect=RuntimeError("x"))
    provider.media_players["touch_1"] = player
    await handlers["media_previous_track"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/media_previous_track"},
    )
    result = conn.send_result.call_args.args
    assert result[1]["success"] is False


# ---------- report_state ----------


async def test_report_state_fires_bus_event_and_records_version() -> None:
    """report_state records the client version and fires a habitron event."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    mod = MagicMock()
    provider.rtr.get_module_by_stream = MagicMock(return_value=mod)
    await handlers["report_state"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/report_state",
         "payload": {"version": "1.2.3", "battery_level": 80}},
    )
    assert mod.client_version == "1.2.3"
    provider.hass.bus.async_fire.assert_called()


async def test_report_state_without_matching_module_just_fires() -> None:
    """If get_module_by_stream returns None the bus event still fires."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    provider.active_ws_connections["touch_1"] = conn
    provider.rtr.get_module_by_stream = MagicMock(return_value=None)
    await handlers["report_state"](
        provider.hass,
        conn,
        {"id": 1, "type": "habitron/report_state", "payload": {}},
    )
    provider.hass.bus.async_fire.assert_called()


# ---------- Error paths (unknown client) ----------


@pytest.mark.parametrize(
    "command",
    [
        "voice_pipeline_status",
        "voice_pipeline_start",
        "voice_pipeline_end",
        "voice_audio_chunk",
        "voice_pipeline_abort",
        "tts_playback_finished",
        "webrtc_answer",
        "webrtc_candidate",
        "snapshot_result",
        "call_announcement",
        "update_media_state",
        "media_next_track",
        "media_previous_track",
        "report_state",
    ],
)
async def test_all_handlers_send_error_for_unknown_client(command: str) -> None:
    """Every handler that calls ``_get_stream_or_send_error`` errors out for unknown clients."""
    provider = _make_provider()
    handlers = _registered_handlers(provider)
    conn = _make_connection()
    # No registration → unknown client → send_error
    msg = {
        "id": 1,
        "type": f"habitron/{command}",
        "stream_name": "touch_1",
        "version": "1.0",
        "payload": {},
        "disabled": False,
        "session_id": "sess",
        "sdp": "",
        "request_id": "req",
        "message": "hello",
        "state": "playing",
    }
    await handlers[command](provider.hass, conn, msg)
    conn.send_error.assert_called()
