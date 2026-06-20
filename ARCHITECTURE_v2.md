# Habitron architecture v2 — move the device model into `habitron_client`

Concept/design document. Goal: make the Home Assistant integration a **thin
wrapper** by moving all protocol parsing and the device state machine out of the
integration and into the `habitron_client` PyPI library — for the **whole**
integration (every platform, not just sensor). Implement in the **HACS version
first** (`habitron_repo`), then mirror into the core PR.

Status: PROPOSAL — review before implementing.

## 1. Why

- HA core rule: *integrations are thin wrappers; protocol parsing and device
  state machines belong in a separate PyPI library, not in the integration.*
  The core reviewer asked for exactly this ("use a Python library for
  communication … should drastically reduce the size of this PR").
- Today only the **transport** (TCP framing, CRC, raw commands) lives in
  `habitron_client`. The **device model** still lives in the integration.
- Moving it shrinks every current and future platform PR, removes duplicated
  logic, and the HACS version benefits identically.

## 2. Current state (what is where)

`habitron_client` (today, ~transport only):
- `connect/close`, discovery, `SmhubInfo`/`SmhubUpdate` TypedDicts.
- Commands return **raw bytes / `(bytes, crc)`**: `get_compact_status`,
  `get_module_status`, `get_router_status`, `get_smr`, `get_module_definitions`,
  `get_router_modules`, `get_global_descriptions`, …
- Setters: `set_output/set_dimmval/set_rgbval/set_shutterpos/set_blindtilt/
  set_flag/set_setpoint/set_climate_mode/set_group_mode/…`.

Integration (today, holds the whole model + parsing):
- `interfaces.py` — descriptor dataclasses (`IfDescriptor`, `CovDescriptor`,
  `CLedDescriptor`, `LgcDescriptor`, `CmdDescriptor`, `StateDescriptor`,
  `AreaDescriptor`, `ModuleDescriptor`) **+ an HA-facing callback registry**
  (`register_callback`/`handle_upd_event`).
- `const.py` — protocol indices/enums (`MStatIdx`, `MSetIdx`, `RoutIdx`,
  `MODULE_CODES`, `HaEvents`, …).
- `module.py` (~1080 lines) — `HbtnModule`/`SmartController`: builds the typed
  I/O groups (`inputs/outputs/dimmers/covers/leds/cleds/sensors/logic/flags/
  setvalues/diags/messages/fingers`), parses module **definitions** and the
  **status bytes** into values, default-naming, type fix-ups.
- `router.py` (~480 lines) — `HbtnRouter`: parses router/SMR status, the module
  inventory, areas, groups; `update_system_status()` distributes the compact
  status to modules.
- `communicate.py` (~670 lines) — `async_system_update()` (fetch compact status
  → distribute), `update_entity()` (event-server → dispatch to the right
  module's `handle_upd_event`), file-save helpers.

## 3. Target architecture

Two layers with a clean seam:

```
habitron_client  (v2 — PyPI)                Integration (thin HA binding)
─────────────────────────────────          ──────────────────────────────
transport (TCP/CRC/frames)         ◄──────  config_flow, reauth/reconfigure
device model (dataclasses, values) ──────►  coordinator (heartbeat wiring)
status/definition PARSING                   entity platforms (bind to model)
event ingestion + change events    ──────►  device & area registry
high-level commands                ◄──────  diagnostics / system_health
                                            services (thin pass-through)
                                            ws_provider (WebRTC/voice — stays)
```

### 3.1 Library owns (moves out of the integration)

- The **object model**: `System`/`SmartHub` → `Router` → `Module`
  (+`SmartController`) → typed members carrying **parsed values**. The
  `interfaces.py` descriptors become the library's public dataclasses
  (data only — no HA imports).
- All **parsing**: module definitions, compact/module status bytes, router/SMR
  status, module inventory, areas, groups. `const.py` protocol indices/enums
  move here.
- **State access**: `await client.async_setup()` builds the model;
  `await client.async_refresh()` fetches the compact status and updates the
  in-memory model in place; the integration reads typed attributes.
- **Change notification**: a generic listener registry on the model
  (`Module.add_listener(cb)` / per-member callbacks) that fires when a value
  changes — replacing today's `register_callback`/`handle_upd_event`. Generic
  `Callable[[], None]`, **no HA dependency**. The integration registers
  `entity.async_write_ha_state` (and the coordinator its fan-out).
- **Event ingestion**: the push path. Today the SmartHub calls the
  `habitron.update_entity` HA service, which the integration translates into
  `handle_upd_event`. In v2 the library exposes `client.apply_event(evt)` that
  updates the model + fires listeners; the integration's job shrinks to handing
  the raw event to the library.

### 3.2 Integration keeps (HA-only concerns)

- Entity classes per platform (sensor, binary_sensor, switch, light, cover,
  climate, number, select, button, event, notify, text, update, media_player,
  camera, assist_satellite) — each binds to a library model object/value and
  registers a listener.
- `config_flow` (+ reconfigure), `__init__` setup/unload, the
  `DataUpdateCoordinator` heartbeat (calls `client.async_refresh()`), device &
  area **registry** wiring, `diagnostics`, `system_health`.
- Domain **services** become thin pass-throughs to library methods (the
  event-server `update_entity` service feeds `client.apply_event`).
- `ws_provider` (WebRTC/voice/camera over the Flutter-panel websocket) is **not**
  bus-protocol parsing and **stays in the integration** — out of scope here.

## 4. Proposed public API (`habitron_client` v2)

```python
client = HabitronClient(host, port, ...)
await client.async_setup()            # connect + read definitions/inventory -> model
system = client.system               # typed model root
for module in system.modules:        # Module objects with typed members + values
    module.outputs, module.sensors, module.covers, ...   # values already parsed
await client.async_refresh()          # poll compact status -> update model in place
client.apply_event(raw_event)         # push event -> update model + fire listeners
module.add_listener(callback)         # generic change notification (no HA)
await client.set_output(module, nmbr, on)   # commands take model objs or addrs
```

Model objects are plain dataclasses with parsed values + a small listener list;
`__init__.py` re-exports the public ones. Internal parsing stays under `_`.

## 5. Migration plan (HACS first, phased)

1. **Library v2 scaffolding**: add `_models`/`_parsing` modules; port
   `interfaces.py` dataclasses (drop HA callback → generic listener) and
   `const.py` protocol indices into the library.
2. **Port parsing**: move `module.py` (definitions + status parsing, naming,
   type fix-ups) and `router.py` (router/SMR/inventory/areas/groups,
   `update_system_status`) into the library; expose `System`/`Router`/`Module`.
3. **Update/event API**: `async_setup`/`async_refresh`/`apply_event` +
   listeners.
4. **Rewrite the HACS integration** onto the new API: each platform binds to
   model objects; `communicate.py` shrinks to coordinator-fetch + event hand-off;
   delete the moved modules from the integration.
5. **Release** `habitron_client` 2.0; bump the HACS manifest requirement; ship &
   validate the HACS version end-to-end on real hardware.
6. **Mirror into core**: regenerate the core tree from the slimmed HACS source;
   the core PR becomes the thin binding the reviewer asked for. Re-pin the new
   library version.

## 6. Decisions (signed off 2026-06-19)

- **Model granularity: per-member classes** (chosen). A dedicated dataclass per
  member kind (`Output.is_on`, `Dimmer.brightness`, `Cover.position/tilt`,
  `Sensor.value`, `ColorLed.rgb`, …) sharing a `BusMember` base. Precise typing,
  trivial entity binding, mypy/Platinum-friendly.
- **Listener model: per-member callbacks** (chosen) — preserves fine-grained
  entity updates. `BusMember.add_listener/remove_listener/notify`.
- **Areas/groups: parsed in the library, mapped by the integration.** The lib
  exposes `Area(nmbr, name)` + `member.area`/`module.area`/`router.groups` as
  plain data (no HA import). The integration reads those and assigns the HA area
  registry / builds the group-mode `select` entities (as today via
  `async_assign_entity_area`).
- **Files/services** (`save_*`, restarts): thin service → library calls.
- **Backwards compat**: HACS + core both move to `habitron_client` 2.0 together;
  no dual-API period (we control both).

## 7. Implementation log

Branch `v2-device-model` in `habitron-client`.

- **Step 1 — done** (`ca74970`): `model.py` — public per-member object model
  (`BusMember` + typed members, `Module`/`SmartController`/`Router`/`Area`,
  per-member listeners). Re-exported from `__init__`.
- **Step 2a — done** (`edd24e6`): `_indices.py` — protocol constants ported
  verbatim (`MODULE_CODES`, `RoutIdx`/`MSetIdx`/`MStatIdx`/`MirrIdx`/`SMirrIdx`,
  `HaEvents`, offsets, `TRUE_VAL`/`FALSE_VAL`). No HA import.
- **Step 2b (modules) — done** (`274e93b`): `_parse.py` — `build_module()`
  (mirrors every subclass `__init__`: correct member lists per type) and
  `apply_status()` (mirrors every subclass `update()`: compact-status → member
  values, fires per-member listeners only on change). Model extended with the
  fields the parser fills (`mode`, `climate_*`, `analogins`, `analog_outputs`,
  command lists; Router channel/voltage/group fields). Smoke-tested: all 24
  module codes build with the expected member counts; status parse + change-only
  notify + idempotent re-apply verified. ruff/mypy --strict green.
  - *Note:* the Smart Controller's analogue output (AOUT, old `outputs[15]`) is
    now a typed `Dimmer` in `analog_outputs` rather than a binary `Output`.

- **Step 2b (definitions) — done** (`c822630`): `parse_definitions()` in
  `_parse.py` — mirrors `get_names` + all label handlers (`_process_*_label`,
  `_set_*_label`), `set_default_names` and the controller/dimm output→dimmer
  type fix-ups. Member names/areas/types, flags, area, messages/dir/vis commands,
  finger ids all fill from the definition block; the controller analogue output
  moves into the typed `analog_outputs[0]`. Tested with synthetic definition
  blocks across controller/out/dimm/mini. ruff/mypy --strict green.

- **Step 2b (settings) — done** (`a1c819b`): `parse_settings()` in `_parse.py`
  — mirrors `get_settings`: hw/sw versions, analog/switch input typing, and
  shutter/blind cover detection (polarity ±1 shutter / ±2 blind, base-name
  derivation, backing-output disable). Tested: controller shutter, Smart Out
  blind w/ negative polarity, Smart In analogue-input fix-up. ruff/mypy green.

- **Step 2b (router) — done** (`7cd3191`): `_parse_router.py` —
  `build_router`, `parse_router_definitions` (SMR: name/users/serial/version/
  groups/channels), `parse_module_inventory` (inventory + factory via
  `_module_kind`, skips uninstantiable types), `parse_global_descriptions`
  (areas/flags/collective commands), `apply_router_status` (mode/flags/currents/
  voltages/sys_ok/mirror) and `pad_sys_status`+`distribute_status` (compact
  status → each module). Tested end-to-end. Also fixed a `nmbr`/`idx` swap in
  the module flag + counter mapping (`StateDescriptor`/`LgcDescriptor` take
  `idx` before `nmbr`; the flag bit-shift uses `nmbr-1`).

### Step 2 — DONE. Parsing fully ported (constants, module build/status,
definitions/labels, settings, router). All ruff/mypy --strict green; each chunk
smoke-tested with synthetic protocol bytes.

- **Step 3 — done** (`aa6f16c`): high-level API, exported from `__init__`:
  - `_setup.py`: `async_build_system(client, *, b_uid)` — SMR defs → global
    descriptions → inventory+factory → per-module definitions+settings (uid set
    to hw_version) → router status + first `distribute_status`; returns a fully
    parsed `Router`. `async_refresh_system(client, router, *, last_crc)` — polls
    compact status, applies router status + distributes on a CRC change, returns
    the new CRC.
  - `_events.py`: `apply_event(router, mod_id, evnt, arg1..arg5)` — ports
    `update_entity` (router flag/mode, module button/switch/output/RGB/finger/
    dim/cover/blind/move/flag/counter); always notifies. HA-only timing (finger
    sleep-reset) intentionally left to the consumer; button press code carried on
    the input member's `value`.
  - Tested end-to-end with a fake client through the public API: build →
    refresh (changed + crc-skip) → events.
  - *Deferred:* `mode` is a plain int (no per-member push); the mode/group-mode
    select updates on the next poll. Revisit if a push update is needed.

### Step 4 — IN PROGRESS: rewrite the HACS integration onto the new API

Branch `v2-thin-integration` in `habitron_repo` (off `dev`). Decisions
(2026-06-20):
- **Tests in lockstep** — migrate each platform together with its tests; keep
  the suite as green as feasible (the foundation rewrite unavoidably reds
  test_module/test_router/test_interfaces/test_smart_hub/test_communicate first).
- **Model has no back-references** — `Module` carries no `comm`/`smhub`. Entities
  reach the transport via `self.coordinator.comm`; commands address modules by
  `module.addr` (was `mod_addr`). `area_member` → `module.area`.
- **Device registry** creation (hub/router/modules + areas) moves from the
  deleted `module.py`/`router.py` into `smart_hub.py`.
- **Area mapping** stays in the integration: it slugifies `Area.name`
  (`{area.nmbr: slugify(area.name)}`) and feeds `async_assign_entity_area`.
- **Shared `HabitronEntity`** base in `_helpers.py` binds a model member's
  listener to `async_write_ha_state`.
- Delete: `module.py`, `router.py`, `interfaces.py`; trim protocol consts out of
  `const.py`; slim `communicate.py` to transport + `apply_event` + refresh.

TODO (rename, later): `BusMember` is a placeholder name the user finds too
vague ("Bus" not an established term, "member" generic; it really describes the
entities). Rename across lib (`model.py` + `__init__`/`__all__`) and integration
(`_helpers.py`, platform imports). Candidate names TBD.

Phase plan: (1) foundation (_helpers, const, smart_hub, communicate, coordinator
+ their tests; delete module/router/interfaces) → (2) reference platform switch
+ test → (3) remaining platforms + tests.

#### Step 4 — DONE (2026-06-20). HACS integration fully on the v2 API.
- All 17 entity platforms migrated (switch, sensor, binary_sensor, light, cover,
  climate, number, select, button, text, notify, event, update, camera,
  media_player, assist_satellite) + services, diagnostics, system_health,
  device_trigger, ws_provider, smart_hub, communicate, coordinator.
- Entities bind to model members via `add_listener`/`async_write_ha_state`;
  commands go through `coordinator.comm` / `smhub.comm` (`module.addr`); the model
  carries no back-references. `module.py`/`router.py`/`interfaces.py` deleted;
  protocol consts trimmed from `const.py`; manifest pins `habitron_client==2.0.0`.
- Lib follow-ups during the rewrite: `mode` notifiable member, `Finger.user`,
  `SmartController.client_version` (commits in habitron-client `v2-device-model`).
- **Full HACS test suite green: 518 passed.** ruff + mypy clean (mypy via the
  /tmp/phacc test venv which has typed HA + habitron_client 2.0).
- Naming: model↔entity clash → entity gets the `Hbtn` prefix (`HbtnColorLight`);
  model imports stay plain. `BusMember` rename still deferred.

### Step 5 — next: release + ship
- Release `habitron_client` 2.0.0 to PyPI (needs explicit user OK).
- Validate the HACS v2 build on real hardware end-to-end.
- Regenerate the slim core tree from the v2 HACS source and redo core PR #174185
  (the thin wrapper the reviewer asked for).

#### Original Step-4 outline
- Pin `habitron_client` 2.0 (once released); delete the moved modules
  (`module.py`, `router.py`, parsing in `communicate.py`, `interfaces.py`
  descriptors, protocol consts in `const.py`).
- Each platform binds to model members + registers `async_write_ha_state` via
  `BusMember.add_listener`; coordinator calls `async_refresh_system`; the event
  service feeds `apply_event`; area/group mapping + device/area registry stay in
  the integration.
- Then release `habitron_client` 2.0, validate on hardware, regenerate the slim
  core tree and redo the core PR.

---
Next step after sign-off: implement steps 1–4 in `habitron_repo` + the
`habitron_client` repo, release 2.0, then redo the core PR from the slim source.
