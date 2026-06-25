# Developer changelog

Detailed, technical changelog for developers. End-user-facing release notes live
in [`CHANGELOG.md`](CHANGELOG.md) as concise one-liners; this file keeps the full
rationale and implementation detail for each release.

## v3.1.0

Pulls in `habitron_client==2.0.7` and ports the latest code-review improvements
(previously released as betas v3.1.0b1–b5).

### Changed
- **eKey finger-name sensor** now reports stable enum keys instead of hardcoded
  German text, with localized labels (en/de) supplied via translations
  (`SensorDeviceClass.ENUM`). ⚠ The entity **state values change** (e.g.
  `left_thumb` instead of "Daumen links"); the displayed label stays localized.
- Hub-acting services (`hub_restart`, `mod_restart`, `save_*`, …) accept an
  optional **device** target to pick a specific SmartHub. With a single
  configured hub the device may be omitted, so existing single-hub automations
  keep working unchanged.
- `.smc` module-definition formatting moved into the library
  (`get_module_definitions_smc`), with length validation against truncated
  responses.
- Diagnostics use public `SmartHub` properties (`smhub_type`/`smhub_name`)
  instead of private attributes.
- Routine setup logging downgraded from info to debug.
- Removed the unused `set_host` reconfiguration path (reconfiguration runs
  through the config flow's reload).
- Added public-surface tests (notify/text/diagnostics, system command + WebRTC
  platforms, hub setup via the config-entry path) and a shared setup fixture.
- Minor cleanups: coordinator uses the config entry directly; corrected internal
  comments and copy-paste property docstrings.

### Fixed
- **APK upload to the SC Touch** failed with an invalid-scheme error: the
  firmware download URL was built from `hass.config.internal_url`, which is
  `None` unless explicitly configured, producing a scheme-less address the
  Touch app rejects. URLs are now built via `get_url`, which always returns an
  absolute URL (internal, auto-detected, or external). The same fix applies to
  media-player artwork and TTS/media URLs.
- **Entity area assignment** now resolves each Habitron area to its real HA
  area-registry id (creating the area when needed) instead of a slugified name.
  A slugified name does not reliably match an area id (renames, umlauts,
  duplicate names), so entities could end up with a dangling area. Applies to
  **all** entity platforms.
- Duplicate `unique_id` for described router sensors (timeout/current/voltage all
  shared `…_snsr0`); each now appends its description key.
- `PARALLEL_UPDATES = 0` for the read-only, push-driven sensor platform.
- Diagnostic "lan" icon now reflects the current value (it lagged one update).
- Module-number service fields reject out-of-range values (only 1..64).
- **HACS/hassfest manifest validation**: removed the core-only `homeassistant`
  key and ordered the keys correctly (`domain`, `name`, then alphabetical), so
  hassfest accepts the manifest. The minimum Home Assistant version is declared
  in `hacs.json` (`2026.4.0`).

## v3.0.2

### Fixed
- Resolves the recurring "Unexpected error fetching Habitron updates data" /
  malformed SmartHub diagnostics at the root. The bus client now uses a fresh
  socket per command (as the original synchronous client did) instead of one
  persistent connection. The persistent connection could be left shifted by one
  frame after an interrupted exchange, so every later poll read the previous
  command's response — recurring roughly every 20 s until the integration was
  reloaded. Per-command sockets make that desync impossible; responses are also
  validated by marker byte and length. Requires `habitron_client==2.0.6`.

## v3.0.1

### Fixed
- A malformed/garbled SmartHub diagnostics response (one containing control
  characters) no longer crashes the update coordinator with repeated
  "Unexpected error fetching Habitron updates data". The host-diagnostics fetch
  shares the bus status tick; a bad response is now treated as a transient
  protocol error and that tick's diagnostics are skipped, while the bus status
  keeps updating. Requires `habitron_client==2.0.5`.

## v3.0.0

Major release: the device model and bus-protocol parsing now live in the
`habitron_client` PyPI library; the integration is a thin wrapper. Requires
`habitron_client==2.0.4` (installed automatically).

### Changed
- **Thin-wrapper architecture.** Module/router parsing, the protocol indices and
  the bus transport moved into `habitron_client` (v2). Entities bind to library
  members via per-member listeners and forward commands through the library. No
  user-visible behaviour change is intended over v2.10.x.

### Fixed
- **Smart Controller Mini colour LEDs** update their on/off + colour state again
  via the mirror/poll, independent of output events.
- **Recovery after a SmartHub reboot.** A flaky/rebooting hub during setup now
  retries instead of failing permanently, and the router mirror is restarted on
  the reboot edge so events resume without a reload.
- **Router firmware version** no longer shows garbled text: a short (payload-less)
  bus acknowledgement is handled as such instead of being parsed as data.
- **Duplicate discovery.** A hub already configured under the `local` host is no
  longer offered again when rediscovered via SSDP at its LAN address.
- **Transient host-diagnostics errors** no longer mark every entity unavailable
  (host diagnostics are decoupled from the bus status tick).

## v3.0.0b2

### Fixed
- Smart Controller Mini colour LEDs now update their state (on/off and colour) via the mirror/poll again, independently of the output events. Requires `habitron_client==2.0.1`.

## v3.0.0b1

### Internal
- The device model and bus-protocol parsing now live in the `habitron_client` library (v2.0.0); the integration is a thin wrapper that binds entities to library members and forwards commands. No user-visible behaviour change is intended — this is a structural refactor ahead of the Home Assistant core submission.

### Note
- Beta release. Requires `habitron_client==2.0.0`. Please report any entity or state that differs from v2.10.3.

## v2.10.3

### Fixed
- Button and finger events no longer log an "invalid event type" warning on release.

## v2.10.2

### Fixed
- Transient bus timeouts are handled cleanly instead of logging an error traceback.

## v2.10.1

### Fixed
- Air-quality sensor no longer logs an invalid AQI device-class warning.
- Smart Touch corner LED labels are parsed correctly.
- No spurious error when the hub posts an event during startup.

### Internal
- Firmware versions polled by a dedicated round-robin coordinator, off the entity poll path.
- Less log noise (firmware/assist/network-info downgraded; auth token no longer logged).
- Entities update only when the bus status actually changes.

## v2.10.0

### New feature
- Each display module (incl. Smart Touch) gets a `text` entity — set its value to show free text on the module display, empty clears it.

### Breaking
- The per-module display notify entity (`notify.<module>_messages`) is replaced by that `text` entity; GSM/SMS notify is unchanged.

## v2.9.0

Restores free-text notify messages to modules; requires habitron_client 1.0.4.

### New feature
- `notify.<module>` sends arbitrary free text to a module's display.

## v2.8.0

Bug-fix and Home-Assistant-Core readiness release; upgrades to habitron_client 1.0.3.

### Fixed
- ekey *Identifier Value* sensor was dropped at startup (shared a unique ID with the user-name sensor).
- SSDP re-offered an already-manually-added SmartHub; now matches on host/IP and adopts the stable ID.

### Changed
- Config flow shows field descriptions and translated abort messages.

### Internal
- Core-submission prep: ruff/mypy aligned with core, all findings fixed, README updated, dead pipeline-option path removed (no functional change).

## v2.7.0

Migrates to habitron_client 1.0.0 (fully async, strict-typed); HbtnComm transport rewritten. No visible change for typical users — ids, states and history are preserved.

### Changed
- Persistent TCP connection per entry; transient reconnects handled inside the library.
- Quality Scale: full Platinum (52 rules); new Tests CI gate (ruff/mypy/pytest) before auto-release.
- Notify entities no longer forward free-text messages — only numeric stored-message ids; non-matching payloads log a warning and skip.

### Fixed
- Media-player Music-Assistant proxy lookup no longer logs a WARNING every 3 s when no MA player is routing (moved to DEBUG).

## v2.6.3

### Fix
- select mode

## v2.6.1 + v2.6.2

### Fix
- Improved support for colors

## v2.6.0

### Fix
- Sensor name from module

## v2.5.10

### Fix
- Find correct apk version

## v2.5.9

### Fix
- Firmware in share
- Missing LEDs

## v2.5.8

### Fix
- Update of sw sc_touch version

## v2.5.7

### Fix
- Improved robustness of webrtc connection

## v2.5.6

### New feature
- Remote reset for Smart Touch

### Fix
- Handling of undefined area indices

## v2.5.5

### New feature
- Battery current for Smart Touch
- Abort recognition

## v2.5.4

### New feature
- Color leds for Smart Touch

### Fix
- Event triggers tested with HA 2024.4

## v2.5.3

# New feature
- Event triggers compatible to HA 2024.4 ff.

## v2.5.2

# New feature
- Improved event triggers for buttons and ekey fingers

## v2.5.1

### New feature
- External climate controller appears as 2nd controller if enabled

## v2.5.0

### New feature
- Additional battery sensors for Smart Touch

## v2.4.9

### Fix
- hvac_modes remain if hvac set to off

## v2.4.8

### Fix
- Set areas for substituted switch entities

## v2.4.7

### Fix
- Correct assignment of areas with German letters ä,ö,ü,ß

## v2.4.6

### Fix
- Analog output only available  for Smart Controllers

## v2.4.5

### New feature
- Climate control mode / controller no can be modified

### Fix
- LED numbering and event

## v2.4.4

### New feature
- Support of analog output for Smart Controllers

## v2.4.3

### Fix
- Forward link to configurator

### Fix
- Changed init sequence for better stability

## v2.4.2

### Fix
- Installation of iconset
- Outdoor temperatures: data format of negative temperatures
