# M2 G0 Transactional Adapter Safety Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bypassable G0 live-gate flow with one fail-closed transactional `N3Adapter` that binds profile identity, enforces ordered forward/recovery work, records evidence before settlement, isolates the fake helper source, and never touches hardware.

**Architecture:** `N3Adapter` is the only public state coordinator and owns immutable profile/commit references, a private `_CapabilityGate`, one injected backend, and mandatory internal evidence. The gate reserves one exact ordered command, the Adapter executes the backend once, evidence accepts the attempt, and only then can the gate settle work or commit a stage; the fake helper uses a stateless `CommandPolicy` and cannot advance main-process state.

**Tech Stack:** Python 3.11+, frozen/slotted dataclasses, `StrEnum`, `Protocol`, SHA-256, JSON, base64, isolated `subprocess.run`, pytest, Ruff, mypy strict, Hatchling/uv.

## Global Constraints

- Sources of truth, in order: `tasks/prd-m2-n3-v3-hardware-controls.md` version 1.0, `docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md`, and `docs/superpowers/specs/2026-08-03-m2-g0-transactional-adapter-safety-design.md`.
- This is a breaking Early Preview safety change. Remove the old public live-gate and arbitrary-state APIs; do not add a compatibility shim.
- Implement G0 only. G1–G7 appear only as immutable FakeBackend manifests and state-machine tests.
- `6602:1000` remains a user-reported candidate with unvalidated protocol and no selected production interface. Do not claim compatibility.
- Never activate a profile, import or load the vendored SDK/native transport, enumerate or open `/dev`, install or edit udev/ACL/systemd state, run sudo, or write attached hardware.
- Do not modify `src/streamdock_n3/_vendor`, `src/streamdock_n3/_data`, legacy daemon/probe/debug/GUI/install paths, or product ID activation tables.
- The G0 production dependency graph remains standard-library-only except for safe M1 `streamdock_n3.device_catalog` contracts.
- `FakeBackend` remains the only G0 backend implementation. Do not add a real-backend stub with active dependencies.
- Evidence must exclude serials, bus locations, `/dev` names, usernames, absolute paths, raw payloads, image bytes, and image digests.
- There is exactly one pending reservation, no automatic backend/evidence/helper/recovery retries, and no automatic writes after disconnect or replug.
- Use one primary fix agent sequentially for Tasks 1–6 so one worker owns the state-machine contract. Fresh read-only reviewers may review each completed task and the final branch.
- Implement one task at a time with RED → observed expected failure → GREEN → focused regression → review → commit.
- Do not push, publish, create releases, or mutate GitHub state under this plan.

---

## File Map

- Modify `src/streamdock_n3/hardware/contracts.py`: ordered command steps, snapshots, phases, and stable safety error codes.
- Rewrite `src/streamdock_n3/hardware/gate.py`: private reservation/settlement state machine plus stateless helper policy.
- Modify `src/streamdock_n3/hardware/backend.py`: deterministic per-call scripted FakeBackend results for recovery testing.
- Rewrite `src/streamdock_n3/hardware/evidence.py`: mandatory internal attempt/commit/failure evidence transaction.
- Rewrite `src/streamdock_n3/hardware/adapter.py`: sole public coordinator with no live gate or arbitrary initial state.
- Modify `src/streamdock_n3/hardware/ipc.py`: closed snapshot-aware request schema and literal isolated helper argv.
- Modify `src/streamdock_n3/hardware/helper_main.py`: validate through `CommandPolicy`, execute FakeBackend once, return one result.
- Keep `src/streamdock_n3/hardware/__init__.py` inert and free of re-exports.
- Rewrite `tests/hardware_fixtures.py`: ordered G1–G7 forward/recovery manifests.
- Modify `tests/test_hardware_contracts.py`: new immutable contract and digest coverage.
- Rewrite `tests/test_hardware_gate.py`: reservation, binding, order, recovery, disconnect, and precommit tests.
- Modify `tests/test_hardware_fake_backend.py`: ordered per-call outcomes and zero-retry assertions.
- Rewrite `tests/test_hardware_evidence.py`: attempt/commit/failure and redaction tests.
- Rewrite `tests/test_hardware_adapter.py`: six blocker regressions and complete G1–G7 FakeBackend path.
- Modify `tests/test_hardware_ipc.py`: snapshot schema, policy checks, and cwd/`PYTHONPATH` shadowing tests.
- Modify `tests/test_hardware_g0_safety.py`: four-element isolated argv rule, removed mutable module symbol, and reviewed hashes.
- Modify `tests/test_public_project.py`: transactional architecture and truthful Early Preview assertions.
- Modify `docs/ARCHITECTURE.md`: document the implemented transactional G0 boundary only.
- Modify `ROADMAP.md`: link the approved safety revision without marking G1–G7 complete.
- Modify `docs/superpowers/plans/2026-08-03-m2-g0-safe-adapter-foundation.md`: retain the supersession warning added when this plan was authored.

## Interface Ledger

The names in this ledger are authoritative across every task:

```python
CommandSpec.from_command(command: AdapterCommand) -> CommandSpec
CommandSpec.matches(command: AdapterCommand) -> bool
CommandStep(forward: CommandSpec, recovery: CommandSpec | None = None)
StageManifest.steps: tuple[CommandStep, ...]

N3Adapter(
    profile: DeviceProfile,
    current_commit: str,
    backend: Backend,
    external_evidence: EvidenceSink | None = None,
)
N3Adapter.begin_stage(manifest: StageManifest) -> None
N3Adapter.execute(command: AdapterCommand) -> OperationResult
N3Adapter.recover(command: AdapterCommand) -> OperationResult
N3Adapter.complete_stage(
    manual_confirmation: bool,
    recovery_confirmation: bool | None = None,
) -> AdapterState
N3Adapter.disconnect() -> AdapterState
N3Adapter.state -> AdapterState
N3Adapter.profile -> DeviceProfile
N3Adapter.capability_snapshot -> CapabilitySnapshot
N3Adapter.session_snapshot -> StageSessionSnapshot | None
N3Adapter.evidence_records -> tuple[EvidenceRecord, ...]

CommandPolicy.validate(
    profile: DeviceProfile,
    capability: CapabilitySnapshot,
    manifest: StageManifest,
    step_index: int,
    command: AdapterCommand,
) -> None
```

Production code does not export `_CapabilityGate`, `_Reservation`, `_TransitionPreview`, internal evidence tokens, or backend references.

---

### Task 1: Ordered Immutable Contracts and Shared Fixtures

**Files:**
- Modify: `src/streamdock_n3/hardware/contracts.py`
- Modify: `tests/hardware_fixtures.py`
- Modify: `tests/test_hardware_contracts.py`

**Interfaces:**
- Consumes: existing safe `DeviceProfile`, `HidInterface`, `AdapterCommand`, `OperationResult`, `Stage`, and `AdapterState` values.
- Produces: `StagePhase`, `CommandSpec`, `CommandStep`, `CapabilitySnapshot`, `StageSessionSnapshot`, `StageManifest.steps`, and six new `ErrorCode` values.

- [ ] **Step 1: Replace rule-oriented tests with ordered contract tests**

Add these tests to `tests/test_hardware_contracts.py` and remove assertions for `CommandRule`, `min_calls`, `max_calls`, and `allowed_commands`:

```python
from dataclasses import FrozenInstanceError, replace

import pytest

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    CapabilitySnapshot,
    CommandSpec,
    CommandStep,
    ErrorCode,
    Operation,
    Stage,
    StagePhase,
    StageSessionSnapshot,
)
from tests.hardware_fixtures import TEST_IMAGE, make_manifest


def test_command_step_is_exact_ordered_and_frozen() -> None:
    forward = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE)
    recovery = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"baseline-1")
    step = CommandStep(CommandSpec.from_command(forward), CommandSpec.from_command(recovery))

    assert step.forward.matches(forward)
    assert step.recovery is not None and step.recovery.matches(recovery)
    assert step.forward.matches(recovery) is False
    with pytest.raises(FrozenInstanceError):
        step.forward = CommandSpec.from_command(recovery)  # type: ignore[misc]


def test_manifest_digest_preserves_repeated_steps_and_order() -> None:
    first = CommandStep(CommandSpec(Operation.SET_BRIGHTNESS, brightness=40))
    second = CommandStep(CommandSpec(Operation.SET_BRIGHTNESS, brightness=50))
    manifest = make_manifest(Stage.G5_BRIGHTNESS, steps=(first, second, first))

    assert len(manifest.steps) == 3
    assert manifest.digest() != replace(manifest, steps=(second, first, first)).digest()


def test_capability_and_session_snapshots_are_closed_immutable_values() -> None:
    capability = CapabilitySnapshot(
        state=AdapterState.CANDIDATE,
        profile_digest=None,
        bcd_device=None,
        interface=None,
        epoch=0,
        stage=Stage.G1_PROFILE,
        phase=StagePhase.FORWARD,
    )
    session = StageSessionSnapshot(Stage.G1_PROFILE, StagePhase.FORWARD, 0, 0, False)

    assert capability.profile_digest is None
    assert session.pending_reservation is False
    with pytest.raises(FrozenInstanceError):
        capability.epoch = 1  # type: ignore[misc]


def test_transaction_error_codes_are_stable() -> None:
    assert tuple(
        code.value
        for code in (
            ErrorCode.RESULT_MISSING,
            ErrorCode.PROFILE_MISMATCH,
            ErrorCode.ORDER_VIOLATION,
            ErrorCode.RECOVERY_REQUIRED,
            ErrorCode.STALE_RESERVATION,
            ErrorCode.EVIDENCE_FAILURE,
        )
    ) == (
        "result_missing",
        "profile_mismatch",
        "order_violation",
        "recovery_required",
        "stale_reservation",
        "evidence_failure",
    )
```

- [ ] **Step 2: Run the contract test and observe RED**

Run: `uv run pytest tests/test_hardware_contracts.py -q`

Expected: collection fails because `CommandSpec`, `CommandStep`, `StagePhase`, and snapshot contracts do not exist.

- [ ] **Step 3: Replace unordered rules with exact ordered contract values**

In `src/streamdock_n3/hardware/contracts.py`, retain existing scalar validators and replace `CommandRule` plus the old manifest field with these definitions:

```python
class StagePhase(StrEnum):
    FORWARD = "forward"
    RECOVERY = "recovery"
    READY = "ready"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    operation: Operation
    brightness: int | None = None
    key: int | None = None
    image_sha256: str | None = None

    def __post_init__(self) -> None:
        _validate_rule_shape(self.operation, self.brightness, self.key, self.image_sha256)

    @classmethod
    def from_command(cls, command: AdapterCommand) -> CommandSpec:
        if not isinstance(command, AdapterCommand):
            raise TypeError("command must be an AdapterCommand")
        return cls(command.operation, command.brightness, command.key, command.image_digest())

    def matches(self, command: AdapterCommand) -> bool:
        return isinstance(command, AdapterCommand) and self == CommandSpec.from_command(command)

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation.value,
            "brightness": self.brightness,
            "key": self.key,
            "image_sha256": self.image_sha256,
        }


@dataclass(frozen=True, slots=True)
class CommandStep:
    forward: CommandSpec
    recovery: CommandSpec | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.forward, CommandSpec):
            raise TypeError("forward must be a CommandSpec")
        if self.recovery is not None and not isinstance(self.recovery, CommandSpec):
            raise TypeError("recovery must be a CommandSpec or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "forward": self.forward.to_dict(),
            "recovery": self.recovery.to_dict() if self.recovery is not None else None,
        }
```

Add the six exact `ErrorCode` members from Step 1. Change `StageManifest.allowed_commands` to `steps: tuple[CommandStep, ...]`, require a non-empty tuple of `CommandStep`, allow repeated steps, serialize under the wire key `steps`, and include order in `digest()`.

Add these frozen snapshots with strict integer and all-or-none profile binding validation:

```python
@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    state: AdapterState
    profile_digest: str | None
    bcd_device: int | None
    interface: HidInterface | None
    epoch: int
    stage: Stage | None
    phase: StagePhase | None


@dataclass(frozen=True, slots=True)
class StageSessionSnapshot:
    stage: Stage
    phase: StagePhase
    forward_index: int
    recovery_remaining: int
    pending_reservation: bool
```

`CapabilitySnapshot` must reject partial profile bindings and require `stage is None` exactly when `phase is None`. `StageSessionSnapshot` must reject negative indexes/counts and non-`bool` pending flags.

- [ ] **Step 4: Rewrite fixtures as forward/recovery manifests**

Replace the rule helper and manifest factory in `tests/hardware_fixtures.py` with:

```python
def command_spec(command: AdapterCommand) -> CommandSpec:
    return CommandSpec.from_command(command)


def command_step(
    forward: AdapterCommand,
    recovery: AdapterCommand | None = None,
) -> CommandStep:
    return CommandStep(command_spec(forward), command_spec(recovery) if recovery is not None else None)


def make_manifest(
    stage: Stage,
    steps: tuple[CommandStep, ...] | None = None,
) -> StageManifest:
    defaults = {
        Stage.G1_PROFILE: (command_step(AdapterCommand(Operation.APPROVE_PROFILE)),),
        Stage.G2_PERMISSION: (command_step(AdapterCommand(Operation.RECORD_PERMISSION)),),
        Stage.G3_INPUT: (command_step(AdapterCommand(Operation.OBSERVE_INPUTS)),),
        Stage.G4_INITIALIZATION: (command_step(AdapterCommand(Operation.INITIALIZE)),),
        Stage.G5_BRIGHTNESS: (
            command_step(
                AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),
                AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50),
            ),
        ),
        Stage.G6_ONE_LCD: (
            command_step(
                AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE),
                AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"g0-baseline"),
            ),
        ),
        Stage.G7_SIX_LCD: tuple(
            command_step(
                AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"test-{key}".encode()),
                AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"base-{key}".encode()),
            )
            for key in range(1, 7)
        ),
    }
    return StageManifest(
        stage=stage,
        commit=TEST_COMMIT,
        profile_digest=make_profile().digest(),
        interface=TEST_INTERFACE,
        steps=steps if steps is not None else defaults[stage],
        deadline_ms=600_000 if stage is Stage.G3_INPUT else 5_000,
        expected_result=f"{stage.value}-validated",
        recovery_plan=f"{stage.value}-recovery",
        approval_reference=f"test:{stage.value}",
    )
```

- [ ] **Step 5: Run focused contract and fixture regressions**

Run: `uv run pytest tests/test_hardware_contracts.py tests/test_hardware_fake_backend.py -q`

Expected: contract tests pass; FakeBackend failures caused only by its remaining old fixture/API assumptions are carried into Task 4, with no contract validation failure.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/streamdock_n3/hardware/contracts.py tests/hardware_fixtures.py tests/test_hardware_contracts.py
git commit -m "refactor: define ordered adapter contracts"
```

---

### Task 2: Private Transactional Capability Gate and Stateless Policy

**Files:**
- Rewrite: `src/streamdock_n3/hardware/gate.py`
- Rewrite: `tests/test_hardware_gate.py`

**Interfaces:**
- Consumes: Task 1 `CommandStep`, snapshots, stage phases, result statuses, profile digest, and immutable manifests.
- Produces privately: `_CapabilityGate`, `_Reservation`, `_TransitionPreview`.
- Produces publicly for the helper only: `GateViolation` and stateless `CommandPolicy.validate(...)`.

- [ ] **Step 1: Write reservation and result-accounting RED tests**

Create direct unit tests against the private gate boundary:

```python
def test_reservation_does_not_count_as_success_without_a_result() -> None:
    gate = _CapabilityGate()
    manifest = make_manifest(Stage.G1_PROFILE)
    command = AdapterCommand(Operation.APPROVE_PROFILE)
    gate.begin(make_profile(), manifest, TEST_COMMIT)

    reservation = gate.reserve_forward(command)

    assert gate.state is AdapterState.CANDIDATE
    assert gate.session_snapshot == StageSessionSnapshot(
        Stage.G1_PROFILE, StagePhase.FORWARD, 0, 0, True
    )
    with pytest.raises(GateViolation) as raised:
        gate.preview_completion(True, None)
    assert raised.value.code is ErrorCode.RESULT_MISSING
    assert reservation.command == CommandSpec.from_command(command)


