"""Live dispatch loop: stream real vendor events to the M3 action engine.

P2 of the live-dispatch design (sections 4.1-4.2 of
docs/superpowers/specs/2026-08-05-live-dispatch-design.md): a bounded,
foreground session that opens one read-only input node, optionally writes the
validated DIS/LIG/STP init trio once through an injected vendor transport, and
dispatches each normalized event to an ActionEngine. A backend OSError ends
the session as a disconnect; engine and plugin failures never crash the loop.
Both the input backend and the vendor transport are injectable so tests never
touch real nodes.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from streamdock_n3.actions.contracts import (
    ActionResult,
    ActionStatus,
    _validate_int,
)
from streamdock_n3.actions.engine import ActionEngine
from streamdock_n3.hardware.contracts import (
    MAX_DEADLINE_MS,
    AdapterCommand,
    KeyMap,
    NormalizedInputEvent,
    Operation,
)
from streamdock_n3.hardware.input_session import ReadOnlyInputBackend, normalize_event
from streamdock_n3.hardware.vendor_backend import VendorHidTransport, _frames_for_command


class LiveSessionStatus(StrEnum):
    """High-level outcome of one live session, distinct from hardware ResultStatus."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class LiveSessionSpec:
    """One bounded live dispatch session."""

    duration_ms: int
    init: bool = True

    def __post_init__(self) -> None:
        _validate_int(self.duration_ms, "duration_ms", 1, MAX_DEADLINE_MS)
        if not isinstance(self.init, bool):
            raise TypeError("init must be a bool")


@dataclass(frozen=True, slots=True)
class LiveSessionResult:
    """Structured counters and outcome of one live session."""

    status: LiveSessionStatus
    events: int
    dispatched: int
    unknown: int
    disconnected: bool
    init_ok: bool
    duration_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.status, LiveSessionStatus):
            raise TypeError("status must be a LiveSessionStatus")
        for field in ("events", "dispatched", "unknown", "duration_ms"):
            _validate_int(getattr(self, field), field, 0, 2**63 - 1)
        if not isinstance(self.disconnected, bool):
            raise TypeError("disconnected must be a bool")
        if not isinstance(self.init_ok, bool):
            raise TypeError("init_ok must be a bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "events": self.events,
            "dispatched": self.dispatched,
            "unknown": self.unknown,
            "disconnected": self.disconnected,
            "init_ok": self.init_ok,
            "duration_ms": self.duration_ms,
        }


def _write_init_frames(node: str, transport: VendorHidTransport) -> bool:
    """Write the validated DIS/LIG/STP init trio once; any failure returns False."""
    try:
        fd = transport.open_read_write(node)
    except OSError:
        return False
    try:
        for frame in _frames_for_command(AdapterCommand(Operation.INITIALIZE)):
            transport.write(fd, frame)
            transport.drain_acks(fd)
    except OSError:
        return False
    finally:
        transport.close(fd)
    return True


def _dispatch(engine: ActionEngine, event: NormalizedInputEvent) -> ActionResult | None:
    """Run one engine dispatch; an unexpected engine failure never raises."""
    try:
        return engine.handle_event(event)
    except Exception as exc:
        return ActionResult(
            ActionStatus.ERROR,
            "<engine>",
            f"handle_event raised {type(exc).__name__}: {exc}",
            0,
        )


def run_live_loop(
    spec: LiveSessionSpec,
    node: str,
    key_map: KeyMap,
    engine: ActionEngine,
    *,
    input_backend: ReadOnlyInputBackend,
    transport: VendorHidTransport,
    on_event: Callable[[NormalizedInputEvent, ActionResult | None], None] | None = None,
) -> LiveSessionResult:
    """Run one bounded live session and return its structured result."""
    if not isinstance(spec, LiveSessionSpec):
        raise TypeError("spec must be a LiveSessionSpec")
    if not isinstance(node, str) or not node:
        raise ValueError("node must be a non-empty path")
    if not isinstance(key_map, KeyMap):
        raise TypeError("key_map must be a KeyMap")
    if not isinstance(engine, ActionEngine):
        raise TypeError("engine must be an ActionEngine")
    if on_event is not None and not callable(on_event):
        raise TypeError("on_event must be callable")

    init_ok = True
    if spec.init:
        init_ok = _write_init_frames(node, transport)

    try:
        handle = input_backend.open_read_only(node)
    except PermissionError:
        return LiveSessionResult(LiveSessionStatus.REJECTED, 0, 0, 0, False, init_ok, 0)
    except OSError:
        return LiveSessionResult(LiveSessionStatus.ERROR, 0, 0, 0, False, init_ok, 0)
    except (TypeError, ValueError):
        return LiveSessionResult(LiveSessionStatus.REJECTED, 0, 0, 0, False, init_ok, 0)

    started_ns = time.monotonic_ns()
    deadline_ns = started_ns + spec.duration_ms * 1_000_000
    events = 0
    dispatched = 0
    unknown = 0
    disconnected = False
    try:
        while time.monotonic_ns() < deadline_ns:
            try:
                for raw in input_backend.read_events(handle, deadline_ns):
                    events += 1
                    try:
                        normalized = normalize_event(raw, key_map)
                    except (TypeError, ValueError):
                        unknown += 1
                        continue
                    if normalized is None:
                        unknown += 1
                        continue
                    dispatched += 1
                    result = _dispatch(engine, normalized)
                    if on_event is not None:
                        on_event(normalized, result)
            except OSError:
                disconnected = True
                break
    finally:
        input_backend.close(handle)

    duration_ms = int((time.monotonic_ns() - started_ns) / 1_000_000)
    return LiveSessionResult(
        status=LiveSessionStatus.SUCCEEDED,
        events=events,
        dispatched=dispatched,
        unknown=unknown,
        disconnected=disconnected,
        init_ok=init_ok,
        duration_ms=duration_ms,
    )
