"""Closed JSON protocol for the fixed hardware helper boundary."""

from __future__ import annotations

import base64
import binascii
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn, Protocol

from streamdock_n3.hardware.contracts import (  # type: ignore[attr-defined]
    MAX_DEADLINE_MS,
    MAX_IMAGE_BYTES,
    SCHEMA_VERSION,
    AdapterCommand,
    AdapterState,
    CapabilitySnapshot,
    CommandSpec,
    CommandStep,
    ControlCount,
    ControlMapping,
    DeviceProfile,
    ErrorCode,
    HidInterface,
    HidInterfaceRole,
    IdentityStatus,
    InputAction,
    InputKind,
    InputSessionResult,
    InputSessionSpec,
    InterfaceRole,
    InterfaceRoleResolution,
    KeyMap,
    KeyMapEntry,
    NormalizedInputEvent,
    ObservedCode,
    Operation,
    OperationResult,
    PermissionArtifact,
    PermissionKind,
    PermissionPlan,
    ProtocolStatus,
    ResultStatus,
    RoleBasis,
    RoleResolutionStatus,
    Stage,
    StageManifest,
    StagePhase,
)

MAX_REQUEST_BYTES = 1_500_000
MAX_RESPONSE_BYTES = 1_000_000
LF_FRAMING_BYTES = 1
OVERFLOW_SENTINEL_BYTES = 1
MAX_FRAMED_REQUEST_BYTES = MAX_REQUEST_BYTES + LF_FRAMING_BYTES
REQUEST_READ_BYTES = MAX_FRAMED_REQUEST_BYTES + OVERFLOW_SENTINEL_BYTES
MAX_FRAMED_RESPONSE_BYTES = MAX_RESPONSE_BYTES + LF_FRAMING_BYTES
_REQUEST_KEYS = frozenset(
    {"schema_version", "profile", "capability", "manifest", "step_index", "command"}
)
_PROFILE_KEYS = frozenset(
    {
        "schema_version",
        "vid",
        "pid",
        "bcd_device",
        "interface",
        "identity_status",
        "protocol_status",
        "source_commit",
    }
)
_INTERFACE_KEYS = frozenset({"number", "class", "subclass", "protocol"})
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
        "role_resolution",
        "permission_plan",
        "session_spec",
    }
)
_SPEC_KEYS = frozenset({"operation", "brightness", "key", "image_sha256"})
_STEP_KEYS = frozenset({"forward", "recovery"})
_COMMAND_KEYS = frozenset({"operation", "brightness", "key", "image_base64"})
_RESPONSE_KEYS = frozenset({"schema_version", "status", "error_code", "duration_ms", "events"})
_EVENT_KEYS = frozenset({"kind", "control_id", "action", "monotonic_ns"})
_ROLE_KEYS = frozenset({"interface", "role", "basis"})
_ROLE_RESOLUTION_KEYS = frozenset(
    {"status", "input_interface", "control_interface", "roles"}
)
_PERMISSION_ARTIFACT_KEYS = frozenset({"kind", "subsystem", "role", "rendered"})
_PERMISSION_PLAN_KEYS = frozenset({"approval_reference", "artifacts"})
_KEY_MAP_ENTRY_KEYS = frozenset(
    {"event_type", "event_code", "control_id", "kind", "press_action"}
)
_KEY_MAP_KEYS = frozenset({"entries"})
_SESSION_SPEC_KEYS = frozenset(
    {
        "duration_ms",
        "expected_press_count",
        "expected_rotation_count",
        "latency_p95_target_ms",
        "disconnect_grace_ms",
        "key_map",
        "calibration",
        "press_only",
    }
)
_SESSION_REQUEST_KEYS = frozenset(
    {
        "schema_version",
        "profile",
        "capability",
        "manifest",
        "step_index",
        "command",
        "device_node",
    }
)
_COUNT_KEYS = frozenset(
    {"control_id", "kind", "press_count", "release_count", "left_count", "right_count"}
)
_MAPPING_KEYS = frozenset({"control_id", "kind", "event_type", "event_code"})
_OBSERVED_CODE_KEYS = frozenset({"event_type", "event_code"})
_SESSION_RESULT_KEYS = frozenset(
    {"counts", "latency_p95_ms", "unknown_count", "disconnected", "mapping", "distinct_codes"}
)
_SESSION_RESPONSE_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "error_code",
        "duration_ms",
        "events",
        "session",
    }
)
_DEVICE_NODE_RE = re.compile(r"(?:/dev/input/event[0-9]+|/dev/hidraw[0-9]+)")
_VENDOR_HID_NODE_RE = re.compile(r"/dev/hidraw[0-9]+")


