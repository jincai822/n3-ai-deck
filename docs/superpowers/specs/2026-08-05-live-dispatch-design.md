# Live Dispatch Design

**Date:** 2026-08-05
**Status:** Draft for owner review
**Supersedes:** None
**Evidence base:** `tasks/prd-n3-ai-deck.md` (US-03), `docs/ARCHITECTURE.md`
("Event and action engine" section), `ROADMAP.md` (M3 line),
`docs/superpowers/specs/2026-08-05-m3-action-engine-design.md` (M3 engine and
config design), `docs/superpowers/specs/2026-08-05-m2-vendor-channel-backend-design.md`
(§2 validated protocol facts), `docs/validation/2026-08-05-g7-six-lcd-and-production-regression.md`
(G7 write/input validation), `src/streamdock_n3/hardware/contracts.py`,
`src/streamdock_n3/hardware/input_session.py`,
`src/streamdock_n3/hardware/vendor_backend.py`, `src/streamdock_n3/input_cli.py`,
`src/streamdock_n3/paths.py`, `src/streamdock_n3/daemon.py`,
`src/streamdock_n3/actions/engine.py`, `src/streamdock_n3/actions/config.py`,
`src/streamdock_n3/actions/builtins.py`, `tests/test_input_cli.py`

## 1. Why this design exists

M3 delivered the action engine and its safe builtins but no owner-facing
runtime that feeds the engine real physical events. The validated vendor
channel today has two disconnected entry points: `run_input_session`
aggregates a bounded window into a report (`input_session.py:202-304`), and
the engine demo CLI synthesizes a single event by hand
(`actions/cli.py`, `n3-ai-deck-run-action`). The legacy `daemon.py` is a
shell-executing service with unresolved G8 concerns and is not a candidate
for wiring.

This design adds the missing runtime: a foreground, owner-run CLI
`n3-ai-deck-live`. The owner plugs in the device, runs it, presses physical
keys, and each press is dispatched to the M3 `ActionEngine` in real time —
logging only by default, and launching allowlisted applications only when the
owner has created a bindings file. Ctrl+C, the session deadline, or a
disconnect ends the session cleanly with a summary. This is explicitly **not**
G8: no daemon, no service, no auto-restart, no shell execution, and
`daemon.py` is untouched. LCD key-image feedback of results is deferred to M4.

## 2. Validated facts (ground truth for implementation)

The live loop reuses already-validated parts; nothing new is invented at the
protocol level. Ground truth, verified against the code:

- **Streaming input parts already exist.** `VendorHidReadOnlyBackend`
  (`hardware/input_session.py:157-196`) opens exactly one node `O_RDONLY`,
  and `read_events(handle, deadline_ns)` (`input_session.py:168-191`) yields
  `RawInputEvent`s until the deadline with a 100 ms poll
  (`POLL_INTERVAL_MS`, `input_session.py:160`); a disconnect propagates
  `OSError` (`input_session.py:184-186`). `parse_vendor_report`
  (`input_session.py:147-154`) turns 512-byte unnumbered vendor reports into
  events and drops ACK reports (code `0xFF`). `normalize_event(raw, key_map)`
  (`input_session.py:43-61`) maps one raw event through the key map and
  returns `None` for unknown codes.
- **The session runner is aggregate-only, not a dispatch loop.**
  `run_input_session` (`input_session.py:202-304`) runs one bounded read and
  returns an `InputSessionResult`; the live loop reuses the backend and
  `normalize_event`, not the runner.
- **Node resolution and key-map loading are importable.** `resolve_vendor_node()`
  (`input_cli.py:185-212`) resolves the unique vendor-HID node path;
  `_load_key_map(path, channel)` (`input_cli.py:215-243`) loads the vendor key
  map (18 entries for `channel="vendor"`; `tests/test_input_cli.py:197-205`).
  Both are importable, with precedent at `tests/test_input_cli.py:13-20`.
