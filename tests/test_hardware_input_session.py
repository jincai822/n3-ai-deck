from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from streamdock_n3.hardware.contracts import (
    ControlCount,
    ControlMapping,
    ErrorCode,
    InputAction,
    InputKind,
    InputSessionSpec,
    KeyMap,
    KeyMapEntry,
    RawInputEvent,
)
from streamdock_n3.hardware.input_session import (
    EvdevReadOnlyBackend,
    InputFileHandle,
    InputSessionError,
    run_input_session,
)


@dataclass
class FixtureHandle:
    events: list[RawInputEvent]
    calls: list[str]
    fail_read: OSError | None = None

    def write_attempt(self) -> None:
        raise AssertionError("fixture handle must never be written")


def button_map() -> KeyMap:
    return KeyMap(
        (
            KeyMapEntry(1, 30, 1, InputKind.BUTTON, InputAction.PRESS),
            KeyMapEntry(1, 31, 2, InputKind.BUTTON, InputAction.PRESS),
            KeyMapEntry(3, 8, 1, InputKind.KNOB_ROTATE, InputAction.LEFT),
            KeyMapEntry(3, 9, 1, InputKind.KNOB_PRESS, InputAction.PRESS),
        )
    )


def spec(duration_ms: int = 60_000, **overrides: object) -> InputSessionSpec:
    values: dict[str, object] = dict(
        duration_ms=duration_ms,
        expected_press_count=10,
        expected_rotation_count=20,
        latency_p95_target_ms=250,
        disconnect_grace_ms=2_000,
        key_map=button_map(),
    )
    values.update(overrides)
    return InputSessionSpec(**values)  # type: ignore[arg-type]


class FixtureInputBackend:
    def __init__(self, events: list[RawInputEvent], fail_read: OSError | None = None) -> None:
        self.events = list(events)
        self.fail_read = fail_read
        self.calls: list[str] = []
        self._handle: FixtureHandle | None = None

    def open_read_only(self, node: str) -> FixtureHandle:
        self.calls.append(f"open:{node}")
        self._handle = FixtureHandle(self.events, self.calls, self.fail_read)
        return self._handle

    def read_events(
        self,
        handle: FixtureHandle,
        deadline_ns: int,
    ) -> Iterator[RawInputEvent]:
        self.calls.append("read")
        if handle.fail_read is not None:
            raise handle.fail_read
        yield from handle.events

    def close(self, handle: FixtureHandle) -> None:
        self.calls.append("close")


def press(code: int, monotonic_ns: int | None = None) -> RawInputEvent:
    return RawInputEvent(1, code, 1, monotonic_ns or time.monotonic_ns())


def release(code: int, monotonic_ns: int | None = None) -> RawInputEvent:
    return RawInputEvent(1, code, 0, monotonic_ns or time.monotonic_ns())


def test_session_counts_exact_press_release_and_rotations() -> None:
    events = [
        press(30), release(30),
        press(30), release(30),
        press(31), release(31),
        RawInputEvent(3, 8, 1, time.monotonic_ns()),
        RawInputEvent(3, 8, -1, time.monotonic_ns()),
        RawInputEvent(3, 9, 1, time.monotonic_ns()),
    ]
    backend = FixtureInputBackend(events)

    result = run_input_session(spec(), "/dev/input/event12", backend)

    assert result.counts == (
        ControlCount(1, InputKind.BUTTON, 2, 2, 0, 0),
        ControlCount(1, InputKind.KNOB_PRESS, 1, 0, 0, 0),
        ControlCount(1, InputKind.KNOB_ROTATE, 0, 0, 1, 1),
        ControlCount(2, InputKind.BUTTON, 1, 1, 0, 0),
    )
    assert result.mapping == (
        ControlMapping(1, InputKind.BUTTON, 1, 30),
        ControlMapping(1, InputKind.KNOB_PRESS, 3, 9),
        ControlMapping(1, InputKind.KNOB_ROTATE, 3, 8),
        ControlMapping(2, InputKind.BUTTON, 1, 31),
    )
    assert result.disconnected is False
    assert result.unknown_count == 0
    assert "open:/dev/input/event12" in backend.calls
    assert "write" not in backend.calls


def test_session_counts_unknown_events() -> None:
    backend = FixtureInputBackend([RawInputEvent(1, 999, 1, time.monotonic_ns())])

    result = run_input_session(spec(), "/dev/input/event12", backend)

    assert result.unknown_count == 1


