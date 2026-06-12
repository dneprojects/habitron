"""Assist voice pipeline execution for the Habitron WebRTC provider.

Holds the long-running ``run_voice_pipeline`` coroutine that pumps audio
chunks from a client through Home Assistant's Assist pipeline and streams
the resulting TTS audio back to the client. Extracted from the provider
module so the audio / TTS plumbing lives in its own file.
"""

import asyncio
import base64
from collections.abc import AsyncIterator
import logging
import struct
from typing import TYPE_CHECKING

from homeassistant.components import tts
from homeassistant.components.assist_pipeline import (
    PipelineEvent,
    PipelineEventType,
    async_pipeline_from_audio_stream,
)
from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
)
from homeassistant.components.websocket_api import ActiveConnection
from homeassistant.core import Context, callback

if TYPE_CHECKING:
    from .provider import HabitronWebRTCProvider


_LOGGER = logging.getLogger(__name__)


async def run_voice_pipeline(
    provider: HabitronWebRTCProvider,
    connection: ActiveConnection,
    stream_name: str,
    context: Context,
    pipeline_id: str | None,
    device_id: str | None,
    satellite_id: str | None,
    tts_voice: str | None,
    audio_queue: asyncio.Queue[bytes | None],
    playback_finished_event: asyncio.Event,
) -> None:
    """Start and manage the Assist pipeline for incoming audio.

    ``audio_queue``, ``playback_finished_event`` and the task handle are
    created by the caller *before* this coroutine is scheduled and
    inserted into ``provider.voice_pipelines`` atomically. That avoids
    losing the task handle if the coroutine raises before reaching this
    point, and gives ``handle_voice_audio_chunk`` a queue to drop into
    even on the very first chunk.
    """
    _LOGGER.info(
        "Starting manual voice pipeline for stream '%s' with pipeline_id: %s",
        stream_name,
        pipeline_id,
    )

    # Set satellite state to LISTENING immediately
    satellite = provider.assist_satellites.get(stream_name)
    if satellite:
        _LOGGER.info(
            "Setting satellite %s state to LISTENING via base class _set_state",
            satellite.entity_id,
        )
        # Use the inherited _set_state method from AssistSatelliteEntity
        satellite.set_listening()
    else:
        _LOGGER.warning(
            "Could not find satellite for stream '%s' to update state",
            stream_name,
        )

    try:
        last_err = ""

        async def audio_stream() -> AsyncIterator[bytes]:
            """Yield audio chunks for the pipeline, starting with a WAV header."""
            # Create a 44-byte WAV header for 16-bit 16kHz mono PCM
            channels = 1
            sample_width_bytes = 2  # 16 bits
            sample_rate = 16000  # 16 kHz
            header = struct.pack(
                "<4sI4s4sIHHIIHH4sI",
                b"RIFF",
                0,  # Placeholder for file size
                b"WAVE",
                b"fmt ",
                16,  # PCM format chunk size
                1,  # PCM format
                channels,
                sample_rate,
                sample_rate * channels * sample_width_bytes,  # byte_rate
                channels * sample_width_bytes,  # block_align
                sample_width_bytes * 8,  # bits_per_sample
                b"data",
                0,  # Placeholder for data size
            )
            yield header

            # Yield chunks from the queue until None is received
            while True:
                chunk = await audio_queue.get()
                if chunk is None:
                    break
                yield chunk

        tts_task: asyncio.Task[None] | None = None  # Task for streaming TTS audio back
        tts_was_streamed = False

        @callback
        def event_callback(event: PipelineEvent) -> None:
            """Handle pipeline events FOR TTS STREAMING ONLY."""
            # This callback is executed synchronously by the pipeline.
            nonlocal tts_task
            _LOGGER.warning(
                "Provider event_callback received: %s for %s",
                event.type,
                stream_name,
            )
            sat = provider.assist_satellites.get(stream_name)
            if sat:
                # Forward the event to the satellite entity's on_pipeline_event method
                # Run as task because on_pipeline_event might become async or do async things
                sat.on_pipeline_event(event)
            else:
                _LOGGER.warning(
                    "Event_callback: Could not find satellite for stream '%s' to forward event",
                    stream_name,
                )
            # --- Specific handling for TTS_END to stream audio ---
            if (
                event.type == PipelineEventType.TTS_END
                and event.data
                and (tts_output := event.data.get("tts_output"))
                and (token := tts_output.get("token"))
            ):

                async def _stream_tts_to_client() -> None:
                    """Fetch TTS audio stream and send chunks to the client."""
                    _LOGGER.debug("Starting TTS stream to client for token %s", token)
                    try:
                        # Get the TTS audio stream using the token
                        stream = tts.async_get_stream(provider.hass, token)
                        if stream is None:
                            _LOGGER.error(
                                "Could not find TTS stream for token %s", token
                            )
                            return

                        # Send each chunk base64 encoded
                        async for chunk in stream.async_stream_result():
                            if chunk:
                                await provider.async_send_json_message(
                                    stream_name,
                                    {
                                        "type": "habitron/voice_tts_chunk",
                                        "payload": base64.b64encode(chunk).decode(
                                            "utf-8"
                                        ),
                                    },
                                )
                        # Send empty payload to signal end of TTS stream
                        await provider.async_send_json_message(
                            stream_name,
                            {"type": "habitron/voice_tts_chunk", "payload": ""},
                        )
                        _LOGGER.debug(
                            "Finished streaming TTS to client for token %s",
                            token,
                        )
                    except Exception:
                        _LOGGER.exception("Error streaming TTS to client")

                # Start the TTS streaming task
                tts_task = provider.hass.async_create_task(_stream_tts_to_client())
                nonlocal tts_was_streamed
                tts_was_streamed = True
            # --- End of TTS_END handling ---

        # Define the expected audio format from the client
        stt_metadata = SpeechMetadata(
            language=provider.hass.config.language,
            format=AudioFormats.WAV,
            codec=AudioCodecs.PCM,
            bit_rate=AudioBitRates.BITRATE_16,
            sample_rate=AudioSampleRates.SAMPLERATE_16000,
            channel=AudioChannels.CHANNEL_MONO,
        )

        # Specify preferred TTS output format and optional voice
        tts_audio_output = {
            tts.ATTR_PREFERRED_FORMAT: AudioFormats.WAV.value,
            tts.ATTR_PREFERRED_SAMPLE_RATE: AudioSampleRates.SAMPLERATE_16000.value,
            tts.ATTR_PREFERRED_SAMPLE_CHANNELS: AudioChannels.CHANNEL_MONO.value,
        }
        if tts_voice:
            tts_audio_output["voice"] = tts_voice

        # Run the Assist pipeline
        await async_pipeline_from_audio_stream(
            provider.hass,
            context=context,
            event_callback=event_callback,  # Pass our local callback for TTS
            stt_stream=audio_stream(),
            stt_metadata=stt_metadata,
            pipeline_id=pipeline_id,  # Use configured or default pipeline
            conversation_id=None,  # Start new conversation
            device_id=device_id,
            satellite_id=satellite_id,
            tts_audio_output=tts_audio_output,
        )

        # Wait for the TTS streaming task (if any) to complete
        if tts_task:
            _LOGGER.debug("Waiting for TTS streaming task to complete")
            await tts_task
            _LOGGER.debug("TTS streaming task completed")

            if tts_was_streamed:
                # Wait for client 'tts_playback_finished' event
                _LOGGER.debug(
                    "Waiting for client to signal TTS playback finished for stream %s",
                    stream_name,
                )
                try:
                    # Wait for the event set by handle_tts_playback_finished
                    await asyncio.wait_for(playback_finished_event.wait(), timeout=30)
                    _LOGGER.debug(
                        "Client confirmed TTS playback finished for stream %s",
                        stream_name,
                    )
                except TimeoutError:
                    _LOGGER.warning(
                        "Client did not confirm TTS playback for stream %s, timing out",
                        stream_name,
                    )

    except asyncio.CancelledError:
        _LOGGER.info("Voice pipeline task cancelled for stream '%s'", stream_name)
    except Exception as err:
        _LOGGER.exception(
            "Unexpected error in voice pipeline for stream '%s'", stream_name
        )
        last_err = str(err)
    finally:
        _LOGGER.info("Voice pipeline for stream '%s' finished", stream_name)
        provider.voice_pipelines.pop(stream_name, None)
        connection.send_message(
            {"type": "habitron/voice_pipeline_finished", "error": last_err}
        )