def test_only_the_exact_pending_reservation_can_settle() -> None:
    gate = _CapabilityGate()
    gate.begin(make_profile(), make_manifest(Stage.G1_PROFILE), TEST_COMMIT)
    reservation = gate.reserve_forward(AdapterCommand(Operation.APPROVE_PROFILE))
    stale = replace(reservation, epoch=reservation.epoch + 1)

    with pytest.raises(GateViolation) as raised:
        gate.settle(stale, OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0))

    assert raised.value.code is ErrorCode.STALE_RESERVATION
    assert gate.state is AdapterState.BLOCKED
```

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `uv run pytest tests/test_hardware_gate.py -q`

Expected: collection fails because the old public `CapabilityGate` has no reservation, snapshot, preview, or ordered recovery contract.

- [ ] **Step 3: Implement private state ownership and one-reservation settlement**

Replace the public gate with these exact private data boundaries and method signatures:

```python
@dataclass(frozen=True, slots=True)
class _Reservation:
    epoch: int
    phase: StagePhase
    step_index: int
    command: CommandSpec


@dataclass(frozen=True, slots=True)
class _TransitionPreview:
    epoch: int
    stage: Stage
    next_state: AdapterState
    recovery_status: RecoveryStatus


class _CapabilityGate:
    def __init__(self) -> None:
        self._state = AdapterState.CANDIDATE
        self._epoch = 0
        self._profile_digest: str | None = None
        self._bcd_device: int | None = None
        self._interface: HidInterface | None = None
        self._pinned_commit: str | None = None
        self._session_profile_bcd_device: int | None = None
        self._manifest: StageManifest | None = None
        self._phase: StagePhase | None = None
        self._forward_index = 0
        self._recovery: list[tuple[int, CommandSpec]] = []
        self._pending: _Reservation | None = None
        self._had_recovery = False
        self._recovery_machine_status = RecoveryStatus.NOT_REQUIRED
        self._committing = False

    @property
    def state(self) -> AdapterState:
        return self._state

    @property
    def capability_snapshot(self) -> CapabilitySnapshot:
        return CapabilitySnapshot(
            self._state,
            self._profile_digest,
            self._bcd_device,
            self._interface,
            self._epoch,
            self._manifest.stage if self._manifest is not None else None,
            self._phase,
        )

    @property
    def session_snapshot(self) -> StageSessionSnapshot | None:
        if self._manifest is None or self._phase is None:
            return None
        return StageSessionSnapshot(
            self._manifest.stage,
            self._phase,
            self._forward_index,
            len(self._recovery),
            self._pending is not None,
        )

    @property
    def active_manifest(self) -> StageManifest:
        return self._require_manifest()
```

Implement `begin`, `reserve_forward`, `reserve_recovery`, `settle`, `fail_evidence`, `block_reentrant`, `preview_completion`, `commit`, and `disconnect` with these rules:

```python
def begin(
    self,
    profile: DeviceProfile,
    manifest: StageManifest,
    current_commit: str,
) -> None:
    if self._manifest is not None or self._state in _TERMINAL_STATES:
        self._violate(ErrorCode.STATE_NOT_ALLOWED)
    transition = _TRANSITIONS.get(manifest.stage)
    if transition is None or transition[0] is not self._state:
        self._violate(ErrorCode.STATE_NOT_ALLOWED)
    identity_matches = (
        manifest.commit == current_commit
        and manifest.profile_digest == profile.digest()
        and manifest.interface == profile.interface
    )
    if self._profile_digest is None:
        if manifest.stage is not Stage.G1_PROFILE or not identity_matches:
            raise GateViolation(ErrorCode.MANIFEST_INVALID)
    elif not (
        identity_matches
        and self._profile_digest == profile.digest()
        and self._bcd_device == profile.bcd_device
        and self._interface == profile.interface
        and self._pinned_commit == current_commit
    ):
        self._block_and_clear()
        raise GateViolation(ErrorCode.PROFILE_MISMATCH)
    allowed = _STAGE_OPERATIONS[manifest.stage]
    specs = tuple(
        spec
        for step in manifest.steps
        for spec in (step.forward, step.recovery)
        if spec is not None
    )
    if any(spec.operation not in allowed for spec in specs):
        raise GateViolation(ErrorCode.MANIFEST_INVALID)
    if not any(step.forward.operation is _REQUIRED_OPERATION[manifest.stage] for step in manifest.steps):
        raise GateViolation(ErrorCode.MANIFEST_INVALID)
    self._epoch += 1
    self._manifest = manifest
    self._session_profile_bcd_device = profile.bcd_device
    self._phase = StagePhase.FORWARD
    self._forward_index = 0
    self._recovery = []
    self._pending = None
    self._had_recovery = False
    self._recovery_machine_status = RecoveryStatus.NOT_REQUIRED


def reserve_forward(self, command: AdapterCommand) -> _Reservation:
    manifest = self._require_session(StagePhase.FORWARD)
    self._require_no_pending()
    if self._forward_index >= len(manifest.steps):
        return self._violate(ErrorCode.ORDER_VIOLATION)
    expected = manifest.steps[self._forward_index].forward
    if not expected.matches(command):
        return self._violate(ErrorCode.ORDER_VIOLATION)
    reservation = _Reservation(
        self._epoch,
        StagePhase.FORWARD,
        self._forward_index,
        CommandSpec.from_command(command),
    )
    self._pending = reservation
    return reservation


def reserve_recovery(self, command: AdapterCommand) -> _Reservation:
    self._require_session(StagePhase.RECOVERY)
    self._require_no_pending()
    if not self._recovery:
        return self._violate(ErrorCode.RECOVERY_REQUIRED)
    step_index, expected = self._recovery[-1]
    if not expected.matches(command):
        return self._violate(ErrorCode.ORDER_VIOLATION)
    reservation = _Reservation(
        self._epoch,
        StagePhase.RECOVERY,
        step_index,
        CommandSpec.from_command(command),
    )
    self._pending = reservation
    return reservation


def settle(self, reservation: _Reservation, result: OperationResult) -> None:
    self._require_pending(reservation)
    self._pending = None
    if result.status is ResultStatus.DISCONNECTED:
        self.disconnect()
        return
    if not result.succeeded:
        self._settle_machine_failure(reservation.phase)
        return
    if reservation.phase is StagePhase.FORWARD:
        step = self._require_manifest().steps[reservation.step_index]
        self._forward_index += 1
        if step.recovery is not None:
            self._recovery.append((reservation.step_index, step.recovery))
            self._had_recovery = True
            self._recovery_machine_status = RecoveryStatus.SUCCEEDED
        if self._forward_index == len(self._require_manifest().steps):
            self._phase = StagePhase.RECOVERY if self._recovery else StagePhase.READY
        return
    self._recovery.pop()
    if not self._recovery:
        self._phase = StagePhase.READY


def preview_completion(
    self,
    manual_confirmation: bool,
    recovery_confirmation: bool | None,
) -> _TransitionPreview:
    if not isinstance(manual_confirmation, bool):
        raise GateViolation(ErrorCode.PARAMETER_NOT_ALLOWED)
    if recovery_confirmation is not None and not isinstance(recovery_confirmation, bool):
        raise GateViolation(ErrorCode.PARAMETER_NOT_ALLOWED)
    manifest = self._require_manifest()
    if self._pending is not None:
        raise GateViolation(ErrorCode.RESULT_MISSING)
    if self._phase is StagePhase.FORWARD:
        raise GateViolation(ErrorCode.RESULT_MISSING)
    if self._phase is StagePhase.RECOVERY:
        raise GateViolation(ErrorCode.RECOVERY_REQUIRED)
    if not self._had_recovery:
        if recovery_confirmation is not None:
            raise GateViolation(ErrorCode.PARAMETER_NOT_ALLOWED)
        recovery_status = RecoveryStatus.NOT_REQUIRED
    elif self._recovery_machine_status is RecoveryStatus.FAILED:
        recovery_status = RecoveryStatus.FAILED
    elif recovery_confirmation is True:
        recovery_status = RecoveryStatus.SUCCEEDED
    elif recovery_confirmation is False:
        recovery_status = RecoveryStatus.FAILED
    else:
        recovery_status = RecoveryStatus.UNKNOWN
    can_advance = (
        self._state is not AdapterState.BLOCKED
        and manual_confirmation
        and recovery_status in (RecoveryStatus.NOT_REQUIRED, RecoveryStatus.SUCCEEDED)
    )
    next_state = _TRANSITIONS[manifest.stage][1] if can_advance else AdapterState.BLOCKED
    return _TransitionPreview(self._epoch, manifest.stage, next_state, recovery_status)
