"""Entry point for the isolated fake-only hardware helper."""

from __future__ import annotations

import sys

from streamdock_n3.hardware.backend import FakeBackend
from streamdock_n3.hardware.contracts import ErrorCode, OperationResult, ResultStatus
from streamdock_n3.hardware.gate import CommandPolicy, GateViolation
from streamdock_n3.hardware.ipc import (
    MAX_FRAMED_REQUEST_BYTES,
    REQUEST_READ_BYTES,
    decode_request,
    encode_response,
)


def _handle_request() -> OperationResult:
    raw = sys.stdin.buffer.read(REQUEST_READ_BYTES)
    if len(raw) > MAX_FRAMED_REQUEST_BYTES:
        raise ValueError
    text = raw.decode("utf-8", errors="strict")
    if not text.endswith("\n") or text.count("\n") != 1 or "\r" in text:
        raise ValueError
    payload = text[:-1]
    if not payload:
        raise ValueError

    request = decode_request(payload)
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
        result = _handle_request()
    except GateViolation as error:
        result = OperationResult(ResultStatus.REJECTED, error.code, 0)
    except (UnicodeDecodeError, ValueError):
        result = OperationResult(ResultStatus.REJECTED, ErrorCode.MANIFEST_INVALID, 0)
    except Exception:
        result = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)
    sys.stdout.write(encode_response(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