def is_vendor_hid_node(node: str) -> bool:
    """Return True when a validated device node names the vendor HID channel."""
    return isinstance(node, str) and _VENDOR_HID_NODE_RE.fullmatch(node) is not None


@dataclass(frozen=True, slots=True)
class IpcRequest:
    profile: DeviceProfile
    capability: CapabilitySnapshot
    manifest: StageManifest
    step_index: int
    command: AdapterCommand
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.profile, DeviceProfile):
            raise TypeError("profile must be a DeviceProfile")
        if not isinstance(self.capability, CapabilitySnapshot):
            raise TypeError("capability must be a CapabilitySnapshot")
        if not isinstance(self.manifest, StageManifest):
            raise TypeError("manifest must be a StageManifest")
        if isinstance(self.step_index, bool) or not isinstance(self.step_index, int):
            raise TypeError("step_index must be an integer")
        if not isinstance(self.command, AdapterCommand):
            raise TypeError("command must be an AdapterCommand")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != SCHEMA_VERSION
        ):
            raise ValueError("invalid schema version")


@dataclass(frozen=True, slots=True)
class IpcSessionRequest:
    profile: DeviceProfile
    capability: CapabilitySnapshot
    manifest: StageManifest
    step_index: int
    command: AdapterCommand
    device_node: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.profile, DeviceProfile):
            raise TypeError("profile must be a DeviceProfile")
        if not isinstance(self.capability, CapabilitySnapshot):
            raise TypeError("capability must be a CapabilitySnapshot")
        if not isinstance(self.manifest, StageManifest):
            raise TypeError("manifest must be a StageManifest")
        if isinstance(self.step_index, bool) or not isinstance(self.step_index, int):
            raise TypeError("step_index must be an integer")
        if not isinstance(self.command, AdapterCommand):
            raise TypeError("command must be an AdapterCommand")
        if not isinstance(self.device_node, str) or _DEVICE_NODE_RE.fullmatch(
            self.device_node
        ) is None:
            raise ValueError("device_node must be a plain input event or hidraw node path")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != SCHEMA_VERSION
        ):
            raise ValueError("invalid schema version")


@dataclass(frozen=True, slots=True)
class IpcSessionResponse:
    result: OperationResult
    session: InputSessionResult | None

    def __post_init__(self) -> None:
        if not isinstance(self.result, OperationResult):
            raise TypeError("result must be an OperationResult")
        if self.session is not None and not isinstance(self.session, InputSessionResult):
            raise TypeError("session must be an InputSessionResult or None")


def _invalid_request() -> NoReturn:
    raise ValueError("invalid_ipc_request")


def _invalid_response() -> NoReturn:
    raise ValueError("invalid_ipc_response")


