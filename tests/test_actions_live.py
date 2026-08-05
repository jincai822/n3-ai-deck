from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterator, Sequence

import pytest

from streamdock_n3.actions.contracts import (
    ActionBinding,
    ActionContext,
    ActionResult,
    ActionStatus,
    PluginMetadata,
)
from streamdock_n3.actions.engine import ActionEngine
from streamdock_n3.actions.live import (
    LiveSessionResult,
    LiveSessionSpec,
    LiveSessionStatus,
    run_live_loop,
)
from streamdock_n3.hardware.contracts import (
    MAX_DEADLINE_MS,
    InputAction,
    InputKind,
    KeyMap,
    KeyMapEntry,
    NormalizedInputEvent,
    RawInputEvent,
)
from streamdock_n3.hardware.input_session import VENDOR_EVENT_TYPE, InputFileHandle
from streamdock_n3.hardware.vendor_backend import REPORT_PAYLOAD_BYTES

_NODE = "vendor-node"


def frame(payload: bytes) -> bytes:
    """Build the expected hidraw write: leading report id + zero-padded payload."""
    return b"\x00" + payload + bytes(REPORT_PAYLOAD_BYTES - len(payload))


EXPECTED_INIT_FRAMES = [
    frame(b"CRT\x00\x00DIS"),
    frame(b"CRT\x00\x00LIG\x00\x00\x32"),
    frame(b"CRT\x00\x00STP"),
]


def _key_map() -> KeyMap:
    return KeyMap(
        (
            KeyMapEntry(VENDOR_EVENT_TYPE, 0x25, 1, InputKind.BUTTON, InputAction.PRESS),
            KeyMapEntry(VENDOR_EVENT_TYPE, 0x30, 1, InputKind.KNOB_PRESS, InputAction.PRESS),
        )
    )


def _raw(code: int, value: int = 1, ns: int = 1_000) -> RawInputEvent:
    return RawInputEvent(VENDOR_EVENT_TYPE, code, value, ns)


class RecordingTransport:
    """Fake vendor transport; records every frame, never touches real nodes."""

    def __init__(
        self,
        *,
        open_error: OSError | None = None,
        write_error_at: int | None = None,
    ) -> None:
        self.open_error = open_error
        self.write_error_at = write_error_at
        self.open_calls: list[str] = []
        self.frames: list[bytes] = []
        self.drain_calls = 0
        self.close_calls = 0

    def open_read_write(self, node: str) -> int:
        self.open_calls.append(node)
        if self.open_error is not None:
            raise self.open_error
        return 997

    def write(self, fd: int, data: bytes) -> None:
        del fd
        if self.write_error_at is not None and len(self.frames) == self.write_error_at:
            raise OSError("scripted write failure")
        self.frames.append(bytes(data))

    def drain_acks(self, fd: int) -> int:
        del fd
        self.drain_calls += 1
        return 0

    def close(self, fd: int) -> None:
        del fd
        self.close_calls += 1


class ScriptedInputBackend:
    """Fake read-only backend; plays one event script once, never touches nodes.

    An ``OSError`` entry in the script raises mid-stream (disconnect). After the
    script is exhausted the backend waits until the deadline like the real
    backend, unless ``wait_until_deadline`` is False (it returns immediately so
    the outer loop re-enters it).
    """

    def __init__(
        self,
        script: Sequence[RawInputEvent | OSError] = (),
        *,
        open_error: OSError | None = None,
        permission_error: bool = False,
        wait_until_deadline: bool = True,
    ) -> None:
        self.script = deque(script)
        self.open_error = open_error
        self.permission_error = permission_error
        self.wait_until_deadline = wait_until_deadline
        self.open_calls: list[str] = []
        self.close_calls = 0
        self.iterations = 0

    def open_read_only(self, node: str) -> InputFileHandle:
        self.open_calls.append(node)
        if self.permission_error:
            raise PermissionError("scripted permission failure")
        if self.open_error is not None:
            raise self.open_error
        return InputFileHandle(11, opened_read_only=True)

    def read_events(
        self,
        handle: InputFileHandle,
        deadline_ns: int,
    ) -> Iterator[RawInputEvent]:
        del handle
        self.iterations += 1
        while self.script:
            item = self.script.popleft()
            if isinstance(item, OSError):
                raise item
            yield item
        if self.wait_until_deadline:
            remaining_ns = deadline_ns - time.monotonic_ns()
            if remaining_ns > 0:
                time.sleep(remaining_ns / 1e9)

    def close(self, handle: InputFileHandle) -> None:
        del handle
        self.close_calls += 1


class _OkPlugin:
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("ok", "1.0.0", "ok plugin")

    def validate_config(self, config: object) -> list[str]:
        return []

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        return ActionResult(ActionStatus.OK, "ok", "done", 0)


