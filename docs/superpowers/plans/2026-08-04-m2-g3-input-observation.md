# M2 G3 Read-Only Input Observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Observe and validate all physical inputs of the G1-approved input interface (`01`, boot keyboard + input subsystem) through one bounded, read-only, short-lived helper session: 6 LCD keys and 3 round buttons at 10/10 press/release, 3 knobs at 20/20 per direction plus 10/10 press/release, 10-minute stability with p95 local event latency ≤ 250 ms, and disconnect classification within 2 seconds with zero automatic recovery writes. The helper never writes to the device and never loads the SDK.

**Architecture:** A pure evdev codec parses raw `input_event` bytes into normalized events through a configurable `KeyMap`. A `ReadOnlyInputBackend` opens exactly one approved input node `O_RDONLY` (the node is resolved from sysfs and its device link is verified against the approved interface before opening), runs a bounded read loop with select-based deadline, counts per-control press/release/rotation, measures read→normalize latency, and classifies read errors as `DISCONNECTED` within a bounded grace without reopening. The existing fixed `-I -m` helper process gains a session branch that returns a structured redacted `InputSessionResult` over the closed JSON protocol. The G3 gate accepts the session result with machine-backed settlement; ambiguous key mappings, unmet counts, unknown-event floods, or any write attempt block the stage.

**Tech Stack:** Python 3.11+, frozen/slotted dataclasses, `StrEnum`, `struct`, `select`, `time`, SHA-256, JSON, pytest, Ruff, mypy strict, Hatchling/uv. Standard library only; no `evdev`/`pyudev`/SDK dependencies.

## Global Constraints

- Sources of truth, in order: `tasks/prd-m2-n3-v3-hardware-controls.md` version 1.0 (M2-03 story, gate table, §11 测试策略), `docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md` (§5.4 `ReadOnlyInputHelper`, §9.1 G3 输入), and `docs/superpowers/plans/2026-08-04-m2-g2-minimal-permissions.md`.
- G3 sessions are read-only: the helper opens exactly one node `O_RDONLY`, sends no heartbeat, no feature/output report, no init, no refresh, no disconnect write, and never calls `EVIOCGRAB`. Any path that cannot prove zero writes blocks the stage — there is no fallback to legacy `open()` or the vendored SDK.
- The helper never imports `_vendor` or native transport, never opens more than one node, never reopens after disconnect, and performs zero automatic recovery writes. Replug starts a fresh M1+G1+G3 session.
- CI and automated tests never open `/dev`; the codec and session runner are tested with fixture byte streams and fault-injected file objects. The real-device session is an owner-gated manual action (temporary single-node ACL from the approved G2 plan, exact command/expectation/deadline/recovery presented before execution).
- The input key mapping of `6602:1000` is unvalidated. The session records observed `(type, code)` per control; a code that maps to more than one control, or a control with zero observations, blocks fail-closed instead of guessing.
- Unknown events are counted and classified only; raw payloads never leave the helper and never enter evidence.
- Evidence stays redacted: no serial, bus location, `/dev` node name, absolute path, username, raw event bytes, or image content. Mapping evidence records stable control/code pairs and digests.
- `6602:1000` remains an owner-reported candidate with unvalidated protocol; a successful G3 session validates inputs for this device/interface only and is not a general compatibility claim.
- The G0 dependency closure stays standard-library-only plus `streamdock_n3.device_catalog`; the fixed helper provenance (one literal `-I -m` subprocess.run in ipc.py) is preserved.
- Do not modify `src/streamdock_n3/_vendor`, `src/streamdock_n3/_data`, legacy daemon/probe/debug/GUI/install paths, or product ID activation tables.
- One task at a time with RED → observed expected failure → GREEN → focused regression → review → commit. No push, no publish, no GitHub mutation under this plan.

---

## File Map

