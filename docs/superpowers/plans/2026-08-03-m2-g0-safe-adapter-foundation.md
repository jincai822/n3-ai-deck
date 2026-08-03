# M2 G0 Safe Adapter Foundation Implementation Plan

> [!WARNING]
> This historical plan is superseded where it conflicts with
> `docs/superpowers/specs/2026-08-03-m2-g0-transactional-adapter-safety-design.md` and
> `docs/superpowers/plans/2026-08-03-m2-g0-transactional-adapter-safety-hardening.md`.
> Do not execute its public live-gate, arbitrary `initial_state`, unordered `CommandRule`,
> caller-supplied `RecoveryStatus`, mutable `HELPER_MODULE`, or post-transition evidence steps.
> Preserve it only as the implementation history for the original G0 foundation.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the hardware-free G0 foundation for the M2 N3 Adapter: immutable contracts, a fail-closed capability gate, a deterministic FakeBackend, adapter orchestration, fake-only process isolation, and redacted evidence without activating `6602:1000` or touching hardware.

**Architecture:** Add a new standard-library-only `streamdock_n3.hardware` package that is independent of the vendored SDK and legacy event module. The main-process `N3Adapter` owns stage state and validates immutable manifests; an injected backend performs only allowlisted typed commands. G0 supplies only `FakeBackend` and a fake-only subprocess harness, so every transition, failure, timeout, disconnect, and privacy rule is testable before G1 chooses an interface or any real backend exists.

**Tech Stack:** Python 3.11+, frozen/slotted dataclasses, `StrEnum`, `Protocol`, SHA-256, JSON, base64, subprocess with fixed argv and `shell=False`, pytest, Ruff, mypy strict, Hatchling/uv.

## Global Constraints

- The approved sources of truth are `tasks/prd-m2-n3-v3-hardware-controls.md` version 1.0 and `docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md`.
- This plan implements G0 only. Tests may exercise G1–G7 transition rules with clearly test-only manifests, but they do not create or persist a real approval, active profile, permission, or device session.
- Never add `6602:1000` to `ProductIDs.g_products`, a production active-profile registry, daemon, probe, debug tool, GUI, or service.
- Never import or load `streamdock_n3._vendor`, `DeviceManager`, `LibUSBHIDAPI`, native `.so`/`.dll`/`.dylib`, `ctypes`, `evdev`, `pyudev`, or GTK from the G0 production dependency graph.
- Never enumerate, open, read, or write `/dev/hidraw*`, `/dev/input/event*`, or any other `/dev` node.
- Never run sudo, setfacl, udevadm, systemctl, an installer, or any command that changes ACL, udev, systemd, group membership, or system files.
- Never initialize hardware or send heartbeat, disconnect, brightness, image, refresh, feature, output, or raw HID data.
- Do not modify `src/streamdock_n3/_vendor`, `src/streamdock_n3/_data/99-streamdock.rules`, service/desktop data, `system_install.py`, or existing legacy entry points.
- New `streamdock_n3.hardware` production modules use only the Python standard library and the safe M1 `streamdock_n3.device_catalog` module.
- `FakeBackend` is the only backend implementation in G0. Do not add a real SDK, hidraw, evdev, udev, or direct-HID backend stub that imports an active dependency.
- Do not add a public console script in G0. The helper is invoked only as the fixed internal module `python -m streamdock_n3.hardware.helper_main` by tests and the fixed runner.
- A profile object is a contract value, not an active registration. G0 contains no module-level target profile and no selected production interface.
- Evidence never contains serial numbers, bus positions, `/dev` names, usernames, absolute paths, raw input payloads, image bytes, or image digests.
- Keep public compatibility wording at candidate/unvalidated. G0 does not establish hardware support.
- Follow RED → verify the expected failure → GREEN for every production behavior. Commit after each independently reviewable task.
- Run focused tests after every task and the full hardware-free suite before final review.

---

## File Map

- Create `src/streamdock_n3/hardware/__init__.py`: side-effect-free package boundary with no re-exports that trigger imports.
- Create `src/streamdock_n3/hardware/contracts.py`: immutable profile, interface, manifest, command, normalized-event, result, stage, state, operation, and recovery contracts.
- Create `src/streamdock_n3/hardware/gate.py`: stage ordering, exact command-rule enforcement, call accounting, block/disconnect behavior, and state transitions.
- Create `src/streamdock_n3/hardware/backend.py`: narrow `Backend` protocol, safe call summaries, and deterministic `FakeBackend` only.
- Create `src/streamdock_n3/hardware/adapter.py`: main-process orchestration around one profile, one gate, one injected backend, and an optional evidence sink.
- Create `src/streamdock_n3/hardware/ipc.py`: closed JSON request/response schema plus a fixed fake-helper runner with bounded timeout.
- Create `src/streamdock_n3/hardware/helper_main.py`: one-request fake-only subprocess entry module; no real backend selection.
- Create `src/streamdock_n3/hardware/evidence.py`: in-memory redacted operation/stage evidence and deterministic JSON rendering.
- Create `tests/hardware_fixtures.py`: shared G0-only profile, rule, manifest, command, and event factories; never imported by production code.
- Create `tests/test_hardware_contracts.py`: validation, canonical digest, command, event, and result tests.
- Create `tests/test_hardware_gate.py`: transition, manifest, allowlist, call-count, block, and disconnect tests.
- Create `tests/test_hardware_fake_backend.py`: deterministic event/result injection and image-redaction tests.
- Create `tests/test_hardware_adapter.py`: end-to-end fake stage orchestration and failure behavior.
- Create `tests/test_hardware_ipc.py`: closed wire schema, real fake-helper round trip, timeout, crash, and malformed-response tests.
- Create `tests/test_hardware_evidence.py`: public evidence schema and privacy tests.
- Create `tests/test_hardware_g0_safety.py`: AST/import/runtime/package guards proving G0 cannot touch active dependencies or system/hardware paths.
- Modify `tests/test_public_project.py:99-112`: assert the public architecture distinguishes implemented G0 from unimplemented active hardware work.
- Modify `docs/ARCHITECTURE.md:3-39`: document the implemented G0 boundary and still-planned G1–G8 boundaries.
- Modify `ROADMAP.md:5-30`: link the M2 PRD/design and mark only G0 complete while M2 remains in progress.

---

## G0 Scope Coverage

| PRD area | G0 plan coverage | Explicit boundary |
|---|---|---|
| M2-00 zero-hardware baseline | Tasks 1–8 | Fully implemented in G0 |
| M2-01 exact active profile | Contract and fail-closed tests in Tasks 1–2 | No production profile or interface selection; G1 remains blocked |
| M2-02 Adapter/helper isolation | Tasks 2–5 and 7 | FakeBackend/helper only; no SDK or device backend |
| M2-03 input | Normalized event fixtures and stage rules in Tasks 1–4 | No `/dev` access or real input helper; G3 remains blocked |
| M2-04 initialization | Typed fake command and stage rules in Tasks 1–4 | No lifecycle or hardware command; G4 remains blocked |
| M2-05–07 brightness/LCD | Exact fake command rules, call counts, recovery state, and evidence | No brightness/image output; G5–G7 remain blocked |
| M2-08 permissions | Static proof and public boundary in Tasks 7–8 | No ACL/udev artifact or system change; G2 remains blocked |
| M2-09 evidence | Task 6 | In-memory, redacted G0 evidence only |
| M2-10 legacy isolation | Tasks 7–8 | Legacy entry points and service remain unchanged |

---

### Task 1: Immutable G0 Contracts

