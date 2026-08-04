# M2 G2 Minimal Linux Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Design, generate, and offline-test minimal permission artifacts for the G1-approved candidate profile (input interface `01`, control interface `00`) without ever writing system state, and record one owner-approved permission plan at the G2 gate. Actual ACL/udev installation, reload, trigger, replug, and systemctl remain separate manual actions before G3.

**Architecture:** A new pure generation module (`hardware/permissions.py`) renders two offline artifacts from the pinned G1 role resolution: a temporary single-node ACL plan and a precise persistent udev rule template using `TAG+="uaccess"`. An offline install transaction verifies and applies artifacts only against an explicit target root (never `/etc` or `/usr`), computing before/after diff and rollback. The `N3Adapter` G2 stage requires the plan in its manifest, verifies it against the pinned roles, and records redacted permission-approval evidence after `manual_confirmation`.

**Tech Stack:** Python 3.11+, frozen/slotted dataclasses, `StrEnum`, SHA-256, pytest, Ruff, mypy strict, Hatchling/uv. Standard library only.

## Global Constraints

- Sources of truth, in order: `tasks/prd-m2-n3-v3-hardware-controls.md` version 1.0, `docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md` (section 8 权限设计), and `docs/superpowers/specs/2026-08-03-m2-g0-transactional-adapter-safety-design.md`.
- G2 produces offline templates and tests only. No command under this plan writes `/etc`, `/usr`, runs `udevadm`, `systemctl`, `setfacl`/`getfacl`, `chown`, `chmod`, `sudo`, triggers replug, or installs/uninstalls anything on the host.
- The persistent rule is a lazy template generated in the repository, matching exactly `6602:1000` plus the validated subsystem/interface, using `TAG+="uaccess"`. Forbidden: vendor-only matching, `MODE="0666"`, unproven combined USB/hidraw/input grants, and adding the user to a generic input-reading group.
- The default first real-device strategy remains: no persistent rule; prefer a temporary single-node ACL for the current user, applied only as a separate manual action.
- Permission grants derive from G1-approved roles only: input interface `01` justifies the input subsystem; control interface `00` justifies hidraw. No other subsystem may be granted.
- The G2 dependency closure remains standard-library-only plus the safe M1 `device_catalog` contracts. The generation module must never execute subprocesses, never open files for writing, and never read `/dev` or sysfs.
- Do not modify `src/streamdock_n3/_vendor`, `src/streamdock_n3/_data/99-streamdock.rules`, legacy daemon/probe/debug/GUI/install paths, or product ID activation tables. The legacy `0666` rules file stays untouched as the forbidden reference.
- Evidence stays redacted: no serial, bus location, `/dev` name, username, absolute path, or raw bitmap. Plan digests are canonical SHA-256 over redacted summaries.
- `6602:1000` remains an owner-reported candidate with unvalidated protocol; G2 templates are not a compatibility claim and grant nothing by themselves.
- One task at a time with RED → observed expected failure → GREEN → focused regression → review → commit. No push, no publish, no GitHub mutation under this plan.

---

## File Map

- Modify `src/streamdock_n3/hardware/contracts.py`: `PermissionKind`, `PermissionArtifact`, `PermissionPlan`, `StageManifest.permission_plan`, one new `ErrorCode` value.
- Create `src/streamdock_n3/hardware/permissions.py`: pure generators (temporary ACL plan, persistent udev rule), plan validation, and the offline install transaction.
- Modify `src/streamdock_n3/hardware/gate.py`: G2 begin requires a role-consistent permission plan; nothing is pinned beyond the G2 record (permissions are per-gate approvals).
- Modify `src/streamdock_n3/hardware/evidence.py`: `EvidenceKind.PERMISSION_APPROVAL` with the plan digest and approval reference.
- Modify `src/streamdock_n3/hardware/adapter.py`: G2 `complete_stage` records permission-approval evidence before the commit callback.
- Modify `tests/hardware_fixtures.py`: permission plan fixtures for the approved roles.
- Create `tests/test_hardware_permissions.py`: generator correctness, forbidden-rule rejection, redaction, and transaction behavior.
- Modify `tests/test_hardware_contracts.py`: permission contract validation.
- Modify `tests/test_hardware_gate.py`: G2 manifest requirement and role-consistency checks.
- Modify `tests/test_hardware_adapter.py`: G2 approval flow and evidence.
- Modify `tests/test_hardware_evidence.py`: permission-approval evidence and redaction.
- Modify `tests/test_hardware_g0_safety.py`: tenth reviewed module, refreshed hashes, no-write static guards for the generators.
- Modify `tests/test_public_project.py`, `docs/ARCHITECTURE.md`, `ROADMAP.md`, `README.md`, `README.zh-CN.md`: G2 offline boundary and truthful status.

