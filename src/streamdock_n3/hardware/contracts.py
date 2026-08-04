"""Immutable, side-effect-free contracts for staged hardware validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

from streamdock_n3.device_catalog import (
    IdentityStatus,
    ProtocolStatus,
    format_usb_id,
    normalize_usb_id,
)

SCHEMA_VERSION = 1
MAX_DEADLINE_MS = 600_000
MAX_IMAGE_BYTES = 1_048_576

_COMMIT_RE = re.compile(r"[0-9a-f]{7,40}")
_SAFE_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,127}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


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


class StagePhase(StrEnum):
    FORWARD = "forward"
    RECOVERY = "recovery"
    READY = "ready"


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
    RESULT_MISSING = "result_missing"
    PROFILE_MISMATCH = "profile_mismatch"
    ORDER_VIOLATION = "order_violation"
    RECOVERY_REQUIRED = "recovery_required"
    STALE_RESERVATION = "stale_reservation"
    EVIDENCE_FAILURE = "evidence_failure"
    INTERFACE_AMBIGUITY = "interface_ambiguity"
    PROFILE_EVIDENCE_INCOMPLETE = "profile_evidence_incomplete"
    PERMISSION_PLAN_INVALID = "permission_plan_invalid"
    INPUT_SESSION_INVALID = "input_session_invalid"
    PERMISSION_DENIED = "permission_denied"


class RecoveryStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class InterfaceRole(StrEnum):
    INPUT = "input"
    CONTROL = "control"
    UNKNOWN = "unknown"


class RoleBasis(StrEnum):
    BOOT_KEYBOARD = "boot_keyboard"
    HID_INTERFACE = "hid_interface"
    INPUT_SUBSYSTEM = "input_subsystem"
    NO_INPUT_ASSOCIATION = "no_input_association"
    VENDOR_HID = "vendor_hid"


class RoleResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"


class PermissionKind(StrEnum):
    TEMPORARY_ACL = "temporary_acl"
    PERSISTENT_RULE = "persistent_rule"


_ROLE_SUBSYSTEMS = {
    InterfaceRole.INPUT.value: "input",
    InterfaceRole.CONTROL.value: "hidraw",
}


@dataclass(frozen=True, slots=True)
class PermissionArtifact:
    kind: PermissionKind
    subsystem: str
    role: InterfaceRole
    rendered: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PermissionKind):
            raise TypeError("kind must be a PermissionKind")
        if not isinstance(self.role, InterfaceRole):
            raise TypeError("role must be an InterfaceRole")
        if not isinstance(self.subsystem, str) or not self.subsystem:
            raise ValueError("subsystem must be a non-empty string")
        if not isinstance(self.rendered, str) or not self.rendered:
            raise ValueError("rendered must be a non-empty string")
        expected = _ROLE_SUBSYSTEMS.get(self.role.value)
        if expected is None or self.subsystem != expected:
            raise ValueError(f"role {self.role.value} does not justify subsystem {self.subsystem}")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "subsystem": self.subsystem,
            "role": self.role.value,
            "rendered": self.rendered,
        }


@dataclass(frozen=True, slots=True)
class PermissionPlan:
    artifacts: tuple[PermissionArtifact, ...]
    approval_reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, tuple) or len(self.artifacts) < 2:
            raise ValueError("artifacts must be a tuple of at least two PermissionArtifact values")
        if not all(isinstance(artifact, PermissionArtifact) for artifact in self.artifacts):
            raise TypeError("artifacts must contain PermissionArtifact values")
        pairs = [(artifact.kind, artifact.subsystem) for artifact in self.artifacts]
        if len(set(pairs)) != len(pairs):
            raise ValueError("artifacts must have unique kind/subsystem pairs")
        _validate_safe_token(self.approval_reference, "approval_reference")

    def to_dict(self) -> dict[str, object]:
        return {
            "approval_reference": self.approval_reference,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return sha256(encoded).hexdigest()


def _validate_schema(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")


def _validate_commit(value: str) -> None:
    if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
        raise ValueError("commit must be 7 to 40 lowercase hexadecimal characters")


def _validate_safe_token(value: str, field: str) -> None:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a safe token")


def _validate_sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def _validate_int(value: int, field: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")


def _validate_operation_shape(
    operation: Operation,
    brightness: int | None,
    key: int | None,
    image: bytes | None,
) -> None:
    if not isinstance(operation, Operation):
        raise TypeError("operation must be an Operation")
    if operation is Operation.SET_BRIGHTNESS:
        if brightness is None:
            raise ValueError("set_brightness requires brightness")
        _validate_int(brightness, "brightness", 0, 100)
        if key is not None or image is not None:
            raise ValueError("set_brightness only accepts brightness")
        return
    if operation is Operation.SET_KEY_IMAGE:
        if key is None or image is None:
            raise ValueError("set_key_image requires key and image")
        _validate_int(key, "key", 1, 6)
        if not isinstance(image, bytes):
            raise TypeError("image must be bytes")
        if len(image) > MAX_IMAGE_BYTES:
            raise ValueError("image exceeds maximum size")
        if brightness is not None:
            raise ValueError("set_key_image only accepts key and image")
        return
    if brightness is not None or key is not None or image is not None:
        raise ValueError(f"{operation.value} accepts no parameters")


def _validate_rule_shape(
    operation: Operation,
    brightness: int | None,
    key: int | None,
    image_sha256: str | None,
) -> None:
    if not isinstance(operation, Operation):
        raise TypeError("operation must be an Operation")
    if operation is Operation.SET_BRIGHTNESS:
        if brightness is None:
            raise ValueError("set_brightness rule requires brightness")
        _validate_int(brightness, "brightness", 0, 100)
        if key is not None or image_sha256 is not None:
            raise ValueError("set_brightness rule only accepts brightness")
        return
    if operation is Operation.SET_KEY_IMAGE:
        if key is None or image_sha256 is None:
            raise ValueError("set_key_image rule requires key and image_sha256")
        _validate_int(key, "key", 1, 6)
        _validate_sha256(image_sha256, "image_sha256")
        if brightness is not None:
            raise ValueError("set_key_image rule only accepts key and image_sha256")
        return
    if brightness is not None or key is not None or image_sha256 is not None:
        raise ValueError(f"{operation.value} rule accepts no parameters")


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
class HidInterfaceRole:
    interface: HidInterface
    role: InterfaceRole
    basis: tuple[RoleBasis, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.interface, HidInterface):
            raise TypeError("interface must be a HidInterface")
        if not isinstance(self.role, InterfaceRole):
            raise TypeError("role must be an InterfaceRole")
        if not isinstance(self.basis, tuple) or not self.basis:
            raise ValueError("basis must be a non-empty tuple")
        if not all(isinstance(basis, RoleBasis) for basis in self.basis):
            raise TypeError("basis must contain RoleBasis values")
        if len(set(self.basis)) != len(self.basis):
            raise ValueError("basis must not contain duplicates")
        if tuple(sorted(self.basis)) != self.basis:
            raise ValueError("basis must be sorted")

    def to_dict(self) -> dict[str, object]:
        return {
            "interface": self.interface.to_dict(),
            "role": self.role.value,
            "basis": [basis.value for basis in self.basis],
        }


@dataclass(frozen=True, slots=True)
class InterfaceRoleResolution:
    roles: tuple[HidInterfaceRole, ...]
    status: RoleResolutionStatus
    input_interface: HidInterface | None
    control_interface: HidInterface | None

    def __post_init__(self) -> None:
        if not isinstance(self.roles, tuple) or len(self.roles) < 2:
            raise ValueError("roles must be a tuple of at least two HidInterfaceRole values")
        if not all(isinstance(role, HidInterfaceRole) for role in self.roles):
            raise TypeError("roles must contain HidInterfaceRole values")
        numbers = [role.interface.number for role in self.roles]
        if len(set(numbers)) != len(numbers):
            raise ValueError("roles must have unique interface numbers")
        if not isinstance(self.status, RoleResolutionStatus):
            raise TypeError("status must be a RoleResolutionStatus")
        input_roles = [role for role in self.roles if role.role is InterfaceRole.INPUT]
        control_roles = [role for role in self.roles if role.role is InterfaceRole.CONTROL]
        unknown_roles = [role for role in self.roles if role.role is InterfaceRole.UNKNOWN]
        if self.status is RoleResolutionStatus.RESOLVED:
            if len(input_roles) != 1 or len(control_roles) != 1 or unknown_roles:
                raise ValueError("RESOLVED requires exactly one INPUT and one CONTROL role")
            if self.input_interface != input_roles[0].interface:
                raise ValueError("input_interface must match the INPUT role interface")
            if self.control_interface != control_roles[0].interface:
                raise ValueError("control_interface must match the CONTROL role interface")
        else:
            if self.input_interface is not None or self.control_interface is not None:
                raise ValueError("AMBIGUOUS resolution must not bind interfaces")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "input_interface": (
                self.input_interface.to_dict() if self.input_interface is not None else None
            ),
            "control_interface": (
                self.control_interface.to_dict() if self.control_interface is not None else None
            ),
            "roles": [role.to_dict() for role in self.roles],
        }

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


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
        if not isinstance(self.interface, HidInterface):
            raise TypeError("interface must be a HidInterface")
        if not isinstance(self.identity_status, IdentityStatus):
            raise TypeError("identity_status must be an IdentityStatus")
        if not isinstance(self.protocol_status, ProtocolStatus):
            raise TypeError("protocol_status must be a ProtocolStatus")
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


@dataclass(frozen=True, slots=True)
class AdapterCommand:
    operation: Operation
    brightness: int | None = None
    key: int | None = None
    image: bytes | None = None

    def __post_init__(self) -> None:
        _validate_operation_shape(self.operation, self.brightness, self.key, self.image)

    def image_digest(self) -> str | None:
        if self.operation is not Operation.SET_KEY_IMAGE:
            return None
        if self.image is None:
            raise AssertionError("validated key-image command has no image")
        return sha256(self.image).hexdigest()


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


@dataclass(frozen=True, slots=True)
class StageManifest:
    stage: Stage
    commit: str
    profile_digest: str
    interface: HidInterface
    steps: tuple[CommandStep, ...]
    deadline_ms: int
    expected_result: str
    recovery_plan: str
    approval_reference: str
    schema_version: int = SCHEMA_VERSION
    role_resolution: InterfaceRoleResolution | None = None
    permission_plan: PermissionPlan | None = None
    session_spec: InputSessionSpec | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, Stage):
            raise TypeError("stage must be a Stage")
        if self.stage is Stage.G0_SIMULATION:
            raise ValueError("G0 simulation cannot have a hardware manifest")
        _validate_commit(self.commit)
        _validate_sha256(self.profile_digest, "profile_digest")
        if not isinstance(self.interface, HidInterface):
            raise TypeError("interface must be a HidInterface")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ValueError("steps must be a non-empty tuple")
        if not all(isinstance(step, CommandStep) for step in self.steps):
            raise TypeError("steps must contain CommandStep values")
        _validate_int(self.deadline_ms, "deadline_ms", 1, MAX_DEADLINE_MS)
        _validate_safe_token(self.expected_result, "expected_result")
        _validate_safe_token(self.recovery_plan, "recovery_plan")
        _validate_safe_token(self.approval_reference, "approval_reference")
        _validate_schema(self.schema_version)
        if self.role_resolution is not None and not isinstance(
            self.role_resolution, InterfaceRoleResolution
        ):
            raise TypeError("role_resolution must be an InterfaceRoleResolution or None")
        if self.permission_plan is not None and not isinstance(
            self.permission_plan, PermissionPlan
        ):
            raise TypeError("permission_plan must be a PermissionPlan or None")
        if self.session_spec is not None and not isinstance(
            self.session_spec, InputSessionSpec
        ):
            raise TypeError("session_spec must be an InputSessionSpec or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stage": self.stage.value,
            "commit": self.commit,
            "profile_digest": self.profile_digest,
            "interface": self.interface.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "deadline_ms": self.deadline_ms,
            "expected_result": self.expected_result,
            "recovery_plan": self.recovery_plan,
            "approval_reference": self.approval_reference,
            "role_resolution": (
                self.role_resolution.to_dict() if self.role_resolution is not None else None
            ),
            "permission_plan": (
                self.permission_plan.to_dict() if self.permission_plan is not None else None
            ),
            "session_spec": (
                self.session_spec.to_dict() if self.session_spec is not None else None
            ),
        }

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    state: AdapterState
    profile_digest: str | None
    bcd_device: int | None
    interface: HidInterface | None
    epoch: int
    stage: Stage | None
    phase: StagePhase | None

    def __post_init__(self) -> None:
        if not isinstance(self.state, AdapterState):
            raise TypeError("state must be an AdapterState")
        profile_values = (self.profile_digest, self.bcd_device, self.interface)
        if any(value is None for value in profile_values) and not all(
            value is None for value in profile_values
        ):
            raise ValueError("profile binding must be all present or all absent")
        if self.profile_digest is not None:
            _validate_sha256(self.profile_digest, "profile_digest")
            bcd_device = self.bcd_device
            if bcd_device is None:
                raise AssertionError("validated profile binding has no bcd_device")
            _validate_int(bcd_device, "bcd_device", 0, 0xFFFF)
            if not isinstance(self.interface, HidInterface):
                raise TypeError("interface must be a HidInterface")
        _validate_int(self.epoch, "epoch", 0, 2**63 - 1)
        if (self.stage is None) != (self.phase is None):
            raise ValueError("stage and phase must both be present or both be absent")
        if self.stage is not None and not isinstance(self.stage, Stage):
            raise TypeError("stage must be a Stage or None")
        if self.phase is not None and not isinstance(self.phase, StagePhase):
            raise TypeError("phase must be a StagePhase or None")


@dataclass(frozen=True, slots=True)
class StageSessionSnapshot:
    stage: Stage
    phase: StagePhase
    forward_index: int
    recovery_remaining: int
    pending_reservation: bool

    def __post_init__(self) -> None:
        if not isinstance(self.stage, Stage):
            raise TypeError("stage must be a Stage")
        if not isinstance(self.phase, StagePhase):
            raise TypeError("phase must be a StagePhase")
        _validate_int(self.forward_index, "forward_index", 0, 2**63 - 1)
        _validate_int(self.recovery_remaining, "recovery_remaining", 0, 2**63 - 1)
        if not isinstance(self.pending_reservation, bool):
            raise TypeError("pending_reservation must be a bool")


@dataclass(frozen=True, slots=True)
class NormalizedInputEvent:
    kind: InputKind
    control_id: int
    action: InputAction
    monotonic_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InputKind):
            raise TypeError("kind must be an InputKind")
        if not isinstance(self.action, InputAction):
            raise TypeError("action must be an InputAction")
        _validate_int(self.monotonic_ns, "monotonic_ns", 0, 2**63 - 1)
        if self.kind is InputKind.BUTTON:
            _validate_int(self.control_id, "control_id", 1, 9)
            allowed_actions = (InputAction.PRESS, InputAction.RELEASE)
        elif self.kind is InputKind.KNOB_PRESS:
            _validate_int(self.control_id, "control_id", 1, 3)
            allowed_actions = (InputAction.PRESS, InputAction.RELEASE)
        else:
            _validate_int(self.control_id, "control_id", 1, 3)
            allowed_actions = (InputAction.LEFT, InputAction.RIGHT)
        if self.action not in allowed_actions:
            raise ValueError("action is not valid for input kind")


@dataclass(frozen=True, slots=True)
class RawInputEvent:
    type: int
    code: int
    value: int
    monotonic_ns: int

    def __post_init__(self) -> None:
        for value, field in ((self.type, "type"), (self.code, "code")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise ValueError("value must be an integer")
        _validate_int(self.monotonic_ns, "monotonic_ns", 0, 2**63 - 1)


@dataclass(frozen=True, slots=True)
class KeyMapEntry:
    event_type: int
    event_code: int
    control_id: int
    kind: InputKind
    press_action: InputAction

    def __post_init__(self) -> None:
        for value, field in (
            (self.event_type, "event_type"),
            (self.event_code, "event_code"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if not isinstance(self.kind, InputKind):
            raise TypeError("kind must be an InputKind")
        if not isinstance(self.press_action, InputAction):
            raise TypeError("press_action must be an InputAction")
        _validate_int(self.control_id, "control_id", 1, 9)
        if self.kind is InputKind.KNOB_ROTATE:
            if self.press_action is not InputAction.LEFT:
                raise ValueError("knob rotation press_action must be LEFT")
        elif self.press_action is not InputAction.PRESS:
            raise ValueError("discrete control press_action must be PRESS")

    def action_for_value(self, value: int) -> InputAction:
        if self.kind is InputKind.KNOB_ROTATE:
            return InputAction.LEFT if value >= 0 else InputAction.RIGHT
        return InputAction.PRESS if value else InputAction.RELEASE


@dataclass(frozen=True, slots=True)
class KeyMap:
    entries: tuple[KeyMapEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise TypeError("entries must be a tuple of KeyMapEntry values")
        if not all(isinstance(entry, KeyMapEntry) for entry in self.entries):
            raise TypeError("entries must contain KeyMapEntry values")
        pairs = [(entry.event_type, entry.event_code) for entry in self.entries]
        if len(set(pairs)) != len(pairs):
            raise ValueError("entries must have unique event type/code pairs")

    def lookup(self, raw: RawInputEvent) -> tuple[KeyMapEntry, InputAction] | None:
        if not isinstance(raw, RawInputEvent):
            raise TypeError("raw must be a RawInputEvent")
        for entry in self.entries:
            if entry.event_type == raw.type and entry.event_code == raw.code:
                return entry, entry.action_for_value(raw.value)
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "entries": [
                {
                    "event_type": entry.event_type,
                    "event_code": entry.event_code,
                    "control_id": entry.control_id,
                    "kind": entry.kind.value,
                    "press_action": entry.press_action.value,
                }
                for entry in self.entries
            ]
        }


@dataclass(frozen=True, slots=True)
class InputSessionSpec:
    duration_ms: int
    expected_press_count: int
    expected_rotation_count: int
    latency_p95_target_ms: int
    disconnect_grace_ms: int
    key_map: KeyMap

    def __post_init__(self) -> None:
        _validate_int(self.duration_ms, "duration_ms", 1, MAX_DEADLINE_MS)
        _validate_int(self.expected_press_count, "expected_press_count", 1, 2**31 - 1)
        _validate_int(self.expected_rotation_count, "expected_rotation_count", 1, 2**31 - 1)
        _validate_int(self.latency_p95_target_ms, "latency_p95_target_ms", 1, MAX_DEADLINE_MS)
        _validate_int(self.disconnect_grace_ms, "disconnect_grace_ms", 1, 2_000)
        if not isinstance(self.key_map, KeyMap):
            raise TypeError("key_map must be a KeyMap")

    def to_dict(self) -> dict[str, object]:
        return {
            "duration_ms": self.duration_ms,
            "expected_press_count": self.expected_press_count,
            "expected_rotation_count": self.expected_rotation_count,
            "latency_p95_target_ms": self.latency_p95_target_ms,
            "disconnect_grace_ms": self.disconnect_grace_ms,
            "key_map": self.key_map.to_dict(),
        }

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ControlCount:
    control_id: int
    kind: InputKind
    press_count: int
    release_count: int
    left_count: int
    right_count: int

    def __post_init__(self) -> None:
        _validate_int(self.control_id, "control_id", 1, 9)
        if not isinstance(self.kind, InputKind):
            raise TypeError("kind must be an InputKind")
        for value, field in (
            (self.press_count, "press_count"),
            (self.release_count, "release_count"),
            (self.left_count, "left_count"),
            (self.right_count, "right_count"),
        ):
            _validate_int(value, field, 0, 2**63 - 1)
        if self.kind is InputKind.KNOB_ROTATE:
            if self.press_count or self.release_count:
                raise ValueError("rotation counts cannot carry press/release counts")
        elif self.left_count or self.right_count:
            raise ValueError("discrete counts cannot carry rotation counts")


@dataclass(frozen=True, slots=True)
class ControlMapping:
    control_id: int
    kind: InputKind
    event_type: int
    event_code: int

    def __post_init__(self) -> None:
        _validate_int(self.control_id, "control_id", 1, 9)
        if not isinstance(self.kind, InputKind):
            raise TypeError("kind must be an InputKind")
        for value, field in ((self.event_type, "event_type"), (self.event_code, "event_code")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class InputSessionResult:
    counts: tuple[ControlCount, ...]
    latency_p95_ms: int
    unknown_count: int
    disconnected: bool
    mapping: tuple[ControlMapping, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.counts, tuple):
            raise TypeError("counts must be a tuple of ControlCount values")
        if not all(isinstance(count, ControlCount) for count in self.counts):
            raise TypeError("counts must contain ControlCount values")
        ids = [(count.control_id, count.kind) for count in self.counts]
        if len(set(ids)) != len(ids):
            raise ValueError("counts must have unique control id/kind pairs")
        _validate_int(self.latency_p95_ms, "latency_p95_ms", 0, 2**63 - 1)
        _validate_int(self.unknown_count, "unknown_count", 0, 2**63 - 1)
        if not isinstance(self.disconnected, bool):
            raise TypeError("disconnected must be a bool")
        if not isinstance(self.mapping, tuple):
            raise TypeError("mapping must be a tuple of ControlMapping values")
        if not all(isinstance(item, ControlMapping) for item in self.mapping):
            raise TypeError("mapping must contain ControlMapping values")

    def meets_requirements(self, spec: InputSessionSpec) -> bool:
        if not isinstance(spec, InputSessionSpec):
            raise TypeError("spec must be an InputSessionSpec")
        if self.disconnected:
            return False
        if self.latency_p95_ms > spec.latency_p95_target_ms:
            return False
        observed: dict[tuple[int, InputKind], ControlCount] = {
            (count.control_id, count.kind): count for count in self.counts
        }
        for entry in spec.key_map.entries:
            count = observed.get((entry.control_id, entry.kind))
            if count is None:
                return False
            if entry.kind is InputKind.KNOB_ROTATE:
                if (
                    count.left_count < spec.expected_rotation_count
                    or count.right_count < spec.expected_rotation_count
                ):
                    return False
            else:
                if (
                    count.press_count < spec.expected_press_count
                    or count.release_count < spec.expected_press_count
                ):
                    return False
        return True

    def to_dict(self) -> dict[str, object]:
        return {
            "counts": [
                {
                    "control_id": count.control_id,
                    "kind": count.kind.value,
                    "press_count": count.press_count,
                    "release_count": count.release_count,
                    "left_count": count.left_count,
                    "right_count": count.right_count,
                }
                for count in self.counts
            ],
            "latency_p95_ms": self.latency_p95_ms,
            "unknown_count": self.unknown_count,
            "disconnected": self.disconnected,
            "mapping": [
                {
                    "control_id": item.control_id,
                    "kind": item.kind.value,
                    "event_type": item.event_type,
                    "event_code": item.event_code,
                }
                for item in self.mapping
            ],
        }

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class OperationResult:
    status: ResultStatus
    error_code: ErrorCode
    duration_ms: int
    events: tuple[NormalizedInputEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ResultStatus):
            raise TypeError("status must be a ResultStatus")
        if not isinstance(self.error_code, ErrorCode):
            raise TypeError("error_code must be an ErrorCode")
        _validate_int(self.duration_ms, "duration_ms", 0, 2**63 - 1)
        if not isinstance(self.events, tuple) or not all(
            isinstance(event, NormalizedInputEvent) for event in self.events
        ):
            raise TypeError("events must be a tuple of NormalizedInputEvent values")
        if (self.status is ResultStatus.SUCCEEDED) != (self.error_code is ErrorCode.NONE):
            raise ValueError("succeeded results require NONE and other results require an error")

    @property
    def succeeded(self) -> bool:
        return self.status is ResultStatus.SUCCEEDED
