# M2 G1 Active Profile and Interface Responsibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Approve one exact active profile for the owner-reported `6602:1000` candidate and resolve unique interface responsibility (input vs control) from read-only sysfs evidence, while still never opening `/dev`, loading the SDK, or writing hardware. Ambiguity, identity drift, or incomplete profile fields block the gate instead of being guessed.

**Architecture:** G1 extends the M1 passive scanner to also gather per-interface input-subsystem evidence, classifies each HID interface into an `InterfaceRole` with a recorded redacted basis, and resolves exactly one input interface and one control interface. The `N3Adapter` G1 stage carries the role resolution in its manifest; the private gate pins the approved profile identity and roles at G1 commit and fails closed on any later drift. The product owner approves the exact profile and role assignment explicitly; M1 observation never auto-creates an active profile.

**Tech Stack:** Python 3.11+, frozen/slotted dataclasses, `StrEnum`, SHA-256, JSON, argparse, pytest, Ruff, mypy strict, Hatchling/uv.

## Global Constraints

- Sources of truth, in order: `tasks/prd-m2-n3-v3-hardware-controls.md` version 1.0, `docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md`, and `docs/superpowers/specs/2026-08-03-m2-g0-transactional-adapter-safety-design.md`.
- G1 approves a profile and interface responsibilities; it never opens `/dev`, never imports or loads the vendored SDK or native transport, never enumerates hidraw/input event nodes, never changes udev/ACL/systemd state, never runs sudo, and never writes hardware.
- The only new real-device read surface is passive sysfs metadata (interface descriptors, input-subsystem associations, input capability bitmaps) under the already-approved `/sys/devices` real-path root; no `/dev`, no debugfs, no ioctl.
- The real-device evidence run is a separate explicit human gate: it executes only after the product owner approves this plan and the exact evidence command.
- M1 observation does not create or approve an active profile; only an explicit G1 approval with `manual_confirmation=True` pins identity and roles.
- `6602:1000` remains an owner-reported candidate with unvalidated protocol. G1 role approval is a candidate profile decision, not a compatibility claim. Do not claim supported/已支持.
- The G1 dependency closure remains standard-library-only plus the safe M1 `streamdock_n3.device_catalog` contracts.
- Do not modify `src/streamdock_n3/_vendor`, `src/streamdock_n3/_data`, legacy daemon/probe/debug/GUI/install paths, or product ID activation tables.
- Evidence stays redacted: no serial, bus location, `/dev` name, username, absolute path, raw report bytes, or image content. Unknown interface evidence is summarized, never dumped.
- One task at a time with RED → observed expected failure → GREEN → focused regression → review → commit. No push, no publish, no GitHub mutation under this plan.

---

## File Map

- Modify `src/streamdock_n3/hardware/contracts.py`: `InterfaceRole`, `RoleBasis`, `HidInterfaceRole`, `RoleResolutionStatus`, `InterfaceRoleResolution`, two new `ErrorCode` values, and the `StageManifest.role_resolution` field.
- Create `src/streamdock_n3/hardware/interface_roles.py`: pure `InterfaceRoleEvidence` and the classifier/resolution functions.
- Modify `src/streamdock_n3/hardware/gate.py`: validate G1 role resolution on begin, pin roles at G1 commit, fail closed on role drift, expose approved roles.
- Modify `src/streamdock_n3/hardware/adapter.py`: require a resolved role manifest for G1, expose the approved profile record, record approval evidence.
- Modify `src/streamdock_n3/hardware/evidence.py`: a profile-approval evidence kind with role summary and approval reference.
- Modify `src/streamdock_n3/discovery.py`: gather per-interface input-subsystem evidence and emit role classification in the JSON output.
- Modify `src/streamdock_n3/device_catalog.py` only if a redacted role summary type must live there (preferred: keep roles in hardware contracts; do not change catalog semantics).
- Modify `tests/hardware_fixtures.py`: role evidence fixtures for all interface topologies.
- Create `tests/test_hardware_interface_roles.py`: classifier rules and resolution statuses.
- Modify `tests/test_hardware_contracts.py`: role contract validation and manifest field coverage.
- Modify `tests/test_hardware_gate.py`: G1 role pinning, ambiguity, drift, and completeness blocks.
- Modify `tests/test_hardware_adapter.py`: G1 approval path and approval record regressions.
- Modify `tests/test_hardware_evidence.py`: profile-approval evidence and redaction.
- Modify `tests/test_discovery.py` and `tests/test_discovery_cli.py`: role output contract.
- Modify `tests/test_discovery_safety.py`: new read-surface guards and no-`/dev` proof.
- Modify `tests/test_public_project.py`: G1 approval is a candidate decision, not compatibility.
- Modify `docs/ARCHITECTURE.md`, `ROADMAP.md`, `README.md`, `README.zh-CN.md`: G1 scope and truthfulness.
- Create `docs/validation/2026-08-XX-g1-profile-approval.md`: sanitized real-device role evidence and approval (only after the owner-gated evidence run).
- Modify `tests/test_hardware_g0_safety.py` only if a reviewed source hash must change; record the byte review in the task.

