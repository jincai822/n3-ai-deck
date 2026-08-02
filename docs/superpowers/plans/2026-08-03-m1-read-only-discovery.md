# M1 Read-Only Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a product-level `n3-ai-deck-detect` command that safely reports USB ID matches and HID interface topology from Linux sysfs without loading the vendored SDK or accessing `/dev`.

**Architecture:** Add a stdlib-only passive catalog and a separate sysfs scanner/CLI inside `streamdock_n3`. The scanner has two path policies: real `/sys/bus/usb/devices` may follow device/interface links only into `/sys/devices`, while every other root rejects links. The active `ProductIDs.g_products`, daemon, probe, debug tool, installer, and udev data remain unchanged.

**Tech Stack:** Python 3.11+, dataclasses, `StrEnum`, pathlib, argparse, JSON, pytest, Ruff, mypy strict, Hatchling/uv.

## Global Constraints

- The approved source of truth is `tasks/prd-n3-v3-read-only-discovery.md` version 1.0.
- M1 production modules use the Python standard library only.
- Never import or call `streamdock_n3._vendor`, `DeviceManager`, native transport, GTK, `evdev`, or `pyudev` from the M1 dependency closure.
- Never enumerate, open, read, or write `/dev/hidraw*`, `/dev/input/event*`, or any other `/dev` node.
- Never change `src/streamdock_n3/_vendor/StreamDock/ProductIDs.py`, `src/streamdock_n3/_data/99-streamdock.rules`, systemd data, or system installer behavior.
- Never initialize hardware, change brightness, refresh displays, or send image/LCD data.
- Never read or publish USB serial, manufacturer, product, raw exception paths, usernames, or absolute workspace paths.
- `6602:1000` means an owner-reported N3 V3.0 candidate, not confirmed identity or protocol support.
- The real-device acceptance command is only `uv run n3-ai-deck-detect --json`; do not run old daemon, probe, debug, GUI, or install commands.
- Follow RED → verify expected failure → GREEN for every production behavior.
- Run focused tests after each story and full tests before the branch review.

---

## File Map

- Create `src/streamdock_n3/device_catalog.py`: passive USB IDs and separate identity/protocol states.
- Create `src/streamdock_n3/discovery.py`: safe path policy, sysfs parsing, report model, JSON/human rendering, CLI, and exit codes.
- Create `tests/test_device_catalog.py`: catalog normalization, lookup, validation, and duplicate protection.
- Create `tests/test_discovery.py`: fixture scanning, ordering, warnings, topology, and exit aggregation.
- Create `tests/test_discovery_cli.py`: human/JSON contract and CLI exit behavior.
- Create `tests/test_discovery_safety.py`: source/import/file-read guards and package entry-point checks.
- Modify `pyproject.toml`: add only the `n3-ai-deck-detect` console entry point.
- Modify `README.md` and `README.zh-CN.md`: safe command, candidate wording, warning about legacy active commands.
- Modify `docs/ARCHITECTURE.md`: implemented passive discovery boundary versus planned active adapter.
- Modify `ROADMAP.md`: M1 status and evidence.
- Modify `tests/test_public_project.py`: public wording and documentation assertions.
- Create `docs/validation/2026-08-03-n3-v3-read-only-discovery.md`: sanitized real-device evidence.
- Modify `tasks/m1-ai-coding-queue.json`: mark reviewed stories complete only after their gates pass.

---

### Task 1: Passive USB Device Catalog

**Files:**
- Create: `tests/test_device_catalog.py`
- Create: `src/streamdock_n3/device_catalog.py`

**Interfaces:**
- Produces: `IdentityStatus`, `ProtocolStatus`, `KnownUsbDevice`, `KNOWN_USB_DEVICES`, `TARGET_USB_ID`, `normalize_usb_id(value: int | str) -> int`, `format_usb_id(value: int | str) -> str`, and `find_known_usb_device(vendor_id: int | str, product_id: int | str) -> KnownUsbDevice | None`.
- `TARGET_USB_ID` is the integer tuple `(0x6602, 0x1000)`.

- [ ] **Step 1: Write failing catalog tests**

Create `tests/test_device_catalog.py` with these concrete behaviors:

