"""Closed JSON protocol for the fixed, fake-only hardware helper."""

from __future__ import annotations

import base64
import binascii
import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn

from streamdock_n3.hardware.contracts import (  # type: ignore[attr-defined]
    MAX_DEADLINE_MS,
    MAX_IMAGE_BYTES,
    SCHEMA_VERSION,
    AdapterCommand,
    AdapterState,
    CommandRule,
    DeviceProfile,
    ErrorCode,
    HidInterface,
    IdentityStatus,
    InputAction,
    InputKind,
    NormalizedInputEvent,
    Operation,
    OperationResult,
    ProtocolStatus,
    ResultStatus,
    Stage,
    StageManifest,
)

MAX_REQUEST_BYTES = 1_500_000
MAX_RESPONSE_BYTES = 1_000_000
HELPER_MODULE = "streamdock_n3.hardware.helper_main"

_REQUEST_KEYS = frozenset({"schema_version", "profile", "state", "manifest", "command"})
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
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "stage",
        "commit",
        "profile_digest",
        "interface",
        "allowed_commands",
        "deadline_ms",
        "expected_result",
        "recovery_plan",
        "approval_reference",
    }
)
_RULE_KEYS = frozenset(
    {"operation", "min_calls", "max_calls", "brightness", "key", "image_sha256"}
)
_COMMAND_KEYS = frozenset({"operation", "brightness", "key", "image_base64"})
_RESPONSE_KEYS = frozenset({"schema_version", "status", "error_code", "duration_ms", "events"})
_EVENT_KEYS = frozenset({"kind", "control_id", "action", "monotonic_ns"})


@dataclass(frozen=True, slots=True)
class IpcRequest:
    profile: DeviceProfile
    state: AdapterState
    manifest: StageManifest
    command: AdapterCommand
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.profile, DeviceProfile):
            raise TypeError("profile must be a DeviceProfile")
        if not isinstance(self.state, AdapterState):
            raise TypeError("state must be an AdapterState")
        if not isinstance(self.manifest, StageManifest):
            raise TypeError("manifest must be a StageManifest")
        if not isinstance(self.command, AdapterCommand):
            raise TypeError("command must be an AdapterCommand")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != SCHEMA_VERSION
        ):
            raise ValueError("invalid schema version")


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
        number=_parse_hex(wire["number"], 2),
        interface_class=_parse_hex(wire["class"], 2),
        subclass=_parse_hex(wire["subclass"], 2),
        protocol=_parse_hex(wire["protocol"], 2),
    )


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


def _rule_to_wire(rule: CommandRule) -> dict[str, object]:
    return rule.to_dict()


def _parse_rule(value: object) -> CommandRule:
    wire = _require_exact_keys(value, _RULE_KEYS)
    image_sha256_value = wire["image_sha256"]
    if image_sha256_value is not None and not isinstance(image_sha256_value, str):
        raise ValueError
    return CommandRule(
        operation=Operation(_require_str(wire["operation"])),
        min_calls=_require_int(wire["min_calls"]),
        max_calls=_require_int(wire["max_calls"]),
        brightness=_require_optional_int(wire["brightness"]),
        key=_require_optional_int(wire["key"]),
        image_sha256=image_sha256_value,
    )


def _manifest_to_wire(manifest: StageManifest) -> dict[str, object]:
    return {
        "schema_version": manifest.schema_version,
        "stage": manifest.stage.value,
        "commit": manifest.commit,
        "profile_digest": manifest.profile_digest,
        "interface": _interface_to_wire(manifest.interface),
        "allowed_commands": [_rule_to_wire(rule) for rule in manifest.allowed_commands],
        "deadline_ms": manifest.deadline_ms,
        "expected_result": manifest.expected_result,
        "recovery_plan": manifest.recovery_plan,
        "approval_reference": manifest.approval_reference,
    }


def _parse_manifest(value: object) -> StageManifest:
    wire = _require_exact_keys(value, _MANIFEST_KEYS)
    rules_value = wire["allowed_commands"]
    if not isinstance(rules_value, list):
        raise ValueError
    return StageManifest(
        stage=Stage(_require_str(wire["stage"])),
        commit=_require_str(wire["commit"]),
        profile_digest=_require_str(wire["profile_digest"]),
        interface=_parse_interface(wire["interface"]),
        allowed_commands=tuple(_parse_rule(rule) for rule in rules_value),
        deadline_ms=_require_int(wire["deadline_ms"]),
        expected_result=_require_str(wire["expected_result"]),
        recovery_plan=_require_str(wire["recovery_plan"]),
        approval_reference=_require_str(wire["approval_reference"]),
        schema_version=_require_int(wire["schema_version"]),
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
        "state": request.state.value,
        "manifest": _manifest_to_wire(request.manifest),
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
            state=AdapterState(_require_str(wire["state"])),
            manifest=_parse_manifest(wire["manifest"]),
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


def _runner_failure(status: ResultStatus, error_code: ErrorCode, duration_ms: int = 0) -> OperationResult:
    return OperationResult(status, error_code, duration_ms)


def run_fake_helper(request: IpcRequest, timeout_ms: int) -> OperationResult:
    """Run the fixed internal fake helper with a bounded deadline and no caller process controls."""
    if not isinstance(request, IpcRequest):
        raise ValueError("invalid_ipc_request")
    if (
        isinstance(timeout_ms, bool)
        or not isinstance(timeout_ms, int)
        or not 1 <= timeout_ms <= request.manifest.deadline_ms <= MAX_DEADLINE_MS
    ):
        raise ValueError("invalid_timeout")

    argv = [sys.executable, "-m", HELPER_MODULE]
    try:
        completed = subprocess.run(
            argv,
            input=encode_request(request) + "\n",
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_ms / 1000,
        )
    except subprocess.TimeoutExpired:
        return _runner_failure(ResultStatus.TIMEOUT, ErrorCode.DEADLINE_EXCEEDED, timeout_ms)
    except OSError:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.HELPER_CRASHED)

    if completed.returncode != 0:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.HELPER_CRASHED)
    if not isinstance(completed.stdout, str):
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
    try:
        response_size = len(completed.stdout.encode("utf-8"))
    except UnicodeError:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
    if response_size > MAX_RESPONSE_BYTES:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
    try:
        return decode_response(completed.stdout)
    except ValueError:
        return _runner_failure(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE)