---

## Interface Ledger

The names in this ledger are authoritative across every task:

```python
class InterfaceRole(StrEnum):
    INPUT = "input"
    CONTROL = "control"
    UNKNOWN = "unknown"

class RoleBasis(StrEnum):
    BOOT_KEYBOARD = "boot_keyboard"          # HID class 03 / subclass 01 / protocol 01
    HID_INTERFACE = "hid_interface"          # fallback basis for UNKNOWN roles (added during Task 1 review)
    INPUT_SUBSYSTEM = "input_subsystem"      # interface owns an input device with EV_KEY
    VENDOR_HID = "vendor_hid"                # HID class 03 / subclass 00 / protocol 00
    NO_INPUT_ASSOCIATION = "no_input_association"

class RoleResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"

@dataclass(frozen=True, slots=True)
class HidInterfaceRole:
    interface: HidInterface
    role: InterfaceRole
    basis: tuple[RoleBasis, ...]   # non-empty, sorted, unique
    # to_dict() -> redacted summary; no paths, no serials

@dataclass(frozen=True, slots=True)
class InterfaceRoleResolution:
    roles: tuple[HidInterfaceRole, ...]      # >= 2, unique interface numbers
    status: RoleResolutionStatus
    input_interface: HidInterface | None     # non-None iff RESOLVED
    control_interface: HidInterface | None   # non-None iff RESOLVED
    # __post_init__: status/fields consistent; digest() canonical

# hardware/interface_roles.py
@dataclass(frozen=True, slots=True)
class InterfaceRoleEvidence:
    interface: HidInterface
    input_associated: bool            # interface owns an input subsystem device
    input_kind: str | None            # "keyboard" | "other" | None

def classify_interface_role(evidence: InterfaceRoleEvidence) -> HidInterfaceRole
def resolve_roles(evidence: tuple[InterfaceRoleEvidence, ...]) -> InterfaceRoleResolution
```

New `ErrorCode` values: `INTERFACE_AMBIGUITY = "interface_ambiguity"` and
`PROFILE_EVIDENCE_INCOMPLETE = "profile_evidence_incomplete"`.

`StageManifest` gains `role_resolution: InterfaceRoleResolution | None = None`
(default keeps existing G0 fixtures valid; G1 and later hardware stages must
provide it, enforced by the gate, not by the contract alone).

`_CapabilityGate` gains `approved_roles: InterfaceRoleResolution | None` and a
`RoleResolutionStatus` consistency check on `begin` for `Stage.G1_PROFILE`.

Classification rules (exact, documented, no guessing):

1. `BOOT_KEYBOARD` (class `03`, subclass `01`, protocol `01`) → `INPUT`.
2. `INPUT_SUBSYSTEM` with `input_kind == "keyboard"` → `INPUT`.
3. `VENDOR_HID` (class `03`, subclass `00`, protocol `00`) with
   `input_associated is False` → `CONTROL` (basis `VENDOR_HID` +
   `NO_INPUT_ASSOCIATION`). This is an owner-approved inference: the interface
   has no registered input device and is the only remaining HID interface.
4. Everything else → `UNKNOWN` (basis `HID_INTERFACE`).

An `INPUT` role accumulates every applicable basis: a boot keyboard that also
owns a keyboard input association carries both `BOOT_KEYBOARD` and
`INPUT_SUBSYSTEM`.