- Modify `src/streamdock_n3/hardware/contracts.py`: `RawInputEvent`, `KeyMap`, `InputSessionSpec`, `InputSessionResult`, one new `ErrorCode`, and `StageManifest.session_spec`.
- Create `src/streamdock_n3/hardware/input_session.py`: pure evdev codec (`parse_raw_event`, `normalize_event`), `ReadOnlyInputBackend` (open `O_RDONLY`, bounded read loop, counts, latency, disconnect), and `run_input_session(spec, node, backend)` returning `InputSessionResult`.
- Modify `src/streamdock_n3/hardware/ipc.py`: session request/response wire types and codecs; preserve the single fixed `subprocess.run` and argv.
- Modify `src/streamdock_n3/hardware/helper_main.py`: dispatch `OBSERVE_INPUTS` sessions to `run_input_session` under `CommandPolicy` validation, returning the structured session result.
- Modify `src/streamdock_n3/hardware/adapter.py` and `gate.py`: G3 session-spec requirement, machine-backed settlement, `INPUT_VALIDATED` transition, and input-session evidence.
- Modify `src/streamdock_n3/hardware/evidence.py`: `EvidenceKind.INPUT_SESSION` with counts, p95 latency, unknown count, and disconnect flag (redacted).
- Modify `pyproject.toml`: add the `n3-ai-deck-observe-inputs` console entry point.
- Create `tests/test_hardware_input_codec.py`: raw parsing, key-map normalization, ambiguity.
- Create `tests/test_hardware_input_session.py`: bounded loop, deadline, counts, latency, disconnect, zero-write proof via fault injection.
- Modify `tests/test_hardware_ipc.py`, `tests/test_hardware_gate.py`, `tests/test_hardware_adapter.py`, `tests/test_hardware_evidence.py`, `tests/hardware_fixtures.py`.
- Modify `tests/test_hardware_g0_safety.py`: eleventh reviewed module, refreshed hashes, no-`/dev`/no-write static guards.
- Modify `tests/test_public_project.py`, `docs/ARCHITECTURE.md`, `ROADMAP.md`, `README.md`, `README.zh-CN.md`: G3 boundary and truthful status.

---

## Interface Ledger

The names in this ledger are authoritative across every task:

```python
@dataclass(frozen=True, slots=True)
class RawInputEvent:
    type: int
    code: int
    value: int
    monotonic_ns: int

@dataclass(frozen=True, slots=True)
class KeyMapEntry:
    event_type: int          # evdev event type (1 = EV_KEY)
    event_code: int          # evdev key/rel code
    control_id: int
    kind: InputKind          # BUTTON / KNOB_PRESS / KNOB_ROTATE
    press_action: InputAction  # PRESS for buttons; LEFT for knob rotation
    # action_for_value(value): PRESS/RELEASE for buttons; LEFT/RIGHT by sign for rotation

@dataclass(frozen=True, slots=True)
class KeyMap:
    entries: tuple[KeyMapEntry, ...]     # unique (event_type, event_code) pairs
    def lookup(self, raw: RawInputEvent) -> tuple[KeyMapEntry, InputAction] | None

@dataclass(frozen=True, slots=True)
class InputSessionSpec:
    duration_ms: int                     # bounded, <= MAX_DEADLINE_MS
    expected_press_count: int            # 10 per discrete control
    expected_rotation_count: int         # 20 per knob direction
    latency_p95_target_ms: int           # 250
    disconnect_grace_ms: int             # <= 2000
    key_map: KeyMap
    # digest() over a stable redacted summary

@dataclass(frozen=True, slots=True)
class InputSessionResult:
    counts: tuple[ControlCount, ...]     # per control observed counts
    latency_p95_ms: int
    unknown_count: int
    disconnected: bool
    mapping: tuple[ControlMapping, ...]  # observed (control -> type/code), redacted
    # meets_requirements(spec) -> bool; digest(); to_dict() redacted

@dataclass(frozen=True, slots=True)
class ControlCount:
    control_id: int
    press_count: int
    release_count: int
    left_count: int
    right_count: int

@dataclass(frozen=True, slots=True)
class ControlMapping:
    control_id: int
    kind: InputKind
    event_type: int
    event_code: int
```

New `ErrorCode`: `INPUT_SESSION_INVALID = "input_session_invalid"`.

`StageManifest` gains `session_spec: InputSessionSpec | None = None` (default `None` keeps G0–G2 fixtures valid; the G3 stage requires it, enforced by the gate).

`ReadOnlyInputBackend` protocol:

```python
class ReadOnlyInputBackend(Protocol):
    def open_read_only(self, node: str) -> InputFileHandle   # O_RDONLY only; raises on any other mode
    def read_events(self, handle: InputFileHandle, deadline_ns: int) -> Iterator[RawInputEvent]
    def close(self, handle: InputFileHandle) -> None
```

The real implementation opens with `os.open(node, os.O_RDONLY)` exactly once; tests inject fixture handles backed by bytes and raise on any write attempt.

Session result semantics:

