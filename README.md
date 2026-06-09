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

The `habitron` integration connects Home Assistant to a [Habitron](https://www.habitron.de/) SmartHub and the modules on its Smart-X bus. It exposes every input, output, sensor, dimmer, colour LED, blind, climate controller and notification target of a Habitron installation as a fully-typed Home Assistant entity. State changes are delivered push-style over a long-lived WebSocket from the SmartHub, with a coordinator-driven heartbeat for liveness detection.

---

## Table of contents

- [Supported devices](#supported-devices)
- [Supported functions](#supported-functions)
- [Use cases](#use-cases)
- [Installation](#installation)
- [Configuration parameters](#configuration-parameters)
- [Data updates](#data-updates)
- [Services](#services)
- [Examples](#examples)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Removal](#removal)

---

## Supported devices

The integration drives one **Habitron SmartHub** (SmartIP / SmartCenter) per config entry. Multiple SmartHubs can be added side-by-side. Through the SmartHub it talks to every module connected to the local Smart-X bus, including:

| Family | Examples | Recognised entities |
| --- | --- | --- |
| Smart Controller | SC, SC Mini, SC Touch | binary sensors, switches, lights, dimmers, climate, notify, group-mode selectors |
| Smart Controller Touch | SC Touch | adds camera, media_player, assist_satellite, microphone switch and on-device speech button |
| Smart Out modules | Out8, Out16, Out8R, Out8R-relais | switches, dimmers, blinds/shutter covers, RGB CLEDs |
| Smart In modules | In16, In16 24V, In16 230V | binary sensors, button events |
| Smart Detect / Climate | motion + rain sensors, ekey, wind | motion, moisture, illuminance, wind-speed sensors plus event entities |
| GSM | Smart GSM | per-recipient SMS notify entities |
| Router & Hub | SmartHub, integrated router | diagnostic sensors (CPU, disk, memory, voltages, currents, timeouts), restart/reboot buttons, firmware update |

Each module appears in Home Assistant as its own device under the SmartHub. Module discovery happens during entry setup via the SmartHub's own bus inventory — there is no per-module pairing step.

## Supported functions

The integration covers every Habitron entity domain Home Assistant offers, except those that are not exposed by the bus:

- **light**: on/off outputs, brightness dimmers, RGB corner & ambient CLEDs (with HA-native colour picker)
- **switch**: digital outputs, flag bits, indicator LEDs, climate-controller-2 toggle, microphone mode
- **cover**: blinds / shutter pairs with optional tilt and an auto-stop fail-safe at the endpoints
- **binary_sensor**: switch inputs, motion and rain detectors, hub state, SC-Touch listening status
- **event**: short-press / long-press / long-press-end on push-button inputs, ekey finger-print users
- **sensor**: temperature, humidity, illuminance, AQI, wind / windpeak, ekey identifier and finger, logic counters, hub diagnostics, channel currents/voltages/timeouts, hub state status, frequencies, percentages
- **number**: dimmer levels, analogue outputs, climate set-points
- **select**: per-group daytime / alarm / group-mode, log-level
- **climate**: per Smart Controller climate group, target-temperature + system-OK readback
- **button**: hub-restart, hub-reboot, module-reset, restart forward table, reset-all-modules, restart-hub, reboot-hub, count up/down, power-cycle router channels, voice-input trigger, collective / direct / visualisation commands
- **notify**: per-module text messages and per-GSM-number SMS targets
- **media_player**: SC Touch audio playback queue with TTS resolution, group seek, history and volume control
- **assist_satellite**: SC Touch microphone as an HA Assist satellite (STT, pipeline routing, TTS playback)
- **camera**: SC Touch front camera over WebRTC
- **text**: ekey identifier / finger name as a writable text entity
- **update**: per-module firmware update entity plus SC Touch APK update

## Use cases

- **Single-family home, on-prem Habitron**: replace the Habitron app with a HA dashboard. All lights, dimmers, blinds, climate and door entry land in HA, then drive automations from HA's calendar, sun and presence sensors.
- **SmartCenter installation**: HA running on the SmartCenter shares the bus with the native Habitron UI. The integration auto-detects the local SmartHub on `localhost`/`local`.
- **SC Touch as a wall-mounted Assist panel**: use the SC Touch microphone and speaker as a fully-integrated Voice Assistant satellite, with Assist pipelines routed through the integration and TTS played back on the device.
- **Power-cycling and remote service**: trigger `habitron.hub_reboot`, `habitron.save_module_smc` and friends from automations during off-hours so configuration is backed up to the HA config directory.
- **Multi-SmartHub**: managing several buildings or floors with separate SmartHubs from one HA instance — every entity is namespaced by the SmartHub UID, services use the loaded-entries lookup.

## Installation

### HACS (recommended)

1. Open HACS in the Home Assistant menu.
2. Click on **Integrations** → top right menu (three dots) → **Custom repositories**.
3. Paste the repository URL `https://github.com/dneprojects/habitron` and set category to **Integration**.
4. Click **Add**, then **Install** on the Habitron card.
5. **Restart Home Assistant** and clear your browser cache.
6. Go to **Settings → Devices & Services → Add Integration → Habitron** and provide the SmartHub address.

### Manual install

```bash
# Clone the repository
git clone https://github.com/dneprojects/habitron.git

# Copy the integration into your HA custom_components
cp -r habitron/custom_components/habitron <home-assistant-config>/custom_components/

# Restart Home Assistant, then add the integration from the UI.
```

After install the integration is also auto-discovered via SSDP when both Home Assistant and the SmartHub share the same network segment. Accept the discovery card to complete setup.

## Configuration parameters

Each field of the config flow (and the matching reconfigure flow) maps to a runtime setting of the integration.

| Parameter | Required | Description |
| --- | --- | --- |
| `Host name or IP of SmartHub` | yes | DNS name or IPv4 address of the SmartHub. Use the literal `local` when HA runs on the SmartCenter itself. |
| `Token for websocket authentication` | optional | Paste a **Long-Lived Access Token** from your HA profile here. Only required when SC Touch and Assist run on remote HA instances (not in a SmartCenter). |

The coordinator's heartbeat interval is fixed at 10 s, in line with Home Assistant's guideline that polling intervals are not user-configurable.

Parameters can be edited later via the **Configure** button on the integration card (Options flow) or by choosing **Reconfigure** to replace the underlying entry (Reconfigure flow). Both update without removing devices or entities.

## Data updates

The integration combines **push** and **polling**:

- **Push updates**: the SmartHub publishes input / output / sensor changes over a persistent WebSocket as they happen. Entities subscribe via `async_added_to_hass` and update instantly — typically in <100 ms.
- **Heartbeat polling**: every 10 s the coordinator calls `comm.async_system_update()`, which pulls the compact system status from the SmartHub. This serves as a liveness probe — entities flip to *unavailable* when the heartbeat fails (timeout, network error, refused connection).
- **Push-only paths** (e.g. SC Touch state) bypass the coordinator and use direct callbacks; the heartbeat still drives availability.

Long-running services (firmware updates, status backups) are routed through `hass.async_add_executor_job`, so the asyncio event loop is never blocked by the synchronous `habitron_client` library calls.

## Services

All services live on the `habitron` domain. When several SmartHubs are configured, singleton services (everything except `update_entity` and `sc_system_command`) target the **first-loaded entry** and log a warning; explicit hub targeting is in `update_entity` via `hub_uid`. Failure cases (`no_hub_loaded`, `no_target_devices`, `no_matching_module`, `websocket_provider_missing`, `hub_not_found`) raise `ServiceValidationError` with translated messages.

| Service | Purpose | Fields |
| --- | --- | --- |
| `habitron.hub_restart` | Soft-restart the SmartHub service. | — |
| `habitron.hub_reboot` | Reboot the SmartHub host. | — |
| `habitron.rtr_restart` | Restart the Habitron router. | — |
| `habitron.mod_restart` | Restart one or all Habitron modules. | `mod_nmbr` (optional, 1–64; omit for all) |
| `habitron.save_module_smc` | Persist a module's rule/name definitions to `.smc`. | `mod_nmbr` (1–64) |
| `habitron.save_module_smg` | Persist a module's settings to `.smg`. | `mod_nmbr` (1–64) |
| `habitron.save_router_smr` | Persist the router settings to `.smr`. | — |
| `habitron.save_module_status` | Persist live module status to `.mstat`. | `mod_nmbr` (1–64) |
| `habitron.save_router_status` | Persist router status (currents / voltages / timeouts) to `.rstat`. | — |
| `habitron.update_entity` | Inject a state-change event into a specific SmartHub. Used by automations to drive HA → Habitron round-trips. | `hub_uid`, `mod_nmbr`, `evnt_type`, `evnt_arg1`, `evnt_arg2`, optional `evnt_arg3`–`evnt_arg5`, optional `rtr_nmbr` (defaults to 1) |
| `habitron.sc_system_command` | Send a system command to an SC Touch client (restart, factory_reset, optional new HA IP). | `target_device` (one or more SC Touch device IDs), `command` (`restart` or `factory_reset`), optional `new_ip` |

Files written by the `save_*` services land in `custom_components/habitron/data/` inside the HA config directory. This directory is created on first use, and is ignored by the integration repo's `.gitignore`.

## Examples

### Save a module backup once a week

```yaml
automation:
  - alias: "Habitron: weekly module backup"
    trigger:
      - platform: time
        at: "03:30:00"
      - platform: state
        entity_id: input_boolean.habitron_backup_now
        to: "on"
    condition:
      - condition: time
        weekday: [sun]
    action:
      - repeat:
          count: 10
          sequence:
            - service: habitron.save_module_smc
              data:
                mod_nmbr: "{{ repeat.index }}"
            - service: habitron.save_module_smg
              data:
                mod_nmbr: "{{ repeat.index }}"
            - delay: "00:00:02"
      - service: habitron.save_router_smr
      - service: habitron.save_router_status
```

### Trigger a SC Touch reboot when its CPU temperature gets too high

```yaml
automation:
  - alias: "SC Touch: emergency reboot when overheating"
    trigger:
      - platform: numeric_state
        entity_id: sensor.smarthub_cpu_temperature
        above: 75
        for: "00:05:00"
    action:
      - service: habitron.sc_system_command
        data:
          target_device:
            - <device_id of the SC Touch>
          command: restart
```

### Route a HA Assist pipeline through the SC Touch microphone

The microphone is exposed as an `assist_satellite` entity. Add it as a satellite to your Assist pipeline in **Settings → Voice Assistants → Assist** and pick your preferred STT / conversation / TTS engines — playback returns to the SC Touch's built-in speaker.

### Use a Habitron flag as a HA presence helper

```yaml
script:
  set_holiday_mode:
    sequence:
      - service: switch.turn_on
        target:
          entity_id: switch.flag_holiday_mode
```

## Known limitations

- **One SmartHub per network** is supported per HACS install. Multiple SmartHubs work fine, but cross-Hub services (`update_entity` / `sc_system_command`) currently use device-registry / `hub_uid` lookups; explicit per-call target selectors will arrive with the multi-hub services follow-up.
- **Habitron module discovery is configuration-time**, not bus-side hot-plug. New modules need to be registered in the SmartHub's web UI; afterwards a reload of the integration picks them up. Stale modules are removed from HA's device registry automatically on the next setup pass.
- **The upstream `habitron_client` library is synchronous.** Every call is routed through `hass.async_add_executor_job` so the asyncio loop is never blocked, but heavy operations (firmware push, full SMC backup) take seconds and run on the executor thread pool.
- **WebRTC and Voice handlers register WebSocket commands globally**. After the last SmartHub is removed those handlers stay registered for the lifetime of the HA process. The provider itself is unregistered on unload, so no stream is double-served.
- **No re-authentication flow**. The optional WebSocket token can be edited via the Reconfigure flow, but the SmartHub does not push auth-fail states back into HA.

## Troubleshooting

| Symptom | Likely cause | What to try |
| --- | --- | --- |
| Setup is stuck at `Setting up Habitron` | DNS for the SmartHub host doesn't resolve, or port 7777 is unreachable. | Switch to the IP form of the host; check firewalls between HA and the SmartHub. |
| Every entity is *unavailable* a few minutes after a smooth setup | Coordinator timeout — the SmartHub is no longer responding. | Power-cycle the SmartHub. Reload the integration; if it recovers within the next 10-second heartbeat, no further action is needed. |
| Service call raises `ServiceValidationError: hub_not_found` | The `hub_uid` you passed does not match any loaded SmartHub's host string. | Use the host you configured in the entry, not the SmartHub serial. |
| `sc_system_command` raises `no_matching_module` | The selected device is not an SC Touch (`typ == 0x0104`) or it doesn't expose a `stream_name`. | Pick the SC Touch device, not its sub-modules. |
| Color picker on RGB CLEDs is empty | Frontend cached the entity's capabilities before the latest update. | Hard-refresh (Ctrl+F5). If still missing, delete the entity from the registry and reload. |
| `save_module_smc` writes nothing | The SmartHub did not return SMC payload, or the data directory could not be created. | Check the HA logs for `OSError` from `save_config_data`. The files land under `custom_components/habitron/data/`. |
| `System Health → Habitron` shows `no hubs` | The integration entry isn't loaded — usually after a setup failure. | Look at the entry's state in Settings → Devices & Services; reload or reconfigure as needed. |

For deeper debugging set the integration's log level to `debug` in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.habitron: debug
    homeassistant.helpers.update_coordinator: debug
```

A copy of the [`Diagnostics`](https://www.home-assistant.io/docs/configuration/troubleshooting/#download-diagnostics) export from the entry context menu is the fastest way to share state with the maintainer.

## Removal

1. Go to **Settings → Devices & Services → Habitron**.
2. Click the three-dot menu → **Delete**. This removes the entry, every device and entity it owns, and (after the last entry is gone) the domain-level services.
3. The WebRTC provider and any registered static paths are torn down on unload.
4. If installed manually, remove `custom_components/habitron` from your HA config directory; if installed through HACS, use the HACS menu to **Remove** the repository.
5. Restart Home Assistant.

State files written by the `save_*` services (`custom_components/habitron/data/`) are not removed automatically — delete them by hand if you no longer need them.