Resolution: exactly one `INPUT` and exactly one `CONTROL` and zero `UNKNOWN` →
`RESOLVED`; otherwise `AMBIGUOUS`. `AMBIGUOUS` blocks G1 with
`INTERFACE_AMBIGUITY`. A G1 manifest whose `role_resolution` is `None` or whose
roles are incomplete blocks with `PROFILE_EVIDENCE_INCOMPLETE`.

---

### Task 1: Interface Role Contracts and Pure Classifier

**Files:**
- Modify: `src/streamdock_n3/hardware/contracts.py`
- Create: `src/streamdock_n3/hardware/interface_roles.py`
- Create: `tests/test_hardware_interface_roles.py`
- Modify: `tests/test_hardware_contracts.py`

**Interfaces:**
- Consumes: existing `HidInterface`, `StageManifest`, `ErrorCode`, `Stage`.
- Produces: `InterfaceRole`, `RoleBasis`, `HidInterfaceRole`, `RoleResolutionStatus`,
  `InterfaceRoleResolution`, `INTERFACE_AMBIGUITY`, `PROFILE_EVIDENCE_INCOMPLETE`,
  `InterfaceRoleEvidence`, `classify_interface_role`, `resolve_roles`.

- [ ] **Step 1: Write classifier RED tests**

Create `tests/test_hardware_interface_roles.py` with these concrete behaviors:

```python
def test_boot_keyboard_class_is_input() -> None:
    evidence = InterfaceRoleEvidence(HidInterface(1, 3, 1, 1), True, "keyboard")
    assert classify_interface_role(evidence).role is InterfaceRole.INPUT
    assert RoleBasis.BOOT_KEYBOARD in classify_interface_role(evidence).basis

def test_input_subsystem_keyboard_without_boot_class_is_input() -> None:
    evidence = InterfaceRoleEvidence(HidInterface(1, 3, 0, 0), True, "keyboard")
    assert classify_interface_role(evidence).role is InterfaceRole.INPUT

def test_vendor_hid_without_input_association_is_control() -> None:
    evidence = InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None)
    role = classify_interface_role(evidence)
    assert role.role is InterfaceRole.CONTROL
    assert RoleBasis.VENDOR_HID in role.basis
    assert RoleBasis.NO_INPUT_ASSOCIATION in role.basis

def test_unknown_topology_is_unknown_role() -> None:
    evidence = InterfaceRoleEvidence(HidInterface(2, 3, 0, 0), False, None)
    assert classify_interface_role(evidence).role is InterfaceRole.UNKNOWN

def test_m1_topology_resolves_input_and_control() -> None:
    evidence = (
        InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None),
        InterfaceRoleEvidence(HidInterface(1, 3, 1, 1), True, "keyboard"),
    )
    resolution = resolve_roles(evidence)
    assert resolution.status is RoleResolutionStatus.RESOLVED
    assert resolution.input_interface == HidInterface(1, 3, 1, 1)
    assert resolution.control_interface == HidInterface(0, 3, 0, 0)

def test_two_input_candidates_are_ambiguous() -> None:
    evidence = (
        InterfaceRoleEvidence(HidInterface(0, 3, 1, 1), True, "keyboard"),
        InterfaceRoleEvidence(HidInterface(1, 3, 1, 1), True, "keyboard"),
    )
    assert resolve_roles(evidence).status is RoleResolutionStatus.AMBIGUOUS

def test_zero_roles_are_invalid() -> None:
    with pytest.raises(ValueError):
        resolve_roles(())

def test_single_role_is_incomplete_and_invalid() -> None:
    with pytest.raises(ValueError):
        resolve_roles((InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None),))
```

Also add contract RED tests to `tests/test_hardware_contracts.py`:

- `InterfaceRoleResolution` with an `AMBIGUOUS` status must have `input_interface is None` and `control_interface is None`; a `RESOLVED` record must have both set; an inconsistent record raises.
- `HidInterfaceRole.basis` must be a non-empty tuple of `RoleBasis` values, sorted, without duplicates.
- `StageManifest` accepts `role_resolution=None` for existing stages and carries a resolved resolution for G1 without raising in the contract layer.

- [ ] **Step 2: Run the contract and classifier tests and observe RED**

Run: `uv run pytest tests/test_hardware_interface_roles.py tests/test_hardware_contracts.py -q`

