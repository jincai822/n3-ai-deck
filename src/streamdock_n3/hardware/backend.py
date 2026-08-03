"""Narrow, side-effect-free backend boundary for staged validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    ErrorCode,
    NormalizedInputEvent,
    Operation,
    OperationResult,
    ResultStatus,
    StageManifest,
)


@runtime_checkable
class Backend(Protocol):
    def execute(
        self,
        command: AdapterCommand,
        manifest: StageManifest,
    ) -> OperationResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class BackendCall:
    operation: Operation
    brightness: int | None
    key: int | None
    payload_sha256: str | None
    payload_size: int


_ERROR_FOR_STATUS = {
    ResultStatus.REJECTED: ErrorCode.OPERATION_NOT_ALLOWED,
    ResultStatus.TIMEOUT: ErrorCode.DEADLINE_EXCEEDED,
    ResultStatus.BACKEND_ERROR: ErrorCode.BACKEND_FAILURE,
    ResultStatus.DISCONNECTED: ErrorCode.DEVICE_DISCONNECTED,
}


class FakeBackend:
    """Deterministic in-memory backend used only for G0 simulation."""

    def __init__(
        self,
        events: tuple[NormalizedInputEvent, ...] = (),
        outcomes: Mapping[Operation, ResultStatus] | None = None,
    ) -> None:
        self._events = tuple(events)
        self._outcomes = dict(outcomes or {})
        self.calls: list[BackendCall] = []

    def execute(
        self,
        command: AdapterCommand,
        manifest: StageManifest,
    ) -> OperationResult:
        del manifest
        self.calls.append(
            BackendCall(
                operation=command.operation,
                brightness=command.brightness,
                key=command.key,
                payload_sha256=command.image_digest(),
                payload_size=len(command.image) if command.image is not None else 0,
            )
        )
        status = self._outcomes.get(command.operation, ResultStatus.SUCCEEDED)
        if status is not ResultStatus.SUCCEEDED:
            return OperationResult(status, _ERROR_FOR_STATUS[status], 0)
        events = self._events if command.operation is Operation.OBSERVE_INPUTS else ()
        return OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0, events)
