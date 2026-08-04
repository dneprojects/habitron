# Developer changelog

Detailed, technical changelog for developers. End-user-facing release notes live
in [`CHANGELOG.md`](CHANGELOG.md) as concise one-liners; this file keeps the full
rationale and implementation detail for each release.

## v3.2.0

Promotion of v3.2.0b1, code unchanged.

### Verified on hardware
- A Raspberry Pi installation migrated a real v1 entry: `version: 2`,
  `habitron_host` -> `host`, `websock_token` preserved, integration loaded with
  all entities and a working hub connection.


Config-entry key alignment ahead of the core migration, plus the entry migration
that makes it non-breaking.

### Changes
- **`habitron_host` -> `CONF_HOST`.** Core review asked for the shared
  `homeassistant.const.CONF_HOST` (value `"host"`) instead of the
  integration-specific key; the core PR carries the same change. Since both
  share the `habitron` domain, a user moving from HACS to core keeps the very
  same config entries -- so the two sides have to agree on the key.
- **`async_migrate_entry` + `VERSION = 2`.** A v1 entry is renamed in place. The
  websocket token stays: unlike the core PR (which drops it, having no consumer
  for it yet), this integration really uses it for SmartController Touch and
  Assist.
- **`update_interval` dropped from the entry data.** The key predates the move
  to a fixed `SCAN_INTERVAL`; neither this integration nor core has read it
  since, so the v1 -> v2 step removes it rather than carrying it forward. Found
  on a real installation while checking the migration result.
- **`KEY_TOKEN` moved to `const.py`.** `smart_hub.py` read
  `config.data["websock_token"]` as a raw string, bypassing the constant that
  `config_flow.py` defined; `diagnostics.py` repeated the literal in its redact
  list. All three now share one definition.

### Ordering (important)
- This has to reach users **before** the core integration ships. Once an entry
  is on version 2, an older HACS build (`VERSION = 1`) refuses it as "created by
  a newer version" -- so a user stepping back from core to HACS 3.1.x would find
  a broken entry. Beta first for exactly that reason.

### Tests
- `test_migrate_v1_entry_renames_the_host_key` sets up a real v1 entry and
  asserts the rename, the retained token and a loaded entry. Verified to fail
  with the rename removed.

## v3.1.11

Decodes the cover autostop counter's "off" marker; needs `habitron_client` 2.0.13.

### Fixed
- **A disabled autostop switched the cover output off after 255 seconds
  (`cover.py`).** The router transmits the delay for switching a cover output
  off after the end position as a single byte (`FF 0B` description record) and
  uses `255` for "no automatic switch-off". The library passed the byte through
  raw, and both `HbtnShutter._handle_coordinator_update` and the `HbtnBlind`
  override guarded on `self.stop_delay >= 0` -- a condition an unsigned byte can
  never fail. So instead of skipping the switch-off, the entity scheduled it
  with a 255 second delay, and `_schedule_stop` held that task against further
  ticks. The `>= 0` looks like it was written for exactly this intent, but no
  negative value ever reaches it.
- **Fix in the library, not here.** `habitron_client` 2.0.13 decodes the marker
  (`_parse_router.py`), so `Router.cover_autostop_del` is `int | None` with
  `None` for "disabled" -- protocol knowledge stays out of the integration, the
  line the core review asked for. Both entities now guard on
  `stop_delay is not None`, and the two endpoint branches collapsed into one
  condition. `0` remains a valid delay ("stop immediately") and is covered by a
  test, since a truthiness check would have quietly broken it.

### Not done here
- The core PR keeps its `habitron_client==2.0.12` pin; the bump goes in with the
  next round.

## v3.1.10

Fixes the colour-LED brightness latch in `HbtnColorLight`.

### Fixed
- **Colour LED relit black (`light.py`).** `_handle_coordinator_update` reset
  `_brightness` to `0` whenever the module reported all three channels as zero,
  i.e. every time the LED was off. A following attribute-less `light.turn_on`
  then computed `bright_factor = 0` and -- because of the per-channel
  `max(..., 1)` floor -- wrote `[1, 1, 1]` to the bus: nominally on, visually
  black. The next poll read that back as `max_channel == 1`, so `_brightness`
  became `1` and `_rgb_color` was rescaled to `(255, 255, 255)`, destroying the
  previous colour and latching the LED at "on and black" for every further
  toggle. Both the last colour and the last brightness are now retained while
  the LED is off, so a plain `turn_on` relights what was there before.
  No guard is needed in `async_turn_on`: `_brightness` starts at `255` and is
  only ever assigned `max_channel > 0` or a service value, and the light service
  routes `turn_on` with `brightness == 0` to `turn_off`
  (`homeassistant/components/light/__init__.py`). The retained value is also
  never visible while the LED is off -- `LightEntity.state_attributes` reports
  `brightness` as `None` whenever `is_on` is `False`.