```

`fail_evidence(reservation)` validates and clears the exact pending reservation, then calls `_settle_machine_failure(reservation.phase)`. Forward failure sets `BLOCKED`, cancels unexecuted forward steps, and retains only the recovery stack already earned by successful forward settlements. Recovery failure sets `RecoveryStatus.FAILED`, clears remaining recovery commands, and sets phase `READY`. `block_reentrant()` invalidates the current epoch, blocks the active session, and raises `GateViolation(ErrorCode.STALE_RESERVATION)`. `_violate()` blocks only after a session exists or after a pinned-profile integrity violation; malformed CANDIDATE/G1 input before session creation leaves state unchanged.

- [ ] **Step 4: Add binding, order, recovery, disconnect, and precommit tests**

Add these concrete cases to `tests/test_hardware_gate.py`:

```python
@pytest.mark.parametrize(
    ("profile", "manifest", "current_commit"),
    (
        (replace(make_profile(), bcd_device=0x0301), make_manifest(Stage.G2_PERMISSION), TEST_COMMIT),
        (
            replace(make_profile(), interface=HidInterface(1, 3, 1, 1)),
            make_manifest(Stage.G2_PERMISSION),
            TEST_COMMIT,
        ),
        (
            make_profile(),
            replace(make_manifest(Stage.G2_PERMISSION), profile_digest="0" * 64),
            TEST_COMMIT,
        ),
        (make_profile(), make_manifest(Stage.G2_PERMISSION), "fedcba9876543210"),
    ),
)
def test_g1_commit_pins_identity_and_later_drift_blocks(
    profile: DeviceProfile,
    manifest: StageManifest,
    current_commit: str,
) -> None:
    gate = advance_through_g1()

    with pytest.raises(GateViolation) as raised:
        gate.begin(profile, manifest, current_commit)

    assert raised.value.code is ErrorCode.PROFILE_MISMATCH
    assert gate.state is AdapterState.BLOCKED


def test_forward_and_recovery_are_exact_and_lifo() -> None:
    gate = advance_to(Stage.G7_SIX_LCD)
    manifest = make_manifest(Stage.G7_SIX_LCD)
    gate.begin(make_profile(), manifest, TEST_COMMIT)

    for key, _step in enumerate(manifest.steps, start=1):
        command = AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"test-{key}".encode())
        reservation = gate.reserve_forward(command)
        gate.settle(reservation, OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0))

    with pytest.raises(GateViolation) as raised:
        gate.reserve_recovery(
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"base-1")
        )
    assert raised.value.code is ErrorCode.ORDER_VIOLATION
    assert gate.state is AdapterState.BLOCKED


def test_disconnect_is_distinct_and_clears_all_queues() -> None:
    gate = _CapabilityGate()
    gate.begin(make_profile(), make_manifest(Stage.G1_PROFILE), TEST_COMMIT)
    reservation = gate.reserve_forward(AdapterCommand(Operation.APPROVE_PROFILE))

    gate.settle(
        reservation,
        OperationResult(ResultStatus.DISCONNECTED, ErrorCode.DEVICE_DISCONNECTED, 0),
    )

    assert gate.state is AdapterState.DISCONNECTED
    assert gate.session_snapshot is None


def test_precommit_callback_failure_never_advances_state() -> None:
    gate = ready_g1_gate()
    preview = gate.preview_completion(True, None)

    with pytest.raises(RuntimeError):
        gate.commit(preview, lambda: (_ for _ in ()).throw(RuntimeError("sink")))

    assert gate.state is AdapterState.BLOCKED
    assert gate.capability_snapshot.profile_digest is None
```

The local helpers `advance_through_g1()`, `advance_to(stage)`, and `ready_g1_gate()` must use real `begin` → reserve → successful result → preview → commit calls; they must not assign state or private counters.

- [ ] **Step 5: Implement profile pinning, preview, and private precommit**

Use this commit boundary:

```python
def commit(
    self,
    preview: _TransitionPreview,
    evidence_callback: Callable[[], None],
) -> AdapterState:
    if self._committing or preview.epoch != self._epoch:
        return self._violate(ErrorCode.STALE_RESERVATION)
    manifest = self._require_manifest()
    if preview.stage is not manifest.stage or self._phase is not StagePhase.READY:
        return self._violate(ErrorCode.STALE_RESERVATION)
    self._committing = True
    try:
        evidence_callback()
    except Exception:
        self._committing = False
        self._block_and_clear()
        raise
    self._committing = False
    if preview.epoch != self._epoch or self._state in _TERMINAL_STATES:
        return self._violate(ErrorCode.STALE_RESERVATION)
    if manifest.stage is Stage.G1_PROFILE and preview.next_state is AdapterState.PROFILE_APPROVED:
        self._profile_digest = manifest.profile_digest
        self._bcd_device = self._session_profile_bcd_device
        self._interface = manifest.interface
        self._pinned_commit = manifest.commit
    self._state = preview.next_state
    self._clear_session()
    self._epoch += 1
    return self._state
```

Store the validated G1 `bcdDevice` privately when the session begins. Revalidate the preview both before and after invoking the callback so a sink cannot catch its own reentrant violation and still permit advancement. Do not expose preview or commit through `N3Adapter` properties. If callback raises, preserve only the bounded recovery-only session when recovery is still safe; otherwise clear the session in `BLOCKED`.

- [ ] **Step 6: Implement stateless `CommandPolicy`**

Add a class with no instance state:

```python
class CommandPolicy:
    @staticmethod
    def validate(
        profile: DeviceProfile,
        capability: CapabilitySnapshot,
        manifest: StageManifest,
        step_index: int,
        command: AdapterCommand,
    ) -> None:
        if manifest.commit != profile.source_commit:
            raise GateViolation(ErrorCode.PROFILE_MISMATCH)
        if manifest.profile_digest != profile.digest() or manifest.interface != profile.interface:
            raise GateViolation(ErrorCode.PROFILE_MISMATCH)
        if capability.stage is not manifest.stage or capability.phase not in (
            StagePhase.FORWARD,
            StagePhase.RECOVERY,
        ):
            raise GateViolation(ErrorCode.ORDER_VIOLATION)
        if isinstance(step_index, bool) or not isinstance(step_index, int):
            raise GateViolation(ErrorCode.ORDER_VIOLATION)
        if not 0 <= step_index < len(manifest.steps):
            raise GateViolation(ErrorCode.ORDER_VIOLATION)
        step = manifest.steps[step_index]
        expected = step.forward if capability.phase is StagePhase.FORWARD else step.recovery
        if expected is None or not expected.matches(command):
            raise GateViolation(ErrorCode.ORDER_VIOLATION)
```

For capability states after G1, also require its pinned digest, `bcdDevice`, and interface to equal the profile and manifest. For CANDIDATE/G1, require all pinned fields to be `None`. This policy returns no state and accepts no reservation token.

- [ ] **Step 7: Run focused gate tests and strict typing**

Run: `uv run pytest tests/test_hardware_gate.py tests/test_hardware_contracts.py -q`

Expected: all tests pass.

Run: `uv run mypy --strict src/streamdock_n3/hardware/contracts.py src/streamdock_n3/hardware/gate.py`

Expected: success with no issues.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/streamdock_n3/hardware/gate.py tests/test_hardware_gate.py
git commit -m "refactor: make capability gate transactional"
```

---

### Task 3: Transactional Redacted Evidence

**Files:**
- Rewrite: `src/streamdock_n3/hardware/evidence.py`
- Rewrite: `tests/test_hardware_evidence.py`

**Interfaces:**
- Consumes: immutable profile, manifest, command, result, state, recovery, epoch, and error values.
- Produces: `EvidenceDisposition`, `EvidenceKind`, frozen `EvidenceRecord`, `EvidenceSink.record(record)`, mandatory `EvidenceRecorder`, and private `_EvidenceToken`.

- [ ] **Step 1: Write evidence attempt/commit/failure tests**

