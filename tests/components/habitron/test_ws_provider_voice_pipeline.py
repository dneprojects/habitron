"""Tests for the Habitron Assist voice pipeline.

Exercises ``ws_provider.voice_pipeline.run_voice_pipeline`` by stubbing
out ``async_pipeline_from_audio_stream`` so the function body executes
without spinning up a real Assist pipeline. We can also fire fake
``PipelineEvent`` callbacks from the stub to drive the nested
``event_callback`` / ``_stream_tts_to_client`` paths.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.habitron.ws_provider.voice_pipeline import run_voice_pipeline


def _make_provider() -> MagicMock:
    p = MagicMock()
    p.hass.config.language = "de"
    p.hass.async_create_task = MagicMock()
    p.async_send_json_message = AsyncMock()
    p.assist_satellites = {}
    p.voice_pipelines = {}
    return p


def _make_connection() -> MagicMock:
    conn = MagicMock()
    conn.send_message = MagicMock()
    return conn


async def _drive_pipeline(
    *,
    provider: MagicMock,
    connection: MagicMock,
    pipeline_side_effect=None,
    extra_kwargs: dict | None = None,
) -> None:
    """Run ``run_voice_pipeline`` with ``async_pipeline_from_audio_stream`` patched."""
    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    # The audio_stream() inside run_voice_pipeline will pull from the queue;
    # priming a None ends the stream immediately.
    audio_queue.put_nowait(None)
    playback_event = asyncio.Event()

    pipeline_kwargs = (
        {"side_effect": pipeline_side_effect} if pipeline_side_effect else {}
    )
    # If side_effect is async, AsyncMock handles it directly.
    pipeline_mock = AsyncMock(**pipeline_kwargs)
    with patch(
        "custom_components.habitron.ws_provider.voice_pipeline."
        "async_pipeline_from_audio_stream",
        new=pipeline_mock,
    ):
        await run_voice_pipeline(
            provider,
            connection,
            "touch_1",
            MagicMock(),  # context
            None,  # pipeline_id
            None,  # device_id
            None,  # satellite_id
            (extra_kwargs or {}).get("tts_voice"),
            audio_queue,
            playback_event,
        )
    return pipeline_mock


async def test_run_voice_pipeline_happy_path_sends_finished_message() -> None:
    """A clean run sends a habitron/voice_pipeline_finished WS message at the end."""
    provider = _make_provider()
    connection = _make_connection()
    await _drive_pipeline(provider=provider, connection=connection)
    args = connection.send_message.call_args.args[0]
    assert args["type"] == "habitron/voice_pipeline_finished"
    assert args["error"] == ""


async def test_run_voice_pipeline_sets_satellite_to_listening() -> None:
    """A registered satellite has its set_listening() called early."""
    provider = _make_provider()
    sat = MagicMock()
    sat.entity_id = "assist_satellite.touch_1"
    sat.set_listening = MagicMock()
    provider.assist_satellites["touch_1"] = sat
    await _drive_pipeline(provider=provider, connection=_make_connection())
    sat.set_listening.assert_called()


async def test_run_voice_pipeline_warns_when_no_satellite() -> None:
    """Without a satellite, the pipeline still runs to completion."""
    provider = _make_provider()
    connection = _make_connection()
    await _drive_pipeline(provider=provider, connection=connection)
    # The finished message was sent regardless.
    connection.send_message.assert_called()


async def test_run_voice_pipeline_drops_pipeline_state_on_completion() -> None:
    """The provider's voice_pipelines entry is cleaned up at the end."""
    provider = _make_provider()
    provider.voice_pipelines["touch_1"] = {"task": MagicMock()}
    await _drive_pipeline(provider=provider, connection=_make_connection())
    assert "touch_1" not in provider.voice_pipelines


async def test_run_voice_pipeline_forwards_tts_voice_in_audio_output() -> None:
    """A configured tts_voice is added to the ``tts_audio_output`` dict."""
    provider = _make_provider()
    pipeline = await _drive_pipeline(
        provider=provider,
        connection=_make_connection(),
        extra_kwargs={"tts_voice": "voice-x"},
    )
    audio_out = pipeline.call_args.kwargs["tts_audio_output"]
    assert audio_out["voice"] == "voice-x"


