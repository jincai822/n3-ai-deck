from __future__ import annotations

import base64
import copy
import io
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from functools import cache
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from streamdock_n3.device_catalog import IdentityStatus, ProtocolStatus
from streamdock_n3.hardware import helper_main
from streamdock_n3.hardware.contracts import (
    MAX_IMAGE_BYTES,
    AdapterCommand,
    AdapterState,
    CapabilitySnapshot,
    CommandSpec,
    CommandStep,
    ControlCount,
    ControlMapping,
    DeviceProfile,
    ErrorCode,
    InputAction,
    InputKind,
    InputSessionResult,
    InputSessionSpec,
    KeyMap,
    KeyMapEntry,
    NormalizedInputEvent,
    Operation,
    OperationResult,
    ResultStatus,
    Stage,
    StageManifest,
    StagePhase,
)
from streamdock_n3.hardware.ipc import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    IpcRequest,
    IpcSessionRequest,
    IpcSessionResponse,
    decode_request,
    decode_response,
    decode_session_request,
    decode_session_response,
    encode_request,
    encode_response,
    encode_session_request,
    encode_session_response,
    run_fake_helper,
)
from tests.hardware_fixtures import (
    TEST_COMMIT,
    TEST_IMAGE,
    TEST_INTERFACE,
    make_manifest,
    make_profile,
    make_resolved_roles,
)


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


def test_fake_helper_call_uses_literal_isolated_module(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(argv)
        result = OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0)
        return subprocess.CompletedProcess(argv, 0, encode_response(result) + "\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert run_fake_helper(valid_request(), 100).succeeded
    assert calls == [[sys.executable, "-I", "-m", "streamdock_n3.hardware.helper_main"]]


def test_helper_ignores_cwd_and_pythonpath_shadow_packages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shadow = tmp_path / "streamdock_n3" / "hardware"
    shadow.mkdir(parents=True)
    (shadow.parent / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "helper_main.py").write_text(
        "raise SystemExit('shadow-helper-executed')\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    assert run_fake_helper(valid_request(), 5_000).succeeded


@cache
def payload_limit_request() -> IpcRequest:
    profile = make_profile()
    image = b"x" * MAX_IMAGE_BYTES
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=image)
    steps = [
        CommandStep(
            CommandSpec(
                Operation.SET_KEY_IMAGE,
                key=1,
                image_sha256=command.image_digest(),
            )
        )
    ]
    steps.extend(
        CommandStep(
            CommandSpec(
                Operation.SET_KEY_IMAGE,
                key=(index % 6) + 1,
                image_sha256=sha256(f"filler-{index}".encode()).hexdigest(),
            )
        )
        for index in range(605)
    )
    manifest = StageManifest(
        Stage.G6_ONE_LCD,
        TEST_COMMIT,
        profile.digest(),
        TEST_INTERFACE,
        tuple(steps),
        600_000,
        "x" * 128,
        "x" * 123,
        "x",
    )
    request = IpcRequest(
        profile,
        CapabilitySnapshot(
            AdapterState.BRIGHTNESS_VALIDATED,
            profile.digest(),
            profile.bcd_device,
            profile.interface,
            8,
            Stage.G6_ONE_LCD,
            StagePhase.FORWARD,
        ),
        manifest,
        0,
        command,
    )

    assert len(encode_request(request).encode("utf-8")) == MAX_REQUEST_BYTES
    return request


@cache
def payload_limit_response() -> str:
    press = NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 0)
    release = NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.RELEASE, 0)
    result = OperationResult(
        ResultStatus.SUCCEEDED,
        ErrorCode.NONE,
        0,
        (press,) * 14_922 + (release,) * 2,
    )
    response = encode_response(result)

    assert len(response.encode("utf-8")) == MAX_RESPONSE_BYTES
    return response


def test_ipc_request_rejects_non_integer_schema_version() -> None:
    request = valid_request()

    with pytest.raises(ValueError):
        IpcRequest(
            request.profile,
            request.capability,
            request.manifest,
            request.step_index,
            request.command,
            schema_version=1.0,  # type: ignore[arg-type]
        )