- `meets_requirements()` is true iff: for every discrete control in the spec's key map, `press_count == expected_press_count` and `release_count == expected_press_count`; for every knob, `left_count >= expected_rotation_count`, `right_count >= expected_rotation_count`, and `press_count >= expected_press_count`; `latency_p95_ms <= latency_p95_target_ms`; `disconnected` is false; and `unknown_count` does not exceed the manifest's recorded limit.
- A control observed under more than one distinct `(type, code)` pair, or a code shared by two controls, blocks fail-closed (`INPUT_SESSION_INVALID`).
- On `O_RDONLY` open failure (permission) the session returns a classified `BACKEND_ERROR` with `ErrorCode.PERMISSION` guidance text (no auto-privilege); on read errors the session returns `DISCONNECTED` within `disconnect_grace_ms` and never reopens.

---

### Task 1: Raw Event Codec and Key-Map Normalization

**Files:**
- Modify: `src/streamdock_n3/hardware/contracts.py`
- Create: `src/streamdock_n3/hardware/input_session.py` (codec part only)
- Create: `tests/test_hardware_input_codec.py`
- Modify: `tests/test_hardware_contracts.py`

**Interfaces:**
- Produces: `RawInputEvent`, `KeyMapEntry`, `KeyMap`, `InputSessionSpec`, `INPUT_SESSION_INVALID`, `StageManifest.session_spec`, and the pure codec functions.

- [ ] **Step 1: Write codec RED tests**

Create `tests/test_hardware_input_codec.py`:

```python
def test_parse_raw_event_from_fixture_bytes() -> None:
    raw = parse_raw_event(struct.pack("qqHHi", 0, 123456, 1, 30, 1))
    assert raw.type == 1 and raw.code == 30 and raw.value == 1

def test_parse_rejects_short_and_misaligned_payloads() -> None:
    with pytest.raises(ValueError):
        parse_raw_event(b"\x00" * 15)

def test_key_map_lookup_maps_press_and_release() -> None:
    key_map = KeyMap((KeyMapEntry(1, InputKind.BUTTON, InputAction.PRESS),))
    press = key_map.lookup(RawInputEvent(1, 30, 1, 0))
    release = key_map.lookup(RawInputEvent(1, 30, 0, 0))
    assert press == (KeyMapEntry(1, InputKind.BUTTON, InputAction.PRESS), InputAction.PRESS)
    assert release[1] is InputAction.RELEASE

def test_key_map_lookup_rejects_duplicate_codes() -> None:
    with pytest.raises(ValueError):
        KeyMap((KeyMapEntry(1, InputKind.BUTTON, InputAction.PRESS),
                KeyMapEntry(2, InputKind.BUTTON, InputAction.PRESS)))

def test_knob_rotation_direction_is_inferred_from_value() -> None:
    entry = KeyMapEntry(1, InputKind.KNOB_ROTATE, InputAction.LEFT)
    assert entry.action_for_value(1) is InputAction.LEFT
    assert entry.action_for_value(-1) is InputAction.RIGHT

def test_normalize_event_returns_unknown_for_unmapped_codes() -> None:
    result = normalize_event(RawInputEvent(1, 999, 1, 0), KeyMap(()))
    assert result is None
```

Contract RED tests: `InputSessionSpec` rejects out-of-range durations/targets/grace and duplicate key-map codes; `StageManifest` accepts `session_spec=None` for existing stages and carries a spec for G3; `INPUT_SESSION_INVALID` value is `"input_session_invalid"`.

- [ ] **Step 2: Run codec tests and observe RED**

Run: `uv run pytest tests/test_hardware_input_codec.py tests/test_hardware_contracts.py -q`

- [ ] **Step 3: Implement the contracts and codec**

Add the ledger contracts to `contracts.py` (raw event parse is `struct`-based: `qqHHi` with Linux `input_event` layout — seconds, microseconds, type, code, value — plus a monotonic timestamp for latency measurement). Implement `parse_raw_event`, `KeyMap.lookup` (with `entry.action_for_value` for knob direction), and `normalize_event` in `input_session.py`. The codec imports only `struct`, `time`, and contracts.

- [ ] **Step 4: Run focused regressions and commit Task 1**

