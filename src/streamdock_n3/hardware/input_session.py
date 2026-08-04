"""Pure evdev codec and read-only bounded input session for G3."""

from __future__ import annotations

import contextlib
import os
import select
import statistics
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from streamdock_n3.hardware.contracts import (
    ControlCount,
    ControlMapping,
    ErrorCode,
    InputAction,
    InputKind,
    InputSessionResult,
    InputSessionSpec,
    KeyMap,
    NormalizedInputEvent,
    RawInputEvent,
)

_INPUT_EVENT_STRUCT = struct.Struct("qqHHi")
_INPUT_EVENT_SIZE = _INPUT_EVENT_STRUCT.size


def parse_raw_event(payload: bytes, monotonic_ns: int) -> RawInputEvent:
    """Parse one Linux input_event payload into a RawInputEvent."""
    if not isinstance(payload, bytes) or len(payload) != _INPUT_EVENT_SIZE:
        raise ValueError("input event payload must be exactly 24 bytes")
    _seconds, _microseconds, event_type, code, value = _INPUT_EVENT_STRUCT.unpack(payload)
    if event_type < 0 or code < 0 or value < 0:
        raise ValueError("input event fields must be non-negative")
    return RawInputEvent(event_type, code, value, monotonic_ns)


def normalize_event(
    raw: RawInputEvent,
    key_map: KeyMap,
) -> NormalizedInputEvent | None:
    """Map one raw event through the key map, or return None for unknown codes."""
    if not isinstance(raw, RawInputEvent):
        raise TypeError("raw must be a RawInputEvent")
    if not isinstance(key_map, KeyMap):
        raise TypeError("key_map must be a KeyMap")
    matched = key_map.lookup(raw)
    if matched is None:
        return None
    entry, action = matched
    return NormalizedInputEvent(
        entry.kind,
        entry.control_id,
        action,
        raw.monotonic_ns,
    )


@dataclass(frozen=True, slots=True)
class InputFileHandle:
    """Opaque read-only handle produced by a ReadOnlyInputBackend."""

    fileno: int
    opened_read_only: bool


class InputSessionError(Exception):
    """A stable fail-closed classification from a read-only input session."""

    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ReadOnlyInputBackend(Protocol):
    def open_read_only(self, node: str) -> InputFileHandle:
        """Open exactly one node O_RDONLY; any other mode raises."""
        ...

    def read_events(
        self,
        handle: InputFileHandle,
        deadline_ns: int,
    ) -> Iterator[RawInputEvent]:
        """Yield raw events until the deadline; classify read failures."""
        ...

    def close(self, handle: InputFileHandle) -> None:
        ...


class EvdevReadOnlyBackend:
    """Real backend: exactly one O_RDONLY open, select-bounded reads, no writes."""

    POLL_INTERVAL_MS = 100

    def open_read_only(self, node: str) -> InputFileHandle:
        if not isinstance(node, str) or not node:
            raise ValueError("device node must be a non-empty path")
        descriptor = os.open(node, os.O_RDONLY)
        return InputFileHandle(descriptor, opened_read_only=True)

    def read_events(
        self,
        handle: InputFileHandle,
        deadline_ns: int,
    ) -> Iterator[RawInputEvent]:
        if not isinstance(handle, InputFileHandle) or not handle.opened_read_only:
            raise ValueError("handle must be a read-only input handle")
        while True:
            remaining_ns = deadline_ns - time.monotonic_ns()
            if remaining_ns <= 0:
                return
            poll_ns = min(remaining_ns, self.POLL_INTERVAL_MS * 1_000_000)
            readable, _, _ = select.select((handle.fileno,), (), (), poll_ns / 1e9)
            if not readable:
                continue
            try:
                payload = os.read(handle.fileno, _INPUT_EVENT_SIZE * 16)
            except OSError:
                raise
            if not payload:
                raise OSError("readable input node returned no data")
            for offset in range(0, len(payload) - _INPUT_EVENT_SIZE + 1, _INPUT_EVENT_SIZE):
                chunk = payload[offset : offset + _INPUT_EVENT_SIZE]
                if len(chunk) != _INPUT_EVENT_SIZE:
                    return
                yield parse_raw_event(chunk, time.monotonic_ns())

    def close(self, handle: InputFileHandle) -> None:
        if isinstance(handle, InputFileHandle):
            with contextlib.suppress(OSError):
                os.close(handle.fileno)