Expected: imports fail because the new names do not exist; then behavioral tests fail.

- [ ] **Step 3: Implement the role contracts**

Add to `contracts.py` after `HidInterface`:

```python
class InterfaceRole(StrEnum):
    INPUT = "input"
    CONTROL = "control"
    UNKNOWN = "unknown"


class RoleBasis(StrEnum):
    BOOT_KEYBOARD = "boot_keyboard"
    INPUT_SUBSYSTEM = "input_subsystem"
    VENDOR_HID = "vendor_hid"
    NO_INPUT_ASSOCIATION = "no_input_association"


class RoleResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
```

Add the frozen dataclasses `HidInterfaceRole` and `InterfaceRoleResolution`
exactly as in the Interface Ledger, with `__post_init__` validation:

- `HidInterfaceRole`: interface is a `HidInterface`; role is an `InterfaceRole`;
  basis is a non-empty sorted tuple of unique `RoleBasis` values.
- `InterfaceRoleResolution`: roles is a tuple of at least two `HidInterfaceRole`
  values with unique `interface.number` values; when `status is RESOLVED` exactly
  one role has role `INPUT` and exactly one has role `CONTROL`, no role is
  `UNKNOWN`, and `input_interface`/`control_interface` equal those role
  interfaces; when `status is AMBIGUOUS` both are `None` and at least one
  `UNKNOWN` role or a duplicate role exists. `to_dict()` returns only redacted
  stable fields; `digest()` returns a canonical SHA-256.

Add the two new `ErrorCode` members and the `role_resolution` field on
`StageManifest` (`InterfaceRoleResolution | None = None`, validated as an
`InterfaceRoleResolution` or `None`). `StageManifest.digest()` covers the field.

- [ ] **Step 4: Implement the pure classifier**

Create `hardware/interface_roles.py`:

```python
@dataclass(frozen=True, slots=True)
class InterfaceRoleEvidence:
    interface: HidInterface
    input_associated: bool
    input_kind: str | None

def classify_interface_role(evidence: InterfaceRoleEvidence) -> HidInterfaceRole
def resolve_roles(evidence: tuple[InterfaceRoleEvidence, ...]) -> InterfaceRoleResolution
```

The module imports only `streamdock_n3.hardware.contracts` and the standard
library. Apply the classification rules from the Interface Ledger verbatim.

- [ ] **Step 5: Run focused regressions**

Run: `uv run pytest tests/test_hardware_interface_roles.py tests/test_hardware_contracts.py tests/test_hardware_gate.py tests/test_hardware_adapter.py tests/test_hardware_fake_backend.py -q`

Expected: all tests pass, including the existing G0 suites (fixture manifests
still default `role_resolution=None`).

- [ ] **Step 6: Run lint, strict types, and commit Task 1**

```bash
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Then commit with `git add` of only this task's files and message
`feat: define interface role contracts and classifier`.

---

### Task 2: G1 Manifest, Gate Pinning, and Failure-Closed Regressions

**Files:**
- Modify: `src/streamdock_n3/hardware/gate.py`
- Modify: `src/streamdock_n3/hardware/adapter.py`
- Modify: `tests/hardware_fixtures.py`
- Modify: `tests/test_hardware_gate.py`
- Modify: `tests/test_hardware_adapter.py`

**Interfaces:**
- Consumes: Task 1 contracts and classifier.
- Produces: gate-level G1 role validation, role pinning at G1 commit, approved-role exposure, and BLOCK regressions.

- [ ] **Step 1: Write gate RED tests**

Add to `tests/hardware_fixtures.py`:

- `make_resolved_roles()` returning the M1 topology resolution (interface `00`
  → CONTROL, interface `01` → INPUT, `RESOLVED`).
- `make_g1_manifest(ambiguous: bool = False)` returning a G1 manifest carrying
  `role_resolution` from `make_resolved_roles()`, or an `AMBIGUOUS` resolution
  when `ambiguous=True`.
- `make_incomplete_g1_manifest()` returning a G1 manifest with
  `role_resolution=None`.

Add to `tests/test_hardware_gate.py`:

```python
def test_g1_begin_rejects_ambiguous_role_resolution() -> None:
    gate = _CapabilityGate()
    with pytest.raises(GateViolation) as raised:
        gate.begin(make_profile(), make_g1_manifest(ambiguous=True), TEST_COMMIT)
    assert raised.value.code is ErrorCode.INTERFACE_AMBIGUITY
    assert gate.state is AdapterState.CANDIDATE