def request_object(request: IpcRequest | None = None) -> dict[str, Any]:
    value = json.loads(encode_request(request or valid_request()))
    assert isinstance(value, dict)
    return value


def response_object(result: OperationResult | None = None) -> dict[str, Any]:
    value = json.loads(
        encode_response(
            result or OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, duration_ms=0)
        )
    )
    assert isinstance(value, dict)
    return value


def all_input_events() -> tuple[NormalizedInputEvent, ...]:
    return (
        NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 1),
        NormalizedInputEvent(InputKind.BUTTON, 9, InputAction.RELEASE, 2),
        NormalizedInputEvent(InputKind.KNOB_PRESS, 1, InputAction.PRESS, 3),
        NormalizedInputEvent(InputKind.KNOB_PRESS, 3, InputAction.RELEASE, 4),
        NormalizedInputEvent(InputKind.KNOB_ROTATE, 1, InputAction.LEFT, 5),
        NormalizedInputEvent(InputKind.KNOB_ROTATE, 3, InputAction.RIGHT, 6),
    )


def test_request_uses_closed_canonical_schema() -> None:
    encoded = encode_request(valid_request())
    wire = json.loads(encoded)

    assert encoded == json.dumps(wire, sort_keys=True, separators=(",", ":"))
    assert set(wire) == {
        "schema_version",
        "profile",
        "capability",
        "manifest",
        "step_index",
        "command",
    }
    assert set(wire["profile"]) == {
        "schema_version",
        "vid",
        "pid",
        "bcd_device",
        "interface",
        "identity_status",
        "protocol_status",
        "source_commit",
    }
    assert set(wire["profile"]["interface"]) == {
        "number",
        "class",
        "subclass",
        "protocol",
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
    assert set(wire["manifest"]) == {
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
    assert set(wire["manifest"]["interface"]) == {
        "number",
        "class",
        "subclass",
        "protocol",
    }
    assert set(wire["manifest"]["steps"][0]) == {"forward", "recovery"}
    assert set(wire["manifest"]["steps"][0]["forward"]) == {
        "operation",
        "brightness",
        "key",
        "image_sha256",
    }
    assert set(wire["command"]) == {"operation", "brightness", "key", "image_base64"}
    assert wire["command"] == {
        "operation": Operation.APPROVE_PROFILE.value,
        "brightness": None,
        "key": None,
        "image_base64": None,
    }


def test_response_uses_closed_canonical_schema() -> None:
    result = OperationResult(
        ResultStatus.SUCCEEDED,
        ErrorCode.NONE,
        duration_ms=7,
        events=all_input_events(),
    )

    encoded = encode_response(result)
    wire = json.loads(encoded)

    assert encoded == json.dumps(wire, sort_keys=True, separators=(",", ":"))
    assert set(wire) == {"schema_version", "status", "error_code", "duration_ms", "events"}
    assert wire["events"]
    assert all(
        set(event) == {"kind", "control_id", "action", "monotonic_ns"} for event in wire["events"]
    )


RequestMutation = Callable[[dict[str, Any]], dict[str, Any]]


def _remove(path: tuple[str | int, ...], key: str) -> RequestMutation:
    def mutate(value: dict[str, Any]) -> dict[str, Any]:
        target: Any = value
        for part in path:
            target = target[part]
        del target[key]
        return value

    return mutate


def _add(path: tuple[str | int, ...]) -> RequestMutation:
    def mutate(value: dict[str, Any]) -> dict[str, Any]:
        target: Any = value
        for part in path:
            target = target[part]
        target["unexpected"] = "secret"
        return value

    return mutate


@pytest.mark.parametrize(
    "mutate",
    (
        _remove((), "capability"),
        _add(()),
        _remove(("profile",), "vid"),
        _add(("profile",)),
        _remove(("profile", "interface"), "number"),
        _add(("profile", "interface")),
        _remove(("capability",), "epoch"),
        _add(("capability",)),
        _remove(("manifest",), "stage"),
        _add(("manifest",)),
        _remove(("manifest", "interface"), "number"),
        _add(("manifest", "interface")),
        _remove(("manifest", "steps", 0, "forward"), "operation"),
        _add(("manifest", "steps", 0, "forward")),
        _remove(("command",), "operation"),
        _add(("command",)),
    ),
)
def test_request_rejects_missing_and_extra_keys(mutate: RequestMutation) -> None:
    wire = mutate(copy.deepcopy(request_object()))

    with pytest.raises(ValueError, match="^invalid_ipc_request$"):
        decode_request(json.dumps(wire))


def test_request_rejects_duplicate_keys() -> None:
    encoded = encode_request(valid_request()).replace(
        '"state":"candidate"',
        '"state":"profile_approved","state":"candidate"',
        1,
    )

    with pytest.raises(ValueError, match="^invalid_ipc_request$"):
        decode_request(encoded)


@pytest.mark.parametrize(
    "mutate",
    (
        _remove((), "status"),
        _add(()),
        _remove(("events", 0), "kind"),
        _add(("events", 0)),
    ),
)
def test_response_rejects_missing_and_extra_keys(mutate: RequestMutation) -> None:
    result = OperationResult(
        ResultStatus.SUCCEEDED,
        ErrorCode.NONE,
        duration_ms=7,
        events=all_input_events(),
    )
    wire = mutate(copy.deepcopy(response_object(result)))

    with pytest.raises(ValueError, match="^invalid_ipc_response$"):
        decode_response(json.dumps(wire))


def test_response_rejects_duplicate_keys() -> None:
    encoded = encode_response(OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0)).replace(
        '"status":"succeeded"',
        '"status":"rejected","status":"succeeded"',
        1,
    )

    with pytest.raises(ValueError, match="^invalid_ipc_response$"):
        decode_response(encoded)


@pytest.mark.parametrize("state", tuple(AdapterState))
def test_all_adapter_states_round_trip(state: AdapterState) -> None:
    request = valid_request()
    pinned = state is not AdapterState.CANDIDATE
    capability = CapabilitySnapshot(
        state,
        request.profile.digest() if pinned else None,
        request.profile.bcd_device if pinned else None,
        request.profile.interface if pinned else None,
        1,
        request.manifest.stage,
        StagePhase.FORWARD,
    )
    request = IpcRequest(
        request.profile,
        capability,
        request.manifest,
        request.step_index,
        request.command,
    )

    assert decode_request(encode_request(request)) == request


@pytest.mark.parametrize("identity_status", tuple(IdentityStatus))
@pytest.mark.parametrize("protocol_status", tuple(ProtocolStatus))
def test_all_profile_enums_round_trip(
    identity_status: IdentityStatus,
    protocol_status: ProtocolStatus,
) -> None:
    original = make_profile()
    profile = DeviceProfile(
        vendor_id=original.vendor_id,
        product_id=original.product_id,
        bcd_device=original.bcd_device,
        interface=original.interface,
        identity_status=identity_status,
        protocol_status=protocol_status,
        source_commit=original.source_commit,
    )
    manifest = make_manifest(Stage.G3_INPUT)
    request = IpcRequest(
        profile,
        valid_request().capability,
        manifest,
        0,
        AdapterCommand(Operation.OBSERVE_INPUTS),
    )

    assert decode_request(encode_request(request)) == request


@pytest.mark.parametrize(
    "stage", tuple(stage for stage in Stage if stage is not Stage.G0_SIMULATION)
)
def test_all_manifest_stages_round_trip(stage: Stage) -> None:
    request = valid_request()
    manifest = make_manifest(stage)
    request = IpcRequest(
        request.profile,
        replace(request.capability, stage=stage),
        manifest,
        request.step_index,
        request.command,
    )

    assert decode_request(encode_request(request)) == request


@pytest.mark.parametrize(
    "command",
    (
        AdapterCommand(Operation.APPROVE_PROFILE),
        AdapterCommand(Operation.RECORD_PERMISSION),
        AdapterCommand(Operation.OBSERVE_INPUTS),
        AdapterCommand(Operation.INITIALIZE),
        AdapterCommand(Operation.SET_BRIGHTNESS, brightness=0),
        AdapterCommand(Operation.SET_BRIGHTNESS, brightness=100),
        AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE),
        AdapterCommand(Operation.CLOSE_SESSION),
    ),
)
def test_all_operations_brightness_and_image_round_trip(command: AdapterCommand) -> None:
    request = valid_request()
    request = IpcRequest(
        request.profile,
        request.capability,
        request.manifest,
        request.step_index,
        command,
    )

    wire = request_object(request)
    decoded = decode_request(encode_request(request))

    assert decoded == request
    if command.image is not None:
        assert wire["command"]["image_base64"] == base64.b64encode(TEST_IMAGE).decode("ascii")
        assert (
            TEST_IMAGE
            not in encode_response(
                OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0)
            ).encode()
        )


