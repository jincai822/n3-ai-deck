"""G8 background service loop: reconnect with backoff, bounded sessions, clean stop.

P2 of the G8 design (section 4 of
docs/superpowers/specs/2026-08-05-g8-service-design.md): the stateless,
restartable loop that keeps re-resolving the vendor hidraw node and re-running
one bounded live session until SIGTERM stops it. Every dependency
(node_resolver, session_runner, sleep, on_lifecycle) is injectable so tests
never touch a real node, a real clock, or a real signal.
"""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from types import FrameType
from typing import NoReturn

from streamdock_n3.actions.contracts import _validate_int
from streamdock_n3.actions.engine import DEFAULT_TIMEOUT_SECONDS
from streamdock_n3.actions.live import LiveSessionResult, LiveSessionStatus
from streamdock_n3.hardware.contracts import MAX_DEADLINE_MS

logger = logging.getLogger(__name__)

DEFAULT_BACKOFF_SCHEDULE = (2.0, 5.0, 10.0, 30.0)


class ServiceStatus(StrEnum):
    """High-level outcome of a stopped background service run."""

    STOPPED = "stopped"


class ServiceStopped(Exception):
    """Raised in the main thread by the SIGTERM handler to stop the loop cleanly."""


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """One background service configuration (immutable)."""

    session_duration_ms: int
    backoff_schedule: tuple[float, ...] = DEFAULT_BACKOFF_SCHEDULE
    init: bool = True
    feedback: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _validate_int(self.session_duration_ms, "session_duration_ms", 1, MAX_DEADLINE_MS)
        if (
            not isinstance(self.backoff_schedule, tuple)
            or not self.backoff_schedule
            or not all(
                isinstance(delay, (int, float))
                and not isinstance(delay, bool)
                and delay > 0
                for delay in self.backoff_schedule
            )
        ):
            raise ValueError(
                "backoff_schedule must be a non-empty tuple of positive numbers"
            )
        if not isinstance(self.init, bool):
            raise TypeError("init must be a bool")
        if not isinstance(self.feedback, bool):
            raise TypeError("feedback must be a bool")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive number")


@dataclass(frozen=True, slots=True)
class ServiceResult:
    """Structured outcome of a stopped background service run."""

    status: ServiceStatus
    sessions_run: int
    retries: int
    stopped_cleanly: bool

    def __post_init__(self) -> None:
        if not isinstance(self.status, ServiceStatus):
            raise TypeError("status must be a ServiceStatus")
        for field in ("sessions_run", "retries"):
            _validate_int(getattr(self, field), field, 0, 2**63 - 1)
        if not isinstance(self.stopped_cleanly, bool):
            raise TypeError("stopped_cleanly must be a bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "sessions_run": self.sessions_run,
            "retries": self.retries,
            "stopped_cleanly": self.stopped_cleanly,
        }


def _handle_sigterm(signum: int, frame: FrameType | None) -> NoReturn:
    """SIGTERM handler: raise ServiceStopped so the main loop exits cleanly."""
    raise ServiceStopped(f"signal {signum} received")


def _emit(
    on_lifecycle: Callable[[dict[str, object]], None] | None,
    event: dict[str, object],
) -> None:
    """Deliver one lifecycle event; a raising callback never crashes the loop."""
    if on_lifecycle is None:
        return
    try:
        on_lifecycle(event)
    except Exception as exc:
        logger.warning("lifecycle callback raised %s: %s", type(exc).__name__, exc)


def _backoff_delay(schedule: tuple[float, ...], index: int) -> float:
    """Return the delay at index, capped at the schedule's last value."""
    return float(schedule[min(index, len(schedule) - 1)])


def run_service(
    spec: ServiceSpec,
    *,
    node_resolver: Callable[[], str],
    session_runner: Callable[[str, ServiceSpec], LiveSessionResult],
    sleep: Callable[[float], None],
    on_lifecycle: Callable[[dict[str, object]], None] | None = None,
) -> ServiceResult:
    """Run bounded sessions back-to-back until SIGTERM, reconnecting with backoff.

    The node resolver is re-called on every iteration and never cached. Only a
    session that ended SUCCEEDED without disconnecting resets the backoff to
    the start; a session that ended rejected, error, or succeeded-but-
    disconnected retries after the current backoff delay.
    """
    if not isinstance(spec, ServiceSpec):
        raise TypeError("spec must be a ServiceSpec")
    if not callable(node_resolver):
        raise TypeError("node_resolver must be callable")
    if not callable(session_runner):
        raise TypeError("session_runner must be callable")
    if not callable(sleep):
        raise TypeError("sleep must be callable")
    if on_lifecycle is not None and not callable(on_lifecycle):
        raise TypeError("on_lifecycle must be callable")

    sessions_run = 0
    retries = 0
    backoff_index = 0
    previous_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        _emit(
            on_lifecycle,
            {
                "event": "started",
                "session_duration_ms": spec.session_duration_ms,
                "init": spec.init,
                "feedback": spec.feedback,
                "timeout_seconds": spec.timeout_seconds,
            },
        )
        while True:
            try:
                node = node_resolver()
            except ServiceStopped:
                raise
            except Exception as exc:
                retries += 1
                delay = _backoff_delay(spec.backoff_schedule, backoff_index)
                backoff_index = min(backoff_index + 1, len(spec.backoff_schedule) - 1)
                _emit(
                    on_lifecycle,
                    {
                        "event": "retry",
                        "reason": "node-absent",
                        "attempt": retries,
                        "backoff_s": delay,
                        "error": type(exc).__name__,
                    },
                )
                sleep(delay)
                continue
            try:
                result = session_runner(node, spec)
            except ServiceStopped:
                raise
            except Exception as exc:
                retries += 1
                delay = _backoff_delay(spec.backoff_schedule, backoff_index)
                backoff_index = min(backoff_index + 1, len(spec.backoff_schedule) - 1)
                _emit(
                    on_lifecycle,
                    {
                        "event": "retry",
                        "reason": "error",
                        "attempt": retries,
                        "backoff_s": delay,
                        "error": type(exc).__name__,
                    },
                )
                sleep(delay)
                continue
            sessions_run += 1
            _emit(
                on_lifecycle,
                {
                    "event": "session_end",
                    "status": result.status.value,
                    "disconnected": result.disconnected,
                    "events": result.events,
                    "dispatched": result.dispatched,
                    "unknown": result.unknown,
                    "duration_ms": result.duration_ms,
                },
            )
            if result.status is LiveSessionStatus.SUCCEEDED and not result.disconnected:
                backoff_index = 0
                continue
            retries += 1
            delay = _backoff_delay(spec.backoff_schedule, backoff_index)
            backoff_index = min(backoff_index + 1, len(spec.backoff_schedule) - 1)
            reason = "disconnected" if result.disconnected else "error"
            _emit(
                on_lifecycle,
                {
                    "event": "retry",
                    "reason": reason,
                    "attempt": retries,
                    "backoff_s": delay,
                },
            )
            sleep(delay)
    except ServiceStopped:
        _emit(
            on_lifecycle,
            {"event": "stopping", "reason": "sigterm", "exit_code": 0},
        )
        return ServiceResult(ServiceStatus.STOPPED, sessions_run, retries, True)
    except Exception as exc:
        _emit(
            on_lifecycle,
            {"event": "stopping", "reason": "fatal", "error": type(exc).__name__},
        )
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_handler)
