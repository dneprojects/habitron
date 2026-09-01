# Latest changes

User-facing release notes. For the detailed technical changelog see
[`developer_doc.md`](developer_doc.md).

## v3.2.3
- The hub's own diagnostic values (CPU, memory, disk, log levels) are read more robustly: a value the hub reports in an unexpected form no longer interrupts the update cycle, so the other entities keep their values instead of all going unavailable for a moment.

## v3.2.2
- Fixed: a manually assigned area on a Habitron *device* is no longer overwritten on every reload/restart. The area from the router is now only suggested when a device is first created, so your own assignment sticks -- the same behaviour the entities already had since v3.1.9. If the router's area list is incomplete or missing, your devices are left alone instead of all being moved into a new "House" area.

## v3.2.1
- Internal preparation for the Home Assistant core version of this integration: both now derive the hub's internal id in exactly the same way, so a future switch keeps your devices, entities and their history. Nothing changes in this release — no entity is renamed, removed or re-created.

## v3.2.0
- The hub address is now stored under Home Assistant's standard `host` key instead of an integration-specific one, matching what the Home Assistant core version of this integration expects. Existing configurations are converted automatically — nothing to re-enter.
- Removed a leftover `update_interval` value from the stored configuration; the polling interval has been a fixed value for a long time and this entry was no longer read.

## v3.1.11
- Fixed: covers whose automatic switch-off is turned off at the router no longer get switched off anyway, 255 seconds after reaching the end position.

## v3.1.10
- Fixed: the colour LEDs of the Smart Controller Touch and Mini (ambient and the four corners) no longer come back almost black after being switched off. Turning one on without picking a colour now restores the colour and brightness it had before.

## v3.1.9
- Fixed: a manually set area on an analog input, dimmer, cover, output switch or button event is no longer reset on every reload/restart. The bus-provided area is now applied only when the entity is first created, so your own area choice sticks.

## v3.1.8
- Fixed: hub discovery no longer briefly freezes Home Assistant while it looks up the local IP address.
- Hubs without host diagnostics (anything other than a Raspberry-Pi-based SmartHub) no longer make a useless status request every 10 seconds.

## v3.1.7
- Fixed: Smart Controller, Mini and IO2 modules now expose their status sensor again (their status diagnostic had no internal name, so it was skipped). Other modules' status sensors now show the actual module status instead of an unrelated value.

## v3.1.6
- Fixed: the router current, voltage and timeout sensors now actually refresh when their value changes on an otherwise quiet bus. v3.1.5 read the fresh values but the entities did not yet show them.

## v3.1.5
- Fixed: the router's own sensors (currents, voltages, channel timeouts, system-OK) and the health repair could stay frozen while the bus was otherwise quiet — they now update on every poll.
- Fixed: the eKey finger-number sensor now updates immediately on a finger event instead of lagging until the next poll.

## v3.1.4
- Fixed: a hub added by host name (rather than by IP) failed to connect on setup — name resolution was broken. IP-based hubs were unaffected.
- Fixed: the SmartHub CPU, memory and disk sensors no longer briefly show 0 before the first reading; they stay "unknown" until real values arrive.
- Fixed: a hub that answers but reports no name no longer creates an entry with a blank title — it falls back to the host address.
- Fixed: short LAN host names such as `pi` or `hub` can now be entered; whether a host works is left to the connection test.
- Fixed: a hub already added by name is no longer offered as a duplicate when it is later discovered by IP.
- A briefly offline hub can now be retried from the discovery confirmation instead of aborting the whole flow.

## v3.1.3
- Module-fault repairs can now be ignored in every case; unreachable room controllers no longer offer a channel power cycle.

## v3.1.2
- Maintenance release — no functional or behavioral changes; repository history cleanup only.

## v3.1.1
- New: per-module health sensor and a repair with one-click recovery (module restart, or channel power cycle when the module is unreachable) for SmartHub operate-mode faults.
- Fixed: room-controller sensors (air quality, illuminance, humidity) keep their original entity IDs again — a 3.1.0 change had renamed them (e.g. prefixed the area).
- Fixed: setting a colour LED to a colour without a brightness now lights it at the matching level — an off LED stayed dark and dimmed colours could come out too dark.

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