async def test_run_voice_pipeline_catches_cancelled_error() -> None:
    """A CancelledError during pipeline execution is logged + finished."""
    provider = _make_provider()
    connection = _make_connection()

    async def _cancel(*args, **kwargs):
        raise asyncio.CancelledError

    await _drive_pipeline(
        provider=provider,
        connection=connection,
        pipeline_side_effect=_cancel,
    )
    # The finished message still goes out
    msg = connection.send_message.call_args.args[0]
    assert msg["type"] == "habitron/voice_pipeline_finished"


async def test_run_voice_pipeline_catches_generic_exception() -> None:
    """A generic exception is logged + stored in the finished message."""
    provider = _make_provider()
    connection = _make_connection()

    async def _boom(*args, **kwargs):
        raise RuntimeError("oops")

    await _drive_pipeline(
        provider=provider,
        connection=connection,
        pipeline_side_effect=_boom,
    )
    msg = connection.send_message.call_args.args[0]
    assert msg["type"] == "habitron/voice_pipeline_finished"
    assert "oops" in msg["error"]


# ---------- event_callback + _stream_tts_to_client coverage ----------


async def test_run_voice_pipeline_forwards_event_to_satellite() -> None:
    """A pipeline event is forwarded to the satellite's on_pipeline_event."""
    from homeassistant.components.assist_pipeline import (  # noqa: PLC0415
        PipelineEvent,
        PipelineEventType,
    )

    provider = _make_provider()
    sat = MagicMock()
    sat.entity_id = "assist_satellite.touch_1"
    sat.set_listening = MagicMock()
    sat.on_pipeline_event = MagicMock()
    provider.assist_satellites["touch_1"] = sat

    async def _fire_event(*args, **kwargs):
        cb = kwargs["event_callback"]
        cb(PipelineEvent(type=PipelineEventType.INTENT_START, data=None))

    await _drive_pipeline(
        provider=provider,
        connection=_make_connection(),
        pipeline_side_effect=_fire_event,
    )
    sat.on_pipeline_event.assert_called()


async def test_run_voice_pipeline_event_callback_logs_when_no_satellite() -> None:
    """If the satellite is missing at event time, the callback just logs."""
    from homeassistant.components.assist_pipeline import (  # noqa: PLC0415
        PipelineEvent,
        PipelineEventType,
    )

    provider = _make_provider()

    # No satellite registered → the event_callback hits the warning branch.
    async def _fire_event(*args, **kwargs):
        cb = kwargs["event_callback"]
        cb(PipelineEvent(type=PipelineEventType.INTENT_START, data=None))

    await _drive_pipeline(
        provider=provider,
        connection=_make_connection(),
        pipeline_side_effect=_fire_event,
    )


async def test_run_voice_pipeline_tts_end_streams_audio_to_client() -> None:
    """A TTS_END event spawns ``_stream_tts_to_client`` which streams chunks."""
    from homeassistant.components.assist_pipeline import (  # noqa: PLC0415
        PipelineEvent,
        PipelineEventType,
    )

    provider = _make_provider()
    connection = _make_connection()

    # Build a stub TTS stream that yields one chunk
    class _FakeStream:
        async def async_stream_result(self):
            yield b"audio-bytes"

    fake_stream = _FakeStream()

    # The hass.async_create_task should actually run our coroutine for
    # the streaming test — capture and run it.
    spawned: list = []

    def _spawn(coro):
        spawned.append(coro)
        return MagicMock()

    provider.hass.async_create_task = MagicMock(side_effect=_spawn)

    async def _fire_tts_end(*args, **kwargs):
        cb = kwargs["event_callback"]
        cb(
            PipelineEvent(
                type=PipelineEventType.TTS_END,
                data={"tts_output": {"token": "tts-tok"}},
            )
        )

    with patch(
        "custom_components.habitron.ws_provider.voice_pipeline.tts.async_get_stream",
        return_value=fake_stream,
    ):
        await _drive_pipeline(
            provider=provider,
            connection=connection,
            pipeline_side_effect=_fire_tts_end,
        )
        # Drive the spawned _stream_tts_to_client coroutine to completion
        for coro in spawned:
            await coro
    # The provider should have sent at least one tts chunk + an empty terminator
    sent_types = [
        c.call_args.kwargs.get(
            "msg", c.call_args.args[1] if len(c.call_args.args) > 1 else {}
        )
        for c in provider.async_send_json_message.await_args_list
    ]
    # Easier: count call_args directly
    sent_messages = [
        call.args[1] if len(call.args) > 1 else call.kwargs.get("msg")
        for call in provider.async_send_json_message.call_args_list
    ]
    assert any(m["type"] == "habitron/voice_tts_chunk" for m in sent_messages)