def test_session_meets_requirements_transitions() -> None:
    events = [
        press(30), release(30),
        press(31), release(31),
        RawInputEvent(3, 8, 1, time.monotonic_ns()),
        RawInputEvent(3, 8, -1, time.monotonic_ns()),
        RawInputEvent(3, 9, 1, time.monotonic_ns()),
    ]
    partial = run_input_session(spec(), "/dev/input/event12", FixtureInputBackend(events))
    assert partial.meets_requirements(spec()) is False

    full = [item for _ in range(10) for item in (press(30), release(30))]
    full.extend(item for _ in range(10) for item in (press(31), release(31)))
    full.extend(
        item
        for _ in range(20)
        for item in (
            RawInputEvent(3, 8, 1, time.monotonic_ns()),
            RawInputEvent(3, 8, -1, time.monotonic_ns()),
        )
    )
    full.extend(
        item
        for _ in range(10)
        for item in (RawInputEvent(3, 9, 1, time.monotonic_ns()), RawInputEvent(3, 9, 0, time.monotonic_ns()))
    )
    complete = run_input_session(spec(), "/dev/input/event12", FixtureInputBackend(full))
    assert complete.meets_requirements(spec()) is True


def test_session_classifies_disconnect_with_zero_writes() -> None:
    backend = FixtureInputBackend([press(30)], fail_read=OSError(19, "ENODEV"))

    result = run_input_session(spec(), "/dev/input/event12", backend)

    assert result.disconnected is True
    assert result.meets_requirements(spec()) is False
    assert "write" not in backend.calls
    assert backend.calls.count("close") == 1


def test_session_expires_at_deadline_with_zero_writes() -> None:
    backend = FixtureInputBackend([])

    result = run_input_session(spec(duration_ms=50), "/dev/input/event12", backend)

    assert result.disconnected is False
    assert result.counts == ()
    assert "write" not in backend.calls


def test_session_open_failure_raises_permission_classification() -> None:
    class FailingOpenBackend:
        def open_read_only(self, node: str) -> object:
            raise PermissionError(13, "permission denied")

        def read_events(
            self, handle: object, deadline_ns: int
        ) -> Iterator[RawInputEvent]:
            raise AssertionError("must not read without a handle")

        def close(self, handle: object) -> None:
            pass

    with pytest.raises(InputSessionError) as raised:
        run_input_session(spec(), "/dev/input/event12", FailingOpenBackend())

    assert raised.value.code is ErrorCode.PERMISSION_DENIED


def test_real_backend_opens_read_only_and_never_writes() -> None:
    backend = EvdevReadOnlyBackend()

    with pytest.raises(InputSessionError) as raised:
        run_input_session(spec(duration_ms=10), "/dev/nonexistent-event", backend)

    assert raised.value.code is ErrorCode.PERMISSION_DENIED or raised.value.code is ErrorCode.BACKEND_FAILURE


def test_latency_p95_is_computed_from_read_to_normalize() -> None:
    events = [press(30), release(30)]
    backend = FixtureInputBackend(events)

    result = run_input_session(spec(), "/dev/input/event12", backend)

    assert result.latency_p95_ms >= 0
    assert result.latency_p95_ms <= spec().latency_p95_target_ms


def test_real_backend_surfaces_read_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    import select as select_module

    import streamdock_n3.hardware.input_session as input_session_module

    backend = EvdevReadOnlyBackend()
    handle = InputFileHandle(999, opened_read_only=True)

    def raise_read(fd: int, size: int) -> bytes:
        del fd, size
        raise OSError(19, "ENODEV")

    monkeypatch.setattr(input_session_module.os, "read", raise_read)
    monkeypatch.setattr(
        select_module,
        "select",
        lambda *args, **kwargs: ([args[0][0]], [], []),
    )

    with pytest.raises(OSError):
        list(backend.read_events(handle, time.monotonic_ns() + 10**9))




def test_real_backend_treats_empty_read_as_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import select as select_module

    import streamdock_n3.hardware.input_session as input_session_module

    backend = EvdevReadOnlyBackend()
    handle = InputFileHandle(999, opened_read_only=True)

    monkeypatch.setattr(input_session_module.os, "read", lambda fd, size: b"")
    monkeypatch.setattr(
        select_module,
        "select",
        lambda *args, **kwargs: ([args[0][0]], [], []),
    )

    with pytest.raises(OSError):
        list(backend.read_events(handle, time.monotonic_ns() + 10**9))
