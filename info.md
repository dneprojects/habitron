<h2 align="center">
  <a href="https://habitron.de"><img src="https://www.habitron.de/tl_files/habitron/design/logo.png" alt="Habitron logotype" width="300"></a>
  <br>
  <i>Home Assistant Habitron custom integration</i>
  <br>
</h2>

<p align="center">
  <a href="https://github.com/custom-components/hacs"><img src="https://img.shields.io/badge/HACS-Custom-orange.svg"></a>
  <img src="https://img.shields.io/github/v/release/dneprojects/habitron" alt="Current version">
</p>

Connects Home Assistant to a [Habitron](https://www.habitron.de/) SmartHub and every module on its Smart-X bus.
Lights, dimmers, RGB CLEDs, blinds and shutters, climate controllers, switches and flags, push-button events, motion / rain / humidity / temperature / illuminance sensors, SC Touch microphone, camera and speaker, SMS notifications, firmware updates, diagnostic counters — all native HA entities, fed by push updates with a coordinator-driven liveness heartbeat.

## Highlights

- **Native HA UX**: every Habitron concept maps to a proper HA domain — no virtual entities, no `device_tracker` workarounds.
- **Push first**: input changes show up in HA in <100 ms via the SmartHub's WebSocket; the heartbeat only validates that the link is alive.
- **SC Touch first-class**: WebRTC camera, an Assist satellite for the on-device microphone, and the speaker as a HA `media_player` with queue.
- **Multi-hub aware**: add more than one SmartHub to manage several buildings from one HA instance.
- **Quality-scale ready**: typed runtime data, runtime data migration, services in `services.py`, icon and entity translations, diagnostics export, reconfiguration flow, stale-device cleanup.

## Configuration

Use **Settings → Devices & Services → Add Integration → Habitron** after installation. Provide the SmartHub host or IP and an update interval (4–60 s). If HA runs directly on the SmartCenter, use the literal `local` as the host.

## More

See the [README](https://github.com/dneprojects/habitron/blob/dev/README.md) on GitHub for the complete documentation, including supported devices, services, examples, known limitations and troubleshooting.

The [SmartCenter PDF](https://github.com/dneprojects/habitron/tree/main/SmartCenter_Dokumentation.pdf) covers the SmartCenter / SmartHub side of the story.
