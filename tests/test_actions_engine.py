from __future__ import annotations

import threading
import time

import pytest

from streamdock_n3.actions.contracts import (
    ActionBinding,
    ActionContext,
    ActionResult,
    ActionStatus,
    PluginMetadata,
)
from streamdock_n3.actions.engine import DEFAULT_TIMEOUT_SECONDS, ActionEngine, event_key_for
from streamdock_n3.hardware.contracts import InputAction, InputKind, NormalizedInputEvent


def _button_press_event() -> NormalizedInputEvent:
    return NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 1_000_000)


class _OkPlugin:
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("ok", "1.0.0", "ok plugin")

    def validate_config(self, config: object) -> list[str]:
        return []

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        return ActionResult(ActionStatus.OK, "ok", "done", 0)


class _StampingPlugin:
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("stamp", "1.0.0", "returns its own plugin and duration")

    def validate_config(self, config: object) -> list[str]:
        return []

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        return ActionResult(ActionStatus.OK, "self-named", "done", 999)


class _ConfigRejectingPlugin:
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("reject", "1.0.0", "rejects its config")

    def validate_config(self, config: object) -> list[str]:
        return ["bad config", "also bad"]

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        raise AssertionError("rejecting plugin must not execute")


class _ConfigExplodingPlugin:
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("explode", "1.0.0", "raises from validate_config")

    def validate_config(self, config: object) -> list[str]:
        raise ValueError("config crash")

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        raise AssertionError("exploding plugin must not execute")


class _RaisingPlugin:
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("raise", "1.0.0", "raises from execute")

    def validate_config(self, config: object) -> list[str]:
        return []

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        raise RuntimeError("boom")


class _NonePlugin:
    def metadata(self) -> PluginMetadata:
        return PluginMetadata("none", "1.0.0", "returns None from execute")

    def validate_config(self, config: object) -> list[str]:
        return []

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        return None  # type: ignore[return-value]


class _BlockingPlugin:
    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate

    def metadata(self) -> PluginMetadata:
        return PluginMetadata("block", "1.0.0", "blocks until released")

    def validate_config(self, config: object) -> list[str]:
        return []

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        self._gate.wait(timeout=30)
        return ActionResult(ActionStatus.OK, "block", "late", 0)


def test_event_key_for_matches_events_py_format() -> None:
    button = NormalizedInputEvent(InputKind.BUTTON, 3, InputAction.PRESS, 0)
    knob_press = NormalizedInputEvent(InputKind.KNOB_PRESS, 2, InputAction.RELEASE, 0)
    knob_rotate = NormalizedInputEvent(InputKind.KNOB_ROTATE, 1, InputAction.LEFT, 0)

    assert event_key_for(button) == "button.3.press"
    assert event_key_for(knob_press) == "knob.2.release"
    assert event_key_for(knob_rotate) == "knob.1.left"


def test_event_key_for_rejects_non_events() -> None:
    with pytest.raises(TypeError):
        event_key_for("button.1.press")


def test_engine_defaults_to_five_second_timeout() -> None:
    assert DEFAULT_TIMEOUT_SECONDS == 5.0


def test_success_returns_plugin_result() -> None:
    bindings = {"button.1.press": ActionBinding("button.1.press", "ok", {"app": "x"})}
    engine = ActionEngine({"ok": _OkPlugin()}, bindings)

    result = engine.handle_event(_button_press_event())

    assert result is not None
    assert result.status is ActionStatus.OK
    assert result.detail == "done"
    assert result.plugin == "ok"
    assert result.duration_ms >= 0


def test_engine_stamps_plugin_and_duration_on_success() -> None:
    bindings = {"button.1.press": ActionBinding("button.1.press", "stamp", {})}
    engine = ActionEngine({"stamp": _StampingPlugin()}, bindings)

    result = engine.handle_event(_button_press_event())

    assert result is not None
    assert result.status is ActionStatus.OK
    assert result.plugin == "stamp"
    assert result.duration_ms < 999


def test_unbound_event_returns_none_without_executing() -> None:
    engine = ActionEngine({"ok": _OkPlugin()}, {})

    assert engine.handle_event(_button_press_event()) is None