```python
from __future__ import annotations

import pytest

from streamdock_n3.device_catalog import (
    KNOWN_USB_DEVICES,
    IdentityStatus,
    ProtocolStatus,
    find_known_usb_device,
    format_usb_id,
    normalize_usb_id,
)


def test_catalog_keeps_identity_and_protocol_evidence_separate() -> None:
    candidate = find_known_usb_device("6602", "1000")
    reference = find_known_usb_device(0x6603, 0x1003)

    assert candidate is not None
    assert candidate.catalog_name == "N3 V3.0 candidate (owner-reported)"
    assert candidate.identity_status is IdentityStatus.USER_REPORTED_CANDIDATE
    assert candidate.protocol_status is ProtocolStatus.UNVALIDATED
    assert reference is not None
    assert reference.identity_status is IdentityStatus.UPSTREAM_REFERENCE
    assert reference.protocol_status is ProtocolStatus.UPSTREAM_REFERENCE


@pytest.mark.parametrize(
    ("value", "normalized", "formatted"),
    ((0x2, 2, "0002"), ("6602", 0x6602, "6602"), (" 0XABCD ", 0xABCD, "abcd")),
)
def test_usb_ids_normalize_as_four_digit_hex(
    value: int | str, normalized: int, formatted: str
) -> None:
    assert normalize_usb_id(value) == normalized
    assert format_usb_id(value) == formatted


@pytest.mark.parametrize("value", (True, -1, 0x10000, "", "10000", "xyz", object()))
def test_invalid_usb_ids_fail_closed(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        normalize_usb_id(value)  # type: ignore[arg-type]


def test_catalog_has_no_duplicate_usb_ids() -> None:
    ids = [(item.vendor_id, item.product_id) for item in KNOWN_USB_DEVICES]
    assert len(ids) == len(set(ids))


def test_unknown_usb_id_is_not_promoted_to_known() -> None:
    assert find_known_usb_device("6602", "1001") is None
    assert find_known_usb_device("6603", "1000") is None
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_device_catalog.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'streamdock_n3.device_catalog'`.

- [ ] **Step 3: Implement the minimal catalog**

Create `src/streamdock_n3/device_catalog.py` with frozen, slotted dataclasses and these exact enum values and records:

```python
class IdentityStatus(StrEnum):
    USER_REPORTED_CANDIDATE = "user_reported_candidate"
    UPSTREAM_REFERENCE = "upstream_reference"


class ProtocolStatus(StrEnum):
    UNVALIDATED = "unvalidated"
    UPSTREAM_REFERENCE = "upstream_reference"


@dataclass(frozen=True, slots=True)
class KnownUsbDevice:
    vendor_id: int
    product_id: int
    catalog_name: str
    identity_status: IdentityStatus
    protocol_status: ProtocolStatus

    def __post_init__(self) -> None:
        normalize_usb_id(self.vendor_id)
        normalize_usb_id(self.product_id)
        if not self.catalog_name.strip():
            raise ValueError("catalog_name must not be empty")


TARGET_USB_ID: Final = (0x6602, 0x1000)
KNOWN_USB_DEVICES: Final = (
    KnownUsbDevice(
        0x6602,
        0x1000,
        "N3 V3.0 candidate (owner-reported)",
        IdentityStatus.USER_REPORTED_CANDIDATE,
        ProtocolStatus.UNVALIDATED,
    ),
    KnownUsbDevice(
        0x6603,
        0x1003,
        "N3 upstream reference variant",
        IdentityStatus.UPSTREAM_REFERENCE,
        ProtocolStatus.UPSTREAM_REFERENCE,
    ),
)
```

Implement normalization with these rules: reject `bool`; integers must be `0..0xffff`; strings are stripped, may start with `0x` case-insensitively, contain one to four ASCII hex digits, and are always parsed base 16. Build a private immutable lookup after checking for duplicate `(vendor_id, product_id)` keys.

- [ ] **Step 4: Verify GREEN and strict types**

Run:

