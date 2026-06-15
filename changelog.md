# Latest changes

## v2.10.1

### Fixed
- Air-quality sensor no longer triggers an invalid AQI device-class warning.
- Smart Touch corner LED labels are parsed correctly.

### Internal
- Logging messages improved.
- Firmware polling spread across heartbeats; coordinator fans out only on bus changes.

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