```python
def test_internal_record_moves_from_attempt_to_committed() -> None:
    recorder = EvidenceRecorder()
    record = operation_evidence(
        make_profile(),
        make_manifest(Stage.G1_PROFILE),
        AdapterCommand(Operation.APPROVE_PROFILE),
        OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0),
        epoch=1,
    )

    token = recorder.begin(record)
    assert recorder.records[-1].disposition is EvidenceDisposition.ATTEMPT
    recorder.commit(token)
    assert recorder.records[-1].disposition is EvidenceDisposition.COMMITTED


def test_failed_attempt_cannot_look_like_a_committed_transition() -> None:
    recorder = EvidenceRecorder()
    record = stage_evidence(
        make_profile(),
        make_manifest(Stage.G1_PROFILE),
        AdapterState.PROFILE_APPROVED,
        RecoveryStatus.NOT_REQUIRED,
        epoch=1,
    )

    token = recorder.begin(record)
    recorder.fail(token, ErrorCode.EVIDENCE_FAILURE)

    failed = recorder.records[-1]
    assert failed.disposition is EvidenceDisposition.FAILED
    assert failed.error_code is ErrorCode.EVIDENCE_FAILURE
    assert failed.adapter_state is AdapterState.PROFILE_APPROVED
```

- [ ] **Step 2: Run evidence tests and observe RED**

Run: `uv run pytest tests/test_hardware_evidence.py -q`

Expected: collection fails because evidence dispositions, transaction tokens, and record factories do not exist.

- [ ] **Step 3: Implement the closed evidence transaction**

Use these exact boundaries:

```python
class EvidenceDisposition(StrEnum):
    ATTEMPT = "attempt"
    COMMITTED = "committed"
    FAILED = "failed"


class EvidenceSink(Protocol):
    def record(self, record: EvidenceRecord) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _EvidenceToken:
    index: int
    epoch: int
    kind: EvidenceKind


class EvidenceRecorder:
    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    def begin(self, record: EvidenceRecord) -> _EvidenceToken:
        if record.disposition is not EvidenceDisposition.ATTEMPT:
            raise ValueError("evidence must begin as an attempt")
        token = _EvidenceToken(len(self._records), record.epoch, record.kind)
        self._records.append(record)
        return token

    def commit(self, token: _EvidenceToken) -> None:
        record = self._require_attempt(token)
        self._records[token.index] = replace(record, disposition=EvidenceDisposition.COMMITTED)

    def fail(self, token: _EvidenceToken, code: ErrorCode) -> None:
        record = self._require_attempt(token)
        self._records[token.index] = replace(
            record,
            disposition=EvidenceDisposition.FAILED,
            error_code=code,
        )
```

Add `epoch: int` and `disposition: EvidenceDisposition` to the closed JSON schema. `operation_evidence(...)` and `stage_evidence(...)` always construct `ATTEMPT` records. `_require_attempt` rejects wrong index, epoch, kind, duplicate commit, and duplicate failure with `ValueError("stale_evidence_token")`.

Operation records include only safe scalar metadata and payload size. Stage records include the proposed adapter state and Adapter-derived `RecoveryStatus`; their `ATTEMPT` disposition prevents an external sink write from representing a committed transition before the gate commits.

- [ ] **Step 4: Preserve deterministic JSON and privacy regression coverage**

Test exact key closure and scan rendered JSON:

```python
def test_json_remains_deterministic_closed_and_redacted() -> None:
    recorder = EvidenceRecorder()
    command = AdapterCommand(
        Operation.SET_KEY_IMAGE,
        key=1,
        image=b"serial=SECRET /home/user /dev/hidraw0 image-bytes",
    )
    record = operation_evidence(
        make_profile(),
        make_manifest(Stage.G6_ONE_LCD),
        command,
        OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0),
        epoch=8,
    )
    recorder.commit(recorder.begin(record))

    rendered = recorder.to_json()
    parsed = json.loads(rendered)
    assert rendered == json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    for forbidden in ("SECRET", "/home/user", "/dev/hidraw0", "image-bytes", command.image_digest()):
        assert forbidden not in rendered
```

- [ ] **Step 5: Run focused evidence tests and strict typing**

Run: `uv run pytest tests/test_hardware_evidence.py tests/test_hardware_contracts.py -q`

Expected: all tests pass.

Run: `uv run mypy --strict src/streamdock_n3/hardware/evidence.py`

Expected: success with no issues.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/streamdock_n3/hardware/evidence.py tests/test_hardware_evidence.py
git commit -m "feat: make adapter evidence transactional"
```

---

### Task 4: Sole-Coordinator Adapter, Scripted FakeBackend, and Six Blocker Regressions

**Files:**
- Modify: `src/streamdock_n3/hardware/backend.py`
- Rewrite: `src/streamdock_n3/hardware/adapter.py`
- Modify: `tests/test_hardware_fake_backend.py`
- Rewrite: `tests/test_hardware_adapter.py`

**Interfaces:**
- Consumes: Tasks 1–3 contracts, private gate, evidence recorder/sink, and existing `Backend.execute(command, manifest)` protocol.
- Produces: the exact public `N3Adapter` interface in the Interface Ledger and a deterministic per-call `FakeBackend(scripted_results=...)`.

- [ ] **Step 1: Write public API and missing-result RED tests**

```python
def test_adapter_has_no_live_gate_or_arbitrary_initial_state() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend())

    assert adapter.state is AdapterState.CANDIDATE
    assert not hasattr(adapter, "gate")
    assert not hasattr(adapter, "backend")
    with pytest.raises(AttributeError):
        adapter.profile = replace(make_profile(), bcd_device=0x0301)  # type: ignore[misc]
    with pytest.raises(TypeError):
        N3Adapter(  # type: ignore[call-arg]
            make_profile(),
            TEST_COMMIT,
            FakeBackend(),
            initial_state=AdapterState.SIX_LCD_VALIDATED,
        )


def test_complete_without_backend_result_cannot_advance() -> None:
    backend = FakeBackend()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))

    with pytest.raises(GateViolation) as raised:
        adapter.complete_stage(True)

    assert raised.value.code is ErrorCode.RESULT_MISSING
    assert adapter.state is AdapterState.CANDIDATE
    assert backend.calls == []
```

- [ ] **Step 2: Run adapter tests and observe RED**

Run: `uv run pytest tests/test_hardware_adapter.py tests/test_hardware_fake_backend.py -q`

Expected: failures show the old live `gate`, arbitrary `initial_state`, caller recovery enum, unordered accounting, and operation-keyed outcome behavior.

- [ ] **Step 3: Make FakeBackend deterministic per call**

Replace operation-keyed outcomes with an immutable copied result script:

```python
class FakeBackend:
    def __init__(
        self,
        events: tuple[NormalizedInputEvent, ...] = (),
        scripted_results: tuple[OperationResult, ...] = (),
    ) -> None:
        self._events = tuple(events)
        self._scripted_results = tuple(scripted_results)
        self._result_index = 0
        self.calls: list[BackendCall] = []

    def execute(self, command: AdapterCommand, manifest: StageManifest) -> OperationResult:
        del manifest
        self.calls.append(BackendCall.from_command(command))
        if self._result_index < len(self._scripted_results):
            result = self._scripted_results[self._result_index]
            self._result_index += 1
            return result
        events = self._events if command.operation is Operation.OBSERVE_INPUTS else ()
        return OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0, events)
```

`BackendCall.from_command()` must keep only operation, brightness, key, payload SHA-256, and payload size. Copy constructor inputs so later caller mutation cannot change outcomes. Never retry or loop inside `execute()`.

- [ ] **Step 4: Implement private ownership and execute/recover transactions**

Use constructor-owned private references and read-only properties:

```python
class N3Adapter:
    __slots__ = (
        "_profile",
        "_current_commit",
        "_backend",
        "_gate",
        "_evidence",
        "_external_evidence",
        "_busy",
    )

    def __init__(
        self,
        profile: DeviceProfile,
        current_commit: str,
        backend: Backend,
        external_evidence: EvidenceSink | None = None,
    ) -> None:
        self._profile = profile
        self._current_commit = current_commit
        self._backend = backend
        self._gate = _CapabilityGate()
        self._evidence = EvidenceRecorder()
        self._external_evidence = external_evidence
        self._busy = False

    @property
    def state(self) -> AdapterState:
        return self._gate.state

    @property
    def profile(self) -> DeviceProfile:
        return self._profile

    @property
    def capability_snapshot(self) -> CapabilitySnapshot:
        return self._gate.capability_snapshot

    @property
    def session_snapshot(self) -> StageSessionSnapshot | None:
        return self._gate.session_snapshot

    @property
    def evidence_records(self) -> tuple[EvidenceRecord, ...]:
        return self._evidence.records

    def begin_stage(self, manifest: StageManifest) -> None:
        self._enter()
        try:
            self._gate.begin(self._profile, manifest, self._current_commit)
        finally:
            self._leave()

    def execute(self, command: AdapterCommand) -> OperationResult:
        self._enter()
        try:
            return self._execute(command, recovery=False)
        finally:
            self._leave()

    def recover(self, command: AdapterCommand) -> OperationResult:
        self._enter()
        try:
            return self._execute(command, recovery=True)
        finally:
            self._leave()

    def disconnect(self) -> AdapterState:
        self._enter()
        try:
            return self._gate.disconnect()
        finally:
            self._leave()