**Files:**
- Create: `src/streamdock_n3/hardware/__init__.py`
- Create: `src/streamdock_n3/hardware/contracts.py`
- Create: `tests/hardware_fixtures.py`
- Create: `tests/test_hardware_contracts.py`

**Interfaces:**
- Consumes: `IdentityStatus`, `ProtocolStatus`, `format_usb_id`, and `normalize_usb_id` from `streamdock_n3.device_catalog`.
- Produces: `SCHEMA_VERSION`, `Stage`, `AdapterState`, `Operation`, `InputKind`, `InputAction`, `ResultStatus`, `ErrorCode`, `RecoveryStatus`, `HidInterface`, `DeviceProfile`, `CommandRule`, `StageManifest`, `AdapterCommand`, `NormalizedInputEvent`, and `OperationResult`.
- Produces exact methods: `DeviceProfile.to_dict() -> dict[str, object]`, `DeviceProfile.digest() -> str`, `CommandRule.matches(command: AdapterCommand) -> bool`, `StageManifest.to_dict() -> dict[str, object]`, `StageManifest.digest() -> str`, `AdapterCommand.image_digest() -> str | None`, and `OperationResult.succeeded -> bool`.

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_hardware_contracts.py` with these concrete tests:

```python
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    CommandRule,
    ErrorCode,
    HidInterface,
    InputAction,
    InputKind,
    NormalizedInputEvent,
    Operation,
    OperationResult,
    ResultStatus,
    Stage,
)
from tests.hardware_fixtures import make_manifest, make_profile


def test_profile_is_frozen_canonical_and_digest_stable() -> None:
    profile = make_profile()

    assert profile.to_dict() == {
        "schema_version": 1,
        "vid": "6602",
        "pid": "1000",
        "bcd_device": "0300",
        "interface": {"number": "00", "class": "03", "subclass": "00", "protocol": "00"},
        "identity_status": "user_reported_candidate",
        "protocol_status": "unvalidated",
        "source_commit": "0123456789abcdef",
    }
    assert len(profile.digest()) == 64
    assert profile.digest() == make_profile().digest()
    with pytest.raises(FrozenInstanceError):
        profile.vendor_id = 1  # type: ignore[misc]


def test_manifest_digest_changes_for_commit_profile_or_rules() -> None:
    manifest = make_manifest(Stage.G3_INPUT)
    changed_commit = replace(manifest, commit="fedcba9876543210")
    changed_rule = replace(
        manifest,
        allowed_commands=(CommandRule(Operation.OBSERVE_INPUTS, 1, 2),),
    )

    assert manifest.digest() != changed_commit.digest()
    assert manifest.digest() != changed_rule.digest()


def test_operation_result_success_requires_none_error() -> None:
    success = OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 3)
    failure = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 3)

    assert success.succeeded is True
    assert failure.succeeded is False
```

Construct invalid values lazily so collection reaches the assertion:

```python
@pytest.mark.parametrize(
    "factory",
    (
        lambda: HidInterface(-1, 3, 0, 0),
        lambda: HidInterface(256, 3, 0, 0),
        lambda: AdapterCommand(Operation.SET_BRIGHTNESS),
        lambda: AdapterCommand(Operation.SET_BRIGHTNESS, brightness=101),
        lambda: AdapterCommand(Operation.SET_KEY_IMAGE, key=0, image=b"image"),
        lambda: AdapterCommand(Operation.OBSERVE_INPUTS, brightness=10),
        lambda: NormalizedInputEvent(InputKind.BUTTON, 10, InputAction.PRESS, 1),
        lambda: NormalizedInputEvent(InputKind.KNOB_PRESS, 4, InputAction.PRESS, 1),
        lambda: NormalizedInputEvent(InputKind.KNOB_ROTATE, 1, InputAction.PRESS, 1),
        lambda: replace(make_profile(), source_commit="not-a-commit"),
        lambda: replace(make_manifest(Stage.G3_INPUT), stage=Stage.G0_SIMULATION),
        lambda: replace(make_manifest(Stage.G3_INPUT), profile_digest="short"),
        lambda: replace(make_manifest(Stage.G3_INPUT), deadline_ms=0),
        lambda: replace(make_manifest(Stage.G3_INPUT), expected_result="unsafe value"),
        lambda: replace(
            make_manifest(Stage.G3_INPUT),
            allowed_commands=(
                CommandRule(Operation.OBSERVE_INPUTS, 1, 1),
                CommandRule(Operation.OBSERVE_INPUTS, 1, 1),
            ),
        ),
        lambda: OperationResult(ResultStatus.SUCCEEDED, ErrorCode.BACKEND_FAILURE, 0),
        lambda: OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.NONE, 0),
    ),
)
def test_invalid_contract_values_fail_closed(factory: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()  # type: ignore[operator]
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_hardware_contracts.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'streamdock_n3.hardware'`.

- [ ] **Step 3: Implement the side-effect-free package and immutable contracts**

Create `src/streamdock_n3/hardware/__init__.py` with only:

```python
"""Hardware-safe adapter contracts and G0 simulation infrastructure."""
```

Create `src/streamdock_n3/hardware/contracts.py`. Use these exact enum values:

```python
SCHEMA_VERSION = 1
MAX_DEADLINE_MS = 600_000
MAX_IMAGE_BYTES = 1_048_576


class Stage(StrEnum):
    G0_SIMULATION = "g0_simulation"
    G1_PROFILE = "g1_profile"
    G2_PERMISSION = "g2_permission"
    G3_INPUT = "g3_input"
    G4_INITIALIZATION = "g4_initialization"
    G5_BRIGHTNESS = "g5_brightness"
    G6_ONE_LCD = "g6_one_lcd"
    G7_SIX_LCD = "g7_six_lcd"


class AdapterState(StrEnum):
    CANDIDATE = "candidate"
    PROFILE_APPROVED = "profile_approved"
    INPUT_VALIDATED = "input_validated"
    INITIALIZATION_VALIDATED = "initialization_validated"
    BRIGHTNESS_VALIDATED = "brightness_validated"
    ONE_LCD_VALIDATED = "one_lcd_validated"
    SIX_LCD_VALIDATED = "six_lcd_validated"
    BLOCKED = "blocked"
    DISCONNECTED = "disconnected"


class Operation(StrEnum):
    APPROVE_PROFILE = "approve_profile"
    RECORD_PERMISSION = "record_permission"
    OBSERVE_INPUTS = "observe_inputs"
    INITIALIZE = "initialize"
    SET_BRIGHTNESS = "set_brightness"
    SET_KEY_IMAGE = "set_key_image"
    CLOSE_SESSION = "close_session"


class InputKind(StrEnum):
    BUTTON = "button"
    KNOB_PRESS = "knob_press"
    KNOB_ROTATE = "knob_rotate"


class InputAction(StrEnum):
    PRESS = "press"
    RELEASE = "release"
    LEFT = "left"
    RIGHT = "right"


class ResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    BACKEND_ERROR = "backend_error"
    DISCONNECTED = "disconnected"


class ErrorCode(StrEnum):
    NONE = "none"
    MANIFEST_INVALID = "manifest_invalid"
    STATE_NOT_ALLOWED = "state_not_allowed"
    OPERATION_NOT_ALLOWED = "operation_not_allowed"
    CALL_LIMIT_EXCEEDED = "call_limit_exceeded"
    PARAMETER_NOT_ALLOWED = "parameter_not_allowed"
    REQUIRED_CALL_MISSING = "required_call_missing"
    BACKEND_FAILURE = "backend_failure"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    HELPER_CRASHED = "helper_crashed"
    INVALID_RESPONSE = "invalid_response"
    DEVICE_DISCONNECTED = "device_disconnected"


class RecoveryStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
```

Implement frozen, slotted dataclasses with these exact fields and validation rules:

```python
@dataclass(frozen=True, slots=True)
class HidInterface:
    number: int
    interface_class: int
    subclass: int
    protocol: int

    def __post_init__(self) -> None:
        for value in (self.number, self.interface_class, self.subclass, self.protocol):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFF:
                raise ValueError("HID interface fields must be bytes")

    def to_dict(self) -> dict[str, str]:
        return {
            "number": f"{self.number:02x}",
            "class": f"{self.interface_class:02x}",
            "subclass": f"{self.subclass:02x}",
            "protocol": f"{self.protocol:02x}",
        }


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    vendor_id: int
    product_id: int
    bcd_device: int
    interface: HidInterface
    identity_status: IdentityStatus
    protocol_status: ProtocolStatus
    source_commit: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        normalize_usb_id(self.vendor_id)
        normalize_usb_id(self.product_id)
        normalize_usb_id(self.bcd_device)
        _validate_schema(self.schema_version)
        _validate_commit(self.source_commit)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "vid": format_usb_id(self.vendor_id),
            "pid": format_usb_id(self.product_id),
            "bcd_device": format_usb_id(self.bcd_device),
            "interface": self.interface.to_dict(),
            "identity_status": self.identity_status.value,
            "protocol_status": self.protocol_status.value,
            "source_commit": self.source_commit,
        }

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())
```

Use a lowercase-hex commit regex of 7–40 characters. Use a safe-token regex
`[a-z0-9][a-z0-9_.:-]{0,127}` for `expected_result`, `recovery_plan`, and
`approval_reference`. `_canonical_digest` must use UTF-8 JSON with
`sort_keys=True`, `separators=(",", ":")`, and SHA-256.

Define `CommandRule` with `operation`, `min_calls`, `max_calls`, optional `brightness`,
optional `key`, and optional `image_sha256`. It validates `0 <= min_calls <= max_calls <= 12`;
brightness is `0..100`; key is `1..6`; image digests are lowercase 64-character SHA-256.
Its parameter shape must match the operation exactly. `matches()` compares operation and all
three optional parameters to `AdapterCommand`, using `command.image_digest()` for images.

Define `StageManifest` with this exact field order:

```python
@dataclass(frozen=True, slots=True)
class StageManifest:
    stage: Stage
    commit: str
    profile_digest: str
    interface: HidInterface
    allowed_commands: tuple[CommandRule, ...]
    deadline_ms: int
    expected_result: str
    recovery_plan: str
    approval_reference: str
    schema_version: int = SCHEMA_VERSION