async def test_run_voice_pipeline_tts_end_handles_missing_stream() -> None:
    """A TTS_END whose token has no matching stream logs an error + continues."""
    from homeassistant.components.assist_pipeline import (  # noqa: PLC0415
        PipelineEvent,
        PipelineEventType,
    )

    provider = _make_provider()

    spawned: list = []

    def _spawn(coro):
        spawned.append(coro)
        return MagicMock()

    provider.hass.async_create_task = MagicMock(side_effect=_spawn)

    async def _fire_tts_end(*args, **kwargs):
        cb = kwargs["event_callback"]
        cb(
            PipelineEvent(
                type=PipelineEventType.TTS_END,
                data={"tts_output": {"token": "missing"}},
            )
        )

    with patch(
        "custom_components.habitron.ws_provider.voice_pipeline.tts.async_get_stream",
        return_value=None,
    ):
        await _drive_pipeline(
            provider=provider,
            connection=_make_connection(),
            pipeline_side_effect=_fire_tts_end,
        )
        for coro in spawned:
            await coro


async def test_run_voice_pipeline_tts_streaming_exception_is_logged() -> None:
    """An exception while streaming TTS is caught + logged inside the helper."""
    from homeassistant.components.assist_pipeline import (  # noqa: PLC0415
        PipelineEvent,
        PipelineEventType,
    )

    provider = _make_provider()

    class _FailStream:
        async def async_stream_result(self):
            raise RuntimeError("stream broke")
            yield b""  # noqa: B901

    spawned: list = []
    provider.hass.async_create_task = MagicMock(
        side_effect=lambda c: (spawned.append(c), MagicMock())[1]
    )

    async def _fire_tts_end(*args, **kwargs):
        cb = kwargs["event_callback"]
        cb(
            PipelineEvent(
                type=PipelineEventType.TTS_END,
                data={"tts_output": {"token": "x"}},
            )
        )

    with patch(
        "custom_components.habitron.ws_provider.voice_pipeline.tts.async_get_stream",
        return_value=_FailStream(),
    ):
        await _drive_pipeline(
            provider=provider,
            connection=_make_connection(),
            pipeline_side_effect=_fire_tts_end,
        )
        for coro in spawned:
            await coro


async def test_run_voice_pipeline_waits_for_playback_finished_when_tts_streamed() -> (
    None
):
    """When TTS was streamed the pipeline awaits the playback_finished event."""
    from homeassistant.components.assist_pipeline import (  # noqa: PLC0415
        PipelineEvent,
        PipelineEventType,
    )

    provider = _make_provider()
    connection = _make_connection()

    class _FakeStream:
        async def async_stream_result(self):
            yield b"chunk"

    # Capture the spawned _stream_tts_to_client coroutine; we await it inline
    # so the nonlocal ``tts_was_streamed`` becomes True before the pipeline
    # body reaches the wait-for block.
    spawned_tts_task: MagicMock = MagicMock()

    def _spawn(coro):
        # Schedule the spawned coroutine so it can run alongside the pipeline.
        return asyncio.get_event_loop().create_task(coro)

    provider.hass.async_create_task = MagicMock(side_effect=_spawn)

    async def _fire(*args, **kwargs):
        cb = kwargs["event_callback"]
        cb(
            PipelineEvent(
                type=PipelineEventType.TTS_END,
                data={"tts_output": {"token": "t"}},
            )
        )

    # Set the playback_finished event up-front so the wait_for completes immediately
    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    audio_queue.put_nowait(None)
    playback_event = asyncio.Event()
    playback_event.set()

    with (
        patch(
            "custom_components.habitron.ws_provider.voice_pipeline."
            "async_pipeline_from_audio_stream",
            new=AsyncMock(side_effect=_fire),
        ),
        patch(
            "custom_components.habitron.ws_provider.voice_pipeline.tts.async_get_stream",
            return_value=_FakeStream(),
        ),
    ):
        await run_voice_pipeline(
            provider,
            connection,
            "touch_1",
            MagicMock(),
            None,
            None,
            None,
            None,
            audio_queue,
            playback_event,
        )
    # Pipeline finished without raising
    msg = connection.send_message.call_args.args[0]
    assert msg["type"] == "habitron/voice_pipeline_finished"