@pytest.mark.parametrize(
    ("status", "error_code"),
    (
        (ResultStatus.SUCCEEDED, ErrorCode.NONE),
        (ResultStatus.REJECTED, ErrorCode.MANIFEST_INVALID),
        (ResultStatus.TIMEOUT, ErrorCode.DEADLINE_EXCEEDED),
        (ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE),
        (ResultStatus.DISCONNECTED, ErrorCode.DEVICE_DISCONNECTED),
    ),
)
def test_all_result_statuses_round_trip(status: ResultStatus, error_code: ErrorCode) -> None:
    result = OperationResult(status, error_code, duration_ms=1)

    assert decode_response(encode_response(result)) == result


@pytest.mark.parametrize(
    "error_code", tuple(code for code in ErrorCode if code is not ErrorCode.NONE)
)
def test_all_non_success_error_codes_round_trip(error_code: ErrorCode) -> None:
    result = OperationResult(ResultStatus.REJECTED, error_code, duration_ms=1)

    assert decode_response(encode_response(result)) == result


def test_all_normalized_events_round_trip() -> None:
    result = OperationResult(
        ResultStatus.SUCCEEDED,
        ErrorCode.NONE,
        duration_ms=1,
        events=all_input_events(),
    )

    assert decode_response(encode_response(result)) == result