```bash
uv run pytest tests/test_device_catalog.py -v
uv run mypy --strict src/streamdock_n3/device_catalog.py
uv run ruff check src/streamdock_n3/device_catalog.py tests/test_device_catalog.py
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit**

Commit: `feat: add passive USB device catalog`

---

### Task 2: Safe Sysfs Scanner and Safety Boundary

**Files:**
- Create: `tests/test_discovery.py`
- Create: `tests/test_discovery_safety.py`
- Create: `src/streamdock_n3/discovery.py`

**Interfaces:**
- Consumes: Task 1 catalog interfaces without importing any other project production module.
- Produces: `WarningCode`, `DiscoveryWarning`, `HidInterfaceObservation`, `UsbObservation`, `DiscoveryReport`, `discover_usb_devices(sysfs_root: Path = DEFAULT_SYSFS_ROOT) -> DiscoveryReport`, and `exit_code_for(report: DiscoveryReport) -> int`.
- JSON conversion is implemented by `DiscoveryReport.to_dict() -> dict[str, object]`; CLI rendering remains Task 3.

- [ ] **Step 1: Write failing happy-path scanner tests**

In `tests/test_discovery.py`, create fixture helpers that write ordinary sibling directories, never symlinks by default:

```python
def write_attr(parent: Path, name: str, value: str) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    (parent / name).write_text(value + "\n", encoding="ascii")


def add_usb_device(root: Path, name: str, vid: str, pid: str, bcd: str | None = None) -> Path:
    device = root / name
    write_attr(device, "idVendor", vid)
    write_attr(device, "idProduct", pid)
    if bcd is not None:
        write_attr(device, "bcdDevice", bcd)
    return device


def add_interface(
    root: Path,
    device_name: str,
    suffix: str,
    number: str,
    class_code: str,
    subclass: str,
    protocol: str,
) -> Path:
    interface = root / f"{device_name}:{suffix}"
    for name, value in (
        ("bInterfaceNumber", number),
        ("bInterfaceClass", class_code),
        ("bInterfaceSubClass", subclass),
        ("bInterfaceProtocol", protocol),
    ):
        write_attr(interface, name, value)
    return interface
```

Add tests that assert:

1. A `6602:1000` fixture with `bcdDevice=0300`, HID `00/03/00/00`, HID `01/03/01/01`, and one non-HID interface yields one candidate, exactly two HID interfaces, and `interface_selection == "ambiguous"`.
2. A single HID interface yields `unique`; no HID yields `none` and process exit `3`.
3. A valid target plus a target with no HID yields process exit `0`.
4. Only an upstream `6603:1003` record is reported but process exit is `1` because the target is absent.
5. Unknown `6602:1001` and `6603:1000` fixtures are not reported.
6. Devices sort by `(vid, pid, sysfs_name)` and HID interfaces sort by numeric interface number.

Use these exact field assertions for the target report:

```python
assert observation.vid == "6602"
assert observation.pid == "1000"
assert observation.catalog_match is True
assert observation.target_match is True
assert observation.identity_status == "user_reported_candidate"
assert observation.protocol_status == "unvalidated"
assert observation.bcd_device == "0300"
assert observation.interface_selection == "ambiguous"
assert [item.number for item in observation.hid_interfaces] == ["00", "01"]
```

- [ ] **Step 2: Write failing path and data safety tests**

In `tests/test_discovery.py`, add cases for missing/invalid IDs, missing/invalid `bcdDevice`, incomplete/invalid HID attributes, an unavailable root, an invalid control-character entry name, and symlink policy. Assert only the versioned warning codes from the PRD and assert unsafe names are represented with `sysfs_name is None`.

Cover raw attribute normalization with uppercase and surrounding whitespace for VID/PID, `bcdDevice`, interface number, class, subclass, and protocol.

Build a complete symlink matrix:

- Strict fixture mode rejects device-directory links, interface-directory links, and attribute-file links whether their targets are inside or outside the fixture root.
- Simulate trusted sysfs mode by monkeypatching `DEFAULT_SYSFS_ROOT` and `SYS_DEVICES_ROOT` to separate temporary bus/devices trees. Accept a device link whose target is beneath the fake devices root and interface links whose targets are beneath that resolved device directory.
- In simulated trusted mode, reject device/interface directory links outside the fake devices root and reject every attribute leaf symlink even when its target remains inside the corresponding resolved entry.
- Assert every accepted resolved attribute is a non-symlink regular file and is relative to its own resolved device/interface directory, not merely to the broad fake devices root.

Add root-failure cases for: missing root; `Path.resolve()` raising `OSError`; and root `Path.iterdir()` raising `PermissionError`. Monkeypatch only the exact root operation and delegate other paths to the original method. Each case must produce `root_available=False` and a single `root_unavailable` warning without traceback.

In `tests/test_discovery_safety.py`, add source/import guards before production code exists:

```python
PRODUCTION_MODULES = (
    Path("src/streamdock_n3/device_catalog.py"),
    Path("src/streamdock_n3/discovery.py"),
)
FORBIDDEN_SOURCE = (
    "DeviceManager",
    "LibUSBHIDAPI",
    "streamdock_n3._vendor",
    "import evdev",
    "import pyudev",
    "import gi",
    "subprocess",
    "os.open",
    "/dev/hidraw",
    "/dev/input",
)