class _RaisingPlugin:
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("raise", "1.0.0", "raises from execute")

    def validate_config(self, config: object) -> list[str]:
        return []

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        raise RuntimeError("boom")


class _RaisingEngine(ActionEngine):
    def __init__(self) -> None:
        super().__init__({}, {})
        self.calls = 0

    def handle_event(self, event: NormalizedInputEvent) -> ActionResult | None:
        del event
        self.calls += 1
        raise RuntimeError("engine boom")


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[NormalizedInputEvent, ActionResult | None]] = []

    def __call__(self, event: NormalizedInputEvent, result: ActionResult | None) -> None:
        self.calls.append((event, result))


def test_normal_dispatch_routes_events_through_engine_and_callback() -> None:
    backend = ScriptedInputBackend((_raw(0x25), _raw(0x30)))
    transport = RecordingTransport()
    bindings = {"button.1.press": ActionBinding("button.1.press", "ok", {})}
    engine = ActionEngine({"ok": _OkPlugin()}, bindings)
    recorder = _Recorder()

    result = run_live_loop(
        LiveSessionSpec(duration_ms=20),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
        on_event=recorder,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.events == 2
    assert result.dispatched == 2
    assert result.unknown == 0
    assert result.disconnected is False
    assert result.init_ok is True
    assert len(recorder.calls) == 2
    event, action_result = recorder.calls[0]
    assert event.kind is InputKind.BUTTON and event.control_id == 1
    assert action_result is not None
    assert action_result.status is ActionStatus.OK
    assert action_result.plugin == "ok"
    event, action_result = recorder.calls[1]
    assert event.kind is InputKind.KNOB_PRESS
    assert action_result is None  # unbound: no result, no execution


def test_unknown_raw_codes_are_counted_not_dispatched() -> None:
    backend = ScriptedInputBackend((_raw(0x99), _raw(0x25)))
    transport = RecordingTransport()
    engine = ActionEngine({}, {})
    recorder = _Recorder()

    result = run_live_loop(
        LiveSessionSpec(duration_ms=20, init=False),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
        on_event=recorder,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.events == 2
    assert result.unknown == 1
    assert result.dispatched == 1
    assert len(recorder.calls) == 1
    assert recorder.calls[0][0].kind is InputKind.BUTTON


def test_plugin_exception_does_not_crash_the_loop() -> None:
    backend = ScriptedInputBackend((_raw(0x25), _raw(0x25)))
    transport = RecordingTransport()
    bindings = {"button.1.press": ActionBinding("button.1.press", "raise", {})}
    engine = ActionEngine({"raise": _RaisingPlugin()}, bindings)
    recorder = _Recorder()

    result = run_live_loop(
        LiveSessionSpec(duration_ms=20, init=False),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
        on_event=recorder,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.dispatched == 2
    assert len(recorder.calls) == 2
    for _, action_result in recorder.calls:
        assert action_result is not None
        assert action_result.status is ActionStatus.ERROR
        assert action_result.plugin == "raise"
        assert "RuntimeError" in action_result.detail
        assert "boom" in action_result.detail


def test_engine_exception_is_captured_and_loop_continues() -> None:
    backend = ScriptedInputBackend((_raw(0x25), _raw(0x25)))
    transport = RecordingTransport()
    engine = _RaisingEngine()
    recorder = _Recorder()

    result = run_live_loop(
        LiveSessionSpec(duration_ms=20, init=False),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
        on_event=recorder,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.dispatched == 2
    assert engine.calls == 2
    assert len(recorder.calls) == 2
    for _, action_result in recorder.calls:
        assert action_result is not None
        assert action_result.status is ActionStatus.ERROR
        assert action_result.plugin == "<engine>"
        assert "engine boom" in action_result.detail


def test_disconnect_oserror_exits_cleanly() -> None:
    backend = ScriptedInputBackend((_raw(0x25), OSError("node unplugged")))
    transport = RecordingTransport()
    engine = ActionEngine({}, {})
    recorder = _Recorder()

    result = run_live_loop(
        LiveSessionSpec(duration_ms=200, init=False),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
        on_event=recorder,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.disconnected is True
    assert result.events == 1
    assert result.dispatched == 1
    assert result.unknown == 0
    assert backend.close_calls == 1


def test_init_on_writes_exact_validated_trio() -> None:
    backend = ScriptedInputBackend()
    transport = RecordingTransport()
    engine = ActionEngine({}, {})

    result = run_live_loop(
        LiveSessionSpec(duration_ms=10),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.init_ok is True
    assert result.events == 0
    assert transport.open_calls == [_NODE]
    assert transport.frames == EXPECTED_INIT_FRAMES
    assert transport.drain_calls == 3
    assert transport.close_calls == 1


def test_init_off_writes_no_frames() -> None:
    backend = ScriptedInputBackend()
    transport = RecordingTransport()
    engine = ActionEngine({}, {})

    result = run_live_loop(
        LiveSessionSpec(duration_ms=10, init=False),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.init_ok is True
    assert result.events == 0
    assert transport.open_calls == []
    assert transport.frames == []
    assert transport.close_calls == 0


def test_init_write_failure_is_recorded_and_loop_continues() -> None:
    backend = ScriptedInputBackend((_raw(0x25),))
    transport = RecordingTransport(write_error_at=0)
    engine = ActionEngine({}, {})
    recorder = _Recorder()

    result = run_live_loop(
        LiveSessionSpec(duration_ms=20),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
        on_event=recorder,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.init_ok is False
    assert result.events == 1
    assert result.dispatched == 1
    assert transport.frames == []
    assert transport.close_calls == 1


def test_init_open_failure_is_recorded_and_loop_continues() -> None:
    backend = ScriptedInputBackend((_raw(0x25),))
    transport = RecordingTransport(open_error=OSError("no write node"))
    engine = ActionEngine({}, {})

    result = run_live_loop(
        LiveSessionSpec(duration_ms=20),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.init_ok is False
    assert result.events == 1
    assert transport.open_calls == [_NODE]
    assert transport.frames == []
    assert transport.close_calls == 0


def test_read_open_permission_failure_returns_rejected() -> None:
    backend = ScriptedInputBackend(permission_error=True)
    transport = RecordingTransport()
    engine = ActionEngine({}, {})

    result = run_live_loop(
        LiveSessionSpec(duration_ms=20, init=False),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
    )

    assert result.status is LiveSessionStatus.REJECTED
    assert result.events == 0
    assert backend.open_calls == [_NODE]
    assert backend.close_calls == 0


def test_read_open_failure_returns_error() -> None:
    backend = ScriptedInputBackend(open_error=OSError("no read node"))
    transport = RecordingTransport()
    engine = ActionEngine({}, {})

    result = run_live_loop(
        LiveSessionSpec(duration_ms=20, init=False),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
    )

    assert result.status is LiveSessionStatus.ERROR
    assert result.events == 0
    assert backend.open_calls == [_NODE]
    assert backend.close_calls == 0


def test_loop_honors_deadline_and_reenters_the_backend() -> None:
    backend = ScriptedInputBackend((_raw(0x25),), wait_until_deadline=False)
    transport = RecordingTransport()
    engine = ActionEngine({}, {})

    result = run_live_loop(
        LiveSessionSpec(duration_ms=10, init=False),
        _NODE,
        _key_map(),
        engine,
        input_backend=backend,
        transport=transport,
    )

    assert result.status is LiveSessionStatus.SUCCEEDED
    assert result.events == 1
    assert result.dispatched == 1
    assert backend.iterations > 1


def test_spec_validates_duration_and_init() -> None:
    assert LiveSessionSpec(duration_ms=1).init is True
    assert LiveSessionSpec(duration_ms=MAX_DEADLINE_MS, init=False).init is False

    with pytest.raises(ValueError):
        LiveSessionSpec(duration_ms=0)
    with pytest.raises(ValueError):
        LiveSessionSpec(duration_ms=MAX_DEADLINE_MS + 1)
    with pytest.raises(TypeError):
        LiveSessionSpec(duration_ms=20, init=1)  # type: ignore[arg-type]


def test_result_to_dict_is_deterministic() -> None:
    result = LiveSessionResult(
        status=LiveSessionStatus.SUCCEEDED,
        events=3,
        dispatched=2,
        unknown=1,
        disconnected=False,
        init_ok=True,
        duration_ms=12,
    )

    assert result.to_dict() == {
        "status": "succeeded",
        "events": 3,
        "dispatched": 2,
        "unknown": 1,
        "disconnected": False,
        "init_ok": True,
        "duration_ms": 12,
    }


def test_run_live_loop_rejects_invalid_arguments() -> None:
    backend = ScriptedInputBackend()
    transport = RecordingTransport()
    engine = ActionEngine({}, {})

    with pytest.raises(TypeError):
        run_live_loop(  # type: ignore[arg-type]
            "nope",
            _NODE,
            _key_map(),
            engine,
            input_backend=backend,
            transport=transport,
        )
    with pytest.raises(ValueError):
        run_live_loop(
            LiveSessionSpec(duration_ms=10),
            "",
            _key_map(),
            engine,
            input_backend=backend,
            transport=transport,
        )
    with pytest.raises(TypeError):
        run_live_loop(  # type: ignore[arg-type]
            LiveSessionSpec(duration_ms=10),
            _NODE,
            "nope",
            engine,
            input_backend=backend,
            transport=transport,
        )
    with pytest.raises(TypeError):
        run_live_loop(  # type: ignore[arg-type]
            LiveSessionSpec(duration_ms=10),
            _NODE,
            _key_map(),
            object(),
            input_backend=backend,
            transport=transport,
        )