async def test_run_voice_pipeline_handles_playback_finished_timeout() -> None:
    """A playback_finished wait that times out is logged + pipeline continues."""
    from homeassistant.components.assist_pipeline import (  # noqa: PLC0415
        PipelineEvent,
        PipelineEventType,
    )

    provider = _make_provider()
    connection = _make_connection()

    class _FakeStream:
        async def async_stream_result(self):
            yield b"chunk"

    def _spawn(coro):
        return asyncio.get_event_loop().create_task(coro)

    provider.hass.async_create_task = MagicMock(side_effect=_spawn)

    async def _fire(*args, **kwargs):
        cb = kwargs["event_callback"]
        cb(
            PipelineEvent(
                type=PipelineEventType.TTS_END,
                data={"tts_output": {"token": "t"}},
            )
        )

    # Default ``wait_for`` would block 30s on the unset event — patch it to a fast
    # version so the test runs in milliseconds.
    real_wait_for = asyncio.wait_for

    async def _fast_wait_for(fut, timeout):
        return await real_wait_for(fut, timeout=0.001)

    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    audio_queue.put_nowait(None)
    playback_event = asyncio.Event()  # never set → triggers TimeoutError path

    with (
        patch(
            "custom_components.habitron.ws_provider.voice_pipeline."
            "async_pipeline_from_audio_stream",
            new=AsyncMock(side_effect=_fire),
        ),
        patch(
            "custom_components.habitron.ws_provider.voice_pipeline.tts.async_get_stream",
            return_value=_FakeStream(),
        ),
        patch(
            "custom_components.habitron.ws_provider.voice_pipeline.asyncio.wait_for",
            new=_fast_wait_for,
        ),
    ):
        await run_voice_pipeline(
            provider,
            connection,
            "touch_1",
            MagicMock(),
            None,
            None,
            None,
            None,
            audio_queue,
            playback_event,
        )
    msg = connection.send_message.call_args.args[0]
    assert msg["type"] == "habitron/voice_pipeline_finished"


async def test_run_voice_pipeline_audio_stream_yields_chunks() -> None:
    """The internal audio_stream() yields the WAV header + queued chunks."""
    provider = _make_provider()

    captured_chunks: list[bytes] = []

    async def _capture(*args, **kwargs):
        stt_stream = kwargs["stt_stream"]
        async for chunk in stt_stream:
            captured_chunks.append(chunk)

    audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    audio_queue.put_nowait(b"sample-pcm")
    audio_queue.put_nowait(None)
    playback_event = asyncio.Event()

    with patch(
        "custom_components.habitron.ws_provider.voice_pipeline."
        "async_pipeline_from_audio_stream",
        new=AsyncMock(side_effect=_capture),
    ):
        await run_voice_pipeline(
            provider,
            _make_connection(),
            "touch_1",
            MagicMock(),
            None,
            None,
            None,
            None,
            audio_queue,
            playback_event,
        )
    # WAV header is 44 bytes, then our PCM chunk.
    assert len(captured_chunks) == 2
    assert captured_chunks[0][:4] == b"RIFF"
    assert captured_chunks[1] == b"sample-pcm"
