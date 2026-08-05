# N3 V3.0 (6602:1000) M3 Action-Engine On-Hardware Smoke

| Field | Result |
|---|---|
| Date | 2026-08-05 |
| Tested commit | `cbb589d` |
| Context | Owner-present smoke session for M3, following the M3 action-engine design (`docs/superpowers/specs/2026-08-05-m3-action-engine-design.md`) and the M2 hardware sessions. Same device and same owner-approved temporary ACL as `2026-08-05-g7-six-lcd-and-production-regression.md`; same vendor HID channel |
| Scope | One bounded read-only vendor-channel input session through the production CLI, then the hardware-free action engine driven by the shipped zero-side-effect default sample (`resources/actions.default.json`). No writes and no daemon wiring |

## Hardware leg: production input session

1. `n3-ai-deck-observe-inputs --json --channel vendor --calibrate --press-only
   --duration-ms 60000` returned `status: succeeded` and `state:
   profile_approved`, capturing **36 press reports** during the 60 s window.
   The distinct-codes report contained exactly one entry:
   `{event_type: 65440, event_code: 1}` — LCD key 1, pressed repeatedly by
   the owner.
2. **Operational guidance**: one earlier run in the same session captured
   zero events because the operator pressed outside the listen window — the
   same lesson as the G7 record. This is operator timing, not a code defect.

## Engine leg: hardware-free action run

1. `n3-ai-deck-run-action --event button.1.press --dry-run` returned
   `{"schema_version": 1, "event_key": "button.1.press", "status": "skipped",
   "plugin": "log_event", "detail": "dry run: plugin not executed"}` with
   exit code 0 — the shipped sample bound the key, the plugin resolved, and
   the config validated without executing.
2. Real run `n3-ai-deck-run-action --event button.1.press` returned
   `status: ok`, `plugin: log_event`, `detail: logged`, `duration_ms: 0`
   with exit code 0 — the `log_event` builtin executed with zero side
   effects.
3. Both runs used the shipped zero-side-effect default sample
   (`resources/actions.default.json`), which binds every standard event to
   `log_event`.

## Conclusions

- The same physical control — an LCD key 1 press, vendor-channel code 1 —
  maps to the standard event key `button.1.press` that the action engine
  consumes.
- The engine resolved the binding and returned a structured result with no
  hardware attached; the end-to-end smoke passed.
- Live wiring of the input listener to the engine (the device daemon) remains
  planned (G8), as the public docs state; this smoke record does not claim it.

## Constraints honored / redaction

- The input leg was read-only (`O_RDONLY`, owner-approved temporary ACL, no
  writes); the engine leg ran without hardware and without loading the SDK.
- This record contains no serial, bus location, `/dev` node name, absolute
  path, or username.