```

`execute()` and `recover()` call a shared private `_execute(command, recovery: bool)` that performs exactly:

```python
reservation = (
    self._gate.reserve_recovery(command)
    if recovery
    else self._gate.reserve_forward(command)
)
manifest = self._gate.active_manifest
try:
    result = self._backend.execute(command, manifest)
except Exception:
    result = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)
if not isinstance(result, OperationResult):
    result = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.RESULT_MISSING, 0)
record = operation_evidence(
    self._profile,
    manifest,
    command,
    result,
    self._gate.capability_snapshot.epoch,
)
token = self._evidence.begin(record)
try:
    if self._external_evidence is not None:
        self._external_evidence.record(record)
except Exception:
    self._evidence.fail(token, ErrorCode.EVIDENCE_FAILURE)
    self._gate.fail_evidence(reservation)
    return OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.EVIDENCE_FAILURE, 0)
try:
    self._gate.settle(reservation, result)
except GateViolation as error:
    self._evidence.fail(token, error.code)
    raise
else:
    self._evidence.commit(token)
return result
```

Wrap every public mutation in a `_busy` guard. A reentrant call invokes `self._gate.block_reentrant()`, which marks the active gate `BLOCKED`, increments the epoch, and raises `GateViolation(ErrorCode.STALE_RESERVATION)`; outer settlement or post-callback validation must then fail stale instead of advancing.

Use this exact guard; do not use locks, threads, or retries in G0:

```python
def _enter(self) -> None:
    if self._busy:
        self._gate.block_reentrant()
    self._busy = True


def _leave(self) -> None:
    self._busy = False
```

- [ ] **Step 5: Implement stage evidence precommit and Adapter-derived recovery**

`complete_stage()` must not accept `RecoveryStatus`. It obtains the preview from the gate, creates an `ATTEMPT` stage record, and uses the external sink only inside the gate callback:

```python
def complete_stage(
    self,
    manual_confirmation: bool,
    recovery_confirmation: bool | None = None,
) -> AdapterState:
    self._enter()
    try:
        preview = self._gate.preview_completion(manual_confirmation, recovery_confirmation)
        record = stage_evidence(
            self._profile,
            self._gate.active_manifest,
            preview.next_state,
            preview.recovery_status,
            preview.epoch,
        )
        token = self._evidence.begin(record)

        def write_external_evidence() -> None:
            if self._external_evidence is not None:
                self._external_evidence.record(record)

        try:
            state = self._gate.commit(preview, write_external_evidence)
        except GateViolation as error:
            self._evidence.fail(token, error.code)
            raise
        except Exception:
            self._evidence.fail(token, ErrorCode.EVIDENCE_FAILURE)
            raise GateViolation(ErrorCode.EVIDENCE_FAILURE) from None
        else:
            self._evidence.commit(token)
        return state
    finally:
        self._leave()
```

Strictly reject non-`bool` manual confirmation and non-`bool`/`None` recovery confirmation without mutation. No-recovery stages require `None`. Stages with recovery require all machine recovery results plus `True`; `False` derives `FAILED`, `None` derives `UNKNOWN`, and neither advances.

- [ ] **Step 6: Add ordered recovery, failure, and disconnect regression tests**

```python
def test_g7_failure_cancels_forward_and_allows_only_lifo_recovery() -> None:
    failure = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)
    prior_stage_results = (success(),) * 8
    backend = FakeBackend(
        scripted_results=prior_stage_results
        + (success(), success(), failure, success(), success())
    )
    adapter = adapter_advanced_to(Stage.G7_SIX_LCD, backend)
    manifest = make_manifest(Stage.G7_SIX_LCD)
    adapter.begin_stage(manifest)

    assert adapter.execute(image_command(1, "test")).succeeded
    assert adapter.execute(image_command(2, "test")).succeeded
    assert not adapter.execute(image_command(3, "test")).succeeded
    assert adapter.state is AdapterState.BLOCKED
    with pytest.raises(GateViolation) as raised:
        adapter.execute(image_command(4, "test"))
    assert raised.value.code is ErrorCode.ORDER_VIOLATION

    assert adapter.recover(image_command(2, "base")).succeeded
    assert adapter.recover(image_command(1, "base")).succeeded
    assert adapter.complete_stage(True, True) is AdapterState.BLOCKED
    assert [call.key for call in backend.calls[-5:]] == [1, 2, 3, 2, 1]


def test_recovery_failure_stops_remaining_recovery_and_never_advances() -> None:
    prior_stage_results = (success(),) * 8
    backend = FakeBackend(
        scripted_results=prior_stage_results + (success(), success(), backend_failure())
    )
    adapter = adapter_advanced_to(Stage.G7_SIX_LCD, backend)
    adapter.begin_stage(make_manifest(Stage.G7_SIX_LCD))
    adapter.execute(image_command(1, "test"))
    adapter.execute(image_command(2, "test"))

    assert not adapter.recover(image_command(2, "base")).succeeded
    with pytest.raises(GateViolation):
        adapter.recover(image_command(1, "base"))
    assert adapter.complete_stage(True, False) is AdapterState.BLOCKED


def test_unknown_recovery_confirmation_never_advances() -> None:
    adapter = adapter_advanced_to(Stage.G5_BRIGHTNESS, FakeBackend())
    manifest = make_manifest(Stage.G5_BRIGHTNESS)
    adapter.begin_stage(manifest)
    adapter.execute(AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40))
    adapter.recover(AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50))

    assert adapter.complete_stage(True, None) is AdapterState.BLOCKED


def test_backend_disconnect_is_disconnected_and_never_recovers() -> None:
    disconnected = OperationResult(
        ResultStatus.DISCONNECTED,
        ErrorCode.DEVICE_DISCONNECTED,
        0,
    )
    backend = FakeBackend(scripted_results=(disconnected,))
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))

    assert adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE)) == disconnected
    assert adapter.state is AdapterState.DISCONNECTED
    assert adapter.session_snapshot is None
    assert len(backend.calls) == 1
```

- [ ] **Step 7: Add evidence failure and full G1–G7 regressions**

Use a sink that raises and prove no transition:

```python
class ThrowingSink:
    def record(self, record: EvidenceRecord) -> None:
        del record
        raise RuntimeError("private sink failure")


def test_throwing_sink_blocks_before_operation_or_stage_advancement() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend(), ThrowingSink())
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))

    result = adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert result.error_code is ErrorCode.EVIDENCE_FAILURE
    assert adapter.state is AdapterState.BLOCKED
    assert adapter.evidence_records[-1].disposition is EvidenceDisposition.FAILED


class SecondWriteThrowingSink:
    def __init__(self) -> None:
        self.calls = 0

    def record(self, record: EvidenceRecord) -> None:
        del record
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("stage sink failure")


def test_stage_sink_failure_occurs_before_profile_commit() -> None:
    sink = SecondWriteThrowingSink()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend(), sink)
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))
    assert adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE)).succeeded

    with pytest.raises(GateViolation) as raised:
        adapter.complete_stage(True)

    assert raised.value.code is ErrorCode.EVIDENCE_FAILURE
    assert adapter.state is AdapterState.BLOCKED
    assert adapter.capability_snapshot.profile_digest is None
    assert adapter.evidence_records[-1].disposition is EvidenceDisposition.FAILED