@pytest.mark.parametrize(
    ("path", "bad_value"),
    (
        (("schema_version",), 2),
        (("capability", "state"), "new_state"),
        (("capability", "phase"), "new_phase"),
        (("profile", "identity_status"), "trusted"),
        (("profile", "protocol_status"), "known"),
        (("manifest", "stage"), "g8_live"),
        (("manifest", "steps", 0, "forward", "operation"), "open_device"),
        (("command", "operation"), "open_device"),
    ),
)
def test_request_rejects_unknown_versions_and_enums(
    path: tuple[str | int, ...],
    bad_value: object,
) -> None:
    wire = request_object()
    target: Any = wire
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = bad_value

    with pytest.raises(ValueError, match="^invalid_ipc_request$"):
        decode_request(json.dumps(wire))


@pytest.mark.parametrize(
    ("path", "bad_value"),
    (
        (("schema_version",), 2),
        (("status",), "partial"),
        (("error_code",), "raw_exception"),
        (("events", 0, "kind"), "touch"),
        (("events", 0, "action"), "hold"),
    ),
)
def test_response_rejects_unknown_versions_and_enums(
    path: tuple[str | int, ...],
    bad_value: object,
) -> None:
    result = OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 1, all_input_events())
    wire = response_object(result)
    target: Any = wire
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = bad_value

    with pytest.raises(ValueError, match="^invalid_ipc_response$"):
        decode_response(json.dumps(wire))


