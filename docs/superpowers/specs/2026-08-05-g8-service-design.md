# G8 Background Service Design (`n3-ai-deck-service`)

**Date:** 2026-08-05
**Status:** Draft for owner review
**Supersedes:** None
**Evidence base:** `docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md`
(G8 gate row and §13), `tasks/prd-m2-n3-v3-hardware-controls.md` (G8
acceptance and owner-gated system changes), `CHANGELOG.md` (0.2.3 tcache
fix), `docs/superpowers/specs/2026-08-05-live-dispatch-design.md` (the loop
this service wraps), `docs/superpowers/specs/2026-08-05-m3-action-engine-design.md`,
`docs/superpowers/specs/2026-08-05-m4-ai-workflow-design.md`,
`docs/validation/2026-08-05-live-dispatch.md`,
`docs/validation/2026-08-05-m4-ai-workflow.md`,
`src/streamdock_n3/actions/live.py`, `src/streamdock_n3/actions/engine.py`,
`src/streamdock_n3/actions/live_cli.py`, `src/streamdock_n3/hardware/permissions.py`,
`src/streamdock_n3/hardware/vendor_backend.py`,
`src/streamdock_n3/hardware/input_session.py`, `src/streamdock_n3/input_cli.py`,
`src/streamdock_n3/daemon.py`, `src/streamdock_n3/_data/streamdock-n3.service`

## 1. Why this design exists

The owner-run live dispatch CLI (`n3-ai-deck-live`) is validated on hardware
but requires a human to start it: the owner plugs in the device, runs the
command, and presses keys during one bounded session. The remaining wiring
gap is G8: a background service that makes the device work automatically when
plugged in after desktop login, auto-recovers from unplug/replug, and needs
no manual command. G8 is the last item the public docs still label as
"planned" (`docs/ARCHITECTURE.md`, `README.md`, `ROADMAP.md`).

This design turns the validated foreground loop into a systemd user service
`n3-ai-deck-service` — explicitly **not** the legacy `streamdock-n3` daemon,
which remains untouched. It reuses only validated, hardware-approved pieces:
the vendor-channel input session, the M3 action engine, and the M4
`--feedback`/`--timeout-seconds` flags.

## 2. Validated facts (ground truth for implementation)

### 2.1 The four G8 prerequisites and their resolution

The M2 hardware-controls spec gates G8 in the stage table (spec:242):
"close/tcache、自动重启和 action 隔离未解决", and §13 (spec:360-362)
requires resolving arbitrary shell action, auto-restart, close/tcache, and
auto-write concerns before G8 planning. The PRD acceptance criterion
(`tasks/prd-m2-n3-v3-hardware-controls.md:322`) states G8 is planned outside
M2 and must first resolve close/tcache, auto-restart, and shell-action
isolation. Each prerequisite resolves as follows:

1. **close/tcache.** The vendored SDK's `device.close()` crashes under
   glibc's tcache integrity check (CHANGELOG 0.2.3); the legacy daemon works
   around it with `os._exit()` instead of a normal close (`daemon.py:276-281`).
   The G8 service path resolves this **by construction**: it never imports
   `_vendor`, so there is no vendored SDK object to close. Verified:
   `hardware/vendor_backend.py`, `hardware/input_session.py`,
   `hardware/ipc.py`, and `hardware/contracts.py` import stdlib and local
   package modules only (no `_vendor`, no `StreamDock` import).
2. **Arbitrary shell actions.** The M3/M4 engine ships allowlisted argv-only
   builtins (`shell=False`) and the `ai_text` plugin uses stdlib urllib; the
   engine, builtins, and service modules contain no shell execution in the
   service path.
3. **Auto-restart.** Designed in this document, in two layers (§2.3).
4. **Action isolation.** The engine runs every plugin in a single-worker
   `ThreadPoolExecutor(max_workers=1)` (`actions/engine.py:120`) under a hard
   timeout (`future.result(timeout=...)`, `engine.py:99`) with full exception
   containment ("never raises", `engine.py:96`). **Known limitation, stated
   honestly:** a hung plugin holds the only worker thread — threads cannot be
   killed — so a stuck engine stalls the session loop; the systemd
   `Restart=on-failure` layer is the backstop.

### 2.2 Service loop facts

- `run_live_loop` returns `LiveSessionStatus.SUCCEEDED` **even when the
  device disconnected** — the returned result carries `disconnected=disconnected`
  alongside `status=SUCCEEDED` (`actions/live.py`, final result block).
  The service therefore resets the backoff only for
  `status == SUCCEEDED` with `disconnected == False`; a `SUCCEEDED` result
  with a disconnect is still a reconnect event, not a success, and
  `rejected`/`error` results retry with backoff too.
- hidraw node numbers can change across unplug/replug. `resolve_vendor_node()`
  (`input_cli.py:185-212`) resolves the approved control interface fresh from
  sysfs each call and raises `NodeResolutionError` when the node is absent.
  The service re-calls it on **every** iteration and never caches its result.
