"""Narrow, side-effect-free backend boundary for staged validation."""

from __future__ import annotations

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

    @classmethod
    def from_command(cls, command: AdapterCommand) -> BackendCall:
        if not isinstance(command, AdapterCommand):
            raise TypeError("command must be an AdapterCommand")
        return cls(
            operation=command.operation,
            brightness=command.brightness,
            key=command.key,
            payload_sha256=command.image_digest(),
            payload_size=len(command.image) if command.image is not None else 0,
        )


class FakeBackend:
    """Deterministic in-memory backend used only for G0 simulation."""

    def __init__(
        self,
        events: tuple[NormalizedInputEvent, ...] = (),
        scripted_results: tuple[OperationResult, ...] = (),
    ) -> None:
        self._events = tuple(events)
        self._scripted_results = tuple(scripted_results)
        self._result_index = 0
        self.calls: list[BackendCall] = []

    def execute(
        self,
        command: AdapterCommand,
        manifest: StageManifest,
    ) -> OperationResult:
        del manifest
        self.calls.append(BackendCall.from_command(command))
        if self._result_index < len(self._scripted_results):
            result = self._scripted_results[self._result_index]
            self._result_index += 1
            return result
        events = self._events if command.operation is Operation.OBSERVE_INPUTS else ()
        return OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0, events)