def test_m1_production_sources_exclude_active_hardware_dependencies() -> None:
    for relative in PRODUCTION_MODULES:
        source = relative.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_SOURCE:
            assert forbidden not in source
```

Also parse imports with `ast.parse`: project imports are allowed only from `streamdock_n3.device_catalog`; standard-library imports are allowed. Monkeypatch the scanner's single attribute-reader helper to record data paths and assert strict fixture reads have allowlisted basenames and lexically remain under the fixture root. Do not intercept importlib or Python module loading.

Add an AST call-site rule over both M1 production modules: calls named `read_text` may occur only inside `_read_attribute`; calls named `read_bytes`, `open`, `write_text`, and `write_bytes`, plus builtin `open(...)`, are forbidden everywhere. Exercise both `discover_usb_devices(...)` and `main(["--sysfs-root", ..., "--json"])` through the runtime data-path recorder after Task 3 adds `main`.

- [ ] **Step 3: Verify RED**

Run: `uv run pytest tests/test_discovery.py tests/test_discovery_safety.py -v`

Expected: collection fails because `streamdock_n3.discovery` does not exist.

- [ ] **Step 4: Implement immutable report types and the closed schema**

In `src/streamdock_n3/discovery.py`, define:

```python
DEFAULT_SYSFS_ROOT = Path("/sys/bus/usb/devices")
SYS_DEVICES_ROOT = Path("/sys/devices")
ALLOWED_DEVICE_ATTRIBUTES = frozenset({"idVendor", "idProduct", "bcdDevice"})
ALLOWED_INTERFACE_ATTRIBUTES = frozenset(
    {
        "bInterfaceNumber",
        "bInterfaceClass",
        "bInterfaceSubClass",
        "bInterfaceProtocol",
    }
)


class WarningCode(StrEnum):
    ROOT_UNAVAILABLE = "root_unavailable"
    INVALID_SYSFS_NAME = "invalid_sysfs_name"
    INCOMPLETE_USB_IDENTITY = "incomplete_usb_identity"
    INVALID_USB_IDENTITY = "invalid_usb_identity"
    MISSING_BCD_DEVICE = "missing_bcd_device"
    INVALID_BCD_DEVICE = "invalid_bcd_device"
    INCOMPLETE_HID_INTERFACE = "incomplete_hid_interface"
    INVALID_HID_INTERFACE = "invalid_hid_interface"
    UNSAFE_SYMLINK = "unsafe_symlink"
    UNREADABLE_ATTRIBUTE = "unreadable_attribute"
