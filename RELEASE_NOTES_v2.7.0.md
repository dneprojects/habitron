# Habitron Integration 2.7.0

This release migrates the integration to **habitron_client 1.0.0**.
The library is now fully async and strict-typed; the integration's
transport layer (`HbtnComm`) has been rewritten on top of it.

## What changed under the hood

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

## What changed for you

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

## Upgrading

1. **HACS → Habitron → Update** (or whatever path you use).
2. **Restart Home Assistant.** First restart after the update is
   a few seconds slower than usual while HA installs
   `habitron_client==1.0.0` into its venv (~5–10 s). The pinned
   version is enforced through `manifest.json`; you don't need
   to install anything manually.
3. **Verify in the log** that you see
   `Setting up habitron` → `Initializing hub` → modules discovered
   → `Re-initialized hub with mode 1` without errors.

## Rollback

If something breaks for you and we haven't shipped a fix yet:

- HACS → Habitron → **Redownload** → choose **2.6.3** → restart HA.
- HA will downgrade `habitron_client` to 0.1.4 automatically on the
  next restart because the older manifest pins that version.

Please open an issue on GitHub describing the symptom so the rollback
can be quick and the next release can include the fix.

## Internals if you're curious

- `HbtnComm` is ~80 lines smaller after dropping the executor and
  the lock plumbing.
- `_async_exec`, `_api_lock` and the sync `set_output` overload are
  removed.
- A new `HbtnComm.async_close()` / `SmartHub.async_close()` pair
  closes the persistent connection on entry unload.
- `set_host()` now closes the old client and constructs a new one
  (the lib's `host` attribute is read-only by design).
- Token + MAC encoding for `send_network_info` happens at the
  `HbtnComm` boundary (`utf-8` for the token, `bytes.fromhex` for
  the 6-byte MAC).

## Acknowledgements

The `habitron_client` async migration that made this release possible
shipped as the lib's own `1.0.0` and is available on PyPI.
