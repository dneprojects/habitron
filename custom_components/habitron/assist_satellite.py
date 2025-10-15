"""Assist satellite platform for Habitron integration."""

import asyncio
import logging
from typing import Any

from homeassistant.components.assist_pipeline.pipeline import (
    PipelineEvent,
    PipelineEventType,
)
from homeassistant.components.assist_satellite import (
    AssistSatelliteAnnouncement,
    AssistSatelliteConfiguration,
    AssistSatelliteEntity,
    AssistSatelliteEntityFeature,
    AssistSatelliteWakeWord,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .module import SmartController
from .smart_hub import SmartHub
from .ws_provider import HabitronWebRTCProvider

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Habitron assist satellite entities."""
    smhub: SmartHub = hass.data[DOMAIN][entry.entry_id]
    hbtn_rt = smhub.router

    if not smhub.ws_provider:
        _LOGGER.error("WebRTC provider not available on SmartHub for assist_satellite")
        return

    provider: HabitronWebRTCProvider = smhub.ws_provider
    new_devices = []

    for hbt_module in hbtn_rt.modules:
        if (
            isinstance(hbt_module, SmartController)
            and hbt_module.mod_type == "Smart Controller Touch"
        ):
            new_devices.append(HbtnAssistSat(hass, hbt_module, provider))
            provider.assist_satellites[hbt_module.name.lower().replace(" ", "_")] = (
                new_devices[-1]
            )

    if new_devices:
        async_add_entities(new_devices)
        _LOGGER.info("Added %d Habitron assist satellite(s)", len(new_devices))


class HbtnAssistSat(AssistSatelliteEntity):
    """Representation of a Habitron client as an assist satellite."""

    def __init__(
        self,
        hass: HomeAssistant,
        module: SmartController,
        provider: HabitronWebRTCProvider,
    ) -> None:
        """Initialize the assist satellite."""
        self._hass = hass
        self._module: SmartController = module
        self._provider = provider
        self._stream_name: str = module.name.lower().replace(" ", "_")
        self._attr_name = f"Voice {module.name}"
        self._attr_unique_id = f"Mod_{self._module.uid}_assist_sat"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}
        self._attr_supported_features = (
            AssistSatelliteEntityFeature.ANNOUNCE
            | AssistSatelliteEntityFeature.START_CONVERSATION
        )

    @property
    def stream_name(self) -> str:
        """Return the stream name used for websocket communication."""
        return self._stream_name

    async def async_start_conversation(
        self, start_announcement: AssistSatelliteAnnouncement
    ) -> None:
        """Handle start conversation action."""
        _LOGGER.debug(
            "Sending start streaming command to client: %s", self._stream_name
        )
        if start_announcement:
            await self.async_announce(start_announcement)
        await self._provider.async_send_json_message(
            self._stream_name,
            {
                "type": "habitron/voice_start_streaming",
                "payload": {"entity_id": self.entity_id},
            },
        )

    async def async_announce(self, announcement: AssistSatelliteAnnouncement) -> None:
        """Sends an announcement to the device.."""
        _LOGGER.debug("Sending media URL to Flutter client: %s", announcement.media_id)
        if announcement.preannounce_media_id:
            media_url = await self._module.media_player.process_media_id(
                announcement.preannounce_media_id
            )
            await self._provider.async_send_json_message(
                self._stream_name,
                {
                    "type": "habitron/voice_play_announcement",
                    "payload": {"url": media_url},
                },
            )
            await asyncio.sleep(0.2)

        media_url = await self._module.media_player.process_media_id(
            announcement.media_id
        )
        await self._provider.async_send_json_message(
            self._stream_name,
            {
                "type": "habitron/voice_play_announcement",
                "payload": {"url": media_url},
            },
        )

    # The following methods are required by the base class but can be minimal
    # if your device doesn't support on-device wake word or VAD configuration.
    async def async_get_configuration(self) -> AssistSatelliteConfiguration | None:
        """Return the current pipeline configuration for this satellite."""

        wake_word = AssistSatelliteWakeWord("ok_home", "OK, home", ["de"])
        return AssistSatelliteConfiguration([wake_word], ["OK, home"], 1)

    async def async_set_configuration(self, config: dict[str, Any]) -> None:
        """Set the pipeline configuration for this satellite."""

    async def on_pipeline_event(self, event: PipelineEvent) -> None:
        """Handle events from the pipeline to notify the client."""
        if event.type == PipelineEventType.RUN_END:
            _LOGGER.debug(
                "Pipeline run ended for %s. Notifying client to finish", self.entity_id
            )
            # This message tells the client that the conversation is over,
            # so it can hide the "Listening..." UI and restart wake word detection.
            await self._provider.async_send_json_message(
                self._stream_name, {"type": "habitron/voice_pipeline_finished"}
            )