```

Reject G0 manifests, blank/duplicate rules, invalid digests, deadlines outside
`1..600_000`, unsafe tokens, and schema versions other than `1`. `to_dict()` uses only
JSON primitives and `digest()` uses canonical SHA-256.

Define `AdapterCommand` with `operation`, optional `brightness`, optional `key`, and optional
`image: bytes`. Validate the exact operation shape and the 1 MiB image limit. Do not include
an image-returning serializer. `image_digest()` returns SHA-256 only for `SET_KEY_IMAGE`.

Define `NormalizedInputEvent` with `kind`, `control_id`, `action`, and `monotonic_ns`.
Buttons accept IDs 1–9 and press/release; knob press accepts IDs 1–3 and press/release;
knob rotate accepts IDs 1–3 and left/right. Require a non-negative integer timestamp.

Define `OperationResult` with `status`, `error_code`, `duration_ms`, and
`events: tuple[NormalizedInputEvent, ...] = ()`. A succeeded status requires `ErrorCode.NONE`;
all other statuses require a non-`NONE` code. `succeeded` is true only for `SUCCEEDED`.

- [ ] **Step 4: Add shared G0 test factories**

Create `tests/hardware_fixtures.py` with no filesystem or environment access:

```python
from __future__ import annotations

from hashlib import sha256

from streamdock_n3.device_catalog import IdentityStatus, ProtocolStatus
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    CommandRule,
    DeviceProfile,
    HidInterface,
    Operation,
    Stage,
    StageManifest,
)

TEST_COMMIT = "0123456789abcdef"
TEST_INTERFACE = HidInterface(0, 3, 0, 0)
TEST_IMAGE = b"g0-test-image"
TEST_IMAGE_DIGEST = sha256(TEST_IMAGE).hexdigest()


def make_profile() -> DeviceProfile:
    return DeviceProfile(
        vendor_id=0x6602,
        product_id=0x1000,
        bcd_device=0x0300,
        interface=TEST_INTERFACE,
        identity_status=IdentityStatus.USER_REPORTED_CANDIDATE,
        protocol_status=ProtocolStatus.UNVALIDATED,
        source_commit=TEST_COMMIT,
    )


def command_rule(command: AdapterCommand, min_calls: int = 1, max_calls: int = 1) -> CommandRule:
    return CommandRule(
        operation=command.operation,
        min_calls=min_calls,
        max_calls=max_calls,
        brightness=command.brightness,
        key=command.key,
        image_sha256=command.image_digest(),
    )


def make_manifest(
    stage: Stage,
    commands: tuple[AdapterCommand, ...] | None = None,
) -> StageManifest:
    defaults = {
        Stage.G1_PROFILE: (AdapterCommand(Operation.APPROVE_PROFILE),),
        Stage.G2_PERMISSION: (AdapterCommand(Operation.RECORD_PERMISSION),),
        Stage.G3_INPUT: (AdapterCommand(Operation.OBSERVE_INPUTS),),
        Stage.G4_INITIALIZATION: (AdapterCommand(Operation.INITIALIZE),),
        Stage.G5_BRIGHTNESS: (
            AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),
            AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50),
        ),
        Stage.G6_ONE_LCD: (
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE),
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"g0-baseline"),
        ),
        Stage.G7_SIX_LCD: tuple(
            AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"test-{key}".encode())
            for key in range(1, 7)
        )
        + tuple(
            AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"base-{key}".encode())
            for key in range(1, 7)
        ),
    }
    selected = commands if commands is not None else defaults[stage]
    return StageManifest(
        stage=stage,
        commit=TEST_COMMIT,
        profile_digest=make_profile().digest(),
        interface=TEST_INTERFACE,
        allowed_commands=tuple(command_rule(command) for command in selected),
        deadline_ms=600_000 if stage is Stage.G3_INPUT else 5_000,
        expected_result=f"{stage.value}-validated",
        recovery_plan=f"{stage.value}-recovery",
        approval_reference=f"test:{stage.value}",
    )
