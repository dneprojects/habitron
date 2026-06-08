# Latest changes

## v2.7.0

This release migrates the integration to **habitron_client 1.0.0**.
The library is now fully async and strict-typed; the integration's
transport layer (`HbtnComm`) has been rewritten on top of it.

### What changed under the hood

- **Async wire transport.** Every bus call is now a direct
  `await client.<method>(...)`. The previous executor-job offload
  pattern (`HbtnComm._async_exec` + per-hub `asyncio.Lock`) is gone;
  the new library serialises requests internally.
- **Eager connect, persistent connection.** `HabitronClient` opens
  one TCP connection per integration entry at setup time and reuses
  it for every poll cycle. Reconnect on transient drops is handled
  inside the lib.
- **Strict-typed dependency.** `habitron_client` 1.0.0 ships
  `py.typed` (PEP 561 compliant). `mypy --strict` over the
  integration source produces zero errors across all 34 files.
- **Quality Scale: full Platinum.** With the lib now async,
  `async-dependency` moves from `exempt` to `done`. All 52 rules
  satisfied (48 done, 4 exempt).
- **CI gate before release.** A new `Tests` workflow runs ruff,
  ruff format, mypy --strict and pytest --cov on every push and PR
  across Python 3.13 + 3.14. The auto-release workflow now depends
  on those tests passing before publishing.

### What changed for you

For the typical user: **nothing visible**. Entity ids, states,
statistics, device configuration and history are preserved. The
integration was verified end-to-end against real hardware before
this release (12 modules, 2 touch panels, WebRTC provider, full
polling cycle).

One narrow behaviour change worth flagging:

- **Notify entities no longer forward free-text messages.** The new
  library only accepts numeric stored-message ids on the bus.
  `notify.<your_module>` calls whose payload doesn't match a known
  stored message log a warning and skip instead of sending raw text.
  If you rely on stored messages this is invisible; if you somehow
  sent raw strings, those now silently no-op.

Small log-noise polish bundled in:

- The media-player Music-Assistant proxy lookup logged a WARNING
  every 3 seconds during playback when no MA player was routing
  through the Habitron output. The absence is an expected case, so
  the message moves to DEBUG.

### Upgrading

1. **HACS → Habitron → Update** (or whatever path you use).
2. **Restart Home Assistant.** First restart after the update is
   a few seconds slower than usual while HA installs
   `habitron_client==1.0.0` into its venv (~5–10 s). The pinned
   version is enforced through `manifest.json`; you don't need
   to install anything manually.
3. **Verify in the log** that you see
   `Setting up habitron` → `Initializing hub` → modules discovered
   → `Re-initialized hub with mode 1` without errors.

### Rollback

If something breaks for you and we haven't shipped a fix yet:

- HACS → Habitron → **Redownload** → choose **2.6.3** → restart HA.
- HA will downgrade `habitron_client` to 0.1.4 automatically on the
  next restart because the older manifest pins that version.

Please open an issue on GitHub describing the symptom so the rollback
can be quick and the next release can include the fix.

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