- **The only device write is the validated init trio, manifest-free.**
  `_frames_for_command` (`vendor_backend.py:131-152`) maps `INITIALIZE` to the
  DIS/LIG/STP output reports and `_HidrawTransport` (`vendor_backend.py:84-114`)
  writes them — the exact frame-level path G7 validated on hardware
  (`docs/validation/2026-08-05-g7-six-lcd-and-production-regression.md:8,27-35`).
  `VendorHidCommandBackend.execute` (`vendor_backend.py:164-217`) is
  manifest-bound and opens the node only inside each `execute`, so it cannot
  be reused for a standalone init write; the live loop goes through the frame
  pipeline via the injectable `VendorHidTransport` protocol
  (`vendor_backend.py:65-82`).
- **Why init at all.** Round buttons and knobs report spontaneously
  (`2026-08-05-m2-vendor-channel-backend-design.md:29-30`), but the LCD keys
  (`0x01`-`0x06`) report only after the init trio
  (`2026-08-05-m2-vendor-channel-backend-design.md:31-32`); G7 confirms the
  trio lights the screens and makes the six keys responsive. The live CLI
  therefore sends one bounded init at start.
- **Engine and config reuse.** M3's `ActionEngine`
  (`actions/engine.py:36`, `handle_event` at `actions/engine.py:60`) consumes
  `NormalizedInputEvent`, derives keys with `event_key_for`
  (`actions/engine.py:23`), and never raises across the plugin boundary;
  `load_bindings`/`default_bindings_path` (`actions/config.py:32,20`) and
  `builtin_registry()` (`actions/builtins.py:102`) provide the safe default.
- **Duration bound.** `MAX_DEADLINE_MS = 600_000` (`contracts.py:19`);
  `InputSessionSpec.duration_ms` is validated to `[1, MAX_DEADLINE_MS]`
  (`contracts.py:749`). The new live spec applies the same bound.
- **XDG convention.** `APP_NAME = "streamdock-n3"` and `config_dir()` =
  `~/.config/streamdock-n3` (`paths.py:8,16-17`). A bindings default at
  `config_dir() / "bindings.json"` follows the convention; the legacy
  `config_file()` (`config.json`, `paths.py:28-29`) holds shell actions for
  `daemon.py` and is deliberately not reused.

## 3. Scope

**In scope (live dispatch):**
1. New `src/streamdock_n3/actions/live.py`: `LiveSessionSpec`,
   `LiveSessionResult`, and `run_live_loop`.
2. New `src/streamdock_n3/actions/live_cli.py` and console script
   `n3-ai-deck-live`.
3. Default bindings resolution: an owner-created
   `~/.config/streamdock-n3/bindings.json`, falling back to the shipped
   zero-side-effect sample (`actions.default.json`, every standard key →
   `log_event`).
4. Tests first (RED→GREEN) with fake scripted input backends and a fake
   recording transport; no real device access, no SDK import.
5. Owner-gated on-hardware validation (P5) and a validation record.

**Out of scope:** G8 (legacy daemon review: close/tcache handling, auto-restart,
shell isolation — unresolved, and this milestone does not touch them); any
wiring of `daemon.py`; auto-reconnect or retry logic; service/systemd/GUI
integration; LCD key-image or brightness feedback of results (M4); binding
configuration from the CLI (the CLI only reads the bindings file, never
writes it); plugins beyond M3's builtins.

## 4. Design

### 4.1 Live session spec

```python
@dataclass(frozen=True, slots=True)
class LiveSessionSpec:
    duration_ms: int       # validated to [1, MAX_DEADLINE_MS] (contracts.py:19)
    init: bool = True      # send the validated DIS/LIG/STP init trio at start
```

`__post_init__` validates `duration_ms` with the house integer-validator style
(`contracts.py:749` shows the same bound). `init=True` is the default because
the LCD keys report only after the init trio (§2); `--no-init` opts out.

### 4.2 Live loop

`src/streamdock_n3/actions/live.py`:

```python
def run_live_loop(
    spec: LiveSessionSpec,
    node: str,
    key_map: KeyMap,
    engine: ActionEngine,
    *,
    input_backend: ReadOnlyInputBackend,
    transport: VendorHidTransport,
    on_event: Callable[[NormalizedInputEvent, ActionResult | None], None] | None = None,
) -> LiveSessionResult
```

Flow:

1. **Init (optional, once).** When `spec.init`, translate
   `AdapterCommand(operation=Operation.INITIALIZE)` through
   `_frames_for_command` (`vendor_backend.py:131-152`) and write each frame
   with `transport.write`, draining ACKs with `transport.drain_acks` — the
   frame-level path G7 validated. A write failure is recorded in the result
   (`init_ok=False`) but does not abort the session: the round buttons and
   knob self-report regardless, and the owner sees the failure in the summary.
2. **Open.** `input_backend.open_read_only(node)`. `PermissionError` →
   a `LiveSessionResult` with `status="rejected"`; any other `OSError` →
   `status="error"` (mirrors `run_input_session`'s classification,
   `input_session.py:210-217`).
3. **Dispatch loop.** The outer loop re-arms the deadline and re-enters
   `input_backend.read_events(handle, deadline_ns)` until the total window
   (`duration_ms` from start) elapses. Each yielded raw event is passed
   through `normalize_event` (`input_session.py:43-61`); `None` → `unknown`
   counter, no engine call. Otherwise `engine.handle_event(normalized)`
   (`actions/engine.py:60`) returns `ActionResult | None` (`None` = unbound);
   the loop then calls `on_event(normalized, result)` if provided. The engine
   call is additionally guarded so that any unexpected exception is recorded
   as an error result and the loop continues to its deadline (belt-and-braces
   on top of M3's never-raise guarantee).
4. **Exit conditions.** A backend `OSError` → `disconnected=True` and the
   loop exits (no reconnect, by design). Deadline exhaustion → clean exit.
   Ctrl+C surfaces as `KeyboardInterrupt`, which the CLI turns into the same
   clean summary path (§4.3).
5. **Close and result.** `backend.close(handle)` runs in a `finally`; the
   function returns a frozen, slotted `LiveSessionResult` with `to_dict()`:
   `status`, `events` (raw events received), `dispatched` (normalized events
   handed to the engine), `unknown` (raw codes not in the key map),
   `disconnected`, `init_ok`, `duration_ms`.

Both `input_backend` and `transport` are injectable so tests never touch real
nodes, matching `input_session.py:80-95` and `vendor_backend.py:65-82`.

### 4.3 CLI

`n3-ai-deck-live = streamdock_n3.actions.live_cli:main`, mirroring
`input_cli.py`'s structure (argparse with `prog=`, `main(argv) -> int`,
deterministic JSON with `schema_version`):

- `--bindings PATH` — defaults to `~/.config/streamdock-n3/bindings.json`
  when it exists, otherwise the bundled `actions.default.json` (§4.4). An
  explicit `--bindings` pointing to a missing or malformed file is a
  structured error (`exit 1`), never a traceback.
- `--duration-ms MS` — default 60 000, validated to `[1, MAX_DEADLINE_MS]`.
- `--no-init` — skip the init trio (default is to send it).
- `--dry-run` — resolve the node, key map, and bindings, print one summary
  JSON line (`schema_version`, bindings path used, node resolved, key-map
  entry count, bindings count), and exit without opening the device, sending
  any write, or touching config.

Output is one JSONL line per received event with `schema_version` (1);
dispatched events carry `event_key`, `control_id`, `kind`, `action`, and the
engine result (`status`, `plugin`, `detail`, `duration_ms`); unbound keys
report `status: "unbound"` with no result; raw codes not in the key map
report `status: "unknown"` with no event key (vendor protocol details never
appear — US-03). A final summary line reports the counters from §4.2.
Ctrl+C, deadline, and disconnect all end with a summary line. Exit codes:
`0` for any clean completion (deadline, Ctrl+C, or disconnect), `1` for
rejected/error (bad arguments, no node, bindings error, open failure).

### 4.4 Default bindings

- Default path follows the XDG convention (`paths.py:16-17`):
  `~/.config/streamdock-n3/bindings.json`. The legacy `config.json`
  shell-action file is not read and never modified.
- When the file does not exist, the CLI falls back to the bundled
  `actions.default.json`, which binds every standard event key to `log_event`
  — an out-of-box run has zero side effects. Allowlisted app launching
  (`launch_app`) is possible only after the owner creates the bindings file
  with an allowlisted name (`LaunchAppPlugin`, M3).
- The CLI never writes the bindings file and exposes no install/reload/config
  flags, mirroring `test_parser_has_no_system_mutation_flags`
  (`tests/test_input_cli.py:93-104`).

## 5. Safety invariants