def _require_exact_keys(value: object, expected: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError
    return value


def _require_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError
    return value


def _require_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return _require_int(value)


def _require_str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _load_json(text: str) -> object:
    value: object = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    return value


def _parse_hex(value: object, width: int) -> int:
    text = _require_str(value)
    if len(text) != width or any(character not in "0123456789abcdef" for character in text):
        raise ValueError
    return int(text, 16)


def _interface_to_wire(interface: HidInterface) -> dict[str, str]:
    return interface.to_dict()


def _parse_interface(value: object) -> HidInterface:
    wire = _require_exact_keys(value, _INTERFACE_KEYS)
    return HidInterface(
        number=int(_require_str(wire["number"]), 16),
        interface_class=int(_require_str(wire["class"]), 16),
        subclass=int(_require_str(wire["subclass"]), 16),
        protocol=int(_require_str(wire["protocol"]), 16),
    )


def _role_resolution_to_wire(resolution: InterfaceRoleResolution) -> dict[str, object]:
    return resolution.to_dict()


def _parse_role_resolution(value: object) -> InterfaceRoleResolution:
    wire = _require_exact_keys(value, _ROLE_RESOLUTION_KEYS)
    roles_value = wire["roles"]
    if not isinstance(roles_value, list):
        raise ValueError
    roles = tuple(_parse_role(role) for role in roles_value)
    input_interface = wire["input_interface"]
    control_interface = wire["control_interface"]
    return InterfaceRoleResolution(
        roles=roles,
        status=RoleResolutionStatus(_require_str(wire["status"])),
        input_interface=(
            _parse_interface(input_interface) if input_interface is not None else None
        ),
        control_interface=(
            _parse_interface(control_interface) if control_interface is not None else None
        ),
    )


def _parse_role(value: object) -> HidInterfaceRole:
    wire = _require_exact_keys(value, _ROLE_KEYS)
    basis_value = wire["basis"]
    if not isinstance(basis_value, list):
        raise ValueError
    return HidInterfaceRole(
        interface=_parse_interface(wire["interface"]),
        role=InterfaceRole(_require_str(wire["role"])),
        basis=tuple(RoleBasis(_require_str(item)) for item in basis_value),
    )


def _permission_plan_to_wire(plan: PermissionPlan) -> dict[str, object]:
    return plan.to_dict()


def _parse_permission_plan(value: object) -> PermissionPlan:
    wire = _require_exact_keys(value, _PERMISSION_PLAN_KEYS)
    artifacts_value = wire["artifacts"]
    if not isinstance(artifacts_value, list):
        raise ValueError
    artifacts = tuple(_parse_permission_artifact(item) for item in artifacts_value)
    return PermissionPlan(
        artifacts=artifacts,
        approval_reference=_require_str(wire["approval_reference"]),
    )


def _parse_permission_artifact(value: object) -> PermissionArtifact:
    wire = _require_exact_keys(value, _PERMISSION_ARTIFACT_KEYS)
    return PermissionArtifact(
        kind=PermissionKind(_require_str(wire["kind"])),
        subsystem=_require_str(wire["subsystem"]),
        role=InterfaceRole(_require_str(wire["role"])),
        rendered=_require_str(wire["rendered"]),
    )


def _session_spec_to_wire(spec: InputSessionSpec) -> dict[str, object]:
    return spec.to_dict()


def _parse_session_spec(value: object) -> InputSessionSpec:
    wire = _require_exact_keys(value, _SESSION_SPEC_KEYS)
    return InputSessionSpec(
        duration_ms=_require_int(wire["duration_ms"]),
        expected_press_count=_require_int(wire["expected_press_count"]),
        expected_rotation_count=_require_int(wire["expected_rotation_count"]),
        latency_p95_target_ms=_require_int(wire["latency_p95_target_ms"]),
        disconnect_grace_ms=_require_int(wire["disconnect_grace_ms"]),
        key_map=_parse_key_map(wire["key_map"]),
        calibration=_require_bool(wire["calibration"]),
        press_only=_require_bool(wire["press_only"]),
    )


def _parse_key_map(value: object) -> KeyMap:
    wire = _require_exact_keys(value, _KEY_MAP_KEYS)
    entries_value = wire["entries"]
    if not isinstance(entries_value, list):
        raise ValueError
    return KeyMap(
        tuple(_parse_key_map_entry(entry) for entry in entries_value)
    )


def _parse_key_map_entry(value: object) -> KeyMapEntry:
    wire = _require_exact_keys(value, _KEY_MAP_ENTRY_KEYS)
    return KeyMapEntry(
        event_type=_require_int(wire["event_type"]),
        event_code=_require_int(wire["event_code"]),
        control_id=_require_int(wire["control_id"]),
        kind=InputKind(_require_str(wire["kind"])),
        press_action=InputAction(_require_str(wire["press_action"])),
    )


def _parse_control_count(value: object) -> ControlCount:
    wire = _require_exact_keys(value, _COUNT_KEYS)
    return ControlCount(
        control_id=_require_int(wire["control_id"]),
        kind=InputKind(_require_str(wire["kind"])),
        press_count=_require_int(wire["press_count"]),
        release_count=_require_int(wire["release_count"]),
        left_count=_require_int(wire["left_count"]),
        right_count=_require_int(wire["right_count"]),
    )


def _parse_control_mapping(value: object) -> ControlMapping:
    wire = _require_exact_keys(value, _MAPPING_KEYS)
    return ControlMapping(
        control_id=_require_int(wire["control_id"]),
        kind=InputKind(_require_str(wire["kind"])),
        event_type=_require_int(wire["event_type"]),
        event_code=_require_int(wire["event_code"]),
    )


def _input_session_result_to_wire(result: InputSessionResult) -> dict[str, object]:
    return result.to_dict()


def _parse_observed_code(value: object) -> ObservedCode:
    wire = _require_exact_keys(value, _OBSERVED_CODE_KEYS)
    return ObservedCode(
        event_type=_require_int(wire["event_type"]),
        event_code=_require_int(wire["event_code"]),
    )


def _parse_input_session_result(value: object) -> InputSessionResult:
    wire = _require_exact_keys(value, _SESSION_RESULT_KEYS)
    counts_value = wire["counts"]
    mapping_value = wire["mapping"]
    distinct_value = wire["distinct_codes"]
    if (
        not isinstance(counts_value, list)
        or not isinstance(mapping_value, list)
        or not isinstance(distinct_value, list)
    ):
        raise ValueError
    return InputSessionResult(
        counts=tuple(_parse_control_count(item) for item in counts_value),
        latency_p95_ms=_require_int(wire["latency_p95_ms"]),
        unknown_count=_require_int(wire["unknown_count"]),
        disconnected=_require_bool(wire["disconnected"]),
        mapping=tuple(_parse_control_mapping(item) for item in mapping_value),
        distinct_codes=tuple(_parse_observed_code(item) for item in distinct_value),
    )


def _require_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError
    return value


def _profile_to_wire(profile: DeviceProfile) -> dict[str, object]:
    return profile.to_dict()


def _parse_profile(value: object) -> DeviceProfile:
    wire = _require_exact_keys(value, _PROFILE_KEYS)
    schema_version = _require_int(wire["schema_version"])
    return DeviceProfile(
        vendor_id=_parse_hex(wire["vid"], 4),
        product_id=_parse_hex(wire["pid"], 4),
        bcd_device=_parse_hex(wire["bcd_device"], 4),
        interface=_parse_interface(wire["interface"]),
        identity_status=IdentityStatus(_require_str(wire["identity_status"])),
        protocol_status=ProtocolStatus(_require_str(wire["protocol_status"])),
        source_commit=_require_str(wire["source_commit"]),
        schema_version=schema_version,
    )


def _capability_to_wire(capability: CapabilitySnapshot) -> dict[str, object]:
    return {
        "state": capability.state.value,
        "profile_digest": capability.profile_digest,
        "bcd_device": capability.bcd_device,
        "interface": (
            _interface_to_wire(capability.interface) if capability.interface is not None else None
        ),
        "epoch": capability.epoch,
        "stage": capability.stage.value if capability.stage is not None else None,
        "phase": capability.phase.value if capability.phase is not None else None,
    }


def _parse_capability(value: object) -> CapabilitySnapshot:
    wire = _require_exact_keys(value, _CAPABILITY_KEYS)
    profile_digest_value = wire["profile_digest"]
    if profile_digest_value is not None and not isinstance(profile_digest_value, str):
        raise ValueError
    interface_value = wire["interface"]
    stage_value = wire["stage"]
    phase_value = wire["phase"]
    return CapabilitySnapshot(
        state=AdapterState(_require_str(wire["state"])),
        profile_digest=profile_digest_value,
        bcd_device=_require_optional_int(wire["bcd_device"]),
        interface=_parse_interface(interface_value) if interface_value is not None else None,
        epoch=_require_int(wire["epoch"]),
        stage=Stage(_require_str(stage_value)) if stage_value is not None else None,
        phase=StagePhase(_require_str(phase_value)) if phase_value is not None else None,
    )


def _spec_to_wire(spec: CommandSpec) -> dict[str, object]:
    return spec.to_dict()


def _parse_spec(value: object) -> CommandSpec:
    wire = _require_exact_keys(value, _SPEC_KEYS)
    image_sha256_value = wire["image_sha256"]
    if image_sha256_value is not None and not isinstance(image_sha256_value, str):
        raise ValueError
    return CommandSpec(
        operation=Operation(_require_str(wire["operation"])),
        brightness=_require_optional_int(wire["brightness"]),
        key=_require_optional_int(wire["key"]),
        image_sha256=image_sha256_value,
    )


def _step_to_wire(step: CommandStep) -> dict[str, object]:
    return step.to_dict()


def _parse_step(value: object) -> CommandStep:
    wire = _require_exact_keys(value, _STEP_KEYS)
    recovery_value = wire["recovery"]
    return CommandStep(
        forward=_parse_spec(wire["forward"]),
        recovery=_parse_spec(recovery_value) if recovery_value is not None else None,
    )


def _manifest_to_wire(manifest: StageManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "stage": manifest.stage.value,
        "commit": manifest.commit,
        "profile_digest": manifest.profile_digest,
        "interface": _interface_to_wire(manifest.interface),
        "steps": [_step_to_wire(step) for step in manifest.steps],
        "deadline_ms": manifest.deadline_ms,
        "expected_result": manifest.expected_result,
        "recovery_plan": manifest.recovery_plan,
        "approval_reference": manifest.approval_reference,
        "role_resolution": (
            _role_resolution_to_wire(manifest.role_resolution)
            if manifest.role_resolution is not None
            else None
        ),
        "permission_plan": (
            _permission_plan_to_wire(manifest.permission_plan)
            if manifest.permission_plan is not None
            else None
        ),
        "session_spec": (
            _session_spec_to_wire(manifest.session_spec)
            if manifest.session_spec is not None
            else None
        ),
    }


def _parse_manifest(value: object) -> StageManifest:
    wire = _require_exact_keys(value, _MANIFEST_KEYS)
    steps_value = wire["steps"]
    if not isinstance(steps_value, list):
        raise ValueError
    role_resolution = wire["role_resolution"]
    permission_plan = wire["permission_plan"]
    session_spec = wire["session_spec"]
    return StageManifest(
        stage=Stage(_require_str(wire["stage"])),
        commit=_require_str(wire["commit"]),
        profile_digest=_require_str(wire["profile_digest"]),
        interface=_parse_interface(wire["interface"]),
        steps=tuple(_parse_step(step) for step in steps_value),
        deadline_ms=_require_int(wire["deadline_ms"]),
        expected_result=_require_str(wire["expected_result"]),
        recovery_plan=_require_str(wire["recovery_plan"]),
        approval_reference=_require_str(wire["approval_reference"]),
        schema_version=_require_int(wire["schema_version"]),
        role_resolution=(
            _parse_role_resolution(role_resolution) if role_resolution is not None else None
        ),
        permission_plan=(
            _parse_permission_plan(permission_plan) if permission_plan is not None else None
        ),
        session_spec=_parse_session_spec(session_spec) if session_spec is not None else None,
    )


def _command_to_wire(command: AdapterCommand) -> dict[str, object]:
    image_base64 = None
    if command.image is not None:
        image_base64 = base64.b64encode(command.image).decode("ascii")
    return {
        "operation": command.operation.value,
        "brightness": command.brightness,
        "key": command.key,
        "image_base64": image_base64,
    }


def _parse_command(value: object) -> AdapterCommand:
    wire = _require_exact_keys(value, _COMMAND_KEYS)
    image_value = wire["image_base64"]
    image: bytes | None = None
    if image_value is not None:
        encoded = _require_str(image_value)
        maximum_encoded_size = ((MAX_IMAGE_BYTES + 2) // 3) * 4
        if len(encoded) > maximum_encoded_size:
            raise ValueError
        try:
            image = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError from None
        if len(image) > MAX_IMAGE_BYTES or base64.b64encode(image).decode("ascii") != encoded:
            raise ValueError
    return AdapterCommand(
        operation=Operation(_require_str(wire["operation"])),
        brightness=_require_optional_int(wire["brightness"]),
        key=_require_optional_int(wire["key"]),
        image=image,
    )


def _event_to_wire(event: NormalizedInputEvent) -> dict[str, object]:
    return {
        "kind": event.kind.value,
        "control_id": event.control_id,
        "action": event.action.value,
        "monotonic_ns": event.monotonic_ns,
    }


def _parse_event(value: object) -> NormalizedInputEvent:
    wire = _require_exact_keys(value, _EVENT_KEYS)
    return NormalizedInputEvent(
        kind=InputKind(_require_str(wire["kind"])),
        control_id=_require_int(wire["control_id"]),
        action=InputAction(_require_str(wire["action"])),
        monotonic_ns=_require_int(wire["monotonic_ns"]),
    )


def encode_request(request: IpcRequest) -> str:
    """Encode one immutable request as canonical compact JSON."""
    if not isinstance(request, IpcRequest):
        _invalid_request()
    wire = {
        "schema_version": request.schema_version,
        "profile": _profile_to_wire(request.profile),
        "capability": _capability_to_wire(request.capability),
        "manifest": _manifest_to_wire(request.manifest),
        "step_index": request.step_index,
        "command": _command_to_wire(request.command),
    }
    encoded = json.dumps(wire, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
        _invalid_request()
    return encoded


def decode_request(text: str) -> IpcRequest:
    """Decode one request and collapse every parse failure to a stable error."""
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError
        wire = _require_exact_keys(_load_json(text), _REQUEST_KEYS)
        request = IpcRequest(
            profile=_parse_profile(wire["profile"]),
            capability=_parse_capability(wire["capability"]),
            manifest=_parse_manifest(wire["manifest"]),
            step_index=_require_int(wire["step_index"]),
            command=_parse_command(wire["command"]),
            schema_version=_require_int(wire["schema_version"]),
        )
    except Exception:
        _invalid_request()
    return request


def encode_response(result: OperationResult) -> str:
    """Encode only the stable result contract; backend diagnostics never cross IPC."""
    if not isinstance(result, OperationResult):
        _invalid_response()
    wire = {
        "schema_version": SCHEMA_VERSION,
        "status": result.status.value,
        "error_code": result.error_code.value,
        "duration_ms": result.duration_ms,
        "events": [_event_to_wire(event) for event in result.events],
    }
    encoded = json.dumps(wire, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
        _invalid_response()
    return encoded


def decode_response(text: str) -> OperationResult:
    """Decode one result and collapse every parse failure to a stable error."""
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError
        wire = _require_exact_keys(_load_json(text), _RESPONSE_KEYS)
        if _require_int(wire["schema_version"]) != SCHEMA_VERSION:
            raise ValueError
        events_value = wire["events"]
        if not isinstance(events_value, list):
            raise ValueError
        result = OperationResult(
            status=ResultStatus(_require_str(wire["status"])),
            error_code=ErrorCode(_require_str(wire["error_code"])),
            duration_ms=_require_int(wire["duration_ms"]),
            events=tuple(_parse_event(event) for event in events_value),
        )
    except Exception:
        _invalid_response()
    return result


def encode_session_request(request: IpcSessionRequest) -> str:
    """Encode one immutable session request as canonical compact JSON."""
    if not isinstance(request, IpcSessionRequest):
        _invalid_request()
    wire = {
        "schema_version": request.schema_version,
        "profile": _profile_to_wire(request.profile),
        "capability": _capability_to_wire(request.capability),
        "manifest": _manifest_to_wire(request.manifest),
        "step_index": request.step_index,
        "command": _command_to_wire(request.command),
        "device_node": request.device_node,
    }
    encoded = json.dumps(wire, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
        _invalid_request()
    return encoded


def decode_session_request(text: str) -> IpcSessionRequest:
    """Decode one session request and collapse every parse failure to a stable error."""
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError
        wire = _require_exact_keys(_load_json(text), _SESSION_REQUEST_KEYS)
        request = IpcSessionRequest(
            profile=_parse_profile(wire["profile"]),
            capability=_parse_capability(wire["capability"]),
            manifest=_parse_manifest(wire["manifest"]),
            step_index=_require_int(wire["step_index"]),
            command=_parse_command(wire["command"]),
            device_node=_require_str(wire["device_node"]),
            schema_version=_require_int(wire["schema_version"]),
        )
    except Exception:
        _invalid_request()
    return request


def encode_session_response(response: IpcSessionResponse) -> str:
    """Encode the session envelope with the stable result and the redacted session summary."""
    if not isinstance(response, IpcSessionResponse):
        _invalid_response()
    result = response.result
    wire = {
        "schema_version": SCHEMA_VERSION,
        "status": result.status.value,
        "error_code": result.error_code.value,
        "duration_ms": result.duration_ms,
        "events": [_event_to_wire(event) for event in result.events],
        "session": (
            _input_session_result_to_wire(response.session)
            if response.session is not None
            else None
        ),
    }
    encoded = json.dumps(wire, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_RESPONSE_BYTES:
        _invalid_response()
    return encoded


def decode_session_response(text: str) -> IpcSessionResponse:
    """Decode one session envelope and collapse every parse failure to a stable error."""
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError
        wire = _require_exact_keys(_load_json(text), _SESSION_RESPONSE_KEYS)
        if _require_int(wire["schema_version"]) != SCHEMA_VERSION:
            raise ValueError
        events_value = wire["events"]
        if not isinstance(events_value, list):
            raise ValueError
        result = OperationResult(
            status=ResultStatus(_require_str(wire["status"])),
            error_code=ErrorCode(_require_str(wire["error_code"])),
            duration_ms=_require_int(wire["duration_ms"]),
            events=tuple(_parse_event(event) for event in events_value),
        )
        session_value = wire["session"]
        session = (
            _parse_input_session_result(session_value) if session_value is not None else None
        )
    except Exception:
        _invalid_response()
    return IpcSessionResponse(result, session)


def _runner_failure(
    status: ResultStatus, error_code: ErrorCode, duration_ms: int = 0
) -> OperationResult:
    return OperationResult(status, error_code, duration_ms)


class SessionRunner(Protocol):
    """Run one read-only input session through the fixed helper boundary."""

    def run(self, request: IpcSessionRequest, timeout_ms: int) -> IpcSessionResponse:
        ...


def run_fake_helper(
    request: IpcRequest | IpcSessionRequest,
    timeout_ms: int,
) -> OperationResult | IpcSessionResponse:
    """Run the fixed internal helper with a bounded deadline and no caller process controls."""
    if not isinstance(request, (IpcRequest, IpcSessionRequest)):
        raise ValueError("invalid_ipc_request")
    if (
        isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or not 1 <= timeout_ms <= request.manifest.deadline_ms <= MAX_DEADLINE_MS
    ):
        raise ValueError("invalid_timeout")
    is_session = isinstance(request, IpcSessionRequest)

    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-m", "streamdock_n3.hardware.helper_main"],
            input=(
                encode_session_request(request)
                if isinstance(request, IpcSessionRequest)
                else encode_request(request)
            )
            + "\n",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            timeout=timeout_ms / 1000,
        )
    except subprocess.TimeoutExpired:
        return _runner_failure(ResultStatus.TIMEOUT, ErrorCode.DEADLINE_EXCEEDED, timeout_ms)
    except subprocess.SubprocessError:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.HELPER_CRASHED)
    except UnicodeError:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
    except OSError:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.HELPER_CRASHED)

    if completed.returncode != 0:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.HELPER_CRASHED)
    if not isinstance(completed.stdout, str):
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
    if (
        completed.stdout == "\n"
        or not completed.stdout.endswith("\n")
        or completed.stdout.count("\n") != 1
        or "\r" in completed.stdout
    ):
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
    try:
        response_size = len(completed.stdout.encode("utf-8"))
    except UnicodeError:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
    if response_size > MAX_FRAMED_RESPONSE_BYTES:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
    try:
        if is_session:
            return decode_session_response(completed.stdout[:-1])
        return decode_response(completed.stdout[:-1])
    except ValueError:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