---

## Interface Ledger

The names in this ledger are authoritative across every task:

```python
class PermissionKind(StrEnum):
    TEMPORARY_ACL = "temporary_acl"
    PERSISTENT_RULE = "persistent_rule"

@dataclass(frozen=True, slots=True)
class PermissionArtifact:
    kind: PermissionKind
    subsystem: str            # "input" or "hidraw"
    role: InterfaceRole       # INPUT for input, CONTROL for hidraw
    rendered: str             # setfacl command plan or udev rule text
    # redacted digest() over a stable summary that excludes usernames/paths/nodes

@dataclass(frozen=True, slots=True)
class PermissionPlan:
    artifacts: tuple[PermissionArtifact, ...]   # >= 2: one ACL plan + one rule template
    approval_reference: str
    # digest(); to_dict() redacted

# hardware/permissions.py
def temporary_acl_plan(role: InterfaceRole) -> PermissionArtifact
def persistent_rule(
    vendor_id: int, product_id: int,
    interface: HidInterface, role: InterfaceRole,
) -> PermissionArtifact
def make_permission_plan(
    resolution: InterfaceRoleResolution, approval_reference: str,
) -> PermissionPlan
class InstallTransaction:
    def __init__(self, root: Path) -> None   # explicit target root; never None for writes
    def plan_install(self, artifact: PermissionArtifact, filename: str) -> None
    def verify_target(self) -> list[str]      # symlink/owner/content guards -> violations
    def diff(self) -> str
    def commit(self) -> None
    def rollback(self) -> None
```

New `ErrorCode`: `PERMISSION_PLAN_INVALID = "permission_plan_invalid"`.

Rules (documented, no guessing):

1. A permission artifact is valid only for a subsystem justified by an approved G1 role:
   `INPUT` → `input`; `CONTROL` → `hidraw`; `UNKNOWN` → invalid.
2. The persistent rule matches `ATTR{idVendor}=="6602"` AND `ATTR{idProduct}=="1000"` AND the
   interface attribute tuple, uses `TAG+="uaccess"`, and never contains `MODE="0666"`,
   a vendor-only match, or combined subsystem grants in one rule.
3. The temporary ACL plan names exactly one node placeholder and the current-user placeholder;
   it is never executed by this plan.
4. `InstallTransaction` rejects any operation without an explicit root; a root equal to or
   containing `/etc` or `/usr` fails closed. Target verification rejects symlinks, wrong
   ownership, and externally modified content before commit; rollback restores the original
   bytes or reports a failure — it never fabricates success.

---

### Task 1: Permission Contracts and Pure Generators

**Files:**
- Modify: `src/streamdock_n3/hardware/contracts.py`
- Create: `src/streamdock_n3/hardware/permissions.py`
- Create: `tests/test_hardware_permissions.py`
- Modify: `tests/test_hardware_contracts.py`

**Interfaces:**
- Produces: `PermissionKind`, `PermissionArtifact`, `PermissionPlan`,
  `PERMISSION_PLAN_INVALID`, and the generator functions from the ledger.

- [ ] **Step 1: Write generator RED tests**

Create `tests/test_hardware_permissions.py` with these concrete behaviors:

```python
def test_input_role_justifies_input_subsystem() -> None:
    artifact = temporary_acl_plan(InterfaceRole.INPUT)
    assert artifact.kind is PermissionKind.TEMPORARY_ACL
    assert artifact.subsystem == "input"
    assert artifact.role is InterfaceRole.INPUT

def test_control_role_justifies_hidraw_subsystem() -> None:
    artifact = temporary_acl_plan(InterfaceRole.CONTROL)
    assert artifact.subsystem == "hidraw"

def test_unknown_role_cannot_generate_artifacts() -> None:
    with pytest.raises(ValueError):
        temporary_acl_plan(InterfaceRole.UNKNOWN)
    with pytest.raises(ValueError):
        persistent_rule(0x6602, 0x1000, HidInterface(0, 3, 0, 0), InterfaceRole.UNKNOWN)

def test_persistent_rule_is_exact_and_uaccess_only() -> None:
    rule = persistent_rule(0x6602, 0x1000, HidInterface(0, 3, 0, 0), InterfaceRole.CONTROL)
    assert 'ATTR{idVendor}=="6602"' in rule.rendered
    assert 'ATTR{idProduct}=="1000"' in rule.rendered
    assert 'TAG+="uaccess"' in rule.rendered
    assert 'MODE="0666"' not in rule.rendered
    assert 'SUBSYSTEM=="hidraw"' in rule.rendered

def test_plan_contains_both_artifacts_for_approved_roles() -> None:
    plan = make_permission_plan(make_resolved_roles(), "test:g2")
    assert {item.subsystem for item in plan.artifacts} == {"input", "hidraw"}
    assert len(plan.digest()) == 64
    assert plan.digest() == make_permission_plan(make_resolved_roles(), "test:g2").digest()

def test_plan_digest_changes_with_approval_reference() -> None:
    plan = make_permission_plan(make_resolved_roles(), "test:g2")
    changed = make_permission_plan(make_resolved_roles(), "owner:2026-08-04:g2")
    assert plan.digest() != changed.digest()

def test_plan_rendering_is_redacted() -> None:
    plan = make_permission_plan(make_resolved_roles(), "test:g2")
    rendered = json.dumps(plan.to_dict(), sort_keys=True)
    for forbidden in ("/dev/", "/home", "/srv", "user", "input12", "serial"):
        assert forbidden not in rendered
```

Also add contract RED tests to `tests/test_hardware_contracts.py`:
- `PermissionArtifact` rejects unknown kinds, empty rendered text, and unapproved role/subsystem pairs.
- `PermissionPlan` requires a non-empty tuple of artifacts with unique subsystem/kind pairs and a valid approval reference.
- `StageManifest` accepts `permission_plan=None` for existing stages and carries a plan for G2 without raising in the contract layer.
- `PERMISSION_PLAN_INVALID` exists with value `"permission_plan_invalid"`.

- [ ] **Step 2: Run the contract and generator tests and observe RED**

Run: `uv run pytest tests/test_hardware_permissions.py tests/test_hardware_contracts.py -q`

Expected: imports fail because the new names do not exist.

- [ ] **Step 3: Implement the permission contracts**

Add to `contracts.py` the `PermissionKind` enum, the frozen `PermissionArtifact`
and `PermissionPlan` dataclasses (validation as in the ledger), the new
`ErrorCode` member, and `StageManifest.permission_plan:
PermissionPlan | None = None` (validated as `PermissionPlan | None`;
`to_dict()` and `digest()` cover it).

- [ ] **Step 4: Implement the pure generators**

Create `hardware/permissions.py` importing only `streamdock_n3.hardware.contracts`
and the standard library. `persistent_rule` renders the exact rule; the input
rule targets `SUBSYSTEM=="input", KERNEL=="event*"` and the hidraw rule targets
`SUBSYSTEM=="hidraw"`, both with the exact `6602:1000` attribute match and the
interface class/subclass/protocol attributes, `TAG+="uaccess"` only. The ACL
plan renders a setfacl command plan with one node placeholder and one
current-user placeholder. `make_permission_plan` derives the subsystems from the
resolution's `input_interface`/`control_interface` roles and raises
`ValueError` (mapped later to `PERMISSION_PLAN_INVALID` at the gate) if the
resolution is not `RESOLVED`.

