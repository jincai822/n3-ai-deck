from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from streamdock_n3.actions.ai import AiTextPlugin
from streamdock_n3.actions.builtins import (
    ALLOWLISTED_EXECUTABLES,
    LaunchAppPlugin,
    LogEventPlugin,
    builtin_registry,
)
from streamdock_n3.actions.contracts import (
    ActionBinding,
    ActionContext,
    ActionPlugin,
    ActionResult,
    ActionStatus,
)
from streamdock_n3.actions.engine import ActionEngine
from streamdock_n3.hardware.contracts import InputAction, InputKind, NormalizedInputEvent


def _context() -> ActionContext:
    return ActionContext("button.1.press", 1, "button", "press", 1_000_000)


def _launch_app_config(app: str, args: list[str] | None = None) -> dict[str, object]:
    config: dict[str, object] = {"app": app}
    if args is not None:
        config["args"] = args
    return config


def test_allowlist_contains_the_documented_safe_names() -> None:
    assert frozenset({"alacritty", "firefox", "wpctl", "playerctl"}) == ALLOWLISTED_EXECUTABLES


def test_launch_app_validate_config_accepts_valid_configs() -> None:
    plugin = LaunchAppPlugin()

    assert plugin.validate_config(_launch_app_config("firefox")) == []
    assert plugin.validate_config(_launch_app_config("wpctl", [])) == []
    assert plugin.validate_config(_launch_app_config("playerctl", ["play-pause"])) == []


@pytest.mark.parametrize(
    "config",
    (
        "alacritty",
        None,
        42,
        {},
        {"args": []},
        {"app": ""},
        {"app": 42},
        {"app": "bash"},
        {"app": "evil.sh"},
        {"app": "firefox", "args": "x"},
        {"app": "firefox", "args": [1]},
        {"app": "firefox", "args": ["ok", 2]},
        {"app": "firefox", "args": [""]},
    ),
)
def test_launch_app_validate_config_rejects_invalid_configs(config: object) -> None:
    assert LaunchAppPlugin().validate_config(config) != []


def test_launch_app_executes_allowlisted_app_as_argv_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> object:
        recorded.append((argv, kwargs))
        return object()

    monkeypatch.setattr(
        "streamdock_n3.actions.builtins.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr("streamdock_n3.actions.builtins.subprocess.Popen", fake_popen)

    result = LaunchAppPlugin().execute(
        _context(), _launch_app_config("alacritty", ["-e", "nvim"])
    )

    assert result.status is ActionStatus.OK
    assert len(recorded) == 1
    argv, kwargs = recorded[0]
    assert argv == ["/usr/bin/alacritty", "-e", "nvim"]
    assert kwargs["shell"] is False
    assert kwargs["start_new_session"] is True


def test_launch_app_without_args_passes_only_the_resolved_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> object:
        recorded.append((argv, kwargs))
        return object()

    monkeypatch.setattr(
        "streamdock_n3.actions.builtins.shutil.which",
        lambda name: f"/opt/bin/{name}",
    )
    monkeypatch.setattr("streamdock_n3.actions.builtins.subprocess.Popen", fake_popen)

    result = LaunchAppPlugin().execute(_context(), _launch_app_config("wpctl"))

    assert result.status is ActionStatus.OK
    assert recorded[0][0] == ["/opt/bin/wpctl"]


def test_launch_app_unresolvable_name_fails_before_any_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []

    def fake_popen(*args: Any, **kwargs: Any) -> object:
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr("streamdock_n3.actions.builtins.shutil.which", lambda name: None)
    monkeypatch.setattr("streamdock_n3.actions.builtins.subprocess.Popen", fake_popen)

    result = LaunchAppPlugin().execute(_context(), _launch_app_config("firefox"))

    assert result.status is ActionStatus.ERROR
    assert "not available on PATH" in result.detail
    assert calls == []


def test_launch_app_popen_failure_is_an_error_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_popen(*args: Any, **kwargs: Any) -> object:
        raise OSError("exec format error")

    monkeypatch.setattr(
        "streamdock_n3.actions.builtins.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr("streamdock_n3.actions.builtins.subprocess.Popen", fake_popen)

    result = LaunchAppPlugin().execute(_context(), _launch_app_config("firefox"))

    assert result.status is ActionStatus.ERROR
    assert "failed to launch firefox" in result.detail


def test_launch_app_rejects_invalid_config_directly() -> None:
    result = LaunchAppPlugin().execute(_context(), "not a config")

    assert result.status is ActionStatus.ERROR


def test_log_event_validate_config_always_passes() -> None:
    plugin = LogEventPlugin()

    assert plugin.validate_config(None) == []
    assert plugin.validate_config({"anything": True}) == []


def test_log_event_logs_a_structured_line_and_returns_ok(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="streamdock_n3.actions.builtins")

    result = LogEventPlugin().execute(_context(), {})

    assert result.status is ActionStatus.OK
    payload = json.loads(caplog.text.split("action event: ", 1)[1])
    assert payload == {
        "action": "press",
        "control_id": 1,
        "event_key": "button.1.press",
        "kind": "button",
        "monotonic_ns": 1_000_000,
    }


def test_builtin_registry_contains_the_builtin_plugins() -> None:
    registry = builtin_registry()

    assert set(registry) == {"ai_text", "launch_app", "log_event"}
    for plugin in registry.values():
        assert isinstance(plugin, ActionPlugin)
    assert isinstance(registry["launch_app"], LaunchAppPlugin)
    assert isinstance(registry["log_event"], LogEventPlugin)
    assert isinstance(registry["ai_text"], AiTextPlugin)


def test_engine_runs_builtin_registry_without_side_effects() -> None:
    bindings = {
        "button.1.press": ActionBinding(
            "button.1.press", "log_event", {"anything": True}
        )
    }
    engine = ActionEngine(builtin_registry(), bindings)
    event = NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 1_000_000)

    result = engine.handle_event(event)

    assert result is not None
    assert result.status is ActionStatus.OK
    assert result.plugin == "log_event"


def test_engine_runs_launch_app_with_mocked_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> object:
        recorded.append((argv, kwargs))
        return object()

    monkeypatch.setattr(
        "streamdock_n3.actions.builtins.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr("streamdock_n3.actions.builtins.subprocess.Popen", fake_popen)

    bindings = {
        "button.2.press": ActionBinding(
            "button.2.press", "launch_app", _launch_app_config("playerctl", ["play-pause"])
        )
    }
    engine = ActionEngine(builtin_registry(), bindings)
    event = NormalizedInputEvent(InputKind.BUTTON, 2, InputAction.PRESS, 1_000_000)

    result = engine.handle_event(event)

    assert result is not None
    assert result.status is ActionStatus.OK
    assert result.plugin == "launch_app"
    assert recorded[0][0] == ["/usr/bin/playerctl", "play-pause"]


def test_engine_returns_error_for_non_allowlisted_app() -> None:
    bindings = {
        "button.1.press": ActionBinding(
            "button.1.press", "launch_app", _launch_app_config("evil.sh")
        )
    }
    engine = ActionEngine(builtin_registry(), bindings)
    event = NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 1_000_000)

    result = engine.handle_event(event)

    assert result is not None
    assert result.status is ActionStatus.ERROR
    assert "not allowlisted" in result.detail


def test_engine_result_survives_action_result_shape() -> None:
    result = ActionResult(ActionStatus.OK, "launch_app", "launched alacritty", 0)

    assert result.to_dict() == {
        "status": "ok",
        "plugin": "launch_app",
        "detail": "launched alacritty",
        "duration_ms": 0,
    }