```bash
uv run pytest tests/test_hardware_input_codec.py tests/test_hardware_contracts.py tests/test_hardware_gate.py -q
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Commit: `feat: define raw input codec and key map normalization`.

---

### Task 2: Read-Only Input Backend and Bounded Session Runner

**Files:**
- Modify: `src/streamdock_n3/hardware/input_session.py`
- Create: `tests/test_hardware_input_session.py`

**Interfaces:**
- Produces: `ReadOnlyInputBackend` protocol, fixture-backed real backend, `ControlCount`/`ControlMapping`/`InputSessionResult`, and `run_input_session`.

- [ ] **Step 1: Write session RED tests**

- The real backend opens exactly one node with `os.O_RDONLY`; opening with any write flag raises.
- A fixture backend emits press/release/rotation sequences; `run_input_session` produces exact `ControlCount` values and `meets_requirements()` transitions from false to true as counts reach expectations.
- A fixture that raises `ENODEV` mid-stream produces `disconnected=True` with `latency` within `disconnect_grace_ms` and exactly zero write calls on the handle (fault injection records every method call).
- A deadline-expiring fixture (no events within `duration_ms`) ends the session with `TIMEOUT` classification and zero writes.
- Two controls observed under the same `(type, code)` pair produce `INPUT_SESSION_INVALID`.
- Latency: a fixture with a delayed read computes `latency_p95_ms` from read→normalize deltas; a session with p95 above target fails `meets_requirements()`.
- Zero-write proof: every fixture handle fails any `write`/`ioctl`-with-write call; the test asserts no write call occurred across all session paths.

- [ ] **Step 2: Run session tests and observe RED**

Run: `uv run pytest tests/test_hardware_input_session.py -q`

- [ ] **Step 3: Implement the session runner**

`run_input_session(spec, node, backend)`:
- opens exactly once with `O_RDONLY`; on failure returns a classified `BACKEND_ERROR` result with a redacted permission guidance flag (never auto-privileges);
- reads until `duration_ms` elapses or the deadline expires, using `select` on the handle with a bounded poll interval; each `read()` payload is parsed with the codec and normalized through `spec.key_map`;
- maintains per-control counts, mapping observations (first-seen `(type, code)` per control), unknown counts, and read→normalize latency samples;
- on `ENODEV`/`EIO`/read errors classifies `disconnected=True` within `disconnect_grace_ms`, closes the handle once, and never reopens;
- returns a frozen `InputSessionResult`; any inconsistency (shared codes, control with no observations) raises `INPUT_SESSION_INVALID`.

- [ ] **Step 4: Run focused regressions and commit Task 2**

```bash
uv run pytest tests/test_hardware_input_session.py tests/test_hardware_input_codec.py -q
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Commit: `feat: run bounded read-only input sessions`.

---

### Task 3: Session IPC and Fixed Helper Integration

**Files:**
- Modify: `src/streamdock_n3/hardware/ipc.py`
- Modify: `src/streamdock_n3/hardware/helper_main.py`
- Modify: `tests/test_hardware_ipc.py`
- Modify: `tests/test_hardware_g0_safety.py` (static provenance checks remain green)

**Interfaces:**
- Produces: `IpcSessionRequest`/`IpcSessionResponse` wire types, codecs, and the helper dispatch.

- [ ] **Step 1: Write IPC RED tests**

- `encode_session_request`/`decode_session_request` round-trip a request carrying the profile, capability, manifest, step index, command, `session_spec`, and `device_node`; the node field is validated as a plain `/dev/input/eventN` path and rejected otherwise.
- `encode_session_response`/`decode_session_response` round-trip an `InputSessionResult`; raw event bytes never appear in the wire text.
- `helper_main.main` with a session request runs exactly one session, emits one structured response, and never calls the write path.
- The static gates still pass: exactly one literal `-I -m` `subprocess.run` in ipc.py, `sys`/`subprocess` immutable, timeout guard unchanged.

- [ ] **Step 2: Run IPC tests and observe RED**

Run: `uv run pytest tests/test_hardware_ipc.py tests/test_hardware_g0_safety.py -q`

- [ ] **Step 3: Implement session IPC and dispatch**

Add the session request/response codecs beside the existing ones (same closed-key parsing helpers). In `helper_main`, after `CommandPolicy.validate`, dispatch: for `Operation.OBSERVE_INPUTS` with a session spec, run `run_input_session` with the real read-only backend and emit the session response; otherwise keep the existing FakeBackend path. Preserve the single fixed argv and the response framing.

- [ ] **Step 4: Run focused regressions and commit Task 3**