- **Zero side effects by default.** No bindings file → every event logs only.
  App launching requires an owner-created file with an allowlisted name and
  runs via argv lists with `shell=False` (M3); no shell, no arbitrary
  command, no downloaded content by default (US-03).
- **Foreground and bounded.** The CLI is owner-run in the foreground; the
  session is bounded by `duration_ms` capped at `MAX_DEADLINE_MS`
  (`contracts.py:19`). The only device write is the single validated init
  trio at start through the G7-validated frame-level path (§2); no key images
  are written this iteration (deferred to M4).
- **Clean exits.** Ctrl+C, deadline, and disconnect all end the session with a
  summary and `exit 0`. A disconnect is never retried — there is no
  reconnect, retry, service, or auto-restart.
- **The loop never crashes from engine/plugin failures.** `handle_event`
  returns structured results (M3 invariant); the loop additionally guards the
  engine call so an unexpected exception is recorded and the session
  continues.
- **Redacted output.** JSONL and summaries contain no device node path, bus
  location, or serial; `--dry-run` reports node resolution as a boolean. The
  bindings file contents are never echoed.
- **Explicitly not G8.** `daemon.py` (shell executor, close/tcache handling,
  auto-restart, shell isolation) is untouched and not wired; no daemonize,
  no systemd/supervisor integration, no background persistence.

## 6. Test plan (RED→GREEN, no real device)

- **Loop** (`actions/live.py`), with a fake scripted input backend (fixed
  `RawInputEvent` sequence; a variant that raises `OSError` mid-stream) and a
  fake recording transport:
  - init on → transport receives exactly the DIS/LIG/STP frames; init off →
    zero frames; init write failure → `init_ok=False`, session continues.
  - dispatch: each normalized event reaches `engine.handle_event` and
    `on_event(event, result)`; unbound (`None`) result still counted as
    dispatched; unknown raw code → `unknown` counter and no engine call.
  - a fake engine that raises → loop continues, error recorded, deadline
    honored; disconnect → loop exits early with `disconnected=True`; deadline
    exhaustion → clean summary with correct counters.
  - `LiveSessionSpec` rejects `duration_ms` outside `[1, MAX_DEADLINE_MS]`.
- **CLI** (`actions/live_cli.py`), with node resolution, key-map loading, and
  the loop mocked (no `/dev` access, no SDK import):
  - `--dry-run` resolves node/key map/bindings without opening anything;
  - `--bindings` missing/malformed → structured error JSON, `exit 1`;
  - default bindings fall back to the sample when the XDG file is absent;
  - `--no-init`/`--duration-ms` wiring; parser exposes no mutation flags;
  - simulated Ctrl+C ends with a summary line and `exit 0`;
  - no device node name or serial appears in any output.
- **Public-project guards** (pattern of `test_public_project.py`) updated in
  P4 alongside the docs flip, plus the `REVIEWED_SOURCE_SHA256` refresh in
  `test_hardware_g0_safety.py` because P3 adds the console script to
  `pyproject.toml`.

## 7. Implementation order

1. **P1** this design doc approved.
2. **P2** live loop: `actions/live.py` (`LiveSessionSpec`,
   `LiveSessionResult`, `run_live_loop`) with the fake-backend/fake-transport
   test suite.
3. **P3** CLI: `actions/live_cli.py`, console script `n3-ai-deck-live` in
   `pyproject.toml`, CLI tests, `uv build`.
4. **P4** docs flip + guards: ARCHITECTURE.md adds the implemented
   "owner-run live dispatch" line, ROADMAP.md checks the new M3 item with an
   evidence link and approval ref `owner:2026-08-05:live-dispatch`,
   README.md/README.zh-CN.md status lines, `test_public_project.py` guard
   updates, and the `REVIEWED_SOURCE_SHA256` refresh in
   `test_hardware_g0_safety.py` for `pyproject.toml` (digest changed in P3).
5. **P5** owner-gated on-hardware validation: the owner plugs in the device
   and drives real key presses through `n3-ai-deck-live` (default logging and
   a bindings file), then a validation record is added under `docs/validation/`.
   Not blocking.

Each phase lands as its own small commit series with the quality gate
(`uv run pytest`, `uv run ruff check .`, `uv build`) green before the next.