- [ ] **Step 5: Run focused regressions**

Run: `uv run pytest tests/test_hardware_permissions.py tests/test_hardware_contracts.py tests/test_hardware_gate.py tests/test_hardware_adapter.py -q`

- [ ] **Step 6: Run lint, strict types, and commit Task 1**

```bash
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Commit: `feat: define permission plan contracts and pure generators`.

---

### Task 2: Offline Install Transaction and Fixtures

**Files:**
- Modify: `src/streamdock_n3/hardware/permissions.py`
- Modify: `tests/test_hardware_permissions.py`

**Interfaces:**
- Produces: `InstallTransaction` with staged plan/verify/diff/commit/rollback against an explicit root.

- [ ] **Step 1: Write transaction RED tests**

- A transaction without an explicit root rejects every operation.
- A root equal to `/etc` or `/usr` (or containing either) fails closed.
- `verify_target` reports a symlink target, a wrong-owner target, and an
  externally modified (content changed since plan) target as violations.
- `diff()` shows before/after bytes; `commit()` writes the rendered artifact into
  the root; `rollback()` restores the original bytes exactly.
- A rollback failure is reported, never fabricated as success.
- Tests use only `tmp_path` roots; a test asserts no write occurs when root is
  `None` (monkeypatched `Path.write_text` must not be called).

- [ ] **Step 2: Run transaction tests and observe RED**

Run: `uv run pytest tests/test_hardware_permissions.py -q`

- [ ] **Step 3: Implement the offline transaction**

`InstallTransaction` keeps an ordered plan of `(artifact, filename)` pairs, a
snapshot of original bytes, and a commit/rollback log. All filesystem access is
scoped to the explicit root; the root guard rejects `/etc`, `/usr`, and
`None`. Verification happens before any write; `rollback()` restores the
snapshot byte-for-byte or records the failure.

- [ ] **Step 4: Run focused regressions and commit Task 2**

```bash
uv run pytest tests/test_hardware_permissions.py -q
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Commit: `feat: add offline permission install transaction`.

---

### Task 3: G2 Gate Requirement, Approval Evidence, and Adapter Flow

**Files:**
- Modify: `src/streamdock_n3/hardware/gate.py`
- Modify: `src/streamdock_n3/hardware/evidence.py`
- Modify: `src/streamdock_n3/hardware/adapter.py`
- Modify: `tests/hardware_fixtures.py`
- Modify: `tests/test_hardware_gate.py`
- Modify: `tests/test_hardware_adapter.py`
- Modify: `tests/test_hardware_evidence.py`

**Interfaces:**
- Produces: G2 manifest requirement, role-consistency check, `EvidenceKind.PERMISSION_APPROVAL`, and the adapter approval path.

- [ ] **Step 1: Write gate and evidence RED tests**

Add to `tests/test_hardware_gate.py`:

```python
def test_g2_begin_rejects_missing_permission_plan() -> None:
    gate = advance_through_g1()
    with pytest.raises(GateViolation) as raised:
        gate.begin(make_profile(), make_manifest(Stage.G2_PERMISSION), TEST_COMMIT)
    assert raised.value.code is ErrorCode.PERMISSION_PLAN_INVALID
    assert gate.state is AdapterState.BLOCKED

def test_g2_begin_rejects_plan_for_unapproved_roles() -> None:
    gate = advance_through_g1()
    plan = make_permission_plan(make_swapped_roles(), "test:g2")
    with pytest.raises(GateViolation) as raised:
        gate.begin(make_profile(), make_manifest(Stage.G2_PERMISSION, permission_plan=plan), TEST_COMMIT)
    assert raised.value.code is ErrorCode.PERMISSION_PLAN_INVALID
    assert gate.state is AdapterState.BLOCKED

def test_g2_with_approved_plan_records_and_stays_approved() -> None:
    gate = advance_through_g1()
    gate.begin(make_profile(), make_g2_manifest(), TEST_COMMIT)
    reservation = gate.reserve_forward(AdapterCommand(Operation.RECORD_PERMISSION))
    gate.settle(reservation, success())
    preview = gate.preview_completion(True, None)
    assert gate.commit(preview, lambda: None) is AdapterState.PROFILE_APPROVED
```