```bash
uv run pytest tests/test_hardware_ipc.py tests/test_hardware_g0_safety.py tests/test_hardware_input_session.py -q
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Commit: `feat: dispatch read-only input sessions through the fixed helper`.

---

### Task 4: G3 Gate, Input-Session Evidence, and Adapter Flow

**Files:**
- Modify: `src/streamdock_n3/hardware/gate.py`
- Modify: `src/streamdock_n3/hardware/evidence.py`
- Modify: `src/streamdock_n3/hardware/adapter.py`
- Modify: `tests/hardware_fixtures.py`
- Modify: `tests/test_hardware_gate.py`
- Modify: `tests/test_hardware_evidence.py`
- Modify: `tests/test_hardware_adapter.py`

**Interfaces:**
- Produces: G3 session-spec requirement, `EvidenceKind.INPUT_SESSION`, and machine-backed `INPUT_VALIDATED` settlement.

- [ ] **Step 1: Write gate, evidence, and adapter RED tests**

Gate:
- `begin` for `Stage.G3_INPUT` on a pinned gate requires `session_spec` (missing → `INPUT_SESSION_INVALID`, BLOCKED).
- A session whose result fails `meets_requirements()` never reaches `INPUT_VALIDATED` (preview yields BLOCKED); a meeting result reaches `INPUT_VALIDATED` only with `manual_confirmation`.

Evidence:
- `INPUT_SESSION` records carry counts, p95, unknown count, disconnect flag, and a mapping digest; reject payload fields; render redacted JSON (no node paths, no raw bytes).
- Adapter: G3 through `N3Adapter` with a meeting session result ends in `INPUT_VALIDATED`, records one `INPUT_SESSION` committed evidence; a throwing sink before the commit blocks the transition.

- [ ] **Step 2: Run gate, evidence, and adapter tests and observe RED**

Run: `uv run pytest tests/test_hardware_gate.py tests/test_hardware_evidence.py tests/test_hardware_adapter.py -q`

- [ ] **Step 3: Implement the G3 gate requirement**

In `begin`, when `manifest.stage is Stage.G3_INPUT`: require `manifest.session_spec` is not None and its key map is non-empty; otherwise `_block_and_clear()` + `INPUT_SESSION_INVALID`. Add the machine-result settlement path: the adapter passes the session result into settlement; `preview_completion` requires a meeting result for `INPUT_VALIDATED`.

- [ ] **Step 4: Implement input-session evidence**

Add `EvidenceKind.INPUT_SESSION`, the redacted fields (`control_counts` summary, `latency_p95_ms`, `unknown_count`, `disconnected`, `mapping_digest`), and `input_session_evidence(...)` with the same closed/redacted shape as the approval kinds. Extend the cross-kind digest rejections.

- [ ] **Step 5: Wire the adapter G3 path**

`execute` for `OBSERVE_INPUTS` uses the session helper (in-process for tests via the fixture backend; the fixed helper in production), records the `INPUT_SESSION` evidence before settlement, and settles machine-backed.

- [ ] **Step 6: Run focused regressions and commit Task 4**

```bash
uv run pytest tests/test_hardware_gate.py tests/test_hardware_evidence.py tests/test_hardware_adapter.py -q
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Commit: `feat: settle the G3 gate on machine-backed input sessions`.

---

### Task 5: Safety Closure, Public Truth, and Owner-Gated Real Session

**Files:**
- Modify: `src/streamdock_n3/hardware/input_session.py` (real backend finalization)
- Modify: `pyproject.toml` (console entry point)
- Modify: `tests/test_hardware_g0_safety.py`
- Modify: `tests/test_public_project.py`
- Modify: `docs/ARCHITECTURE.md`, `ROADMAP.md`, `README.md`, `README.zh-CN.md`
- Create: `docs/validation/2026-08-XX-g3-input-validation.md` (owner-gated run only)

**Interfaces:**
- Produces: eleventh reviewed module, static no-`/dev`/no-write guards, the `n3-ai-deck-observe-inputs` entry point, and the sanitized real-session record.

- [ ] **Step 1: Extend the reviewed closure and static guards**

Add `Path("src/streamdock_n3/hardware/input_session.py")` to `G0_MODULES`; update exact-closure tuples and counts. Add guards: no `/dev/input` root reads in tests, no `write`/`EVIOCGRAB`/`EVIOCS*` strings in session code, `os.open` only with `O_RDONLY` literal inside `ReadOnlyInputBackend`, no SDK imports. Refresh `REVIEWED_SOURCE_SHA256` (contracts, input_session, ipc, helper_main, adapter, gate, evidence, pyproject).