```

- [ ] **Step 5: Verify GREEN and strict types**

Run:

```bash
uv run pytest tests/test_hardware_contracts.py -v
uv run mypy --strict src/streamdock_n3/hardware/contracts.py tests/hardware_fixtures.py
uv run ruff check src/streamdock_n3/hardware tests/hardware_fixtures.py tests/test_hardware_contracts.py
```

Expected: all commands exit `0`; contract tests pass without importing active hardware modules.

- [ ] **Step 6: Commit**

```bash
git add src/streamdock_n3/hardware/__init__.py src/streamdock_n3/hardware/contracts.py tests/hardware_fixtures.py tests/test_hardware_contracts.py
git commit -m "feat: add hardware-safe adapter contracts"
```

---

### Task 2: Fail-Closed Capability Gate

**Files:**
- Create: `src/streamdock_n3/hardware/gate.py`
- Create: `tests/test_hardware_gate.py`

**Interfaces:**
- Consumes: all Task 1 contracts.
- Produces: `GateViolation(code: ErrorCode)`, `StageSession`, and `CapabilityGate(initial_state: AdapterState = AdapterState.CANDIDATE)`.
- Produces exact methods: `begin(profile: DeviceProfile, manifest: StageManifest, current_commit: str) -> None`, `authorize(command: AdapterCommand) -> None`, `record_result(result: OperationResult) -> None`, `complete(manual_confirmation: bool) -> AdapterState`, and `disconnect() -> AdapterState`.

- [ ] **Step 1: Write failing state and manifest tests**

Create `tests/test_hardware_gate.py` with a helper that constructs a gate in an explicit state. Add these tests:

```python
def test_g3_cannot_begin_before_profile_is_approved() -> None:
    gate = CapabilityGate()
    with pytest.raises(GateViolation) as raised:
        gate.begin(make_profile(), make_manifest(Stage.G3_INPUT), TEST_COMMIT)
    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED
    assert gate.state is AdapterState.CANDIDATE


@pytest.mark.parametrize(
    "mutation",
    (
        lambda manifest: replace(manifest, commit="fedcba9876543210"),
        lambda manifest: replace(manifest, profile_digest="0" * 64),
        lambda manifest: replace(manifest, interface=HidInterface(1, 3, 1, 1)),
    ),
)
def test_manifest_must_match_commit_profile_and_interface(mutation: object) -> None:
    gate = CapabilityGate(AdapterState.PROFILE_APPROVED)
    with pytest.raises(GateViolation) as raised:
        gate.begin(make_profile(), mutation(make_manifest(Stage.G3_INPUT)), TEST_COMMIT)  # type: ignore[operator]
    assert raised.value.code is ErrorCode.MANIFEST_INVALID


def test_permission_gate_does_not_advance_capability_state() -> None:
    gate = CapabilityGate(AdapterState.PROFILE_APPROVED)
    manifest = make_manifest(Stage.G2_PERMISSION)
    command = AdapterCommand(Operation.RECORD_PERMISSION)

    gate.begin(make_profile(), manifest, TEST_COMMIT)
    gate.authorize(command)
    gate.record_result(OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0))

    assert gate.complete(manual_confirmation=True) is AdapterState.PROFILE_APPROVED
```

- [ ] **Step 2: Write failing command-rule, failure, and disconnect tests**

Add tests that prove:

1. A command absent from the manifest fails with `OPERATION_NOT_ALLOWED` before backend execution.
2. A brightness value, LCD key, or image digest not exactly present in a rule fails with `PARAMETER_NOT_ALLOWED`.
3. A rule cannot exceed `max_calls`; the extra attempt fails with `CALL_LIMIT_EXCEEDED`.
4. `complete(True)` fails with `REQUIRED_CALL_MISSING` until every rule reaches `min_calls`.
5. `complete(False)` moves the gate to `BLOCKED`.
6. A non-success backend result immediately moves the gate to `BLOCKED` and clears the active session.
7. `disconnect()` moves any nonterminal state to `DISCONNECTED` and clears the active session.
8. A blocked or disconnected gate cannot begin another stage.
9. G1→G3→G4→G5→G6→G7 produces the exact approved state sequence; G2 leaves the state unchanged.

Use actual `AdapterCommand` values from `tests.hardware_fixtures`, not mock objects.

- [ ] **Step 3: Verify RED**

Run: `uv run pytest tests/test_hardware_gate.py -v`

Expected: collection fails because `streamdock_n3.hardware.gate` does not exist.

- [ ] **Step 4: Implement exact transition and operation maps**

Create `src/streamdock_n3/hardware/gate.py` with these immutable maps:

```python
_TRANSITIONS = {
    Stage.G1_PROFILE: (AdapterState.CANDIDATE, AdapterState.PROFILE_APPROVED),
    Stage.G2_PERMISSION: (AdapterState.PROFILE_APPROVED, AdapterState.PROFILE_APPROVED),
    Stage.G3_INPUT: (AdapterState.PROFILE_APPROVED, AdapterState.INPUT_VALIDATED),
    Stage.G4_INITIALIZATION: (
        AdapterState.INPUT_VALIDATED,
        AdapterState.INITIALIZATION_VALIDATED,
    ),
    Stage.G5_BRIGHTNESS: (
        AdapterState.INITIALIZATION_VALIDATED,
        AdapterState.BRIGHTNESS_VALIDATED,
    ),
    Stage.G6_ONE_LCD: (AdapterState.BRIGHTNESS_VALIDATED, AdapterState.ONE_LCD_VALIDATED),
    Stage.G7_SIX_LCD: (AdapterState.ONE_LCD_VALIDATED, AdapterState.SIX_LCD_VALIDATED),
}

_STAGE_OPERATIONS = {
    Stage.G1_PROFILE: frozenset({Operation.APPROVE_PROFILE}),
    Stage.G2_PERMISSION: frozenset({Operation.RECORD_PERMISSION}),
    Stage.G3_INPUT: frozenset({Operation.OBSERVE_INPUTS, Operation.CLOSE_SESSION}),
    Stage.G4_INITIALIZATION: frozenset({Operation.INITIALIZE, Operation.CLOSE_SESSION}),
    Stage.G5_BRIGHTNESS: frozenset({Operation.SET_BRIGHTNESS, Operation.CLOSE_SESSION}),
    Stage.G6_ONE_LCD: frozenset({Operation.SET_KEY_IMAGE, Operation.CLOSE_SESSION}),
    Stage.G7_SIX_LCD: frozenset({Operation.SET_KEY_IMAGE, Operation.CLOSE_SESSION}),
}

_REQUIRED_OPERATION = {
    Stage.G1_PROFILE: Operation.APPROVE_PROFILE,
    Stage.G2_PERMISSION: Operation.RECORD_PERMISSION,
    Stage.G3_INPUT: Operation.OBSERVE_INPUTS,
    Stage.G4_INITIALIZATION: Operation.INITIALIZE,
    Stage.G5_BRIGHTNESS: Operation.SET_BRIGHTNESS,
    Stage.G6_ONE_LCD: Operation.SET_KEY_IMAGE,
    Stage.G7_SIX_LCD: Operation.SET_KEY_IMAGE,
}
```

`GateViolation` stores only a stable `ErrorCode`; its message is `code.value`. `StageSession`
stores the manifest and a call-count list indexed exactly like `allowed_commands`.

`begin()` checks, in this order: no active session; nonterminal current state; stage present in
`_TRANSITIONS`; expected current state; exact current commit; exact profile digest; exact
interface; every rule operation belongs to the stage; and at least one required-operation rule
has `min_calls >= 1`. A failure never mutates state.

`authorize()` finds the first exact matching rule with remaining capacity, increments only that
rule count, and otherwise distinguishes parameter mismatch from exhausted capacity.
`record_result()` changes state to `BLOCKED` for every non-success result. `complete()` checks
manual confirmation and every `min_calls`; it then applies the transition and clears the session.
No method retries, changes profiles, or selects another interface.

- [ ] **Step 5: Verify GREEN and strict types**

Run:

```bash
uv run pytest tests/test_hardware_gate.py -v
uv run mypy --strict src/streamdock_n3/hardware/contracts.py src/streamdock_n3/hardware/gate.py
uv run ruff check src/streamdock_n3/hardware/gate.py tests/test_hardware_gate.py
```

Expected: all commands exit `0`; all transition and rejection cases pass.

- [ ] **Step 6: Commit**

```bash
git add src/streamdock_n3/hardware/gate.py tests/test_hardware_gate.py
git commit -m "feat: add fail-closed hardware capability gate"
```

---

### Task 3: Narrow Backend Protocol and Deterministic FakeBackend

**Files:**
- Create: `src/streamdock_n3/hardware/backend.py`
- Create: `tests/test_hardware_fake_backend.py`

**Interfaces:**
- Consumes: `AdapterCommand`, `StageManifest`, `NormalizedInputEvent`, `OperationResult`, and related enums.
- Produces: runtime-checkable `Backend` protocol with `execute(command: AdapterCommand, manifest: StageManifest) -> OperationResult`.
- Produces: `BackendCall`, `FakeBackend(events: tuple[NormalizedInputEvent, ...] = (), outcomes: Mapping[Operation, ResultStatus] | None = None)`, `FakeBackend.calls`, and `FakeBackend.execute(...)`.

- [ ] **Step 1: Write failing fake-backend tests**

Create `tests/test_hardware_fake_backend.py` with deterministic fixtures for all logical controls:

```python
def all_input_events() -> tuple[NormalizedInputEvent, ...]:
    button_events = tuple(
        NormalizedInputEvent(InputKind.BUTTON, key, action, key * 10 + offset)
        for key in range(1, 10)
        for offset, action in enumerate((InputAction.PRESS, InputAction.RELEASE))
    )
    knob_events = tuple(
        NormalizedInputEvent(kind, knob, action, 1_000 + knob * 10 + offset)
        for knob in range(1, 4)
        for kind, action in (
            (InputKind.KNOB_PRESS, InputAction.PRESS),
            (InputKind.KNOB_PRESS, InputAction.RELEASE),
            (InputKind.KNOB_ROTATE, InputAction.LEFT),
            (InputKind.KNOB_ROTATE, InputAction.RIGHT),
        )
        for offset in (0,)
    )
    return button_events + knob_events