Add to `tests/test_hardware_evidence.py`:
- A `PERMISSION_APPROVAL` record requires the plan digest and approval reference,
  rejects operation payloads and non-zero counters, and renders redacted JSON.
- `test_hardware_adapter.py`: G2 approval through `N3Adapter` ends in
  `PROFILE_APPROVED`, records exactly one `PERMISSION_APPROVAL` committed
  evidence record, and a throwing sink before the G2 commit blocks the record.

- [ ] **Step 2: Run gate, evidence, and adapter tests and observe RED**

Run: `uv run pytest tests/test_hardware_gate.py tests/test_hardware_evidence.py tests/test_hardware_adapter.py -q`

- [ ] **Step 3: Implement the G2 gate requirement**

In `begin`, when `manifest.stage is Stage.G2_PERMISSION` and the gate is
pinned: require `manifest.permission_plan` is not None, its subsystems match the
pinned roles exactly (`INPUT` → `input`, `CONTROL` → `hidraw`), and its
artifacts are valid; otherwise `_block_and_clear()` + `PERMISSION_PLAN_INVALID`.
Do not pin the plan after G2: permissions are per-gate approvals, and later
stage manifests do not need it.

- [ ] **Step 4: Implement the permission-approval evidence**

Add `EvidenceKind.PERMISSION_APPROVAL = "permission_approval"`, a
`permission_plan_digest: str | None = None` field validated as a 64-hex digest
when set, and `permission_approval_evidence(profile, manifest, epoch)` with the
same closed/redacted shape as `profile_approval_evidence`. Extend
`profile_approval_evidence` validation so the two approval kinds reject each
other's digest field.

- [ ] **Step 5: Wire the adapter G2 path**

In `complete_stage`, when the manifest stage is `G2_PERMISSION` and the
`RECORD_PERMISSION` step is being committed, emit the `PERMISSION_APPROVAL`
record (before the precommit callback, so a sink failure still blocks) and keep
the `ApprovedProfile` unchanged.

- [ ] **Step 6: Run focused regressions and commit Task 3**

```bash
uv run pytest tests/test_hardware_gate.py tests/test_hardware_evidence.py tests/test_hardware_adapter.py -q
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
```

Commit: `feat: require and record the approved permission plan at G2`.

---

### Task 4: Static Safety Guards and Reviewed Closure

**Files:**
- Modify: `tests/test_hardware_g0_safety.py`

**Interfaces:**
- Produces: tenth reviewed module, refreshed hashes, and no-write static guards.

- [ ] **Step 1: Extend the reviewed closure**

Add `Path("src/streamdock_n3/hardware/permissions.py")` to `G0_MODULES` (this
extends `G0_SOURCE_CLOSURE`, `G0_IMPORTS`, `ALLOWED_PROJECT_IMPORTS`, wheel
expectations, and the module-set gates automatically). Update the exact-closure
test tuples and the reviewed-path count.

- [ ] **Step 2: Add no-write and no-process static guards**

Add to the safety test: `permissions.py` contains no `subprocess`, no
`os.open`, no `write_text`/`write_bytes` outside `InstallTransaction`, no
`/etc`, no `/usr`, and no `setfacl`/`udevadm`/`systemctl` invocation strings;
the ACL plan renders only placeholders.

- [ ] **Step 3: Refresh reviewed hashes**

```bash
sha256sum src/streamdock_n3/hardware/*.py | grep -E 'contracts|permissions|gate|evidence|adapter'
```

Copy the changed digests into `REVIEWED_SOURCE_SHA256`. Run:
`uv run pytest tests/test_hardware_g0_safety.py -q`; expected: all pass.

- [ ] **Step 4: Run the full suite and commit Task 4**

```bash
uv run pytest
uv run ruff check .
```

Commit: `test: extend reviewed G0 closure with permission generators`.