```

Build the normal path only through public Adapter calls:

```python
def test_adapter_advances_g1_to_g7_with_ordered_recovery() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend())

    for stage in stages_g1_to_g7():
        manifest = make_manifest(stage)
        adapter.begin_stage(manifest)
        for step in manifest.steps:
            assert adapter.execute(command_for(step.forward)).succeeded
        for step in reversed(manifest.steps):
            if step.recovery is not None:
                assert adapter.recover(command_for(step.recovery)).succeeded
        recovery_confirmation = True if any(step.recovery for step in manifest.steps) else None
        adapter.complete_stage(True, recovery_confirmation)

    assert adapter.state is AdapterState.SIX_LCD_VALIDATED
```

Also retain tests for backend exception normalization, non-contract result normalization, immutable snapshots, construction without backend work, no backend call before `begin_stage`, and no backend retry.

- [ ] **Step 8: Run the complete in-process transactional suite**

Run: `uv run pytest tests/test_hardware_contracts.py tests/test_hardware_gate.py tests/test_hardware_fake_backend.py tests/test_hardware_evidence.py tests/test_hardware_adapter.py -q`

Expected: all tests pass.

Run: `uv run mypy --strict src/streamdock_n3/hardware/contracts.py src/streamdock_n3/hardware/gate.py src/streamdock_n3/hardware/backend.py src/streamdock_n3/hardware/evidence.py src/streamdock_n3/hardware/adapter.py`

Expected: success with no issues.

- [ ] **Step 9: Commit Task 4**

```bash
git add src/streamdock_n3/hardware/backend.py src/streamdock_n3/hardware/adapter.py tests/test_hardware_fake_backend.py tests/test_hardware_adapter.py
git commit -m "fix: coordinate adapter transactions end to end"
```

---

### Task 5: Snapshot-Aware IPC and Isolated Fixed Helper

**Files:**
- Modify: `src/streamdock_n3/hardware/ipc.py`
- Modify: `src/streamdock_n3/hardware/helper_main.py`
- Modify: `tests/test_hardware_ipc.py`
- Modify: `tests/test_hardware_g0_safety.py`

**Interfaces:**
- Consumes: `CapabilitySnapshot`, ordered manifests, `CommandPolicy`, and FakeBackend.
- Produces: `IpcRequest(profile, capability, manifest, step_index, command)` and fixed `[sys.executable, "-I", "-m", "streamdock_n3.hardware.helper_main"]` execution.

- [ ] **Step 1: Write closed snapshot request RED tests**

```python
def valid_request() -> IpcRequest:
    return IpcRequest(
        profile=make_profile(),
        capability=CapabilitySnapshot(
            AdapterState.CANDIDATE,
            None,
            None,
            None,
            1,
            Stage.G1_PROFILE,
            StagePhase.FORWARD,
        ),
        manifest=make_manifest(Stage.G1_PROFILE),
        step_index=0,
        command=AdapterCommand(Operation.APPROVE_PROFILE),
    )


def test_request_contains_snapshot_and_no_authority_token() -> None:
    wire = json.loads(encode_request(valid_request()))

    assert set(wire) == {
        "schema_version",
        "profile",
        "capability",
        "manifest",
        "step_index",
        "command",
    }
    assert set(wire["capability"]) == {
        "state",
        "profile_digest",
        "bcd_device",
        "interface",
        "epoch",
        "stage",
        "phase",
    }
    assert "reservation" not in encode_request(valid_request())
    assert decode_request(encode_request(valid_request())) == valid_request()
```

- [ ] **Step 2: Write exact isolated argv and shadow-package RED tests**

```python
def test_fake_helper_call_uses_literal_isolated_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, encode_response(success()) + "\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_fake_helper(valid_request(), 100).succeeded
    assert calls == [[
        sys.executable,
        "-I",
        "-m",
        "streamdock_n3.hardware.helper_main",
    ]]


def test_helper_ignores_cwd_and_pythonpath_shadow_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shadow = tmp_path / "streamdock_n3" / "hardware"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "helper_main.py").write_text(
        "raise SystemExit('shadow-helper-executed')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    assert run_fake_helper(valid_request(), 5_000).succeeded
```

The test writes only inside pytest's temporary directory and invokes only the audited fake helper; it does not enumerate or access hardware.

- [ ] **Step 3: Run IPC tests and observe RED**

Run: `uv run pytest tests/test_hardware_ipc.py -q`

Expected: failures show the old `state` request field, `CommandRule` wire schema, mutable `HELPER_MODULE`, three-element argv, and helper-owned live gate.

- [ ] **Step 4: Replace the IPC request and ordered manifest wire schema**

Use exact closed keys:

```python
_REQUEST_KEYS = frozenset(
    {"schema_version", "profile", "capability", "manifest", "step_index", "command"}
)
_CAPABILITY_KEYS = frozenset(
    {"state", "profile_digest", "bcd_device", "interface", "epoch", "stage", "phase"}
)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "stage",
        "commit",
        "profile_digest",
        "interface",
        "steps",
        "deadline_ms",
        "expected_result",
        "recovery_plan",
        "approval_reference",
    }
)
_STEP_KEYS = frozenset({"forward", "recovery"})
_SPEC_KEYS = frozenset({"operation", "brightness", "key", "image_sha256"})
```

Define:

```python
@dataclass(frozen=True, slots=True)
class IpcRequest:
    profile: DeviceProfile
    capability: CapabilitySnapshot
    manifest: StageManifest
    step_index: int
    command: AdapterCommand
    schema_version: int = SCHEMA_VERSION
```

Encode/decode optional pinned fields as JSON `null` before G1 and exact validated scalar/interface values after G1. Keep duplicate-key rejection, canonical compact JSON, 1 MiB image bound, total request/response bounds, strict enum/version parsing, and one-line LF framing.

- [ ] **Step 5: Make helper policy stateless and runner provenance literal**

Replace helper execution logic with:

```python
request = decode_request(payload)
CommandPolicy.validate(
    request.profile,
    request.capability,
    request.manifest,
    request.step_index,
    request.command,
)
result = FakeBackend().execute(request.command, request.manifest)
return result
```

Remove every import and construction of `_CapabilityGate`/`CapabilityGate` from `helper_main.py`. In `run_fake_helper`, delete `HELPER_MODULE` and use only:

```python
completed = subprocess.run(
    [sys.executable, "-I", "-m", "streamdock_n3.hardware.helper_main"],
    input=encode_request(request) + "\n",
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="strict",
    check=False,
    timeout=timeout_ms / 1000,
)
```

Retain the exact immutable timeout guard and stable timeout/crash/invalid-response mappings. Do not add `cwd`, `env`, `shell`, executable overrides, or retry options.

- [ ] **Step 6: Update the static fixed-helper proof**

In `tests/test_hardware_g0_safety.py`:

```python
PROTECTED_SYMBOLS = {"subprocess", "sys"}


def _fixed_argv(call: ast.Call, bindings: dict[str, set[str]]) -> bool:
    if len(call.args) != 1 or not isinstance(call.args[0], (ast.List, ast.Tuple)):
        return False
    value = call.args[0]
    return (
        len(value.elts) == 4
        and _canonical_names(value.elts[0], bindings) == {"sys.executable"}
        and _literal(value.elts[1], "-I")
        and _literal(value.elts[2], "-m")
        and _literal(value.elts[3], "streamdock_n3.hardware.helper_main")
    )
```

Delete the `HELPER_MODULE` assignment/immutability branch from `_fixed_helper_violations`. Keep the exact single `subprocess.run`, import provenance, closed kwargs, bounded timeout, no-shell, source closure, import-time, and dynamic-resolution protections.

- [ ] **Step 7: Run IPC, helper, and static regressions**

Run: `uv run pytest tests/test_hardware_ipc.py tests/test_hardware_g0_safety.py -q`

Expected: all runtime/static tests pass except reviewed SHA-256 assertions, whose production-file digest updates are intentionally performed after final code review in Task 6.

Run: `uv run mypy --strict src/streamdock_n3/hardware/ipc.py src/streamdock_n3/hardware/helper_main.py`

Expected: success with no issues.

- [ ] **Step 8: Commit Task 5**

```bash
git add src/streamdock_n3/hardware/ipc.py src/streamdock_n3/hardware/helper_main.py tests/test_hardware_ipc.py tests/test_hardware_g0_safety.py
git commit -m "fix: isolate transactional fake helper policy"
```

---

### Task 6: Safety Closure, Public Truth, and Regression Completion

**Files:**
- Modify: `tests/test_hardware_g0_safety.py`
- Modify: `tests/test_public_project.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `ROADMAP.md`