```

Use frozen, slotted dataclasses. `DiscoveryWarning.to_dict()` always returns exactly `code`, `sysfs_name`, and `attribute`. `HidInterfaceObservation.to_dict()` returns exactly `number`, `class`, `subclass`, and `protocol`. `UsbObservation.to_dict()` and `DiscoveryReport.to_dict()` must reproduce the PRD JSON schema without extra fields. Store `root_available: bool` on `DiscoveryReport` for exit aggregation, but deliberately omit it from JSON.

- [ ] **Step 5: Implement the two path policies and scanner algorithm**

Use one private function with this exact boundary for every data-file read:

```python
def _read_attribute(
    logical_entry: Path,
    resolved_entry: Path,
    attribute: str,
    allowed_attributes: frozenset[str],
    trusted_sysfs: bool,
    warnings: list[DiscoveryWarning],
) -> str | None:
```

It rejects leaf symlinks, checks the attribute against `allowed_attributes`, requires a non-symlink regular file, uses `Path.is_relative_to(resolved_entry)` after resolution, catches `OSError`, never returns raw exception text, and calls `Path.read_text(encoding="ascii")` only after checks pass.

Implement this exact scan order:

1. Resolve the root. If it is unavailable or not a directory, return an empty report with `ROOT_UNAVAILABLE` and `root_available=False`.
2. Trusted mode is true only when the resolved root equals `DEFAULT_SYSFS_ROOT`; every other root is strict fixture mode.
3. Sort root entries by name. Reject an unsafe entry name using `^[A-Za-z0-9._:-]+$`; do not echo the invalid name.
4. Trusted mode accepts a device-directory link only if its resolved target is relative to `SYS_DEVICES_ROOT`, and accepts its interface-directory links only when their targets are relative to that resolved device directory. Strict mode rejects every directory or attribute symlink.
5. Read `idVendor` and `idProduct`. Ignore entries with both absent; warn when only one exists; normalize both as one-to-four-digit hex; silently ignore complete unknown IDs.
6. For catalog matches only, read optional `bcdDevice`, then scan same-root siblings beginning with `<device>:`. Only complete class `03` interfaces enter `hid_interfaces`.
7. Sort interfaces numerically, derive `none`/`unique`/`ambiguous`, and sort observations/warnings deterministically.

Implement `exit_code_for` with the exact precedence: unavailable root `2`; any target observation with at least one HID interface `0`; any target observation `3`; otherwise `1`.

- [ ] **Step 6: Verify GREEN and strict types**

Run:

```bash
uv run pytest tests/test_discovery.py tests/test_discovery_safety.py -v
uv run mypy --strict src/streamdock_n3/device_catalog.py src/streamdock_n3/discovery.py
uv run ruff check src/streamdock_n3/device_catalog.py src/streamdock_n3/discovery.py tests/test_device_catalog.py tests/test_discovery.py tests/test_discovery_safety.py
```

Expected: all commands exit `0`.

- [ ] **Step 7: Commit**

Commit: `feat: add safe sysfs device discovery`

---

### Task 3: Human and JSON CLI

**Files:**
- Create: `tests/test_discovery_cli.py`
- Modify: `tests/test_discovery_safety.py`
- Modify: `src/streamdock_n3/discovery.py`
- Modify: `pyproject.toml:52-58`

**Interfaces:**
- Consumes: `discover_usb_devices`, `DiscoveryReport.to_dict`, and `exit_code_for` from Task 2.
- Produces: `build_parser() -> argparse.ArgumentParser`, `render_human(report: DiscoveryReport) -> str`, `render_json(report: DiscoveryReport) -> str`, and `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write failing CLI contract tests**

Use `capsys` and fixture roots to call `main()` directly. Assert:

- `--json` emits exactly the four top-level fields `schema_version`, `target`, `devices`, `warnings`; the target is `{"vid": "6602", "pid": "1000"}`.
- JSON optional `bcd_device` is `null`, warnings have exactly `code`, `sysfs_name`, `attribute`, and repeated runs are byte-for-byte deterministic.
- Human output says `USB ID match`, `identity not confirmed`, `protocol unvalidated`, and `read-only sysfs`; it never says `supported` for `6602:1000`.
- No target returns `1`; target without HID returns `3`; target with HID returns `0`; unavailable root with `--json` returns `2` and emits parseable JSON containing `root_unavailable`.
- Invalid argparse syntax exits `2` through standard argparse behavior.
- An invalid control-character entry name is never echoed.

- [ ] **Step 2: Extend failing dependency-closure tests**

In `tests/test_discovery_safety.py`:

1. Parse `pyproject.toml` and require `project.scripts["n3-ai-deck-detect"] == "streamdock_n3.discovery:main"`.
2. In a fresh Python subprocess import `streamdock_n3.discovery`, then assert loaded module names do not include prefixes `streamdock_n3._vendor`, `evdev`, `pyudev`, or `gi`, and do not include `ctypes`.
3. Load the configured entry point through `importlib.metadata`, call its parser/help path, and assert the same forbidden modules remain absent.
4. Monkeypatch `discover_usb_devices` to raise `AssertionError`, call `main(["--help"])`, and assert argparse exits `0` without invoking the scanner.
5. Run the Task 2 data-path recorder through `main(["--sysfs-root", str(root), "--json"])` so the CLI path is covered as well as the direct scanner path.