@pytest.mark.parametrize("bad_value", (1.0, True))
@pytest.mark.parametrize(
    "path",
    (
        ("schema_version",),
        ("capability", "epoch"),
        ("step_index",),
        ("manifest", "deadline_ms"),
    ),
)
def test_request_rejects_float_and_bool_for_integer_fields(
    path: tuple[str | int, ...],
    bad_value: float | bool,
) -> None:
    wire = request_object()
    target: Any = wire
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = bad_value

    with pytest.raises(ValueError, match="^invalid_ipc_request$"):
        decode_request(json.dumps(wire))


@pytest.mark.parametrize("bad_value", (1.0, True))
@pytest.mark.parametrize("field", ("duration_ms", "control_id", "monotonic_ns"))
def test_response_rejects_float_and_bool_for_integer_fields(
    field: str,
    bad_value: float | bool,
) -> None:
    result = OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 1, all_input_events())
    wire = response_object(result)
    if field == "duration_ms":
        wire[field] = bad_value
    else:
        wire["events"][0][field] = bad_value

    with pytest.raises(ValueError, match="^invalid_ipc_response$"):
        decode_response(json.dumps(wire))


@pytest.mark.parametrize("bad_hex", ("2", "00000", "zzzz"))
def test_request_rejects_hex_fields_without_exact_four_digit_shape(bad_hex: str) -> None:
    wire = request_object()
    wire["profile"]["vid"] = bad_hex

    with pytest.raises(ValueError, match="^invalid_ipc_request$"):
        decode_request(json.dumps(wire))


def test_request_rejects_invalid_base64() -> None:
    request = valid_request()
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE)
    wire = request_object(
        IpcRequest(
            request.profile,
            request.capability,
            request.manifest,
            request.step_index,
            command,
        )
    )
    wire["command"]["image_base64"] = "not+canonical/base64==="

    with pytest.raises(ValueError, match="^invalid_ipc_request$"):
        decode_request(json.dumps(wire))


def test_request_rejects_image_payload_over_one_mib() -> None:
    wire = request_object()
    wire["command"] = {
        "operation": Operation.SET_KEY_IMAGE.value,
        "brightness": None,
        "key": 1,
        "image_base64": base64.b64encode(b"x" * (MAX_IMAGE_BYTES + 1)).decode("ascii"),
    }

    with pytest.raises(ValueError, match="^invalid_ipc_request$"):
        decode_request(json.dumps(wire, separators=(",", ":")))


def test_request_rejects_text_over_limit_before_parsing() -> None:
    oversized = "{" + (" " * MAX_REQUEST_BYTES) + "}"

    with pytest.raises(ValueError, match="^invalid_ipc_request$"):
        decode_request(oversized)


def test_response_rejects_text_over_limit_before_parsing() -> None:
    oversized = "{" + (" " * MAX_RESPONSE_BYTES) + "}"

    with pytest.raises(ValueError, match="^invalid_ipc_response$"):
        decode_response(oversized)


def test_fake_helper_round_trip_uses_fixed_internal_module() -> None:
    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result.succeeded is True
    assert result.error_code is ErrorCode.NONE


def test_fake_helper_accepts_request_at_exact_payload_limit() -> None:
    result = run_fake_helper(payload_limit_request(), timeout_ms=10_000)

    assert result.succeeded is True
    assert result.error_code is ErrorCode.NONE


@pytest.mark.parametrize("suffix", (" \n", "\nX"), ids=("payload_over_limit", "trailing_byte"))
def test_helper_rejects_request_over_framed_limit_before_decode(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    framed = (encode_request(payload_limit_request()) + suffix).encode("utf-8")
    decode_called = False

    def fail_decode(text: str) -> IpcRequest:
        nonlocal decode_called
        del text
        decode_called = True
        raise AssertionError("must reject before decode")

    monkeypatch.setattr(helper_main.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(framed)))
    monkeypatch.setattr(helper_main, "decode_request", fail_decode)

    with pytest.raises(ValueError):
        helper_main._handle_request()

    assert decode_called is False


