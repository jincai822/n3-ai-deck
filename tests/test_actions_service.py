"""Tests for the G8 background service loop (P2 of the G8 design, section 4).

No real device, no real sleep, and no real signals: the resolver, runner, and
sleep are scripted fakes, and the SIGTERM handler is invoked directly. The
loop is stopped by fakes raising ServiceStopped, which is exactly the path the
real handler takes.
"""

from __future__ import annotations

import signal

import pytest

from streamdock_n3.actions import service as service_module
from streamdock_n3.actions.engine import DEFAULT_TIMEOUT_SECONDS
from streamdock_n3.actions.live import LiveSessionResult, LiveSessionStatus
from streamdock_n3.actions.service import (
    DEFAULT_BACKOFF_SCHEDULE,
    ServiceResult,
    ServiceSpec,
    ServiceStatus,
    ServiceStopped,
    run_service,
)
from streamdock_n3.input_cli import NodeResolutionError

FAKE_NODE = "fake-node"


def _spec(
    session_duration_ms: int = 1_000,
    backoff_schedule: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE,
    init: bool = True,
    feedback: bool = False,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> ServiceSpec:
    return ServiceSpec(session_duration_ms, backoff_schedule, init, feedback, timeout_seconds)


def _result(*, disconnected: bool = False, events: int = 0, dispatched: int = 0) -> LiveSessionResult:
    return LiveSessionResult(
        LiveSessionStatus.SUCCEEDED,
        events,
        dispatched,
        0,
        disconnected,
        True,
        0,
    )


def _status_result(status: LiveSessionStatus, *, disconnected: bool = False) -> LiveSessionResult:
    """A session that ran but ended in a non-succeeded status (rejected/error)."""
    return LiveSessionResult(status, 0, 0, 0, disconnected, True, 0)


class ScriptedResolver:
    """Resolver with a scripted queue of nodes or exceptions; defaults to a node.

    With ``failure`` set, every call raises it; otherwise outcomes are consumed
    in order and a default node is returned once the queue is empty.
    """

    def __init__(self, *outcomes: str | Exception, failure: Exception | None = None) -> None:
        self._outcomes = list(outcomes)
        self._failure = failure
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        if not self._outcomes:
            return FAKE_NODE
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ScriptedRunner:
    """Session runner with a scripted queue of results or exceptions."""

    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[str] = []

    def __call__(self, node: str, spec: ServiceSpec) -> LiveSessionResult:
        self.calls.append(node)
        if not self._outcomes:
            return _result()
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[return-value]


class ScriptedSleep:
    """Sleep recording delays; optionally raises ServiceStopped after k calls."""

    def __init__(self, stop_after: int | None = None) -> None:
        self.calls: list[float] = []
        self._stop_after = stop_after

    def __call__(self, delay: float) -> None:
        self.calls.append(delay)
        if self._stop_after is not None and len(self.calls) >= self._stop_after:
            raise ServiceStopped("test stop")


class TestServiceSpec:
    def test_valid_default_spec(self) -> None:
        spec = _spec()
        assert spec.backoff_schedule == DEFAULT_BACKOFF_SCHEDULE
        assert spec.init is True
        assert spec.feedback is False
        assert spec.timeout_seconds == DEFAULT_TIMEOUT_SECONDS

    def test_rejects_invalid_session_duration_ms(self) -> None:
        for bad in (0, -1, 600_001, True, 1.5):
            with pytest.raises(ValueError):
                _spec(session_duration_ms=bad)

    def test_rejects_invalid_backoff_schedule(self) -> None:
        for bad in ((), (0.0,), (2.0, -1.0), (2.0, True), [2.0, 5.0]):
            with pytest.raises(ValueError):
                _spec(backoff_schedule=bad)

    def test_rejects_invalid_flag_types(self) -> None:
        with pytest.raises(TypeError):
            _spec(init=1)
        with pytest.raises(TypeError):
            _spec(feedback="yes")

    def test_rejects_invalid_timeout_seconds(self) -> None:
        for bad in (0, -1, True):
            with pytest.raises(ValueError):
                _spec(timeout_seconds=bad)


class TestServiceResult:
    def test_to_dict(self) -> None:
        result = ServiceResult(ServiceStatus.STOPPED, 3, 2, True)
        assert result.to_dict() == {
            "status": "stopped",
            "sessions_run": 3,
            "retries": 2,
            "stopped_cleanly": True,
        }

    def test_validation(self) -> None:
        with pytest.raises(TypeError):
            ServiceResult("stopped", 0, 0, True)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            ServiceResult(ServiceStatus.STOPPED, -1, 0, True)
        with pytest.raises(TypeError):
            ServiceResult(ServiceStatus.STOPPED, 0, 0, 1)  # type: ignore[arg-type]


class TestRunServiceArguments:
    def test_rejects_invalid_spec(self) -> None:
        with pytest.raises(TypeError):
            run_service(  # type: ignore[arg-type]
                "not-a-spec",
                node_resolver=lambda: FAKE_NODE,
                session_runner=lambda node, spec: _result(),
                sleep=lambda delay: None,
            )

    def test_rejects_non_callable_dependencies(self) -> None:
        with pytest.raises(TypeError):
            run_service(
                _spec(),
                node_resolver=None,  # type: ignore[arg-type]
                session_runner=lambda node, spec: _result(),
                sleep=lambda delay: None,
            )
        with pytest.raises(TypeError):
            run_service(
                _spec(),
                node_resolver=lambda: FAKE_NODE,
                session_runner=None,  # type: ignore[arg-type]
                sleep=lambda delay: None,
            )
        with pytest.raises(TypeError):
            run_service(
                _spec(),
                node_resolver=lambda: FAKE_NODE,
                session_runner=lambda node, spec: _result(),
                sleep=None,  # type: ignore[arg-type]
            )
        with pytest.raises(TypeError):
            run_service(
                _spec(),
                node_resolver=lambda: FAKE_NODE,
                session_runner=lambda node, spec: _result(),
                sleep=lambda delay: None,
                on_lifecycle=3,  # type: ignore[arg-type]
            )


class TestRunService:
    def test_node_absent_backoff_progression_and_cap(self) -> None:
        resolver = ScriptedResolver(failure=NodeResolutionError("gone"))
        runner = ScriptedRunner()
        sleep = ScriptedSleep(stop_after=6)
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        assert result.status is ServiceStatus.STOPPED
        assert result.stopped_cleanly is True
        assert result.sessions_run == 0
        assert result.retries == 6
        assert sleep.calls == [2.0, 5.0, 10.0, 30.0, 30.0, 30.0]
        assert runner.calls == []
        retry_events = [e for e in events if e["event"] == "retry"]
        assert [e["reason"] for e in retry_events] == ["node-absent"] * 6
        assert [e["backoff_s"] for e in retry_events] == [2.0, 5.0, 10.0, 30.0, 30.0, 30.0]

    def test_disconnect_reconnects_with_backoff(self) -> None:
        resolver = ScriptedResolver()
        runner = ScriptedRunner(_result(disconnected=True), _result(disconnected=True))
        sleep = ScriptedSleep(stop_after=2)
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        assert result.sessions_run == 2
        assert result.retries == 2
        assert sleep.calls == [2.0, 5.0]
        assert runner.calls == [FAKE_NODE, FAKE_NODE]
        retry_events = [e for e in events if e["event"] == "retry"]
        assert [e["reason"] for e in retry_events] == ["disconnected", "disconnected"]

    def test_runner_error_is_contained_and_retries(self) -> None:
        resolver = ScriptedResolver()
        runner = ScriptedRunner(OSError("boom"), _result())
        sleep = ScriptedSleep(stop_after=1)
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        assert result.sessions_run == 0
        assert result.retries == 1
        assert sleep.calls == [2.0]
        retry_events = [e for e in events if e["event"] == "retry"]
        assert retry_events[0]["reason"] == "error"
        assert retry_events[0]["error"] == "OSError"

    def test_success_resets_backoff_to_start(self) -> None:
        resolver = ScriptedResolver(
            NodeResolutionError("gone"), NodeResolutionError("gone")
        )
        runner = ScriptedRunner(_result(), _result(disconnected=True))
        sleep = ScriptedSleep(stop_after=3)
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        # Two node-absent retries (2s, 5s), one clean session that resets the
        # backoff, then a disconnect that sleeps 2s again -- not 10s.
        assert sleep.calls == [2.0, 5.0, 2.0]
        assert result.sessions_run == 2
        assert result.retries == 3
        assert resolver.calls == 4
        assert runner.calls == [FAKE_NODE, FAKE_NODE]

    def test_rejected_session_backs_off_without_reset(self) -> None:
        resolver = ScriptedResolver()
        runner = ScriptedRunner(
            _status_result(LiveSessionStatus.REJECTED),
            _status_result(LiveSessionStatus.REJECTED),
            _status_result(LiveSessionStatus.REJECTED),
        )
        sleep = ScriptedSleep(stop_after=3)
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        assert result.stopped_cleanly is True
        # Every session ran and returned a result, even though none succeeded.
        assert result.sessions_run == 3
        assert result.retries == 3
        assert sleep.calls == [2.0, 5.0, 10.0]  # advancing, never reset
        assert runner.calls == [FAKE_NODE, FAKE_NODE, FAKE_NODE]
        retry_events = [e for e in events if e["event"] == "retry"]
        assert [e["reason"] for e in retry_events] == ["error", "error", "error"]
        assert [e["backoff_s"] for e in retry_events] == [2.0, 5.0, 10.0]
        assert [e["status"] for e in events if e["event"] == "session_end"] == [
            "rejected",
            "rejected",
            "rejected",
        ]

    def test_rejected_session_then_success_resets_backoff(self) -> None:
        resolver = ScriptedResolver()
        runner = ScriptedRunner(
            _status_result(LiveSessionStatus.REJECTED),
            _result(),
            _status_result(LiveSessionStatus.REJECTED),
            ServiceStopped("stop"),
        )
        sleep = ScriptedSleep(stop_after=2)
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        assert result.stopped_cleanly is True
        assert result.sessions_run == 3
        assert result.retries == 2
        # rejected -> 2s; the clean success resets the backoff; the next
        # rejected session sleeps 2s again -- not 10s.
        assert sleep.calls == [2.0, 2.0]
        retry_events = [e for e in events if e["event"] == "retry"]
        assert [e["backoff_s"] for e in retry_events] == [2.0, 2.0]

    def test_error_status_session_backs_off(self) -> None:
        resolver = ScriptedResolver()
        runner = ScriptedRunner(
            _status_result(LiveSessionStatus.ERROR),
            _status_result(LiveSessionStatus.ERROR),
        )
        sleep = ScriptedSleep(stop_after=2)
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        assert result.stopped_cleanly is True
        assert result.sessions_run == 2
        assert result.retries == 2
        assert sleep.calls == [2.0, 5.0]
        retry_events = [e for e in events if e["event"] == "retry"]
        assert [e["reason"] for e in retry_events] == ["error", "error"]

    def test_resolver_called_every_iteration(self) -> None:
        resolver = ScriptedResolver(FAKE_NODE, FAKE_NODE, ServiceStopped("stop"))
        runner = ScriptedRunner(_result(), _result())
        sleep = ScriptedSleep()
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        assert resolver.calls == 3
        assert runner.calls == [FAKE_NODE, FAKE_NODE]
        assert result.sessions_run == 2
        assert result.stopped_cleanly is True
        assert sleep.calls == []
        assert events[0]["event"] == "started"
        assert events[-1] == {"event": "stopping", "reason": "sigterm", "exit_code": 0}

    def test_sigterm_mid_sleep_stops_cleanly(self) -> None:
        resolver = ScriptedResolver(failure=NodeResolutionError("gone"))
        runner = ScriptedRunner()
        sleep = ScriptedSleep(stop_after=1)
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        assert result.stopped_cleanly is True
        assert result.sessions_run == 0
        assert result.retries == 1
        assert events[-1] == {"event": "stopping", "reason": "sigterm", "exit_code": 0}

    def test_sigterm_mid_session_stops_cleanly(self) -> None:
        resolver = ScriptedResolver()
        runner = ScriptedRunner(ServiceStopped("stop"))
        sleep = ScriptedSleep()
        events: list[dict[str, object]] = []
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=sleep,
            on_lifecycle=events.append,
        )
        assert result.stopped_cleanly is True
        assert result.sessions_run == 0
        assert sleep.calls == []
        # The aborted session must not emit a session_end event.
        assert [e["event"] for e in events] == ["started", "stopping"]

    def test_lifecycle_callback_raising_never_crashes_loop(self) -> None:
        def exploding(event: dict[str, object]) -> None:
            raise RuntimeError("callback broken")

        resolver = ScriptedResolver(FAKE_NODE, ServiceStopped("stop"))
        runner = ScriptedRunner(_result())
        result = run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=runner,
            sleep=ScriptedSleep(),
            on_lifecycle=exploding,
        )
        assert result.sessions_run == 1
        assert result.stopped_cleanly is True

    def test_lifecycle_events_shape(self) -> None:
        resolver = ScriptedResolver(ServiceStopped("stop"))
        events: list[dict[str, object]] = []
        run_service(
            _spec(),
            node_resolver=resolver,
            session_runner=ScriptedRunner(),
            sleep=ScriptedSleep(),
            on_lifecycle=events.append,
        )
        assert events[0] == {
            "event": "started",
            "session_duration_ms": 1_000,
            "init": True,
            "feedback": False,
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        }
        assert events[-1] == {"event": "stopping", "reason": "sigterm", "exit_code": 0}


class TestSigtermHandler:
    def test_handler_raises_service_stopped(self) -> None:
        with pytest.raises(ServiceStopped):
            service_module._handle_sigterm(signal.SIGTERM, None)
