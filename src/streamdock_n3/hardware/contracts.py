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


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
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
class CommandRule:
    operation: Operation
    min_calls: int
    max_calls: int
    brightness: int | None = None
    key: int | None = None
    image_sha256: str | None = None

    def __post_init__(self) -> None:
        _validate_int(self.min_calls, "min_calls", 0, 12)
        _validate_int(self.max_calls, "max_calls", 0, 12)
        if self.min_calls > self.max_calls:
            raise ValueError("min_calls must not exceed max_calls")
        _validate_rule_shape(self.operation, self.brightness, self.key, self.image_sha256)

    def matches(self, command: AdapterCommand) -> bool:
        if not isinstance(command, AdapterCommand):
            return False
        return (
            self.operation is command.operation
            and self.brightness == command.brightness
            and self.key == command.key
            and self.image_sha256 == command.image_digest()
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation.value,
            "min_calls": self.min_calls,
            "max_calls": self.max_calls,
            "brightness": self.brightness,
            "key": self.key,
            "image_sha256": self.image_sha256,
        }


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

    def __post_init__(self) -> None:
        if not isinstance(self.stage, Stage):
            raise TypeError("stage must be a Stage")
        if self.stage is Stage.G0_SIMULATION:
            raise ValueError("G0 simulation cannot have a hardware manifest")
        _validate_commit(self.commit)
        _validate_sha256(self.profile_digest, "profile_digest")
        if not isinstance(self.interface, HidInterface):
            raise TypeError("interface must be a HidInterface")
        if not isinstance(self.allowed_commands, tuple) or not self.allowed_commands:
            raise ValueError("allowed_commands must be a non-empty tuple")
        if not all(isinstance(rule, CommandRule) for rule in self.allowed_commands):
            raise TypeError("allowed_commands must contain CommandRule values")
        if len(set(self.allowed_commands)) != len(self.allowed_commands):
            raise ValueError("allowed_commands must not contain duplicate rules")
        _validate_int(self.deadline_ms, "deadline_ms", 1, MAX_DEADLINE_MS)
        _validate_safe_token(self.expected_result, "expected_result")
        _validate_safe_token(self.recovery_plan, "recovery_plan")
        _validate_safe_token(self.approval_reference, "approval_reference")
        _validate_schema(self.schema_version)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "stage": self.stage.value,
            "commit": self.commit,
            "profile_digest": self.profile_digest,
            "interface": self.interface.to_dict(),
            "allowed_commands": [rule.to_dict() for rule in self.allowed_commands],
            "deadline_ms": self.deadline_ms,
            "expected_result": self.expected_result,
            "recovery_plan": self.recovery_plan,
            "approval_reference": self.approval_reference,
        }

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


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