- Bounded sessions re-run back-to-back; the loop is stateless and restartable
  at any point (a session ends at its hard deadline, on disconnect, or on
  SIGTERM).

### 2.3 Auto-restart, two layers

- **Layer 1 — in-process reconnect with backoff.** Node absent → sleep →
  retry; session ends with `disconnected` → retry; a fully successful session
  (no disconnect, events dispatched) resets the backoff to the minimum. The
  loop is stateless between sessions.
- **Layer 2 — systemd.** The user unit uses `Restart=on-failure` with
  `RestartSec=2` — the pattern already proven by the legacy
  `_data/streamdock-n3.service`, which is **legacy and must not be reused by
  name**; the new asset is `n3-ai-deck.service`.

### 2.4 Permission model (v0.1.x: session-bound)

- G2's approved rule shape comes from `hardware/permissions.py`
  `persistent_rule`: precise `6602:1000` + the interface triple +
  `TAG+="uaccess"`; no `0666` anywhere.
- `uaccess` grants access through logind active-session ACLs. The service
  runs in the user manager (`systemctl --user`); where no seat session
  provides an ACL, the owner enables `Linger=yes` so the user manager can
  start the service. This is an **accepted, documented limitation**: the
  target scenario is an active desktop session, not headless boot.
- udev rule installation is system-level and therefore **owner-gated**: the
  M2 spec's default is not to install persistent rules (spec §8), the PRD
  requires separate approval for every active action (`prd:26`), and
  unapproved system modifications count as failures (`prd:345`). The CLI only
  **prints** the rule; the owner installs it with sudo themselves.

### 2.5 Credentials

The unit reads credentials from
`EnvironmentFile=-%h/.config/streamdock-n3/service.env` (owner-created, mode
`0600`). The leading `-` means a missing file is not a failure. The AI key
never enters the unit file, the command line, or the repository.

### 2.6 SIGTERM

The service installs a SIGTERM handler that raises a custom exception in the
main thread, which interrupts the select loop. The loop unwinds to a clean
summary and exit; systemd stop does not hit its default timeout.

### 2.7 Legacy assets untouched

`daemon.py`, `_data/streamdock-n3.service`, `_data/99-streamdock.rules`, and
`system_install.py` stay exactly as they are. The new asset is named
`n3-ai-deck.service`, distinct from every legacy name.

## 3. Scope

**In scope:** a `ServiceSpec`-driven, fully injectable service loop
(`run_service`); JSONL lifecycle logging; the `n3-ai-deck-service` console
script reusing the validated live flags plus `--print-unit` and
`--print-udev-rule`; the `n3-ai-deck.service` user unit template; unit tests
with fakes (no real device); P4 doc flip and P5 owner-present validation.

**Out of scope:** udev or systemd installation (owner-gated, print only);
the legacy daemon/GUI/probe/debug/install commands and their unit and udev
assets (untouched); the vendored SDK (never imported); headless-boot support
(the documented limitation); GUI configuration.

## 4. Design

### 4.1 `ServiceSpec` and `run_service`

```python
@dataclass(frozen=True)
class ServiceSpec:
    session_duration_ms: int
    backoff_schedule: tuple[float, ...] = (2.0, 5.0, 10.0, 30.0)  # caps at last value
    init: bool = True
    feedback: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


def run_service(
    spec: ServiceSpec,
    *,
    node_resolver: Callable[[], str],
    session_runner: Callable[[str, ServiceSpec], LiveSessionResult],
    sleep: Callable[[float], None],
    on_lifecycle: Callable[[dict], None],
) -> int:
```

Every dependency is injected: `node_resolver` (wraps `resolve_vendor_node`),
`session_runner` (wraps the validated live loop), `sleep` (for tests), and
`on_lifecycle` (JSONL logging hook). The loop body imports stdlib and local
hardware/actions modules only — never `_vendor`.

Loop algorithm (per iteration):

1. Try `node_resolver()`. On `NodeResolutionError`: emit `retry`
   (reason `node-absent`), sleep the current backoff, advance the schedule,
   repeat.
2. Run one bounded session via `session_runner(node, spec)`.
3. If `result.disconnected` (including a `SUCCEEDED` status with a
   disconnect): emit `session_end` + `retry` (reason `disconnected`); do
   **not** reset backoff; continue.
4. Only a session that ended `status == SUCCEEDED` with
   `disconnected == False` resets the backoff to the minimum and emits
   `session_end`; any other status (`rejected`, `error`) emits `session_end`
   plus `retry` (reason `error`), sleeps the current backoff, and advances
   the schedule.
5. Any unexpected exception from the runner is contained: emit `retry`
   (reason `error`) and let systemd's restart layer cover a repeated hard
   failure.

### 4.2 Lifecycle events (JSONL)

- `{"event": "started", "session_duration_ms": ..., "init": ..., "feedback": ...}`
- `{"event": "retry", "reason": "node-absent"|"disconnected"|"error", "attempt": N, "backoff_s": ...}`
- `{"event": "session_end", "status": ..., "disconnected": ..., "events": ..., "dispatched": ..., "unknown": ...}`
- `{"event": "stopping", "reason": "sigterm"|"fatal", "exit_code": ...}`