def test_fake_helper_call_is_closed_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}
    response = encode_response(OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0)) + "\n"

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded["argv"] = argv
        recorded.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout=response, stderr="")

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result.succeeded is True
    assert recorded["argv"] == [
        sys.executable,
        "-I",
        "-m",
        "streamdock_n3.hardware.helper_main",
    ]
    assert recorded.get("shell", False) is False
    assert recorded["check"] is False
    assert recorded["capture_output"] is True
    assert recorded["timeout"] == 2.0
    assert recorded["text"] is True
    assert recorded["encoding"] == "utf-8"
    assert recorded["errors"] == "strict"
    assert recorded["input"] == encode_request(valid_request()) + "\n"
    assert "env" not in recorded


def test_fake_helper_maps_timeout_to_stable_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise subprocess.TimeoutExpired(
            ["secret/path"], timeout=2, output="secret", stderr="secret"
        )

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result == OperationResult(ResultStatus.TIMEOUT, ErrorCode.DEADLINE_EXCEEDED, 2_000)
    assert "secret" not in repr(result)


def test_fake_helper_redacts_subprocess_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sensitive_text = "credential=" + "private /" + "home/alice/helper"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise subprocess.SubprocessError(sensitive_text)

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result == OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.HELPER_CRASHED, 0)
    assert sensitive_text not in repr(result)


def test_fake_helper_redacts_nonzero_child_output(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "token=private /" + "home/alice/device stderr-secret"

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(argv, 9, stdout=secret, stderr=secret)

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result == OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.HELPER_CRASHED, 0)
    assert secret not in repr(result)


def test_fake_helper_maps_unicode_decode_failure_to_stable_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"token=private /" + b"home/alice/device"

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise UnicodeDecodeError("utf-8", secret + b"\xff", len(secret), len(secret) + 1, "secret")

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result == OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE, 0)
    assert "secret" not in repr(result)


@pytest.mark.parametrize(
    "stdout_factory",
    (
        lambda response: response,
        lambda response: response + "\n\n",
        lambda response: response + "\n" + response + "\n",
        lambda response: response + "\r\n",
        lambda response: "\n",
    ),
    ids=("no_newline", "extra_blank_line", "multiple_lines", "carriage_return", "empty_line"),
)
def test_fake_helper_rejects_response_without_exactly_one_nonempty_json_line(
    monkeypatch: pytest.MonkeyPatch,
    stdout_factory: Callable[[str], str],
) -> None:
    response = encode_response(OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0))

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            argv, 0, stdout=stdout_factory(response), stderr="secret"
        )

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result == OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE, 0)


def test_fake_helper_accepts_response_at_exact_payload_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = payload_limit_response()

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(argv, 0, stdout=response + "\n", stderr="")

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result.succeeded is True
    assert len(result.events) == 14_924


def test_fake_helper_rejects_response_payload_one_byte_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = payload_limit_response() + " "

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(argv, 0, stdout=response + "\n", stderr="")

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result == OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE, 0)


@pytest.mark.parametrize(
    "stdout",
    ("not-json", "x" * (MAX_RESPONSE_BYTES + 1), "\ud800"),
    ids=("invalid_json", "oversized", "invalid_text"),
)
def test_fake_helper_rejects_invalid_or_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
) -> None:
    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="secret")

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    result = run_fake_helper(valid_request(), timeout_ms=2_000)

    assert result == OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.INVALID_RESPONSE, 0)
    assert stdout not in repr(result)


def test_fake_helper_rejects_timeout_beyond_manifest_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        del args, kwargs
        called = True
        raise AssertionError("must not spawn")

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)
    request = valid_request()

    with pytest.raises(ValueError):
        run_fake_helper(request, timeout_ms=request.manifest.deadline_ms + 1)

    assert called is False


@pytest.mark.parametrize("timeout_ms", (0, True, 1.0, 600_001))
def test_fake_helper_rejects_invalid_timeout_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
    timeout_ms: object,
) -> None:
    called = False

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        del args, kwargs
        called = True
        raise AssertionError("must not spawn")

    monkeypatch.setattr("streamdock_n3.hardware.ipc.subprocess.run", fake_run)

    with pytest.raises(ValueError):
        run_fake_helper(valid_request(), timeout_ms=timeout_ms)  # type: ignore[arg-type]

    assert called is False