**Interfaces:**
- Consumes: the reviewed final bytes and public behavior from Tasks 1–5.
- Produces: closed source/wheel review digests and truthful documentation of the transactional G0 foundation.

- [ ] **Step 1: Run the complete test suite before updating reviewed hashes**

Run: `uv run pytest -q`

Expected: behavioral tests pass; only assertions that intentionally pin the pre-hardening `REVIEWED_SOURCE_SHA256` values may fail.

- [ ] **Step 2: Review every changed G0 source byte before accepting new hashes**

Run:

```bash
git diff c72f157 -- src/streamdock_n3/hardware tests/test_hardware_contracts.py tests/test_hardware_gate.py tests/test_hardware_fake_backend.py tests/test_hardware_evidence.py tests/test_hardware_adapter.py tests/test_hardware_ipc.py tests/test_hardware_g0_safety.py
```

Expected review result: no live gate, arbitrary `initial_state`, caller `RecoveryStatus`, unordered `CommandRule`, mutable helper module, SDK/native import, `/dev` access, system mutation, retry, raw write, or post-transition external evidence call.

- [ ] **Step 3: Update reviewed source SHA-256 values only after review**

Run:

```bash
sha256sum src/streamdock_n3/hardware/__init__.py src/streamdock_n3/hardware/contracts.py src/streamdock_n3/hardware/gate.py src/streamdock_n3/hardware/backend.py src/streamdock_n3/hardware/adapter.py src/streamdock_n3/hardware/ipc.py src/streamdock_n3/hardware/helper_main.py src/streamdock_n3/hardware/evidence.py src/streamdock_n3/__init__.py src/streamdock_n3/device_catalog.py src/streamdock_n3/_vendor/StreamDock/ProductIDs.py src/streamdock_n3/_data/99-streamdock.rules pyproject.toml
```

Copy those 13 lowercase 64-character digests into the matching `REVIEWED_SOURCE_SHA256` entries. Do not change the reviewed path set, source closure, wheel closure, or forbidden gates. Re-run `uv run pytest tests/test_hardware_g0_safety.py -q`; expected: all tests pass.

- [ ] **Step 4: Update public architecture assertions first**

Change `tests/test_public_project.py` to require this exact flow:

```text
N3Adapter transaction coordinator
  -> private capability reservation
  -> FakeBackend exactly once
  -> redacted evidence acceptance
  -> private settlement / stage commit

fake-only isolated helper process
  -> stateless CommandPolicy
  -> FakeBackend exactly once
  -> OperationResult only
```

Assert the public files still contain `does not activate \`6602:1000\``, `candidate`, `unvalidated`, and `active hardware stages G1–G7 remain planned M2 work`. Assert they do not contain a supported/已支持 claim for `6602:1000`.

- [ ] **Step 5: Run public assertions and observe RED**

Run: `uv run pytest tests/test_public_project.py -q`

Expected: architecture flow assertions fail because the docs still describe the superseded live `CapabilityGate` helper path.

- [ ] **Step 6: Update architecture and roadmap truthfully**

Replace only the implemented G0 flow in `docs/ARCHITECTURE.md` with the exact text from Step 4. Add links in `ROADMAP.md` to:

```text
docs/superpowers/specs/2026-08-03-m2-g0-transactional-adapter-safety-design.md
docs/superpowers/plans/2026-08-03-m2-g0-transactional-adapter-safety-hardening.md
```

Describe G0 as a hardware-free transactional simulation foundation. Keep G1 profile/interface, G2 permissions, and G3–G7 physical validation unchecked. State that helper snapshots are validation context, not state authority.

- [ ] **Step 7: Run focused public and safety regression**

Run: `uv run pytest tests/test_public_project.py tests/test_hardware_g0_safety.py -q`

Expected: all tests pass.

- [ ] **Step 8: Run final lint and strict G0 types before commit**

Run: `uv run ruff check .`

Expected: all checks pass.

Run: `uv run mypy --strict src/streamdock_n3/hardware`

Expected: success with no issues in all eight G0 source files.

- [ ] **Step 9: Commit Task 6**

```bash
git add tests/test_hardware_g0_safety.py tests/test_public_project.py docs/ARCHITECTURE.md ROADMAP.md
git commit -m "docs: publish transactional G0 safety boundary"
```

---

### Task 7: Final Verification and Independent Whole-Branch Review

**Files:**
- Verify only; do not change production behavior during this task.
- Update ignored local ledger only: `.superpowers/sdd/progress.md`.

**Interfaces:**
- Consumes: committed Tasks 1–6.
- Produces: verification evidence and an independent `APPROVED` or actionable review report.

- [ ] **Step 1: Run all required repository checks**

Run separately:

```bash
uv run pytest
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
uv run mypy src/streamdock_n3
uv build
git diff --check
git status --short --branch
```

Expected:

- pytest passes.
- Ruff passes.
- strict hardware mypy passes for all eight hardware modules.
- full-package mypy is executed and may report only the already-recorded 11 unchanged legacy errors in `gui.py`, `probe.py`, `debug_tool.py`, and `daemon.py`; any new location or changed count blocks completion.
- wheel and sdist build successfully.
- diff check is clean.
- only intentional committed branch changes are present; ignored progress tracking is not staged.

- [ ] **Step 2: Verify forbidden paths and hardware isolation from the branch diff**

Run:

```bash
git diff --name-only da721af..HEAD
git diff -- src/streamdock_n3/_vendor src/streamdock_n3/_data src/streamdock_n3/daemon.py src/streamdock_n3/probe.py src/streamdock_n3/debug_tool.py src/streamdock_n3/gui.py src/streamdock_n3/system_install.py
```

Expected: the second command prints no diff. No command in this plan has accessed a device node, activated the SDK, changed udev, installed system files, or written hardware.

- [ ] **Step 3: Request one independent whole-branch safety review**

Give the reviewer the approved PRD, formal design, transactional safety design, this plan, and the full diff `da721af..HEAD`. Require explicit findings for:

```text
1. no result/evidence bypass to stage advancement
2. profile/commit/bcdDevice/interface pinning
3. exact forward order and bounded LIFO recovery
4. DISCONNECTED classification and zero automatic recovery writes
5. literal -I helper provenance and stateless policy
6. evidence failure/reentrancy before settlement or stage commit
7. public candidate/unvalidated truth
8. no SDK, /dev, udev, sudo, system install, or hardware write
```

Expected: `APPROVED` with no Critical or Important findings. If findings exist, return to the owning task, add a failing regression, implement the smallest fix, rerun that task and all final checks, commit the fix, and request a fresh whole-branch review.

- [ ] **Step 4: Update local progress and stop before external actions**

Record commit IDs, check results, full-package mypy baseline, and reviewer verdict in `.superpowers/sdd/progress.md`. Do not stage that ignored file. Report completion locally and stop; do not push or publish.

---

## Completion Checklist

- [ ] All six original whole-branch blockers have a regression that failed before its fix and passes after it.
- [ ] The only public coordinator is `N3Adapter`; no live gate or arbitrary initial state is exposed.
- [ ] Profile identity and interface are pinned at G1 and drift fails closed.
- [ ] Forward and recovery work is exact, ordered, bounded, and machine-result-backed.
- [ ] A missing result, stale reservation, reentrancy, or evidence failure cannot advance state.
- [ ] Backend disconnect maps to `DISCONNECTED`, clears queues, and causes zero automatic recovery writes.
- [ ] The fake helper uses literal `-I -m`, ignores cwd/`PYTHONPATH` shadow packages, and cannot advance Adapter state.
- [ ] Internal evidence is mandatory, immutable to callers, deterministic, and redacted.
- [ ] G0 source/import/runtime/wheel isolation gates pass without weakening their coverage.
- [ ] Public docs still describe `6602:1000` as candidate/unvalidated and G1–G7 as unimplemented physical validation.
- [ ] Required tests, lint, strict G0 typing, full-package mypy baseline check, build, diff check, and independent review are recorded.
- [ ] No SDK activation, `/dev` access, udev/ACL/system change, hardware write, push, or publication occurred.