### Tooling
- **ruff pinned to 0.15.14.** `requirements_test.txt` asked for `ruff>=0.13`, so
  CI drifted onto a release that enables `PLR0917` ("Too many positional
  arguments") -- a rule HA core does not run -- and 17 pre-existing findings
  turned the `Tests` workflow red. ruff is now pinned to the exact version core
  pins in `requirements_test_pre_commit.txt`, and `required-version` in
  `pyproject.toml` moves from `>=0.15.15` back to core's `>=0.15.14`.

## v3.1.9

Reworks area assignment so a deviating bus area is applied **once, at first
creation**, instead of on every setup.

### Fixed
- **Area overwritten on every reload.** `async_assign_entity_area` was called
  after `async_add_entities` and unconditionally (re-)applied the computed area
  each setup, clobbering a later user area move -- and resetting non-deviating
  entities to `None`. Because HA registers entities asynchronously
  (`config_entry.async_create_task`), that post-add pass also ran before new
  entities were registered, so the area only landed on a *later* run.

### Changed
- New `HbtnAreaMixin` + `deviating_area_id` in `_helpers.py`. Each platform
  (sensor, cover, light, number, event, switch) snapshots the already-registered
  unique ids *before* `async_add_entities`, sets `_initial_area_id` only on a
  newly-created entity, and the mixin applies it from `async_added_to_hass`
  (after registration). `switch` outputs keep the hidden-duplicate propagation
  via `_initial_area_propagate`. The old `async_assign_entity_area` helper is
  removed. Analog inputs are now derived from the model's `analogins` rather
  than hard-coded module type codes.

## v3.1.8

Bumps `habitron_client` to 2.0.12 and trims a needless host-diagnostics poll.

### Fixed
- **Blocking discovery (`habitron_client` 2.0.12).** `discover_smarthubs` called
  the socket-opening `get_own_ip` inline on the event loop; it now runs in an
  executor.
- **Host-diagnostics poll (`smart_hub.py`).** `update()` now returns before
  querying `get_smhub_update()` when the hub exposes no diagnostic members
  (every non-Raspberry-Pi platform), instead of fetching and discarding the
  response on every 10-second tick.

## v3.1.7

Bumps `habitron_client` to 2.0.11. No integration code changed.

### Fixed
- **Module status diagnostics (`habitron_client` 2.0.11).** The library now
  names `diags[0]` — where every `_status_*` writes `MODULE_STAT` — `Status`
  for every module kind. Smart Controller / Mini / IO2 previously overrode the
  diagnostics list without a `Status` name, so `sensor.py`'s name-based filter
  never created their status entity; other modules bound the status sensor to a
  slot that received no status value (dimmers showed the power temperature).
  Member numbers are unchanged, so existing status/power-temp entity_ids stay
  stable; Smart Controller / Mini / IO2 gain a status sensor.

## v3.1.6

Completes the router-status fix shipped in 3.1.5 on the integration side.

### Fixed
- **Router telemetry push subscription (`sensor.py`).** 2.0.10 refreshes the
  router status (currents, voltages, channel timeouts) on every poll, but the
  `CURRENT`/`VOLTAGE`/`TIMEOUT` sensors were coordinator-only and the
  coordinator runs `always_update=False`, keyed on the compact-module CRC. A
  router-only change therefore never reached the entities. `HbtnDescribedSensor`
  now supports a `subscribe_fn` (as the per-module and eKey sensors already
  did); the three router descriptions subscribe to their bus member, whose
  `notify()` the library fires on change. Without this, 3.1.5's fix was
  ineffective for exactly these sensors.

## v3.1.5

Bumps `habitron_client` from 2.0.8 to 2.0.10 (skips 2.0.9). No integration code
changed; both fixes live in the library.

### Fixed
- **Router status refresh (`habitron_client` 2.0.10).** `async_refresh_system`
  now reads the router status on every poll instead of only when the module
  compact-status CRC changes. Router currents, voltages, channel timeouts and
  `sys_ok`/health change independently of the modules, so gating their read on
  the module CRC left those sensors (and the health repair) stale on an
  otherwise idle bus. The compact-status CRC still gates the per-module status
  distribution; the mirror-down (hub reboot) edge is now also caught on a quiet
  bus.
- **eKey finger-number sensor (`habitron_client` 2.0.9).** The FINGER push event
  now updates the finger-number member (`sensors[1]`), normalized like the
  polled parser, so it no longer lags until the next poll. HACS was still on
  2.0.8 and had not shipped this.

### Fixed
- **Hostname resolution (`communicate.py`).** `get_host_ip` is `async` in
  `habitron_client` ≥ 2.0.9; `async_setup` handed it to
  `async_add_executor_job`, which only *builds* the coroutine and assigned that
  (unrun) to `self._host`. Every hostname-based setup then passed a coroutine to
  `async_get_source_ip`/`HabitronClient`. Now awaited directly. IP-based configs
  set `_host` in `__init__` and the `local` sentinel uses the still-sync
  `get_own_ip`, so only hostname setups were affected. The test doubles were
  sync `return_value` mocks that hid this; they are now `AsyncMock`.
- **Blank entry title (`config_flow.py`).** `test_connection` returns
  `(True, "")` when the TCP probe succeeds but the metadata query is unanswered.
  `validate_input` now falls back to the probed address (`host_name or
  host_to_test`) so an entry is never created with an empty title.
- **Minimum host length (`config_flow.py`).** Dropped the `len(host) < 4`
  rejection (and the now-unreachable `InvalidHost` machinery). Valid short LAN
  names like `pi`/`hub` are for the connection probe to accept or reject.
- **SSDP duplicate detection (`config_flow.py`).** The SSDP step compared the
  configured host raw while only canonicalising the discovered side, so a hub
  added manually as `smarthub.local` was not matched against a discovery
  reporting its IP. `_is_device_already_configured` is now async and
  canonicalises both sides through `_async_canonical_host` (name resolution +
  `local` sentinel), and the SSDP step reuses it. A test fixture that resolved
  *every* host to one IP was replaced with a realistic resolver.

### Changed
- **Host diagnostics gating (`smart_hub.py`, `sensor.py`).** `Diagnostic`/
  `Sensor` default to 0, a plausible reading for CPU load or disk usage. A
  `host_diags_valid` flag now gates the SmartHub host sensors to `None`
  (`unknown`) until the first successful `update()`, and that first success
  notifies every member so entities whose value equals their placeholder still
  publish.
- **Discovery confirm (`config_flow.py`).** A briefly-offline hub
  (`CannotConnect`/`HostNotFound`) is surfaced on the confirm form as
  `cannot_connect` instead of aborting; unexpected errors are logged before the
  `unknown` abort. `validate_input` narrows its swallow to
  `(OSError, TimeoutError, HabitronError)` so a genuine bug still surfaces.

## v3.1.3

Refines the `module_fault` repair flow (`repairs.py`).

### Changed
- **Ignore in every step.** The restart and power-cycle confirm steps are now
  `async_show_menu` menus offering the action *or* "Ignore" (previously a single
  Submit button ran the action with no way to dismiss). Ignoring calls
  `issue_registry.async_ignore_issue(..., True)`, so the issue is hidden with
  standard HA semantics until the user re-enables it — not resolved-and-recreated
  on the next health poll.
- **Room controllers.** An `F1` communication timeout on a `SmartController` no
  longer offers a channel power cycle: a room controller has its own 230 V
  supply, so cutting the router channel would not reset it (and would needlessly
  reset the channel's other modules). A new `room_controller_unreachable` step
  shows only the fault text — no channel, no co-located module list — and offers
  Ignore.

Adds the `menu_options`, `room_controller_unreachable` and `abort.ignored`
strings in `strings.json` and `translations/de.json`, plus repair-flow tests for
the room-controller and ignore paths.

## v3.1.2

Housekeeping release, no code changes to the integration itself. Two Home
Assistant long-lived access tokens that had been left in commented-out example
lines of `__init__.py` and `communicate.py` were scrubbed from the entire git
history (`git filter-repo --replace-text`, all branches and tags force-pushed).
The tokens had already been revoked in Home Assistant, so they carried no live
access; this release exists so HACS/core review sees a clean history and a fresh
tag. No manifest, entity, or behavioral changes.

## v3.1.1

Pulls in `habitron_client==2.0.8` and surfaces the SmartHub's new per-module
operate-mode fault detection.

### Added
- **Per-module health.** The SmartHub now fires a `SYS_ERR` (event type 16) HA
  event **per module** (`mod_id > 0`) whose `arg1` is a one-byte fault bitmask
  (`arg2` reserved). The library applies it to a new notifiable
  `Module.health` member (`habitron_client` ≥ 2.0.8) and exposes
  `decode_module_faults()` / `ModuleFault`, mapping the bitmask to display codes
  and labels. The bit layout is the fixed contract shared with the SmartHub
  firmware (`0x08` reserved):

  | bit | code | label |
  | --- | --- | --- |
  | `0x01` | F1 | Timeout Modulkommunikation |
  | `0x02` | F2 | Fehler Modulkommunikation |
  | `0x04` | F4 | Abspeicherfehler |
  | `0x10` | F16 | Fehler Leistungsteil |
  | `0x20` | F32 | Fehler Ekey/GSM-Kommunikation |
  | `0x40` | F3 | Weiterleitungstabelle nicht geheilt |
  | `0x80` | F5 | Spiegelung gestört |

- **`ModuleHealthSensor`** (`binary_sensor`, `problem` device class, diagnostic
  category) bound to `module.health`; the active `fault_codes` and `faults`
  (code + label) are exposed as attributes. `arg1 == 0` means the module is
  healthy again.
- **Repairs issue per module** (`health.py`): `async_setup_module_health_issues`
  subscribes each `module.health` member and mirrors it into a `module_fault`
  repair issue (stable id `module_fault_<module-uid>`, severity ERROR, the fault
  list passed as a translation placeholder, `is_persistent=False` so the user can
  also Ignore it). `arg1 == 0` deletes the issue. The subscription is independent
  of the diagnostic entity so faults are tracked even when that entity is
  disabled. The issue carries `{entry_id, module_uid}` in its `data` for the fix
  flow.
- **Fixable repair flow** (`repairs.py`, `ModuleFaultRepairFlow`): the issue is
  `is_fixable=True` and offers a recovery action picked from the module's *live*
  fault mask at click time:
  - **F1 (comm timeout, `0x01`) set** → the module is unreachable on the bus, so
    a restart command would not arrive. Step `confirm_power_cycle` offers a
    **channel power cycle** (`comm.async_power_cycle_channel`) and warns that the
    whole channel (pair) drops, listing the co-located modules from
    `router.chan_list`. F1 takes precedence even when combined with other bits.
  - **otherwise** → step `confirm_restart` offers a plain
    **module restart** (`comm.module_restart(module.addr)`).
  - The flow re-reads the model on every step: a cleared mask completes the flow
    (HA drops the issue), an unloaded hub / removed module aborts
    (`module_unavailable`), an unmapped channel aborts (`channel_unknown`).

The existing global router `SYS_ERR` path (`mod_id == 0`, router system-error
state / `router_system_error` issue) keeps its own contract and is untouched.

### Fixed
- **Per-module sensor entity_ids restored (3.1.0 rename regression).** Beta
  3.1.0b1 appended the description `key` to *every* `HbtnDescribedSensor`
  unique_id, including the per-module humidity/illuminance/wind/airquality
  sensors whose `nmbr` is already unique
  (`Mod_{uid}_snsr{n}` → `Mod_{uid}_snsr{n}_{key}`). The changed unique_id made
  Home Assistant register fresh entities, and 2026.6's entity-id area prefix
  rewrote their entity_ids to `sensor.<area>_<device>_<name>`; temperature and
  climate (stable ids) were untouched — hence only some sensors moved. The key
  suffix is now opt-in via a new `HbtnSensorEntityDescription.disambiguate`
  flag, set only on the colliding router streams (current/voltage/timeout). A
  one-time, idempotent migration in `async_setup_entry`
  (`_async_restore_legacy_sensor_ids`) realigns the per-module sensors: it drops
  the suffixed duplicate when the original bare-id entry still exists (upgrade
  case — the original entity_id takes over), otherwise rewrites the unique_id in
  place (fresh 3.1.0b1 install). A regression test pins both unique_id formats so
  any future format change fails CI.
- **Colour LED brightness on a colour-only `turn_on`.** When `async_turn_on`
  gets `rgb_color` without `brightness`, `HbtnColorLight` now derives the
  brightness from the highest RGB channel and rescales the colour to 100 %,
  mirroring `_handle_coordinator_update`. Previously the colour was applied
  against the stale `_brightness`, so an off LED (`_brightness == 0`) produced
  `(1,1,1)` and stayed invisible. The added normalisation also keeps the
  write/read round-trip consistent — a sub-255 colour is no longer dimmed twice
  (`dimmed = normalized_rgb * max_channel / 255 == input rgb`), so the state no
  longer jumps on the next coordinator update.

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
