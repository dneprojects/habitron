"""Habitron WebRTC / WebSocket provider package.

Split out of the original single-file ``ws_provider.py`` for content
cohesion:

* ``provider``        — the ``HabitronWebRTCProvider`` class itself plus
  the message-passing API, WebRTC negotiation and snapshot requests.
* ``voice_pipeline``  — the ``run_voice_pipeline`` coroutine that runs
  Home Assistant's Assist pipeline over a client's audio stream.
* ``handlers``        — every ``habitron/*`` WebSocket command handler.

External code keeps importing ``HabitronWebRTCProvider`` (and the lower
level ``async_register_webrtc_provider`` from the camera component) from
``custom_components.habitron.ws_provider`` exactly as before.
"""

from __future__ import annotations

from homeassistant.components.camera import async_register_webrtc_provider

from .provider import HabitronWebRTCProvider

__all__ = ["HabitronWebRTCProvider", "async_register_webrtc_provider"]
