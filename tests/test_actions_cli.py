from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from streamdock_n3.actions.cli import main, parse_event_key
from streamdock_n3.hardware.contracts import InputAction, InputKind


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict[str, Any]]:
    code = main(argv)
    rendered = json.loads(capsys.readouterr().out)
    return code, rendered


def _write_bindings(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_parse_event_key_round_trips_standard_keys() -> None:
    button = parse_event_key("button.3.press")
    assert button.kind is InputKind.BUTTON
    assert button.control_id == 3
    assert button.action is InputAction.PRESS

    knob_press = parse_event_key("knob.2.press")
    assert knob_press.kind is InputKind.KNOB_PRESS
    assert knob_press.control_id == 2

    knob_rotate = parse_event_key("knob.1.left")
    assert knob_rotate.kind is InputKind.KNOB_ROTATE
    assert knob_rotate.action is InputAction.LEFT


def test_dry_run_with_shipped_sample(capsys: pytest.CaptureFixture[str]) -> None:
    code, rendered = _run(["--event", "button.1.press", "--dry-run"], capsys)

    assert code == 0
    assert rendered["schema_version"] == 1
    assert rendered["event_key"] == "button.1.press"
    assert rendered["status"] == "skipped"
    assert rendered["plugin"] == "log_event"
    assert rendered["detail"] == "dry run: plugin not executed"


def test_real_run_against_log_event(capsys: pytest.CaptureFixture[str]) -> None:
    code, rendered = _run(["--event", "button.1.press"], capsys)

    assert code == 0
    assert rendered["schema_version"] == 1
    assert rendered["status"] == "ok"
    assert rendered["plugin"] == "log_event"
    assert rendered["duration_ms"] >= 0


def test_knob_event_key_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    code, rendered = _run(["--event", "knob.1.left", "--dry-run"], capsys)

    assert code == 0
    assert rendered["status"] == "skipped"
    assert rendered["event_key"] == "knob.1.left"


def test_unknown_event_key_is_unbound(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bindings = _write_bindings(tmp_path, {"button.1.press": {"plugin": "log_event"}})

    code, rendered = _run(
        ["--event", "knob.1.left", "--bindings", str(bindings)], capsys
    )

    assert code == 0
    assert rendered["status"] == "unbound"
    assert rendered["event_key"] == "knob.1.left"


def test_bad_bindings_file_is_structured_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bindings = tmp_path / "bindings.json"
    bindings.write_text("{not json", encoding="utf-8")

    code, rendered = _run(
        ["--event", "button.1.press", "--bindings", str(bindings)], capsys
    )

    assert code == 1
    assert rendered["status"] == "error"
    assert "invalid JSON" in rendered["detail"]


@pytest.mark.parametrize(
    "event",
    (
        "bogus",
        "",
        "button.x.press",
        "button.1.left",
        "button.0.press",
        "knob.4.press",
        "knob.2.frobnicate",
        "switch.1.press",
        "button.1.press.extra",
    ),
)
def test_malformed_event_value_is_structured_error(
    event: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, rendered = _run(["--event", event, "--dry-run"], capsys)

    assert code == 1
    assert rendered["status"] == "error"
    assert rendered["detail"]


def test_non_allowlisted_app_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bindings = _write_bindings(
        tmp_path,
        {"button.1.press": {"plugin": "launch_app", "config": {"app": "evil.sh"}}},
    )

    code, rendered = _run(
        ["--event", "button.1.press", "--bindings", str(bindings)], capsys
    )

    assert code == 1
    assert rendered["status"] == "error"
    assert "not allowlisted" in rendered["detail"]


def test_dry_run_unknown_plugin_is_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bindings = _write_bindings(tmp_path, {"button.1.press": {"plugin": "ghost"}})

    code, rendered = _run(
        ["--event", "button.1.press", "--bindings", str(bindings), "--dry-run"], capsys
    )

    assert code == 1
    assert rendered["status"] == "error"
    assert "ghost" in rendered["detail"]


def test_real_run_launch_app_uses_mocked_process(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[Any] = []

    def fake_popen(argv: list[str], **kwargs: Any) -> object:
        recorded.append(argv)
        return object()

    monkeypatch.setattr(
        "streamdock_n3.actions.builtins.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr("streamdock_n3.actions.builtins.subprocess.Popen", fake_popen)
    bindings = _write_bindings(
        tmp_path,
        {
            "button.1.press": {
                "plugin": "launch_app",
                "config": {"app": "alacritty", "args": ["-e", "nvim"]},
            }
        },
    )

    code, rendered = _run(
        ["--event", "button.1.press", "--bindings", str(bindings)], capsys
    )

    assert code == 0
    assert rendered["status"] == "ok"
    assert rendered["plugin"] == "launch_app"
    assert recorded == [["/usr/bin/alacritty", "-e", "nvim"]]


def test_missing_event_is_usage_error() -> None:
    with pytest.raises(SystemExit):
        main(["--dry-run"])
