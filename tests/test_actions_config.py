from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamdock_n3.actions.builtins import builtin_registry
from streamdock_n3.actions.config import (
    BindingsError,
    default_bindings_path,
    load_bindings,
)
from streamdock_n3.actions.contracts import ActionBinding
from streamdock_n3.actions.engine import ActionEngine
from streamdock_n3.hardware.contracts import InputAction, InputKind, NormalizedInputEvent


def _write(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_raw(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "bindings.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_yields_empty_bindings(tmp_path: Path) -> None:
    assert load_bindings(tmp_path / "nope.json") == {}


def test_malformed_json_raises_structured_error(tmp_path: Path) -> None:
    path = _write_raw(tmp_path, "{not json")

    with pytest.raises(BindingsError, match="invalid JSON"):
        load_bindings(path)


def test_empty_file_is_malformed(tmp_path: Path) -> None:
    with pytest.raises(BindingsError, match="invalid JSON"):
        load_bindings(_write_raw(tmp_path, ""))


@pytest.mark.parametrize(
    "payload",
    (
        [],
        "button.1.press",
        42,
        None,
        {"button.1.press": "log_event"},
        {"button.1.press": ["log_event"]},
        {"button.1.press": {}},
        {"button.1.press": {"config": {}}},
        {"button.1.press": {"plugin": ""}},
        {"button.1.press": {"plugin": 42}},
        {"button.1.press": {"plugin": "log_event", "bogus": 1}},
        {"button.1.press": {"plugin": "log_event", "config": "nope"}},
        {"button1press": {"plugin": "log_event"}},
        {"": {"plugin": "log_event"}},
        {"button.1.press.x.y": {"plugin": "log_event"}},
    ),
)
def test_wrong_shapes_raise_structured_error(tmp_path: Path, payload: object) -> None:
    with pytest.raises(BindingsError):
        load_bindings(_write(tmp_path, payload))


def test_valid_file_round_trips_to_action_bindings(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "button.1.press": {
                "plugin": "launch_app",
                "config": {"app": "alacritty", "args": ["-e", "nvim"]},
            },
            "knob.2.left": {"plugin": "log_event"},
        },
    )

    bindings = load_bindings(path)

    assert set(bindings) == {"button.1.press", "knob.2.left"}
    first = bindings["button.1.press"]
    assert isinstance(first, ActionBinding)
    assert first.plugin == "launch_app"
    assert first.config == {"app": "alacritty", "args": ["-e", "nvim"]}
    second = bindings["knob.2.left"]
    assert second.plugin == "log_event"
    assert second.config is None


def test_bindings_error_is_a_value_error() -> None:
    assert issubclass(BindingsError, ValueError)


def test_shipped_default_sample_binds_every_standard_event_to_log_event() -> None:
    path = default_bindings_path()
    assert path is not None
    assert path.name == "actions.default.json"

    bindings = load_bindings(path)

    expected_keys = {
        *(f"button.{control}.{state}" for control in range(1, 10) for state in ("press", "release")),
        *(f"knob.{knob}.{part}" for knob in range(1, 4) for part in ("press", "release", "left", "right")),
    }
    assert set(bindings) == expected_keys
    for binding in bindings.values():
        assert binding.plugin == "log_event"
        assert binding.config == {}


def test_shipped_default_sample_runs_through_the_engine() -> None:
    path = default_bindings_path()
    assert path is not None
    engine = ActionEngine(builtin_registry(), load_bindings(path))

    events = (
        NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 1),
        NormalizedInputEvent(InputKind.BUTTON, 9, InputAction.RELEASE, 2),
        NormalizedInputEvent(InputKind.KNOB_PRESS, 2, InputAction.PRESS, 3),
        NormalizedInputEvent(InputKind.KNOB_ROTATE, 3, InputAction.LEFT, 4),
        NormalizedInputEvent(InputKind.KNOB_ROTATE, 3, InputAction.RIGHT, 5),
    )
    for event in events:
        result = engine.handle_event(event)
        assert result is not None
        assert result.status.value == "ok"
        assert result.plugin == "log_event"