---

### Task 5: Public Truth, Docs, and Final Verification

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `ROADMAP.md`
- Modify: `README.md` and `README.zh-CN.md`
- Modify: `tests/test_public_project.py`

**Interfaces:**
- Produces: truthful public G2 status and full branch verification.

- [ ] **Step 1: Update public truth assertions first**

Change `tests/test_public_project.py` to require:

- ARCHITECTURE/ROADMAP describe G2 as offline permission design: temporary ACL
  preference, exact `6602:1000` + `TAG+="uaccess"` rule templates only, no
  `MODE="0666"`, no vendor-only match, no system write performed.
- ROADMAP keeps G2 unchecked and states the offline artifacts are implemented
  while the permission approval and any real installation remain owner-gated.
- `6602:1000` remains candidate/unvalidated; no supported/已支持 claim.

- [ ] **Step 2: Run public assertions and observe RED**

Run: `uv run pytest tests/test_public_project.py -q`

- [ ] **Step 3: Update ARCHITECTURE, ROADMAP, and READMEs**

- ARCHITECTURE: add the implemented G2 offline boundary paragraph (templates,
  transaction, redaction, and the no-system-write guarantee).
- ROADMAP: G2 bullet notes the offline artifacts are implemented and the gate
  approval plus any install remain owner-gated; keep G2 unchecked.
- READMEs: bilingual G2 wording without claiming any permission was granted.

- [ ] **Step 4: Final verification**

```bash
uv run pytest
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
uv run mypy src/streamdock_n3        # only the recorded 11 legacy errors
uv build
git diff --check
git diff --name-only da721af..HEAD   # no _vendor/_data/legacy paths
```

- [ ] **Step 5: Request one independent whole-branch safety review**

Give the reviewer the M2 PRD, the M2 design, this plan, and the full branch
diff. Require explicit findings for:

1. G2 never writes system state and never executes permission commands; the
   transaction only ever targets an explicit root outside `/etc`/`/usr`.
2. Rules match exactly `6602:1000` plus the validated subsystem/interface and use
   `TAG+="uaccess"`; no `MODE="0666"`, no vendor-only match, no combined grants.
3. The temporary ACL plan is the default first strategy and is never executed.
4. The G2 gate requires a role-consistent permission plan and fails closed on
   missing or mismatched plans.
5. Approval evidence is mandatory, redacted, and sink-failure-blocked.
6. Public truth keeps `6602:1000` candidate/unvalidated; no permission change
   occurred; G2 stays unchecked pending the owner gate.
7. No SDK activation, `/dev` access, udev/ACL/system change, hardware write,
   push, or publication occurred.

Expected: `APPROVED` with no Critical or Important findings.

- [ ] **Step 6: Record local progress and stop**

Write commit IDs, check results, full-package mypy baseline, and reviewer
verdict into the ignored `.superpowers/sdd/progress.md`. Report completion
locally and stop; do not push or publish.

---

## Completion Checklist

- [ ] Artifacts derive only from G1-approved roles; `UNKNOWN` cannot generate anything.
- [ ] The persistent rule is exact `6602:1000` + subsystem/interface + `TAG+="uaccess"`; forbidden forms are rejected by tests.
- [ ] The ACL plan uses placeholders only and is never executed.
- [ ] `InstallTransaction` requires an explicit root, rejects `/etc`/`/usr`, verifies symlink/owner/content before commit, and rolls back byte-for-byte.
- [ ] The G2 gate requires a role-consistent permission plan and fails closed otherwise.
- [ ] Permission approval evidence is mandatory, redacted, and sink-failure-blocked.
- [ ] The reviewed G0 closure covers the new module with refreshed hashes and no-write guards.
- [ ] Public docs describe G2 as offline design with no granted permissions; `6602:1000` stays candidate/unvalidated; G2 remains unchecked.
- [ ] pytest, Ruff, strict G2 typing, full-package mypy baseline, build, diff check, and independent review pass.
- [ ] No system write, permission execution, `/dev` access, SDK load, hardware write, push, or publication occurred.