def test_g1_begin_rejects_missing_role_resolution() -> None:
    gate = _CapabilityGate()
    with pytest.raises(GateViolation) as raised:
        gate.begin(make_profile(), make_incomplete_g1_manifest(), TEST_COMMIT)
    assert raised.value.code is ErrorCode.PROFILE_EVIDENCE_INCOMPLETE
    assert gate.state is AdapterState.CANDIDATE

def test_g1_commit_pins_roles_and_later_role_drift_blocks() -> None:
    gate = _CapabilityGate()
    gate.begin(make_profile(), make_g1_manifest(), TEST_COMMIT)
    reservation = gate.reserve_forward(AdapterCommand(Operation.APPROVE_PROFILE))
    gate.settle(reservation, success())
    preview = gate.preview_completion(True, None)
    assert gate.commit(preview, lambda: None) is AdapterState.PROFILE_APPROVED
    assert gate.approved_roles is not None
    assert gate.approved_roles.status is RoleResolutionStatus.RESOLVED

    drift_manifest = make_g1_manifest(ambiguous=True)
    with pytest.raises(GateViolation) as raised:
        gate.begin(make_profile(), drift_manifest, TEST_COMMIT)
    assert raised.value.code is ErrorCode.PROFILE_MISMATCH
    assert gate.state is AdapterState.BLOCKED
```

Also add: a later hardware stage (e.g. G3) whose manifest carries roles different
from the pinned ones blocks with `PROFILE_MISMATCH`, and one whose manifest
carries `role_resolution=None` after pinning blocks with `PROFILE_MISMATCH`.

- [ ] **Step 2: Run the gate tests and observe RED**

Run: `uv run pytest tests/test_hardware_gate.py -q`

Expected: new tests fail; existing tests pass.

- [ ] **Step 3: Implement gate role validation and pinning**

In `_CapabilityGate`:

- Add `self._approved_roles: InterfaceRoleResolution | None = None` in `__init__`
  and reset it in `_clear_session()`.
- Add `approved_roles` property.
- In `begin`, when `manifest.stage is Stage.G1_PROFILE` and
  `self._profile_digest is None`: after the existing identity/`MANIFEST_INVALID`
  validation (which keeps priority), require `manifest.role_resolution` is not
  None (else raise `PROFILE_EVIDENCE_INCOMPLETE`) and has `status is RESOLVED`
  (else raise `INTERFACE_AMBIGUITY`). Raise `GateViolation` directly at
  CANDIDATE state, matching the existing `MANIFEST_INVALID` semantics: the
  gate stays `CANDIDATE` and remains recoverable with new evidence — it is not
  blocked. (Drift after pinning, by contrast, blocks via the existing
  `_block_and_clear()` path.)
- In `begin`, when the gate is already pinned (`self._profile_digest` not None):
  add `manifest.role_resolution == self._approved_roles` to the drift checks;
  mismatch goes through the existing `_block_and_clear()` + `PROFILE_MISMATCH`
  path.
- In `commit`, when `manifest.stage is Stage.G1_PROFILE and preview.next_state is
  AdapterState.PROFILE_APPROVED`: pin `self._approved_roles` from the manifest.

Do not change `CapabilitySnapshot` or `CommandPolicy` signatures.

- [ ] **Step 4: Add adapter-level regressions**

Add to `tests/test_hardware_adapter.py`:

- G1 approval through `N3Adapter` with a resolved manifest ends in
  `PROFILE_APPROVED`, exposes `approved_profile` with input/control interfaces,
  and records one profile-approval evidence record.
- A G1 manifest with `role_resolution=None` fails at `begin_stage` with
  `PROFILE_EVIDENCE_INCOMPLETE` and the adapter stays CANDIDATE.
- After approval, a later stage with drifted roles fails at `begin_stage` with
  `PROFILE_MISMATCH` and the adapter is BLOCKED.

- [ ] **Step 5: Implement adapter approval flow**

In `N3Adapter`:

- `begin_stage` propagates the gate's new `INTERFACE_AMBIGUITY` /
  `PROFILE_EVIDENCE_INCOMPLETE` rejections unchanged.
- Add `approved_profile` property returning a redacted record when state is
  `PROFILE_APPROVED` or later: profile digest, bcdDevice, input interface,
  control interface, role resolution digest, approval reference, pinned commit.
- `complete_stage` already requires `manual_confirmation`; ensure the G1 path
  records approval evidence (see Task 3) before returning `PROFILE_APPROVED`.

- [ ] **Step 6: Run focused gate and adapter regressions**

Run: `uv run pytest tests/test_hardware_gate.py tests/test_hardware_adapter.py tests/test_hardware_interface_roles.py -q`

- [ ] **Step 7: Run lint, strict types, and commit Task 2**

```bash
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Commit: `feat: pin active profile roles at the G1 gate`.

