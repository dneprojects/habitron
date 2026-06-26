# Latest changes

User-facing release notes. For the detailed technical changelog see
[`developer_doc.md`](developer_doc.md).

## v3.1.1
- New: per-module health sensor and a repair with one-click recovery (module restart, or channel power cycle when the module is unreachable) for SmartHub operate-mode faults.

## v3.1.0
- New: hub actions (restart, save, …) can target a specific SmartHub in multi-hub setups.
- ⚠ eKey finger-name sensor: state values changed (the displayed label stays localized).
- Fixed APK upload to the SC Touch.
- Fixed entity area assignment.
- Improved robustness and HACS compatibility.

## v3.0.2
- Fixed recurring update errors and garbled hub diagnostics.

## v3.0.1
- Fixed update errors caused by a garbled hub diagnostics response.

## v3.0.0
- Internal: device model and bus protocol moved into the `habitron_client` library; no visible change intended.
- Fixed Smart Controller Mini colour LEDs, recovery after a hub reboot, garbled router firmware version, duplicate discovery, and entities briefly going unavailable.

## v3.0.0b2
- Fixed Smart Controller Mini colour LED state.

## v3.0.0b1
- Internal: structural refactor (parsing moved into the library); no visible change. Beta.

## v2.10.3
- Fixed a spurious "invalid event type" warning on button/finger release.

## v2.10.2
- Transient bus timeouts no longer log an error traceback.

## v2.10.1
- Fixed air-quality warning, Smart Touch corner LED labels, and a spurious startup error.

## v2.10.0
- New: each display module gets a `text` entity to show free text on its display.
- ⚠ Breaking: the per-module notify entity is replaced by that `text` entity (GSM/SMS notify unchanged).

## v2.9.0
- New: `notify.<module>` sends free text to a module's display.

## v2.8.0
- Fixed ekey Identifier Value sensor and SSDP re-offering an already-added hub.
- Config flow shows field descriptions and translated abort messages.

## v2.7.0
- Migrated to the fully async `habitron_client` library; no visible change for typical users.
- Notify entities now accept only numeric stored-message ids (free text dropped).
- Fixed media-player log spam when no Music Assistant player is routing.

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
