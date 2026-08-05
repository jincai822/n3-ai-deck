"""Timeout-enforcing action engine that never raises across the plugin boundary."""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

from streamdock_n3.actions.contracts import (
    ActionBinding,
    ActionContext,
    ActionPlugin,
    ActionResult,
    ActionStatus,
)
from streamdock_n3.hardware.contracts import InputKind, NormalizedInputEvent

DEFAULT_TIMEOUT_SECONDS = 5.0
_MAX_DURATION_NS = 2**63 - 1


def event_key_for(event: NormalizedInputEvent) -> str:
    """Derive a transport-neutral event key mirroring events.py's format."""
    if not isinstance(event, NormalizedInputEvent):
        raise TypeError("event must be a NormalizedInputEvent")
    if event.kind is InputKind.BUTTON:
        prefix = "button"
    elif event.kind in (InputKind.KNOB_PRESS, InputKind.KNOB_ROTATE):
        prefix = "knob"
    else:
        raise ValueError(f"unsupported input kind: {event.kind!r}")
    return f"{prefix}.{event.control_id}.{event.action.value}"


class ActionEngine:
    """Resolve configured actions for normalized events under a hard timeout."""

    def __init__(
        self,
        registry: Mapping[str, ActionPlugin],
        bindings: Mapping[str, ActionBinding],
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive number")
        if not all(isinstance(value, ActionPlugin) for value in registry.values()):
            raise TypeError("registry values must be ActionPlugin instances")
        if not all(isinstance(value, ActionBinding) for value in bindings.values()):
            raise TypeError("bindings values must be ActionBinding instances")
        self._registry = dict(registry)
        self._bindings = dict(bindings)
        self._timeout_seconds = float(timeout_seconds)
        self._executor: ThreadPoolExecutor | None = None

    def handle_event(self, event: NormalizedInputEvent) -> ActionResult | None:
        """Resolve and execute the action for one event, or None when unbound."""
        key = event_key_for(event)
        binding = self._bindings.get(key)
        if binding is None:
            return None
        plugin = self._registry.get(binding.plugin)
        if plugin is None:
            return self._failure(binding.plugin, f"unknown plugin: {binding.plugin}")
        try:
            problems = plugin.validate_config(binding.config)
        except Exception as exc:
            return self._failure(
                binding.plugin,
                f"validate_config raised {type(exc).__name__}: {exc}",
            )
        if problems:
            return self._failure(binding.plugin, "; ".join(problems))
        context = ActionContext(
            event_key=key,
            control_id=event.control_id,
            kind=event.kind.value,
            action=event.action.value,
            monotonic_ns=event.monotonic_ns,
        )
        started_ns = time.monotonic_ns()
        status, detail = self._run_with_timeout(plugin, context, binding.config)
        duration_ms = self._elapsed_ms(started_ns)
        return ActionResult(status, binding.plugin, detail, duration_ms)

    def _run_with_timeout(
        self,
        plugin: ActionPlugin,
        context: ActionContext,
        config: object,
    ) -> tuple[ActionStatus, str]:
        """Run one plugin call with the engine timeout; never raises."""
        future = self._ensure_executor().submit(plugin.execute, context, config)
        try:
            outcome = future.result(timeout=self._timeout_seconds)
        except concurrent.futures.TimeoutError:
            future.cancel()
            return (
                ActionStatus.TIMEOUT,
                f"plugin exceeded the {self._timeout_seconds:g}s timeout",
            )
        except Exception as exc:
            return (
                ActionStatus.ERROR,
                f"plugin raised {type(exc).__name__}: {exc}",
            )
        if not isinstance(outcome, ActionResult):
            return ActionStatus.ERROR, "plugin execute did not return an ActionResult"
        return outcome.status, outcome.detail

    def _failure(self, plugin: str, detail: str) -> ActionResult:
        return ActionResult(ActionStatus.ERROR, plugin, detail, 0)

    def _ensure_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="n3-action")
        return self._executor

    def _elapsed_ms(self, started_ns: int) -> int:
        return min(_MAX_DURATION_NS, max(0, time.monotonic_ns() - started_ns)) // 1_000_000