---

### Task 3: Profile-Approval Evidence and Redaction

**Files:**
- Modify: `src/streamdock_n3/hardware/evidence.py`
- Modify: `tests/test_hardware_evidence.py`
- Modify: `tests/test_hardware_adapter.py`

**Interfaces:**
- Consumes: Task 1 role contracts and Task 2 pinning.
- Produces: a profile-approval `EvidenceKind`, redacted role summary in records, and failure-closed evidence behavior for G1 approval.

- [ ] **Step 1: Write evidence RED tests**

Add to `tests/test_hardware_evidence.py`:

- A `PROFILE_APPROVAL` record accepts the resolved role summary, stores
  `approval_reference` and the role `digest()`, and renders to JSON with no
  serial, path, username, or raw payload field (assert absent keys).
- A record whose kind is `PROFILE_APPROVAL` rejects non-role-summary payloads
  (e.g. `operation` set, or payload_size > 0).
- The redaction guard rejects any record whose JSON would contain a `/dev/`,
  `/sys/`, `input[0-9]`, or serial-looking token.
- G1 approval failure still follows the existing evidence transaction: a
  throwing external sink before G1 commit blocks with `EVIDENCE_FAILURE` or
  `STALE_RESERVATION` and never reaches `PROFILE_APPROVED` (reuse the adapter
  regression pattern from `test_hardware_adapter.py`).

- [ ] **Step 2: Run evidence tests and observe RED**

Run: `uv run pytest tests/test_hardware_evidence.py -q`

- [ ] **Step 3: Implement the profile-approval evidence kind**

In `evidence.py`:

- Add `EvidenceKind.PROFILE_APPROVAL = "profile_approval"`.
- Extend `EvidenceRecord` with an optional `role_resolution_digest:
  str | None = None` field validated as a 64-hex digest when set.
- For `PROFILE_APPROVAL` records: `operation`, `status`, `error_code`,
  `payload_size`, `duration_ms`, `event_count` must be `None`/0 and
  `role_resolution_digest` must be present; the record still carries stage,
  commit, profile_digest, interface, approval_reference, expected_result, and
  recovery_plan exactly as existing kinds.
- Keep JSON rendering deterministic and redacted (reuse the existing canonical
  renderer).

- [ ] **Step 4: Wire approval evidence into the adapter**

In `N3Adapter.complete_stage`, when the G1 commit is about to be pinned, emit a
`PROFILE_APPROVAL` evidence record with the resolved role digest and the
manifest's `approval_reference` before the gate precommit callback, so a sink
failure still blocks the commit (existing machinery already enforces this; the
test must prove it for the G1 path).

- [ ] **Step 5: Run focused evidence and adapter regressions**

Run: `uv run pytest tests/test_hardware_evidence.py tests/test_hardware_adapter.py tests/test_hardware_gate.py -q`

- [ ] **Step 6: Run lint, strict types, and commit Task 3**

Commit: `feat: record redacted profile approval evidence`.

---

### Task 4: Passive Sysfs Role Evidence and CLI Output

**Files:**
- Modify: `src/streamdock_n3/discovery.py`
- Modify: `tests/test_discovery.py`
- Modify: `tests/test_discovery_cli.py`
- Modify: `tests/test_discovery_safety.py`

**Interfaces:**
- Consumes: Task 1 classifier; M1 scanner and path policy.
- Produces: per-interface `role` and `role_basis` in the JSON output and a derived `interface_selection` of `resolved` / `ambiguous` / `none`, plus new read-surface safety guards.

