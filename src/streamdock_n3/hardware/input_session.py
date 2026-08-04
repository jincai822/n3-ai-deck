"""Pure evdev codec and read-only bounded input session for G3."""

from __future__ import annotations

import contextlib
import os
import select
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from streamdock_n3.hardware.contracts import (
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
            readable, _, _ = select.select((handle.fileno,), (), (), remaining_ns / 1e9)
            if not readable:
                return
            try:
                payload = os.read(handle.fileno, _INPUT_EVENT_SIZE * 16)
            except OSError:
                return
            if not payload:
                return
            for offset in range(0, len(payload) - _INPUT_EVENT_SIZE + 1, _INPUT_EVENT_SIZE):
                chunk = payload[offset : offset + _INPUT_EVENT_SIZE]
                if len(chunk) != _INPUT_EVENT_SIZE:
                    return
                yield parse_raw_event(chunk, time.monotonic_ns())

    def close(self, handle: InputFileHandle) -> None:
        if isinstance(handle, InputFileHandle):
            with contextlib.suppress(OSError):
                os.close(handle.fileno)
