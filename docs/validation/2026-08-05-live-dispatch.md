# N3 V3.0 (6602:1000) M3 Live-Dispatch On-Hardware Validation

| Field | Result |
|---|---|
| Date | 2026-08-05 |
| Tested commit | `2c814af` |
| Context | Owner-present validation session for the owner-run live dispatch CLI, following the live dispatch design (`docs/superpowers/specs/2026-08-05-live-dispatch-design.md`) and the M3 action-engine sessions. Same device as the M3 smoke sessions |
| Scope | One bounded owner-run foreground session streaming physical LCD key 1 presses through the action engine (`n3-ai-deck-live`), using an explicit demo bindings file outside the repository that binds exactly `button.1.press` to the zero-side-effect `log_event` builtin. No device writes and no daemon wiring |

## Pre-flight: dry runs

1. `n3-ai-deck-run-action --event button.1.press --bindings <demo> --dry-run`
   resolved the binding against the explicit demo bindings file and skipped
   execution (launch resolved OK), with exit code 0.
2. `n3-ai-deck-live --dry-run --bindings <demo> --duration-ms 90000` returned
   `{"status": "ok", "node_resolved": true, "key_map_entries": 18,
   "bindings_source": "explicit", "bindings_count": 1, "duration_ms": 90000,
   "init": true}` with exit code 0 — the device node resolved, the key map
   loaded (18 entries), the single explicit binding was picked up, and the
   session would initialize.

## Live run: foreground dispatch on hardware

1. `n3-ai-deck-live --bindings <demo> --duration-ms 90000` with the owner
   pressing LCD key 1 repeatedly.
2. A single init line was sent at startup (INITIALIZE, `init_ok: true`).
3. Every press produced one JSONL line in real time:
   `{"schema_version": 1, "event_key": "button.1.press", "control_id": 1,
   "kind": "button", "action": "press", "status": "ok", "plugin":
   "log_event", "detail": "logged", "duration_ms": 0}` — 23/23 presses
   dispatched, engine latency 0 ms per event.
4. The final summary line reported
   `{"status": "succeeded", "events": 23, "dispatched": 23, "unknown": 0,
   "disconnected": false, "init_ok": true, "duration_ms": 90000}` with exit
   code 0 — a clean, bounded exit at the hard deadline.

## Conclusions

- The live foreground dispatch chain works end to end on hardware: physical
  LCD key 1 press → vendor-channel report → normalized `button.1.press` →
  ActionEngine dispatch → structured result, all in real time (0 ms engine
  latency per event).
- 23/23 presses were dispatched through the explicit demo binding to the
  zero-side-effect `log_event` builtin, and the session exited cleanly at the
  hard deadline.
- This is the owner-run foreground CLI. The daemon-managed background wiring
  (G8) remains planned and is not claimed by this record.

## Constraints honored / redaction

- The session was foreground and bounded by a hard deadline; it only logs by
  default, exits cleanly on deadline, Ctrl+C, or disconnect, and made no
  device writes. The engine and plugin ran in-process with no daemon wiring.
- This record contains no serial, bus location, `/dev` node name, absolute
  path, or username. The demo bindings file is referred to only as an
  explicit bindings file outside the repository.