- [ ] **Step 1: Write scanner RED tests**

Add to `tests/test_discovery.py`, using the existing fixture-dir scanner:

- A fixture device with interface `00` (`03/00/00`, no input association) and
  interface `01` (`03/01/01`, with `input/inputX` containing
  `capabilities/ev` with `EV_KEY` and a non-empty `capabilities/key`) produces
  `interface_selection == "resolved"`, per-interface roles `control`/`input`,
  and redacted role bases.
- A fixture where both interfaces have input associations produces
  `interface_selection == "ambiguous"` with per-interface roles.
- A fixture with no HID interfaces keeps `interface_selection == "none"`.
- The role fields never contain paths (`inputX` appears only as a redacted
  summary like `"input_association": true`), and no serial or bus number leaks.

Add to `tests/test_discovery_cli.py`:

- `--json` output includes `role` and `role_basis` per HID interface and the new
  `interface_selection` values; exit codes unchanged.

Add to `tests/test_discovery_safety.py`:

- The scanner reads input capability bitmaps only under the already-approved
  real-path root in `/sys/devices`; a symlink from an input `capabilities`
  directory pointing outside the approved root is rejected (dangling/foreign
  link test).
- Assert the scanner never reads `/dev`, `/sys/kernel/debug`, or
  `/sys/class/input` roots, and no read path contains `input[0-9]+` as a
  prefix root.

- [ ] **Step 2: Run discovery tests and observe RED**

Run: `uv run pytest tests/test_discovery.py tests/test_discovery_cli.py tests/test_discovery_safety.py -q`

- [ ] **Step 3: Extend the scanner with input-subsystem evidence**

In `discovery.py`:

- For each HID interface with a real path inside the approved `/sys/devices`
  root: look for `input/` subdirectories (input associations). For each
  association, read `capabilities/ev` (bitmap string) and, when `EV_KEY` is
  set, `capabilities/key` (bitmap string). Summarize as
  `input_associated: bool` and `input_kind: "keyboard" | "other"` — a keyboard
  iff `EV_KEY` is set and the key bitmap has any non-zero bit. Do not store the
  raw bitmaps or paths in any output.
- Classify each interface with `classify_interface_role` from
  `hardware/interface_roles.py` and emit `role` (`input`/`control`/`unknown`)
  plus a sorted list of role bases per interface in `to_dict()`.
- Derive `interface_selection` from `resolve_roles(...)`: `resolved`,
  `ambiguous`, or `none` when no HID interfaces exist. Keep the existing warning
  behavior; an `ambiguous` selection still warns and exits as today.
- Keep the strict link policy: every resolved real path must be under the
  approved roots; any foreign or dangling link rejects that association
  (classified as `input_associated: False` with a warning), never follows.

- [ ] **Step 4: Update fixtures and safety guards**

- Extend the fixture tree helpers with the new `input/inputX/capabilities/ev|key`
  layout, including foreign-link and dangling-link fixtures.
- Extend the static source guard to assert `discovery.py` contains no `/dev/`
  root reads and no `class/input` root reads.

- [ ] **Step 5: Run focused discovery regressions**

Run: `uv run pytest tests/test_discovery.py tests/test_discovery_cli.py tests/test_discovery_safety.py tests/test_public_project.py -q`

- [ ] **Step 6: Run the full suite, lint, strict types, and commit Task 4**

