"""Owner-gated read-only input observation CLI for G3."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from streamdock_n3.device_catalog import IdentityStatus, ProtocolStatus
from streamdock_n3.hardware.adapter import N3Adapter
from streamdock_n3.hardware.backend import FakeBackend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    CommandSpec,
    CommandStep,
    DeviceProfile,
    ErrorCode,
    HidInterface,
    InputAction,
    InputKind,
    InputSessionSpec,
    KeyMap,
    KeyMapEntry,
    Operation,
    Stage,
    StageManifest,
)
from streamdock_n3.hardware.gate import GateViolation
from streamdock_n3.hardware.interface_roles import InterfaceRoleEvidence, resolve_roles
from streamdock_n3.hardware.permissions import make_permission_plan

DEFAULT_SYSFS_ROOT = Path("/sys/bus/usb/devices")
SYS_DEVICES_ROOT = Path("/sys/devices")
INPUT_CLASS_ROOT = Path("/sys/class/input")

APPROVED_VENDOR_ID = 0x6602
APPROVED_PRODUCT_ID = 0x1000
APPROVED_BCD_DEVICE = 0x0300
APPROVED_INPUT_INTERFACE = (3, 1, 1)
APPROVED_CONTROL_INTERFACE = (3, 0, 0)
COMMIT = "e4e9e47"

_SAFE_SYSFS_NAME = re.compile(r"[A-Za-z0-9._:-]+")
_INPUT_ASSOCIATION_RE = re.compile(r"input[0-9]+")
_EVENT_NODE_RE = re.compile(r"event[0-9]+")
_HID_DEVICE_RE = re.compile(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\.[0-9a-fA-F]+")


class NodeResolutionError(Exception):
    """A stable failure while resolving the approved input node."""


def _resolve_interface_real_path(
    sysfs_root: Path, devices_root: Path
) -> Path | None:
    """Return the real path of the approved input interface, or None."""
    try:
        resolved_root = sysfs_root.resolve(strict=True)
        entries = tuple(sorted(resolved_root.iterdir(), key=lambda item: item.name))
    except (OSError, RuntimeError):
        raise NodeResolutionError("sysfs root unavailable") from None
    for entry in entries:
        if ":" in entry.name or _SAFE_SYSFS_NAME.fullmatch(entry.name) is None:
            continue
        try:
            if not entry.is_symlink():
                continue
            resolved = entry.resolve(strict=True)
            if not resolved.is_relative_to(devices_root):
                continue
        except (OSError, RuntimeError):
            continue
        try:
            raw_vid = (entry / "idVendor").read_text(encoding="ascii").strip()
            raw_pid = (entry / "idProduct").read_text(encoding="ascii").strip()
        except (OSError, RuntimeError, UnicodeError):
            continue
        if (raw_vid, raw_pid) != ("6602", "1000"):
            continue
        for interface_entry in entries:
            if not interface_entry.name.startswith(f"{entry.name}:"):
                continue
            try:
                resolved_interface = interface_entry.resolve(strict=True)
                if not resolved_interface.is_relative_to(devices_root):
                    continue
                raw_class = (interface_entry / "bInterfaceClass").read_text(
                    encoding="ascii"
                ).strip()
                raw_subclass = (interface_entry / "bInterfaceSubClass").read_text(
                    encoding="ascii"
                ).strip()
                raw_protocol = (interface_entry / "bInterfaceProtocol").read_text(
                    encoding="ascii"
                ).strip()
            except (OSError, RuntimeError, UnicodeError):
                continue
            try:
                descriptor = (int(raw_class, 16), int(raw_subclass, 16), int(raw_protocol, 16))
            except ValueError:
                continue
            if descriptor == APPROVED_INPUT_INTERFACE:
                return resolved_interface
    return None


def _input_association_dirs(resolved_interface: Path) -> tuple[Path, ...]:
    input_dirs: list[Path] = []
    direct = resolved_interface / "input"
    if direct.is_dir():
        input_dirs.append(direct)
    try:
        for entry in resolved_interface.iterdir():
            if _HID_DEVICE_RE.fullmatch(entry.name) is None:
                continue
            nested = entry / "input"
            if nested.is_dir():
                input_dirs.append(nested)
    except (OSError, RuntimeError):
        pass
    return tuple(input_dirs)


def _verify_input_link(resolved_interface: Path, association: Path) -> Path | None:
    """Verify /sys/class/input/inputN/device resolves inside the interface."""
    try:
        if not association.is_dir():
            return None
        input_class_entry = INPUT_CLASS_ROOT / association.name
        if not input_class_entry.is_symlink():
            return None
        resolved_class_entry = input_class_entry.resolve(strict=True)
        if resolved_class_entry != association:
            return None
        device_link = input_class_entry / "device"
        if not device_link.is_symlink():
            return None
        resolved_device = device_link.resolve(strict=True)
        if not resolved_device.is_relative_to(resolved_interface):
            return None
        for event_entry in input_class_entry.iterdir():
            if _EVENT_NODE_RE.fullmatch(event_entry.name) is not None:
                return event_entry
    except (OSError, RuntimeError):
        return None
    return None


def resolve_input_node(
    sysfs_root: Path = DEFAULT_SYSFS_ROOT,
    devices_root: Path = SYS_DEVICES_ROOT,
) -> str:
    """Resolve /dev/input/eventN for the approved input interface, verified."""
    resolved_interface = _resolve_interface_real_path(sysfs_root, devices_root)
    if resolved_interface is None:
        raise NodeResolutionError("approved input interface not found")
    for input_dir in _input_association_dirs(resolved_interface):
        try:
            associations = tuple(
                sorted(
                    entry.name
                    for entry in input_dir.iterdir()
                    if _INPUT_ASSOCIATION_RE.fullmatch(entry.name)
                )
            )
        except (OSError, RuntimeError):
            continue
        for name in associations:
            event_entry = _verify_input_link(resolved_interface, input_dir / name)
            if event_entry is not None:
                return f"/dev/input/{event_entry.name}"
    raise NodeResolutionError("approved input node not found")


def _load_key_map(path: Path | None) -> KeyMap:
    if path is None:
        return KeyMap(())
    try:
        wire = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f"invalid key map file: {error}") from None
    if not isinstance(wire, list):
        raise ValueError("key map must be a JSON list")
    entries: list[KeyMapEntry] = []
    for item in wire:
        if not isinstance(item, dict):
            raise ValueError("key map entries must be objects")
        try:
            entries.append(
                KeyMapEntry(
                    event_type=int(item["event_type"]),
                    event_code=int(item["event_code"]),
                    control_id=int(item["control_id"]),
                    kind=InputKind(item["kind"]),
                    press_action=InputAction(item["press_action"]),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid key map entry: {error}") from None
    return KeyMap(tuple(entries))


def _build_profile() -> DeviceProfile:
    return DeviceProfile(
        vendor_id=APPROVED_VENDOR_ID,
        product_id=APPROVED_PRODUCT_ID,
        bcd_device=APPROVED_BCD_DEVICE,
        interface=HidInterface(0, *APPROVED_CONTROL_INTERFACE),
        identity_status=IdentityStatus.USER_REPORTED_CANDIDATE,
        protocol_status=ProtocolStatus.UNVALIDATED,
        source_commit=COMMIT,
    )


def _build_session_spec(key_map: KeyMap, duration_ms: int) -> InputSessionSpec:
    return InputSessionSpec(
        duration_ms=duration_ms,
        expected_press_count=10,
        expected_rotation_count=20,
        latency_p95_target_ms=250,
        disconnect_grace_ms=2_000,
        key_map=key_map,
    )


def _build_manifest(spec: InputSessionSpec) -> StageManifest:
    profile = _build_profile()
    resolution = resolve_roles(
        (
            InterfaceRoleEvidence(
                HidInterface(0, *APPROVED_CONTROL_INTERFACE), False, None
            ),
            InterfaceRoleEvidence(
                HidInterface(1, *APPROVED_INPUT_INTERFACE), True, "keyboard"
            ),
        )
    )
    return StageManifest(
        stage=Stage.G3_INPUT,
        commit=COMMIT,
        profile_digest=profile.digest(),
        interface=profile.interface,
        steps=(
            CommandStep(CommandSpec.from_command(AdapterCommand(Operation.OBSERVE_INPUTS))),
        ),
        deadline_ms=spec.duration_ms,
        expected_result="g3_input-validated",
        recovery_plan="g3_input-recovery",
        approval_reference="owner:2026-08-04:g1-profile-approval",
        role_resolution=resolution,
        session_spec=spec,
    )


def _render_result(adapter: N3Adapter, node: str) -> dict[str, object]:
    result = adapter.execute(AdapterCommand(Operation.OBSERVE_INPUTS))
    session = result.session
    state = adapter.state.value
    return {
        "schema_version": 1,
        "status": result.status.value,
        "error_code": result.error_code.value,
        "state": state,
        "input_node_resolved": bool(node),
        "session": session.to_dict() if session is not None else None,
    }


def _advance_approvals(adapter: N3Adapter, manifest: StageManifest) -> None:
    adapter.begin_stage(
        StageManifest(
            stage=Stage.G1_PROFILE,
            commit=manifest.commit,
            profile_digest=manifest.profile_digest,
            interface=manifest.interface,
            steps=(CommandStep(CommandSpec.from_command(AdapterCommand(Operation.APPROVE_PROFILE))),),
            deadline_ms=5_000,
            expected_result="g1-validated",
            recovery_plan="g1-recovery",
            approval_reference=manifest.approval_reference,
            role_resolution=manifest.role_resolution,
        )
    )
    adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))
    adapter.complete_stage(True)
    resolution = manifest.role_resolution
    if resolution is None:
        raise GateViolation(ErrorCode.INPUT_SESSION_INVALID)
    permission_plan = make_permission_plan(resolution, manifest.approval_reference)
    adapter.begin_stage(
        StageManifest(
            stage=Stage.G2_PERMISSION,
            commit=manifest.commit,
            profile_digest=manifest.profile_digest,
            interface=manifest.interface,
            steps=(CommandStep(CommandSpec.from_command(AdapterCommand(Operation.RECORD_PERMISSION))),),
            deadline_ms=5_000,
            expected_result="g2-validated",
            recovery_plan="g2-recovery",
            approval_reference=manifest.approval_reference,
            role_resolution=manifest.role_resolution,
            permission_plan=permission_plan,
        )
    )
    adapter.execute(AdapterCommand(Operation.RECORD_PERMISSION))
    adapter.complete_stage(True)


def run_session_flow(
    node: str,
    key_map: KeyMap,
    duration_ms: int,
    session_runner: object | None = None,
) -> dict[str, object]:
    spec = _build_session_spec(key_map, duration_ms)
    manifest = _build_manifest(spec)
    profile = _build_profile()
    adapter = N3Adapter(
        profile,
        COMMIT,
        FakeBackend(),
        session_runner=session_runner,  # type: ignore[arg-type]
        input_node=node,
    )
    _advance_approvals(adapter, manifest)
    adapter.begin_stage(manifest)
    rendered = _render_result(adapter, node)
    session = rendered["session"]
    disconnected = (
        isinstance(session, dict) and bool(session.get("disconnected", False))
    )
    if (
        session is not None
        and not disconnected
        and rendered["state"] not in ("input_validated",)
    ):
        adapter.complete_stage(True)
        rendered["state"] = adapter.state.value
    return rendered


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="n3-ai-deck-observe-inputs",
        description=(
            "Run one bounded read-only input session for the approved input "
            "interface. Never writes to the device and never loads the SDK."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the stable redacted JSON session contract",
    )
    parser.add_argument(
        "--duration-ms",
        type=int,
        default=600_000,
        metavar="MS",
        help="bounded session window (default: 600000)",
    )
    parser.add_argument(
        "--key-map",
        type=Path,
        default=None,
        metavar="PATH",
        help="JSON key map file (list of event mappings)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    duration_ms = cast(int, args.duration_ms)
    key_map = _load_key_map(cast(Path | None, args.key_map))
    use_json = cast(bool, args.json)

    try:
        node = resolve_input_node()
        rendered = run_session_flow(node, key_map, duration_ms)
    except (GateViolation, NodeResolutionError, ValueError) as error:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "rejected",
                    "error_code": getattr(error, "code", "invalid_input_session"),
                }
            )
        )
        return 1
    if use_json:
        print(json.dumps(rendered, ensure_ascii=True, indent=2))
    else:
        if rendered["session"] is None:
            print(
                f"session rejected: {rendered['error_code']} "
                f"(state {rendered['state']})"
            )
        else:
            session = rendered["session"]
            assert isinstance(session, dict)
            print(
                f"session complete: state {rendered['state']}, "
                f"latency p95 {session['latency_p95_ms']} ms, "
                f"unknown {session['unknown_count']}"
            )
    return 0