- [ ] **Step 3: Verify RED**

Run: `uv run pytest tests/test_discovery_cli.py tests/test_discovery_safety.py -v`

Expected: failures show missing `main`/rendering behavior and missing `n3-ai-deck-detect` script.

- [ ] **Step 4: Implement rendering and CLI**

Add the console script:

```toml
n3-ai-deck-detect = "streamdock_n3.discovery:main"
```

Use `json.dumps(report.to_dict(), ensure_ascii=True, indent=2)` plus a trailing newline supplied by `print`. The human renderer must list only safe schema fields, show warnings by stable code/attribute without paths or raw exceptions, and always end with this meaning: read-only sysfs discovery does not confirm device identity or protocol compatibility. `main()` parses `--json` and `--sysfs-root`, scans once, prints one format, and returns `exit_code_for(report)`.

- [ ] **Step 5: Verify GREEN, installed entry point, and types**

Run:

```bash
uv sync --extra dev
uv run pytest tests/test_discovery_cli.py tests/test_discovery_safety.py -v
uv run n3-ai-deck-detect --help
uv run mypy --strict src/streamdock_n3/device_catalog.py src/streamdock_n3/discovery.py
uv run ruff check src/streamdock_n3/discovery.py tests/test_discovery_cli.py tests/test_discovery_safety.py
```

Expected: tests and checks exit `0`; help text explicitly says sysfs-only and does not access the real scanner.

- [ ] **Step 6: Commit**

Commit: `feat: add read-only detection CLI`

---

### Task 4: Public Documentation and Package Gate

**Files:**
- Modify: `tests/test_public_project.py`
- Modify: `tests/test_discovery_safety.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/ARCHITECTURE.md`

**Interfaces:**
- Consumes: installed `n3-ai-deck-detect` command from Task 3.
- Produces: public safe-use contract and built-wheel smoke evidence.

- [ ] **Step 1: Write failing public-document tests**

Extend `tests/test_public_project.py` to require both READMEs to contain `n3-ai-deck-detect`, candidate/identity-not-confirmed wording, `sysfs`, and an explicit warning that legacy daemon/probe/debug/install commands are outside M1's read-only guarantee. Require `docs/ARCHITECTURE.md` to name `device_catalog.py`, `discovery.py`, `ProductIDs.g_products`, and the passive/active separation. Assert neither README claims `6602:1000` is supported.

Extend `tests/test_discovery_safety.py` with a wheel metadata smoke test. Build a fresh wheel into pytest's `tmp_path` using `uv build --wheel --out-dir`, assert exactly one wheel exists, open it as a zip, and assert its `entry_points.txt` contains `n3-ai-deck-detect = streamdock_n3.discovery:main` and both new modules are present. Do not inspect a possibly stale repository `dist/` wheel.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_public_project.py tests/test_discovery_safety.py -v`

Expected: documentation assertions fail because M1 usage and boundaries are not documented yet; build the wheel before evaluating the wheel test if its only failure is absence of `dist/*.whl`.

- [ ] **Step 3: Update public documentation**

In both READMEs:

- Replace model-confirmation language with USB ID candidate language.
- Add a “Safe read-only discovery” section with `uv run n3-ai-deck-detect` and `uv run n3-ai-deck-detect --json`.
- State that the command reads only approved sysfs attributes, may report multiple HID candidates, and does not prove protocol compatibility.
- Warn that inherited daemon, probe, debug, GUI, and install commands are outside this guarantee and must not be used for `6602:1000` in M1.

In `docs/ARCHITECTURE.md`, mark passive catalog/discovery as implemented in M1 and keep active SDK/device adapter as planned M2 work. State explicitly that the passive catalog is not `ProductIDs.g_products`.

- [ ] **Step 4: Verify docs and built wheel**

Run:

```bash
uv run pytest tests/test_public_project.py tests/test_discovery_safety.py -v
wheel_smoke_dir=$(mktemp -d)
trap 'rm -rf "$wheel_smoke_dir"' EXIT
uv build --wheel --out-dir "$wheel_smoke_dir/dist"
uv venv "$wheel_smoke_dir/venv"
uv pip install --no-deps --python "$wheel_smoke_dir/venv/bin/python" "$wheel_smoke_dir"/dist/*.whl
"$wheel_smoke_dir/venv/bin/n3-ai-deck-detect" --help
```