All lifecycle fields are redacted: no serials, no node paths, no absolute
paths, no credentials.

### 4.3 CLI `n3-ai-deck-service`

Reuses the validated live flags from `actions/live_cli.py` (`--bindings`,
`--duration-ms`, `--no-init`, `--dry-run`, `--feedback`,
`--timeout-seconds`), plus:

- `--print-unit`: print the user unit to stdout — `%h` placeholders,
  `ExecStart=%h/.local/bin/n3-ai-deck-service`,
  `EnvironmentFile=-%h/.config/streamdock-n3/service.env`,
  `Restart=on-failure`, `RestartSec=2`, `WantedBy=default.target`.
  **Print only; never installs or enables.**
- `--print-udev-rule`: print the G2-shape rule for the approved input and
  control interfaces (exact `6602:1000` + interface triple +
  `TAG+="uaccess"`). **Print only; never writes to the system.**

### 4.4 systemd user unit (`n3-ai-deck.service`)

```
[Unit]
Description=N3 AI Deck background service
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/n3-ai-deck-service
EnvironmentFile=-%h/.config/streamdock-n3/service.env
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

Every path is a `%h` placeholder — no absolute paths in the unit or the
repo.

## 5. Safety invariants

1. **Never imports `_vendor`.** The service, its loop, and its import graph
   contain no vendored SDK import — close/tcache is resolved by construction
   (no SDK object exists to close).
2. **No shell.** The service path has no shell execution; plugins run as
   allowlisted argv-only builtins (`shell=False`).
3. **No auto-install.** `--print-unit` and `--print-udev-rule` print to
   stdout only; the service never writes udev rules, systemd units, ACLs, or
   system files.
4. **Credentials via `EnvironmentFile` only.** The AI key never appears in a
   unit file, a command line, or the repository.
5. **Backoff reset only on clean success.** The loop resets the backoff
   only for `status == SUCCEEDED` with `disconnected == False`; a `SUCCEEDED`
   result with `disconnected=True` is a reconnect event, not a success, and
   `rejected`/`error` sessions retry with backoff — never a hot loop.
6. **Callbacks are exception-contained.** A throwing `on_lifecycle` callback
   is logged and skipped; it never kills the loop.
7. **Redacted logging.** Lifecycle events carry no serial, `/dev` node name,
   absolute path, or credential.

## 6. Test plan (RED→GREEN, no real device)

All tests use injected fakes: a `NodeAbsentThenPresentResolver`, a
`CountingSessionRunner`, a fake `sleep` that records delays, and an
`on_lifecycle` collector.

- **Node-absent backoff.** Resolver raises `NodeResolutionError` for the
  first iterations → loop sleeps `2s → 5s → 10s → 30s` and caps at `30s`;
  `retry` events carry the right `reason` and `attempt`.
- **Disconnect reconnect.** Runner returns `disconnected=True` → next
  iteration re-resolves and re-runs; backoff is not reset.
- **Backoff reset.** A clean session (no disconnect, events dispatched)
  resets the backoff to the minimum.
- **Resolver called every iteration.** Assert the resolver call count equals
  the iteration count — no caching across replugs.
- **SIGTERM clean exit.** Raise the custom SIGTERM exception from within a
  fake `sleep` → loop unwinds, emits `stopping` (reason `sigterm`), exits 0.
- **Lifecycle callback exception containment.** A throwing callback does not
  crash the loop.
- **CLI print flags.** `--print-unit` and `--print-udev-rule` emit the
  expected text and perform no writes; `--dry-run` resolves without opening
  the device.
- **Public-doc guards.** `tests/test_public_project.py` updates in lockstep
  with the P4 doc flip; `tests/test_hardware_g0_safety.py`'s
  `REVIEWED_SOURCE_SHA256` for `pyproject.toml` changes in P3 when the
  console script is added.

## 7. Implementation order

1. **P1** — this design doc approved.
2. **P2** — service loop: `actions/service.py` (`ServiceSpec`,
   `run_service`, lifecycle JSONL) plus the fake-based unit tests above.
3. **P3** — CLI + unit: `actions/service_cli.py` (`n3-ai-deck-service` with
   the live flags + `--print-unit` + `--print-udev-rule`), console script in
   `pyproject.toml`, `_data/n3-ai-deck.service` asset; update
   `REVIEWED_SOURCE_SHA256` for `pyproject.toml` in
   `tests/test_hardware_g0_safety.py`.
4. **P4** — docs flip: ROADMAP G8 line moves from planned to implemented with
   approval reference `owner:2026-08-05:g8-service`; the README/ARCHITECTURE
   "daemon-managed background wiring remains planned" lines are updated in
   lockstep with their public-doc guards.
5. **P5** — owner-present validation: foreground unplug/replug test (device
   unplugged mid-session → reconnect observed → session resumes, including a
   node-number change), then the owner-gated install (the owner runs
   `--print-unit`/`--print-udev-rule` and installs with sudo themselves) and
   an automation check (plug in → service auto-runs with no manual command).