def test_missing_plugin_returns_error_result() -> None:
    bindings = {"button.1.press": ActionBinding("button.1.press", "ghost", {})}
    engine = ActionEngine({}, bindings)

    result = engine.handle_event(_button_press_event())

    assert result is not None
    assert result.status is ActionStatus.ERROR
    assert result.plugin == "ghost"
    assert "ghost" in result.detail
    assert result.duration_ms == 0


def test_config_validation_failure_returns_error_result() -> None:
    bindings = {"button.1.press": ActionBinding("button.1.press", "reject", {"app": "x"})}
    engine = ActionEngine({"reject": _ConfigRejectingPlugin()}, bindings)

    result = engine.handle_event(_button_press_event())

    assert result is not None
    assert result.status is ActionStatus.ERROR
    assert result.plugin == "reject"
    assert "bad config" in result.detail
    assert "also bad" in result.detail
    assert result.duration_ms == 0


def test_validate_config_exception_returns_error_result_without_raising() -> None:
    bindings = {"button.1.press": ActionBinding("button.1.press", "explode", {})}
    engine = ActionEngine({"explode": _ConfigExplodingPlugin()}, bindings)

    result = engine.handle_event(_button_press_event())

    assert result is not None
    assert result.status is ActionStatus.ERROR
    assert "ValueError" in result.detail
    assert "config crash" in result.detail


def test_plugin_exception_returns_error_result_without_raising() -> None:
    bindings = {"button.1.press": ActionBinding("button.1.press", "raise", {})}
    engine = ActionEngine({"raise": _RaisingPlugin()}, bindings)

    result = engine.handle_event(_button_press_event())

    assert result is not None
    assert result.status is ActionStatus.ERROR
    assert result.plugin == "raise"
    assert "RuntimeError" in result.detail
    assert "boom" in result.detail


def test_non_action_result_return_is_an_error_result() -> None:
    bindings = {"button.1.press": ActionBinding("button.1.press", "none", {})}
    engine = ActionEngine({"none": _NonePlugin()}, bindings)

    result = engine.handle_event(_button_press_event())

    assert result is not None
    assert result.status is ActionStatus.ERROR
    assert "ActionResult" in result.detail


def test_timeout_returns_timeout_result_without_raising() -> None:
    gate = threading.Event()
    bindings = {"button.1.press": ActionBinding("button.1.press", "block", {})}
    engine = ActionEngine({"block": _BlockingPlugin(gate)}, bindings, timeout_seconds=0.05)
    started = time.monotonic()

    try:
        result = engine.handle_event(_button_press_event())
        elapsed = time.monotonic() - started

        assert result is not None
        assert result.status is ActionStatus.TIMEOUT
        assert result.plugin == "block"
        assert "0.05" in result.detail
        assert elapsed < 1.0
        assert result.duration_ms >= 0
    finally:
        gate.set()


def test_engine_accepts_int_timeout_and_snapshots_inputs() -> None:
    bindings = {"button.1.press": ActionBinding("button.1.press", "ok", {})}
    registry = {"ok": _OkPlugin()}
    engine = ActionEngine(registry, bindings, timeout_seconds=1)

    bindings["knob.1.left"] = ActionBinding("knob.1.left", "ok", {})
    del registry["ok"]

    assert engine.handle_event(_button_press_event()) is not None
    knob = NormalizedInputEvent(InputKind.KNOB_ROTATE, 1, InputAction.LEFT, 0)
    assert engine.handle_event(knob) is None


def test_engine_rejects_invalid_arguments() -> None:
    with pytest.raises(ValueError):
        ActionEngine({}, {}, timeout_seconds=0)
    with pytest.raises(ValueError):
        ActionEngine({}, {}, timeout_seconds=-1)
    with pytest.raises(ValueError):
        ActionEngine({}, {}, timeout_seconds=True)
    with pytest.raises(TypeError):
        ActionEngine({"bad": object()}, {})
    with pytest.raises(TypeError):
        ActionEngine({}, {"button.1.press": object()})


def test_handle_event_rejects_non_events() -> None:
    engine = ActionEngine({}, {})

    with pytest.raises(TypeError):
        engine.handle_event("button.1.press")  # type: ignore[arg-type]