def test_fake_backend_returns_injected_normalized_events() -> None:
    backend = FakeBackend(events=all_input_events())
    result = backend.execute(
        AdapterCommand(Operation.OBSERVE_INPUTS),
        make_manifest(Stage.G3_INPUT),
    )

    assert result.succeeded is True
    assert result.events == all_input_events()
    assert backend.calls[0].operation is Operation.OBSERVE_INPUTS


def test_fake_backend_records_only_image_digest_and_size() -> None:
    backend = FakeBackend()
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE)

    backend.execute(command, make_manifest(Stage.G6_ONE_LCD))

    call = backend.calls[0]
    assert call.key == 1
    assert call.payload_size == len(TEST_IMAGE)
    assert call.payload_sha256 == command.image_digest()
    assert not hasattr(call, "image")
    assert TEST_IMAGE not in repr(call).encode()
```

Add a parameterized test for `REJECTED`, `TIMEOUT`, `BACKEND_ERROR`, and `DISCONNECTED`.
Assert the matching stable error codes are respectively `OPERATION_NOT_ALLOWED`,
`DEADLINE_EXCEEDED`, `BACKEND_FAILURE`, and `DEVICE_DISCONNECTED`; events are empty for every
non-success result. Also assert `outcomes` is copied on construction so caller mutation cannot
change behavior.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_hardware_fake_backend.py -v`

Expected: collection fails because `streamdock_n3.hardware.backend` does not exist.

- [ ] **Step 3: Implement the backend protocol and fake backend**

Create `src/streamdock_n3/hardware/backend.py` with:

```python
@runtime_checkable
class Backend(Protocol):
    def execute(
        self,
        command: AdapterCommand,
        manifest: StageManifest,
    ) -> OperationResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class BackendCall:
    operation: Operation
    brightness: int | None
    key: int | None
    payload_sha256: str | None
    payload_size: int


_ERROR_FOR_STATUS = {
    ResultStatus.REJECTED: ErrorCode.OPERATION_NOT_ALLOWED,
    ResultStatus.TIMEOUT: ErrorCode.DEADLINE_EXCEEDED,
    ResultStatus.BACKEND_ERROR: ErrorCode.BACKEND_FAILURE,
    ResultStatus.DISCONNECTED: ErrorCode.DEVICE_DISCONNECTED,
}
```

`FakeBackend` copies the supplied outcomes with `dict(outcomes or {})`, stores events as a tuple,
and starts with an empty mutable call list owned by the instance. `execute()` appends one safe
`BackendCall` and returns duration `0`. Only successful `OBSERVE_INPUTS` returns injected events;
all other successful operations return no events. It never stores image bytes, imports a device
library, opens files, reads environment variables, or sleeps.

- [ ] **Step 4: Verify GREEN and strict types**

Run:

```bash
uv run pytest tests/test_hardware_fake_backend.py -v
uv run mypy --strict src/streamdock_n3/hardware/backend.py
uv run ruff check src/streamdock_n3/hardware/backend.py tests/test_hardware_fake_backend.py
```

Expected: all commands exit `0`; every simulated result is deterministic.

- [ ] **Step 5: Commit**

```bash
git add src/streamdock_n3/hardware/backend.py tests/test_hardware_fake_backend.py
git commit -m "feat: add deterministic fake hardware backend"
```

---

### Task 4: Main-Process N3Adapter Orchestration

**Files:**
- Create: `src/streamdock_n3/hardware/adapter.py`
- Create: `tests/test_hardware_adapter.py`

**Interfaces:**
- Consumes: Task 1 contracts, `CapabilityGate`, and `Backend`.
- Produces: `EvidenceSink` protocol and `N3Adapter(profile: DeviceProfile, current_commit: str, backend: Backend, initial_state: AdapterState = AdapterState.CANDIDATE, evidence: EvidenceSink | None = None)`.
- Produces exact methods: `begin_stage(manifest: StageManifest) -> None`, `execute(command: AdapterCommand) -> OperationResult`, `complete_stage(manual_confirmation: bool, recovery_status: RecoveryStatus = RecoveryStatus.NOT_REQUIRED) -> AdapterState`, and `disconnect() -> AdapterState`.

- [ ] **Step 1: Write failing adapter happy-path and isolation tests**

Create `tests/test_hardware_adapter.py`. Add a helper that executes every command rule exactly once
by reconstructing an `AdapterCommand` from the test fixture's original command list. Test the full
fake sequence G1, G2, G3, G4, G5, G6, and G7 and assert these states in order:

```python
(
    AdapterState.PROFILE_APPROVED,
    AdapterState.PROFILE_APPROVED,
    AdapterState.INPUT_VALIDATED,
    AdapterState.INITIALIZATION_VALIDATED,
    AdapterState.BRIGHTNESS_VALIDATED,
    AdapterState.ONE_LCD_VALIDATED,
    AdapterState.SIX_LCD_VALIDATED,
)
```

Assert the exact number and order of `FakeBackend.calls`; G5 has two brightness calls and G7 has
twelve image calls. Assert there is no automatic call between stages and no `CLOSE_SESSION` call
unless the manifest explicitly contains it and the test invokes it.

- [ ] **Step 2: Write failing adapter failure tests**

Add tests that prove:

1. `execute()` before `begin_stage()` raises `GateViolation` and the backend sees zero calls.
2. A command absent from the manifest never reaches the backend.
3. A FakeBackend timeout/backend error/disconnect moves adapter state to `BLOCKED` and prevents completion.
4. `complete_stage(False, RecoveryStatus.UNKNOWN)` blocks even after successful calls.
5. `disconnect()` leaves prior call history unchanged and prevents new stages.
6. Backend exceptions are caught, converted to `BACKEND_ERROR/BACKEND_FAILURE`, and block the gate; exception text is neither returned nor stored.
7. Constructing `N3Adapter` does not execute, enumerate, open, initialize, or spawn anything.