_META_EVENT_TYPES = frozenset({0, 4})


def run_input_session(
    spec: InputSessionSpec,
    node: str,
    backend: ReadOnlyInputBackend,
) -> InputSessionResult:
    """Run one bounded read-only session and return its structured result."""
    if not isinstance(spec, InputSessionSpec):
        raise TypeError("spec must be an InputSessionSpec")
    try:
        handle = backend.open_read_only(node)
    except PermissionError:
        raise InputSessionError(ErrorCode.PERMISSION_DENIED) from None
    except OSError:
        raise InputSessionError(ErrorCode.BACKEND_FAILURE) from None
    except (TypeError, ValueError):
        raise InputSessionError(ErrorCode.INPUT_SESSION_INVALID) from None

    started_ns = time.monotonic_ns()
    deadline_ns = started_ns + spec.duration_ms * 1_000_000
    counts: dict[tuple[int, InputKind], list[int]] = {}
    mapping: dict[tuple[int, InputKind], ControlMapping] = {}
    unknown_count = 0
    latency_samples: list[int] = []
    disconnected = False

    try:
        for raw in backend.read_events(handle, deadline_ns):
            if not isinstance(raw, RawInputEvent):
                raise InputSessionError(ErrorCode.INPUT_SESSION_INVALID)
            if raw.type in _META_EVENT_TYPES:
                continue
            normalized = normalize_event(raw, spec.key_map)
            if normalized is None:
                unknown_count += 1
                continue
            key = (normalized.control_id, normalized.kind)
            matched = spec.key_map.lookup(raw)
            if matched is None:
                raise InputSessionError(ErrorCode.INPUT_SESSION_INVALID)
            entry, _action = matched
            candidate = ControlMapping(
                normalized.control_id,
                normalized.kind,
                entry.event_type,
                entry.event_code,
            )
            mapping.setdefault(key, candidate)
            counters = counts.setdefault(key, [0, 0, 0, 0])
            if normalized.action is InputAction.PRESS:
                counters[0] += 1
            elif normalized.action is InputAction.RELEASE:
                counters[1] += 1
            elif normalized.action is InputAction.LEFT:
                counters[2] += 1
            else:
                counters[3] += 1
            latency_samples.append(max(0, time.monotonic_ns() - raw.monotonic_ns))
    except InputSessionError:
        raise
    except OSError:
        disconnected = True
    except (TypeError, ValueError):
        raise InputSessionError(ErrorCode.INPUT_SESSION_INVALID) from None
    finally:
        backend.close(handle)

    latency_p95_ms = 0
    if latency_samples:
        latency_p95_ms = int(
            statistics.quantiles(latency_samples, n=20)[18] / 1_000_000
            if len(latency_samples) >= 20
            else max(latency_samples) / 1_000_000
        )
    return InputSessionResult(
        counts=tuple(
            ControlCount(
                control_id=control_id,
                kind=kind,
                press_count=counters[0],
                release_count=counters[1],
                left_count=counters[2],
                right_count=counters[3],
            )
            for (control_id, kind), counters in sorted(
                counts.items(), key=lambda item: (item[0][0], item[0][1].value)
            )
        ),
        latency_p95_ms=latency_p95_ms,
        unknown_count=unknown_count,
        disconnected=disconnected,
        mapping=tuple(
            mapping[key]
            for key in sorted(mapping, key=lambda item: (item[0], item[1].value))
        ),
    )