```bash
uv run pytest
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Commit: `feat: derive interface roles from passive sysfs evidence`.

---

### Task 5: Public Truth, Docs, and Owner-Gated Real-Device Evidence

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `ROADMAP.md`
- Modify: `README.md` and `README.zh-CN.md`
- Modify: `tests/test_public_project.py`
- Create: `docs/validation/2026-08-XX-g1-profile-approval.md` (owner-gated run only)

**Interfaces:**
- Consumes: implemented Tasks 1–4.
- Produces: truthful public G1 status and one sanitized real-device approval record when the owner authorizes the evidence run.

- [ ] **Step 1: Update public truth assertions first**

Change `tests/test_public_project.py` to require:

- README/ARCHITECTURE describe G1 as approving a candidate profile and interface
  responsibilities from passive evidence; `6602:1000` remains a
  candidate/unvalidated identifier; input and control roles are approved
  candidate roles pending G3 physical validation.
- The public files assert G1 role approval does not create a
  supported/已支持 claim, and G3–G7 remain planned M2 work.

- [ ] **Step 2: Run public assertions and observe RED**

Run: `uv run pytest tests/test_public_project.py -q`

Expected: failures because docs still describe only the G0 foundation.

- [ ] **Step 3: Update ARCHITECTURE, ROADMAP, and READMEs**

- `docs/ARCHITECTURE.md`: describe the implemented G1 boundary — passive
  interface-role evidence, explicit profile approval, role pinning, and the
  still-unopened device boundary; keep the G0 flow text intact.
- `ROADMAP.md`: mark G1 complete **only after** the owner-gated evidence run and
  approval record exist; otherwise leave unchecked and describe G1 as in
  progress. Do not mark G2–G7.
- READMEs: add the G1 candidate-profile wording without claiming support.

- [ ] **Step 4: Owner-gated real-device evidence run**

Only after the product owner explicitly approves this plan and the exact
command:

```bash
uv run n3-ai-deck-detect --json
```

Record into `docs/validation/2026-08-XX-g1-profile-approval.md` (sanitized):
date, tested commit, command, actual USB ID, bcdDevice, per-interface
class/subclass/protocol, per-interface role + basis, resolution status, the
owner's approval reference, and the explicit statement that no `/dev`, SDK,
permission, or hardware write occurred. If the real-device resolution is
`AMBIGUOUS`, record the evidence requirement, keep G1 BLOCKED, and stop.

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

Give the reviewer the M2 PRD, the M2 design, the transactional safety design,
this plan, and the full branch diff. Require explicit findings for:

1. G1 never opens `/dev` and never loads the SDK; the only new read surface is
   passive sysfs under the approved root.
2. M1 observation cannot auto-approve a profile; approval requires
   `manual_confirmation` plus a resolved role manifest.
3. Ambiguity, missing/incomplete role evidence, and any identity/interface/role
   drift fail closed (`INTERFACE_AMBIGUITY`, `PROFILE_EVIDENCE_INCOMPLETE`,
   `PROFILE_MISMATCH`) with no guessing fallback.
4. Roles are pinned at G1 commit and later manifests must match exactly.
5. Approval evidence is mandatory, redacted, and a sink failure still blocks
   the commit.
6. Public truth keeps `6602:1000` candidate/unvalidated; no supported/已支持
   claim; G3–G7 remain planned.
7. The real-device evidence run happened only under explicit owner approval and
   produced a sanitized record.
8. No SDK activation, `/dev` access, udev/ACL/system change, hardware write,
   push, or publication occurred.

Expected: `APPROVED` with no Critical or Important findings.

- [ ] **Step 7: Record local progress and stop**

Write commit IDs, check results, full-package mypy baseline, reviewer verdict,
and the approval reference into the ignored `.superpowers/sdd/progress.md`. Do
not stage it. Report completion locally and stop; do not push or publish.

---

## Completion Checklist

- [ ] Interface roles and basis are contract-validated, deterministic, and redacted.
- [ ] The classifier implements the four documented rules; any other topology is `UNKNOWN`.
- [ ] `RESOLVED` means exactly one input and one control interface; everything else is `AMBIGUOUS`.
- [ ] G1 requires an explicit resolved role manifest and `manual_confirmation`; M1 observation alone approves nothing.
- [ ] Ambiguity and incomplete evidence reject G1 begin fail-closed at CANDIDATE (recoverable with new evidence); identity/interface/role drift after pinning blocks fail-closed.
- [ ] Roles pinned at G1 commit match every later manifest exactly.
- [ ] Profile approval evidence is mandatory, redacted, and sink-failure-blocked.
- [ ] The scanner gathers input-subsystem evidence passively under the approved root with strict link policy.
- [ ] Public docs keep `6602:1000` candidate/unvalidated; G2–G7 remain unchecked.
- [ ] The real-device evidence run (if performed) is owner-approved, sanitized, and recorded.
- [ ] pytest, Ruff, strict G1 typing, full-package mypy baseline, build, diff check, and independent review pass.
- [ ] No `/dev` access, SDK load, permission change, hardware write, push, or publication occurred.