- [ ] **Step 2: Update public truth assertions**

Require: README/ARCHITECTURE describe G3 as bounded read-only input observation with zero writes; ROADMAP keeps G3 unchecked and states the real-device session and approval are owner-gated; `6602:1000` stays candidate/unvalidated; no supported/已支持 claim.

- [ ] **Step 3: Update docs**

ARCHITECTURE: implemented G3 boundary (read-only session, machine-backed settlement, disconnect semantics, redaction). ROADMAP: G3 bullet with the pending owner gate. READMEs: bilingual G3 wording.

- [ ] **Step 4: Owner-gated real-device session**

Only after the product owner explicitly approves this plan and the exact session command:

1. Verify the input node mapping read-only via sysfs (`n3-ai-deck-detect --json`); resolve the current node.
2. The owner applies the temporary single-node ACL from the approved G2 plan (or confirms existing read access); the helper fails closed with a redacted permission message otherwise.
3. Run the bounded session:

```bash
uv run n3-ai-deck-observe-inputs --json
```

with the owner executing the press protocol: LCD keys 1–6 and round buttons 7–9 at 10/10 press/release each, each knob 20 rotations per direction plus 10 presses, within the 10-minute window; the owner observes and confirms.

4. Record the sanitized validation record with date, commit, session duration, per-control counts, p95 latency, unknown count, disconnect observations, approval reference, and the zero-write statement. If counts are unmet, mapping is ambiguous, or the session disconnected, keep G3 BLOCKED and record the evidence requirement.

- [ ] **Step 5: Final verification**

```bash
uv run pytest
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
uv run mypy src/streamdock_n3        # only the recorded 11 legacy errors
uv build
git diff --check
git diff --name-only da721af..HEAD   # no _vendor/_data/legacy paths
```

- [ ] **Step 6: Request one independent whole-branch safety review**

Give the reviewer the M2 PRD, the M2 design, this plan, and the full branch diff. Require explicit findings for:

1. The helper opens exactly one node `O_RDONLY`, sends no writes/grab, and never loads the SDK; any non-read path fails closed.
2. Automated tests never open `/dev`; fixtures and fault injection cover timeout, crash, partial reads, and disconnect.
3. Disconnect is classified within the bounded grace with zero automatic recovery writes and no reopen.
4. Unknown events are counted only; raw payloads never leave the helper or enter evidence.
5. Key-map ambiguity and unmet counts block the gate machine-backed; no guessing fallback.
6. Session evidence is mandatory, redacted, and sink-failure-blocked.
7. Public truth keeps `6602:1000` candidate/unvalidated; G3 stays unchecked until the owner-gated session passes.
8. No SDK activation, `/dev` write, permission change, system mutation, hardware write, push, or publication occurred.

Expected: `APPROVED` with no Critical or Important findings.

- [ ] **Step 7: Record local progress and stop**

Write commit IDs, check results, full-package mypy baseline, and reviewer verdict into the ignored `.superpowers/sdd/progress.md`. Report completion locally and stop; do not push or publish.

---

## Completion Checklist

- [ ] The codec parses raw `input_event` bytes and normalizes through a configurable key map with knob-direction inference.
- [ ] The backend opens exactly one node `O_RDONLY`, runs a bounded select-based loop, and never writes or grabs.
- [ ] Sessions count per-control press/release/rotation, measure p95 read→normalize latency, and classify disconnect within the grace without reopening.
- [ ] Ambiguous mappings, shared codes, unmet counts, or unknown-event floods block fail-closed.
- [ ] The fixed `-I -m` helper provenance and closed JSON protocol are preserved.
- [ ] The G3 gate requires a session spec and settles machine-backed to `INPUT_VALIDATED`.
- [ ] Input-session evidence is mandatory, redacted, and sink-failure-blocked.
- [ ] Automated tests never open `/dev`; static guards prove zero-write session code.
- [ ] Public docs keep `6602:1000` candidate/unvalidated; G3 remains unchecked pending the owner-gated session.
- [ ] pytest, Ruff, strict G3 typing, full-package mypy baseline, build, diff check, and independent review pass.
- [ ] No `/dev` write, SDK load, permission change, hardware write, push, or publication occurred; the real session (if run) was owner-gated and sanitized.
