"""Entry point for the isolated hardware helper."""

from __future__ import annotations

import sys
import time

from streamdock_n3.hardware.backend import Backend, FakeBackend
from streamdock_n3.hardware.contracts import (
    ErrorCode,
    OperationResult,
    ResultStatus,
    Stage,
)
from streamdock_n3.hardware.gate import CommandPolicy, GateViolation
from streamdock_n3.hardware.input_session import (
    EvdevReadOnlyBackend,
    InputSessionError,
    ReadOnlyInputBackend,
    VendorHidReadOnlyBackend,
    run_input_session,
)
from streamdock_n3.hardware.ipc import (
    MAX_FRAMED_REQUEST_BYTES,
    REQUEST_READ_BYTES,
    IpcRequest,
    IpcSessionRequest,
    IpcSessionResponse,
    decode_request,
    decode_session_request,
    encode_response,
    encode_session_response,
    is_vendor_hid_node,
)
from streamdock_n3.hardware.vendor_backend import (
    VENDOR_COMMAND_OPERATIONS,
    VendorHidCommandBackend,
    manifest_uses_vendor_channel,
)


def _read_framed_payload() -> str:
    raw = sys.stdin.buffer.read(REQUEST_READ_BYTES)
    if len(raw) > MAX_FRAMED_REQUEST_BYTES:
        raise ValueError
    text = raw.decode("utf-8", errors="strict")
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise ValueError
    payload = text[:-1]
    if not payload:
        raise ValueError
    return payload


def _select_backend(node: str) -> ReadOnlyInputBackend:
    """Select the read-only backend matching the validated device node path."""
    if is_vendor_hid_node(node):
        return VendorHidReadOnlyBackend()
    return EvdevReadOnlyBackend()


def _select_command_backend(request: IpcSessionRequest) -> Backend:
    """Select the real vendor backend only for validated vendor-channel commands."""
    if (
        request.command.operation in VENDOR_COMMAND_OPERATIONS
        and is_vendor_hid_node(request.device_node)
        and manifest_uses_vendor_channel(request.manifest)
    ):
        return VendorHidCommandBackend(request.device_node)
    return FakeBackend()


def _run_command(request: IpcSessionRequest) -> IpcSessionResponse:
    """Execute one non-session command carrying its freshly resolved device node."""
    CommandPolicy.validate(
        request.profile,
        request.capability,
        request.manifest,
        request.step_index,
        request.command,
    )
    backend = _select_command_backend(request)
    result = backend.execute(request.command, request.manifest)
    return IpcSessionResponse(result, None)


def _run_session(request: IpcSessionRequest) -> IpcSessionResponse:
    spec = request.manifest.session_spec
    if spec is None or request.manifest.stage is not Stage.G3_INPUT:
        raise ValueError
    CommandPolicy.validate(
        request.profile,
        request.capability,
        request.manifest,
        request.step_index,
        request.command,
    )
    started_ns = time.monotonic_ns()
    backend = _select_backend(request.device_node)
    try:
        session = run_input_session(spec, request.device_node, backend)
    except InputSessionError as error:
        return IpcSessionResponse(
            OperationResult(ResultStatus.REJECTED, error.code, 0),
            None,
        )
    duration_ms = int((time.monotonic_ns() - started_ns) / 1_000_000)
    if session.disconnected:
        result = OperationResult(
            ResultStatus.DISCONNECTED,
            ErrorCode.DEVICE_DISCONNECTED,
            duration_ms,
        )
    else:
        result = OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, duration_ms)
    return IpcSessionResponse(result, session)


def _handle_request() -> OperationResult | IpcSessionResponse:
    payload = _read_framed_payload()
    try:
        request: IpcRequest | IpcSessionRequest = decode_request(payload)
    except ValueError:
        request = decode_session_request(payload)
    if isinstance(request, IpcSessionRequest):
        if request.manifest.stage is Stage.G3_INPUT or request.manifest.session_spec is not None:
            return _run_session(request)
        return _run_command(request)
    CommandPolicy.validate(
        request.profile,
        request.capability,
        request.manifest,
        request.step_index,
        request.command,
    )
    return FakeBackend().execute(request.command, request.manifest)


def main() -> int:
    """Read one bounded request and emit one stable response."""
    try:
        handled = _handle_request()
    except GateViolation as error:
        result = OperationResult(ResultStatus.REJECTED, error.code, 0)
        sys.stdout.write(encode_response(result) + "\n")
        return 0
    except (UnicodeDecodeError, ValueError):
        result = OperationResult(ResultStatus.REJECTED, ErrorCode.MANIFEST_INVALID, 0)
        sys.stdout.write(encode_response(result) + "\n")
        return 0
    except Exception:
        result = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)
        sys.stdout.write(encode_response(result) + "\n")
        return 0
    if isinstance(handled, IpcSessionResponse):
        sys.stdout.write(encode_session_response(handled) + "\n")
    else:
        sys.stdout.write(encode_response(handled) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