- [ ] **Step 3: Verify RED**

Run: `uv run pytest tests/test_hardware_adapter.py -v`

Expected: collection fails because `streamdock_n3.hardware.adapter` does not exist.

- [ ] **Step 4: Implement orchestration with no implicit work**

Create `src/streamdock_n3/hardware/adapter.py`. Define an optional sink protocol whose methods use
only safe contract objects:

```python
class EvidenceSink(Protocol):
    def record_operation(
        self,
        profile: DeviceProfile,
        manifest: StageManifest,
        command: AdapterCommand,
        result: OperationResult,
    ) -> None:
        raise NotImplementedError

    def record_stage(
        self,
        profile: DeviceProfile,
        manifest: StageManifest,
        state: AdapterState,
        recovery_status: RecoveryStatus,
    ) -> None:
        raise NotImplementedError
```

`N3Adapter.__init__` only assigns fields and creates `CapabilityGate(initial_state)`; it performs
no backend call, subprocess call, I/O, import, or discovery. `begin_stage()` delegates to
`gate.begin(...)`. `execute()` first authorizes, then calls the backend exactly once. Convert any
backend exception to `OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)`
without retaining its text. Record the result in the gate, then call the evidence sink when present.
`complete_stage()` delegates to the gate and records the resulting stage state. `disconnect()`
delegates only to the gate and performs no backend close command.

- [ ] **Step 5: Verify GREEN and strict types**

Run:

```bash
uv run pytest tests/test_hardware_adapter.py -v
uv run mypy --strict src/streamdock_n3/hardware/adapter.py
uv run ruff check src/streamdock_n3/hardware/adapter.py tests/test_hardware_adapter.py
```

Expected: all commands exit `0`; fake stages advance only after explicit calls and completion.

- [ ] **Step 6: Commit**

```bash
git add src/streamdock_n3/hardware/adapter.py tests/test_hardware_adapter.py
git commit -m "feat: add explicit N3 adapter orchestration"
```

---

### Task 5: Closed IPC Schema and Fake-Only Helper Process

**Files:**
- Create: `src/streamdock_n3/hardware/ipc.py`
- Create: `src/streamdock_n3/hardware/helper_main.py`
- Create: `tests/test_hardware_ipc.py`

**Interfaces:**
- Consumes: contracts, gate, and FakeBackend.
- Produces: `IpcRequest`, `encode_request(request: IpcRequest) -> str`, `decode_request(text: str) -> IpcRequest`, `encode_response(result: OperationResult) -> str`, `decode_response(text: str) -> OperationResult`, and `run_fake_helper(request: IpcRequest, timeout_ms: int) -> OperationResult`.
- Produces: `helper_main.main() -> int`, accepting exactly one bounded JSON request on stdin and emitting exactly one JSON response on stdout.

- [ ] **Step 1: Write failing closed-schema tests**

Create `tests/test_hardware_ipc.py` and define a valid request from `make_profile()`,
`make_manifest(Stage.G3_INPUT)`, `AdapterState.PROFILE_APPROVED`, and
`AdapterCommand(Operation.OBSERVE_INPUTS)`. Assert request JSON has exactly:

```python
{
    "schema_version",
    "profile",
    "state",
    "manifest",
    "command",
}
```

Assert nested profile, interface, manifest, rule, command, response, and event objects also reject
missing and extra keys. Add round trips for every enum, brightness, all normalized events, and an
image payload. Image bytes are base64 only inside the request and never appear in a response.
Reject invalid base64, payloads over 1 MiB, request text over 1,500,000 bytes, unknown enum values,
floats where integers are required, booleans where integers are required, and schema versions other
than `1`.

- [ ] **Step 2: Write failing process and failure-boundary tests**

Add one real subprocess round trip:

```python
def test_fake_helper_round_trip_uses_fixed_internal_module() -> None:
    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result.succeeded is True
    assert result.error_code is ErrorCode.NONE
```

Monkeypatch only `subprocess.run` inside `streamdock_n3.hardware.ipc` to cover:

- `subprocess.TimeoutExpired` → `TIMEOUT/DEADLINE_EXCEEDED`.
- nonzero return code with arbitrary stdout/stderr paths and secrets → `BACKEND_ERROR/HELPER_CRASHED`, with neither stream copied into the result.
- zero return code plus invalid JSON → `BACKEND_ERROR/INVALID_RESPONSE`.
- a completed response larger than 1 MiB → `BACKEND_ERROR/INVALID_RESPONSE`.

Inspect the patched call and assert argv equals
`[sys.executable, "-m", "streamdock_n3.hardware.helper_main"]`, `shell` is absent or false,
`check=False`, `capture_output=True`, and the timeout is exactly `timeout_ms / 1000`.
Also assert a timeout greater than `request.manifest.deadline_ms` raises `ValueError` before
`subprocess.run` is called.

- [ ] **Step 3: Verify RED**

Run: `uv run pytest tests/test_hardware_ipc.py -v`

Expected: collection fails because `streamdock_n3.hardware.ipc` does not exist.

- [ ] **Step 4: Implement canonical serializers and strict parsers**

Create `src/streamdock_n3/hardware/ipc.py`. Define:

```python
MAX_REQUEST_BYTES = 1_500_000
MAX_RESPONSE_BYTES = 1_000_000
HELPER_MODULE = "streamdock_n3.hardware.helper_main"


@dataclass(frozen=True, slots=True)
class IpcRequest:
    profile: DeviceProfile
    state: AdapterState
    manifest: StageManifest
    command: AdapterCommand
    schema_version: int = SCHEMA_VERSION
```

Use private `_require_exact_keys(mapping, expected)` and `_require_int(value)` helpers. The latter
must reject `bool`. Parse hex text with explicit length before integer conversion. Parse every enum
by constructor and convert all parser exceptions to `ValueError("invalid_ipc_request")` or
`ValueError("invalid_ipc_response")`; never include raw values or exception text.

Use canonical compact JSON with sorted keys. The command wire object always contains exactly
`operation`, `brightness`, `key`, and `image_base64`, with absent optionals represented by `null`.
The response always contains exactly `schema_version`, `status`, `error_code`, `duration_ms`, and
`events`. Do not serialize profile paths, native errors, backend call history, image digest, or
manifest approval text beyond its validated safe tokens.

- [ ] **Step 5: Implement the fixed fake-only helper and runner**

Create `src/streamdock_n3/hardware/helper_main.py` with a `main()` that:

1. Reads at most `MAX_REQUEST_BYTES + 1` bytes from `sys.stdin.buffer` and decodes strict UTF-8.
2. Rejects an oversized payload, invalid UTF-8, or anything other than one nonempty JSON line.
3. Decodes one `IpcRequest`.
4. Creates `CapabilityGate(request.state)` and `FakeBackend()` only.
5. Calls `begin()`, `authorize()`, `FakeBackend.execute()`, and `record_result()` exactly once.
6. Prints one encoded result and returns `0` for accepted/rejected protocol results.
7. Catches `GateViolation` and returns `REJECTED` with its stable code.
8. Catches all parse errors and returns `REJECTED/MANIFEST_INVALID`.
9. Catches unexpected exceptions and returns `BACKEND_ERROR/BACKEND_FAILURE` without traceback or exception text.

End with:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

In `run_fake_helper()`, validate
`1 <= timeout_ms <= request.manifest.deadline_ms <= 600_000`, call the fixed module via
`subprocess.run` with string input, captured text output, `check=False`, and bounded timeout. Never
accept a module name, executable, command list, environment command, or shell flag from a caller.
Map timeout, nonzero exit, oversized output, and invalid response to stable `OperationResult` values.