def valid_session_request() -> IpcSessionRequest:
    return IpcSessionRequest(
        profile=make_profile(),
        capability=CapabilitySnapshot(
            AdapterState.PROFILE_APPROVED,
            make_profile().digest(),
            make_profile().bcd_device,
            TEST_INTERFACE,
            4,
            Stage.G3_INPUT,
            StagePhase.FORWARD,
        ),
        manifest=make_manifest(
            Stage.G3_INPUT,
            role_resolution=make_resolved_roles(),
            session_spec=InputSessionSpec(
                duration_ms=600_000,
                expected_press_count=10,
                expected_rotation_count=20,
                latency_p95_target_ms=250,
                disconnect_grace_ms=2_000,
                key_map=KeyMap(
                    (
                        KeyMapEntry(1, 30, 1, InputKind.BUTTON, InputAction.PRESS),
                        KeyMapEntry(3, 8, 1, InputKind.KNOB_ROTATE, InputAction.LEFT),
                    )
                ),
            ),
        ),
        step_index=0,
        command=AdapterCommand(Operation.OBSERVE_INPUTS),
        device_node="/dev/input/event12",
    )


def test_session_request_round_trips_with_closed_schema() -> None:
    encoded = encode_session_request(valid_session_request())
    wire = json.loads(encoded)

    assert set(wire) == {
        "schema_version",
        "profile",
        "capability",
        "manifest",
        "step_index",
        "command",
        "device_node",
    }
    assert wire["device_node"] == "/dev/input/event12"
    assert "serial" not in encoded
    assert decode_session_request(encoded) == valid_session_request()


def test_session_request_rejects_arbitrary_device_nodes() -> None:
    for node in ("/dev/hidraw0", "/tmp/event12", "event12", "/dev/input/eventx"):
        with pytest.raises(ValueError):
            replace(valid_session_request(), device_node=node)


def test_session_response_round_trips_redacted_summary() -> None:
    session = InputSessionResult(
        counts=(ControlCount(1, InputKind.BUTTON, 10, 10, 0, 0),),
        latency_p95_ms=120,
        unknown_count=3,
        disconnected=False,
        mapping=(ControlMapping(1, InputKind.BUTTON, 1, 30),),
    )
    result = OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 60_000)
    response = IpcSessionResponse(result, session)

    encoded = encode_session_response(response)
    wire = json.loads(encoded)
    assert set(wire) == {
        "schema_version",
        "status",
        "error_code",
        "duration_ms",
        "events",
        "session",
    }
    assert decode_session_response(encoded) == response
    assert "/dev/" not in encoded


def test_session_response_accepts_null_session() -> None:
    result = OperationResult(ResultStatus.REJECTED, ErrorCode.PERMISSION_DENIED, 0)
    response = IpcSessionResponse(result, None)

    assert decode_session_response(encode_session_response(response)) == response


def test_helper_dispatches_session_requests_with_fixed_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(argv)
        session = InputSessionResult(
            counts=(ControlCount(1, InputKind.BUTTON, 1, 1, 0, 0),),
            latency_p95_ms=10,
            unknown_count=0,
            disconnected=False,
            mapping=(ControlMapping(1, InputKind.BUTTON, 1, 30),),
        )
        result = OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 5)
        return subprocess.CompletedProcess(
            argv,
            0,
            encode_session_response(IpcSessionResponse(result, session)) + "\n",
            "",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    handled = run_fake_helper(valid_session_request(), 100)

    assert isinstance(handled, IpcSessionResponse)
    assert handled.result.succeeded is True
    assert handled.session is not None
    assert handled.session.counts[0].press_count == 1
    assert calls == [[sys.executable, "-I", "-m", "streamdock_n3.hardware.helper_main"]]