Expected: build, tests, install, and help all exit `0`. The help path must not enumerate hardware.

- [ ] **Step 5: Commit**

Commit: `docs: publish M1 read-only discovery guidance`

---

### Task 5: Real-Device Read-Only Acceptance and M1 Completion

**Files:**
- Create: `docs/validation/2026-08-03-n3-v3-read-only-discovery.md`
- Modify: `ROADMAP.md`
- Modify: `tasks/m1-ai-coding-queue.json`

**Interfaces:**
- Consumes: the exact installed CLI from Task 3 and documentation contract from Task 4.
- Produces: sanitized physical evidence and M1 completion status; it does not activate M2.

- [ ] **Step 1: Run fresh automated gates before touching real sysfs**

Run:

```bash
uv run pytest
uv run ruff check .
uv run mypy --strict src/streamdock_n3/device_catalog.py src/streamdock_n3/discovery.py
uv build
```

Expected: every command exits `0`. Stop and fix failures before the live read.

- [ ] **Step 2: Run only the approved live read**

Run: `uv run n3-ai-deck-detect --json`

Expected exit `0` and JSON evidence containing:

```json
{
  "vid": "6602",
  "pid": "1000",
  "target_match": true,
  "identity_status": "user_reported_candidate",
  "protocol_status": "unvalidated",
  "bcd_device": "0300",
  "interface_selection": "ambiguous"
}
```

The observation must contain two HID candidates `00/03/00/00` and `01/03/01/01`. Do not run any old hardware command even if this differs.

- [ ] **Step 3: Write and verify a failing validation-record privacy test**

Before creating the record, extend `tests/test_public_project.py` so its fixed public-document set includes `docs/validation/2026-08-03-n3-v3-read-only-discovery.md`. The test must reject raw serial markers, machine-specific `/home`, `/srv`, or `/Users` paths, numbered `/dev/hidrawN` and `/dev/input/eventN` strings, the literal field name `sysfs_name`, and a bus-name match using `(?<![-\d])\d+-\d+(?::\d+\.\d+)?(?![-\d])`. Run the focused test and verify it fails because the validation document is absent.

- [ ] **Step 4: Write the sanitized validation record**

Create `docs/validation/2026-08-03-n3-v3-read-only-discovery.md` containing only: date, tested commit, command name, expected fields, actual VID/PID, `bcdDevice`, the two interface tuples, `ambiguous`, exit code, safety statement, and remaining M2 limitations. Do not include serial, raw full udev output, `/dev` numbering, sysfs bus name, username, or absolute workspace path.

- [ ] **Step 5: Verify the validation record privacy test passes**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: the new validation-record assertion and all existing public-project tests pass.

- [ ] **Step 6: Mark M1 complete in durable public state**

- Change all five task `state` values and `execution_status` in `tasks/m1-ai-coding-queue.json` to `complete`; per-task progress before this point lives only in the ignored SDD ledger.
- Change ROADMAP M1 status to `Complete — read-only discovery only` and check its three bullets.
- Keep M2 pending and repeat that SDK activation and udev permission design require manual approval.

- [ ] **Step 7: Run final privacy and regression gates**

Run:

```bash
git diff --check
uv run pytest
uv run ruff check .
uv run mypy --strict src/streamdock_n3/device_catalog.py src/streamdock_n3/discovery.py
uv build
```

Expected: all commands exit `0`; the tracked-publication privacy test reports no findings.

- [ ] **Step 8: Commit**

Commit: `docs: record M1 read-only validation`

---

## Plan Self-Review

- Spec coverage: M1-01 through M1-05, closed JSON, exit aggregation, two path policies, identity/protocol separation, package smoke, public wording, and real read-only evidence each map to a task.
- Scope exclusions: no planned edit touches `_vendor`, udev data, systemd data, installer behavior, old hardware tools, or `/dev`.
- Type consistency: catalog integer IDs become formatted strings only in observations; report methods and CLI signatures are used consistently across tasks.
- Placeholder scan: every implementation step names concrete interfaces, data, commands, and expected outcomes.