- [ ] **Step 6: Verify GREEN and strict types**

Run:

```bash
uv run pytest tests/test_hardware_ipc.py -v
uv run mypy --strict src/streamdock_n3/hardware/ipc.py src/streamdock_n3/hardware/helper_main.py
uv run ruff check src/streamdock_n3/hardware/ipc.py src/streamdock_n3/hardware/helper_main.py tests/test_hardware_ipc.py
```

Expected: all commands exit `0`; the actual fake-only subprocess round trip succeeds and failure
results contain no child stdout/stderr.

- [ ] **Step 7: Commit**

```bash
git add src/streamdock_n3/hardware/ipc.py src/streamdock_n3/hardware/helper_main.py tests/test_hardware_ipc.py
git commit -m "feat: add fake-only isolated helper protocol"
```

---

### Task 6: Redacted Evidence Recorder

**Files:**
- Create: `src/streamdock_n3/hardware/evidence.py`
- Create: `tests/test_hardware_evidence.py`

**Interfaces:**
- Consumes: the exact `EvidenceSink` protocol from Task 4 and all safe contracts.
- Produces: `EvidenceKind`, `EvidenceRecord.to_dict() -> dict[str, object]`, and `EvidenceRecorder` implementing `record_operation(...)`, `record_stage(...)`, `records -> tuple[EvidenceRecord, ...]`, and `to_json() -> str`.

- [ ] **Step 1: Write failing operation/stage evidence tests**

Create `tests/test_hardware_evidence.py`. Run a G3 FakeBackend stage through `N3Adapter` with an
`EvidenceRecorder` and assert `recorder.records[0].to_dict()` contains exactly:

```python
{
    "schema_version": 1,
    "kind": "operation",
    "stage": "g3_input",
    "commit": TEST_COMMIT,
    "profile_digest": make_profile().digest(),
    "interface": {"number": "00", "class": "03", "subclass": "00", "protocol": "00"},
    "operation": "observe_inputs",
    "brightness": None,
    "key": None,
    "payload_size": 0,
    "status": "succeeded",
    "error_code": "none",
    "duration_ms": 0,
    "event_count": 0,
    "expected_result": "g3_input-validated",
    "recovery_plan": "g3_input-recovery",
    "approval_reference": "test:g3_input",
    "adapter_state": None,
    "recovery_status": None,
}
```

After `complete_stage(True, RecoveryStatus.NOT_REQUIRED)`, assert a second `kind="stage"` record
has `adapter_state="input_validated"`, `recovery_status="not_required"`, and operation/result fields
represented by `null` or zero according to the closed schema.

- [ ] **Step 2: Write failing privacy and determinism tests**

Execute an image command containing all of these byte markers:

```python
sensitive_image = b"LOCAL_USER_PATH WORKSPACE_PATH DEVICE_NODE serial_number=SECRET image-bytes"
```

Assert none of the markers, the image bytes, or `command.image_digest()` occurs in `to_json()`.
Assert JSON has stable key ordering, records remain in append order, `records` is an immutable tuple,
and mutating a returned dictionary cannot change recorder state. Scan keys recursively and reject:
`serial`, `serial_number`, `path`, `device_node`, `raw_payload`, `image`, `image_base64`, and
`image_sha256`.

- [ ] **Step 3: Verify RED**

Run: `uv run pytest tests/test_hardware_evidence.py -v`

Expected: collection fails because `streamdock_n3.hardware.evidence` does not exist.

- [ ] **Step 4: Implement the closed evidence schema**

Create `src/streamdock_n3/hardware/evidence.py` with:

```python
class EvidenceKind(StrEnum):
    OPERATION = "operation"
    STAGE = "stage"
```

Define a frozen, slotted `EvidenceRecord` with the exact keys asserted by Step 1. Store safe
contract values, never `AdapterCommand.image`, `AdapterCommand.image_digest()`, an exception, a
path, or backend-native output. For image operations record only logical key and payload byte count.

`EvidenceRecorder` owns a private list. `records` returns `tuple(self._records)`. `to_json()` returns
a JSON array with `ensure_ascii=False`, `sort_keys=True`, and compact separators. It performs no
file write. `record_operation()` and `record_stage()` append exactly one record each and satisfy the
Task 4 `EvidenceSink` protocol without changing `adapter.py` signatures.

- [ ] **Step 5: Verify GREEN and strict types**

Run:

```bash
uv run pytest tests/test_hardware_evidence.py tests/test_hardware_adapter.py -v
uv run mypy --strict src/streamdock_n3/hardware/evidence.py src/streamdock_n3/hardware/adapter.py
uv run ruff check src/streamdock_n3/hardware/evidence.py tests/test_hardware_evidence.py
```

Expected: all commands exit `0`; serialized evidence contains no sensitive marker or image digest.

- [ ] **Step 6: Commit**

```bash
git add src/streamdock_n3/hardware/evidence.py tests/test_hardware_evidence.py
git commit -m "feat: add redacted hardware stage evidence"
```

---

### Task 7: G0 Static, Runtime, and Package Safety Gates

**Files:**
- Create: `tests/test_hardware_g0_safety.py`

**Interfaces:**
- Consumes: every G0 production module and the built wheel.
- Produces: automated proof that the new dependency closure is hardware-free, system-change-free, and fake-only.

- [ ] **Step 1: Write the complete safety test before changing production code**

Create `tests/test_hardware_g0_safety.py` with this exact production file list:

```python
G0_MODULES = (
    Path("src/streamdock_n3/hardware/__init__.py"),
    Path("src/streamdock_n3/hardware/contracts.py"),
    Path("src/streamdock_n3/hardware/gate.py"),
    Path("src/streamdock_n3/hardware/backend.py"),
    Path("src/streamdock_n3/hardware/adapter.py"),
    Path("src/streamdock_n3/hardware/ipc.py"),
    Path("src/streamdock_n3/hardware/helper_main.py"),
    Path("src/streamdock_n3/hardware/evidence.py"),
)

FORBIDDEN_SOURCE = (
    "streamdock_n3._vendor",
    "DeviceManager",
    "LibUSBHIDAPI",
    "import ctypes",
    "from ctypes",
    "import evdev",
    "import pyudev",
    "import gi",
    "os.open",
    "/dev/hidraw",
    "/dev/input",
    "udevadm",
    "systemctl",
    "setfacl",
    "sudo ",
    "shell=True",
    "subprocess.Popen",
)
```

Add tests that:

1. Scan every source for every forbidden string.
2. Parse imports with `ast`; allow project imports only from `streamdock_n3.device_catalog` or another `streamdock_n3.hardware` module. Allow `subprocess` only in `ipc.py`.
3. Parse calls with `ast`; forbid builtin `open`, `os.open`, `Path.open`, `read_bytes`, `write_bytes`, `read_text`, `write_text`, `unlink`, `chmod`, `chown`, and every `subprocess` function except `subprocess.run` inside `ipc.py`.
4. Inspect the only `subprocess.run` call and require a literal fixed module constant, captured text I/O, a timeout, `check=False`, and no shell argument.
5. Start a fresh Python process that imports every G0 module and prints `sys.modules`; assert no module prefix `_vendor`, `ctypes`, `evdev`, `pyudev`, or `gi` appears.
6. Monkeypatch `subprocess.run` in the parent process, import and construct all G0 classes, and assert the patch was never called until `run_fake_helper()` is explicitly invoked.
7. Read `ProductIDs.py` as text and assert no active mapping line combines `USB_VIDN3E` with `USB_PID_STREAMDOCK_N1EN`; read the packaged udev rule and assert it contains no `6602` target rule.
8. Build a fresh wheel with `uv build --wheel --out-dir <tmp>` and assert all eight G0 module paths are present.
9. Install that wheel without dependencies into a temporary uv venv; import all G0 modules and assert the same forbidden runtime modules remain absent.
10. Assert no new project script in `pyproject.toml` targets `streamdock_n3.hardware`.

- [ ] **Step 2: Verify the safety gate passes**

Run: `uv run pytest tests/test_hardware_g0_safety.py -v`

Expected: all safety tests pass. If a test fails, remove or narrow the offending G0 behavior; do not
relax a forbidden dependency or system/hardware boundary.

- [ ] **Step 3: Run the whole G0 test slice**

Run:

```bash
uv run pytest tests/test_hardware_contracts.py tests/test_hardware_gate.py tests/test_hardware_fake_backend.py tests/test_hardware_adapter.py tests/test_hardware_ipc.py tests/test_hardware_evidence.py tests/test_hardware_g0_safety.py -v
uv run mypy --strict src/streamdock_n3/hardware
uv run ruff check src/streamdock_n3/hardware tests/test_hardware_*.py tests/hardware_fixtures.py
```

Expected: all commands exit `0`; no test requires hardware, root, sudo, `/dev`, udev, systemd, or
vendored SDK loading.

- [ ] **Step 4: Commit**

```bash
git add tests/test_hardware_g0_safety.py
git commit -m "test: prove G0 hardware isolation"
```

---

### Task 8: Public Architecture Status and Final G0 Verification

**Files:**
- Modify: `tests/test_public_project.py:99-112`
- Modify: `docs/ARCHITECTURE.md:3-39`
- Modify: `ROADMAP.md:5-30`

**Interfaces:**
- Consumes: the completed G0 package and approved M2 documents.
- Produces: public documentation that says G0 simulation infrastructure is implemented while active profile, permissions, SDK loading, `/dev`, and hardware validation remain pending.

- [ ] **Step 1: Write failing public-document assertions**

Replace `test_architecture_documents_m1_passive_and_m2_active_boundaries` with an expanded test that
keeps every existing M1 assertion and additionally requires these phrases in `docs/ARCHITECTURE.md`:

```python
for required in (
    "G0",
    "FakeBackend",
    "N3Adapter",
    "helper process",
    "does not activate `6602:1000`",
    "does not import the vendored SDK",
    "G1",
    "G7",
):
    assert required in architecture
```

Add a roadmap assertion that requires the M2 PRD/design links,
`**Status:** In progress — G0 foundation only`, a checked G0 item, and unchecked G1–G7 hardware work. Assert neither document says
`6602:1000` is supported.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: the new G0 architecture/status assertions fail because the public documents still describe
all active adapter work as planned and M2 as pending.

- [ ] **Step 3: Update architecture with exact implemented/planned boundaries**

In `docs/ARCHITECTURE.md`, retain the M1 paragraph and add this implemented G0 data flow:

```text
M1 passive observation
  -> immutable test/profile contract
  -> CapabilityGate
  -> N3Adapter
  -> FakeBackend or fake-only helper process
  -> redacted in-memory evidence
```

State explicitly:

- G0 does not activate `6602:1000` and contains no selected production interface.
- G0 does not import the vendored SDK, open `/dev`, install permissions, or write hardware.
- `FakeBackend` is the only implemented backend.
- G1 chooses and approves an exact active profile/interface; G2 covers permissions; G3–G7 cover
  input, initialization, brightness, one LCD, and six LCDs.
- The legacy daemon/action/plugin/UI flow remains planned and disconnected from the G0 Adapter.

Preserve the existing `target architecture` and `planned responsibility` language for the still
unimplemented action engine, plugin contract, UI, and later active hardware stages so existing public
truthfulness tests remain valid. Do not change README hardware compatibility claims or present G0 as
user-facing hardware support.

- [ ] **Step 4: Update the roadmap without claiming M2 completion**

Add links near the existing M1 PRD link to:

- `tasks/prd-m2-n3-v3-hardware-controls.md`
- `docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md`

Change only the M2 block to:

```markdown
**Status:** In progress — G0 foundation only

- [x] Define and test the hardware-free Adapter contracts, capability gate, FakeBackend,
  fake-only helper isolation, and redacted evidence.
- [ ] G1: approve an exact active profile and resolve interface responsibility.
- [ ] G2: approve any permission change separately.
- [ ] G3–G7: validate input, initialization, brightness, one LCD, and all six LCDs through
  their independent manual gates.
```

- [ ] **Step 5: Verify public documentation GREEN**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: all public-project tests pass and continue to reject unsupported compatibility claims.

- [ ] **Step 6: Run fresh complete verification**

Run every command separately and read each full result:

```bash
uv run pytest
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
uv build
git diff --check
git status --short
```

Expected:

- Full pytest exits `0` with zero failures.
- Ruff exits `0` with `All checks passed!`.
- Strict mypy exits `0` for every G0 module.
- Wheel and sdist build exit `0`.
- `git diff --check` prints nothing.
- `git status --short` lists only the intended Task 8 documentation/test edits before commit.

- [ ] **Step 7: Review the final scope diff**

Run:

```bash
git diff "$(git merge-base main HEAD)"..HEAD -- src/streamdock_n3/hardware tests/test_hardware_contracts.py tests/test_hardware_gate.py tests/test_hardware_fake_backend.py tests/test_hardware_adapter.py tests/test_hardware_ipc.py tests/test_hardware_evidence.py tests/test_hardware_g0_safety.py tests/hardware_fixtures.py
git diff -- docs/ARCHITECTURE.md ROADMAP.md tests/test_public_project.py
git diff "$(git merge-base main HEAD)"..HEAD -- src/streamdock_n3/_vendor src/streamdock_n3/_data src/streamdock_n3/system_install.py pyproject.toml
git diff -- src/streamdock_n3/_vendor src/streamdock_n3/_data src/streamdock_n3/system_install.py pyproject.toml
```

Expected: the first command shows the committed Task 1–7 G0 package/tests; the second shows only the
uncommitted Task 8 documentation/test edits; both forbidden-path commands print nothing. Confirm there
is no active profile registry, SDK import, `/dev` access, permission action, hardware command, console
entry point, or compatibility claim.

- [ ] **Step 8: Commit**

```bash
git add docs/ARCHITECTURE.md ROADMAP.md tests/test_public_project.py
git commit -m "docs: publish G0 adapter safety boundary"
```

- [ ] **Step 9: Verify the committed branch state**

Run:

```bash
git diff HEAD^ HEAD --check
git diff "$(git merge-base main HEAD)"..HEAD -- src/streamdock_n3/_vendor src/streamdock_n3/_data src/streamdock_n3/system_install.py pyproject.toml
git status --short --branch
git log --oneline -8
```

Expected: both diff commands print nothing; status shows the G0 branch with no worktree changes; the
log shows the eight task commits in order.

---

## G0 Completion Gate

G0 is complete only when all eight tasks are committed, the final verification commands have fresh
exit-zero evidence, and a scope review confirms that only FakeBackend can execute. G0 completion does
not advance the physical state beyond `CANDIDATE`, create an active profile, resolve interface `00/01`,
or authorize G1–G7.

Before any next action, stop and request a separate written approval for G1 active-profile/interface
design. Do not import the SDK, open `/dev`, change permissions, or access hardware as part of that
request.
