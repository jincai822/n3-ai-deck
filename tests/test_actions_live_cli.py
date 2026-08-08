from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from streamdock_n3.actions import live_cli
from streamdock_n3.actions.contracts import ActionResult, ActionStatus
from streamdock_n3.actions.engine import ActionEngine
from streamdock_n3.actions.feedback import FeedbackState
from streamdock_n3.actions.live import (
    LiveSessionResult,
    LiveSessionSpec,
    LiveSessionStatus,
)
from streamdock_n3.actions.live_cli import build_parser, main
from streamdock_n3.hardware.contracts import (
    MAX_DEADLINE_MS,
    InputAction,
    InputKind,
    NormalizedInputEvent,
)
from streamdock_n3.hardware.input_session import VendorHidReadOnlyBackend
from streamdock_n3.hardware.vendor_backend import _HidrawTransport
from streamdock_n3.input_cli import NodeResolutionError


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(argv)
    return code, capsys.readouterr().out


def _write_bindings(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _bindings_payload() -> dict[str, object]:
    return {"button.1.press": {"plugin": "log_event", "config": {}}}


def _button_event() -> NormalizedInputEvent:
    return NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 1_000)


class ScriptedLoop:
    """Fake run_live_loop; drives on_event with scripted dispatches, never opens nodes."""

    def __init__(
        self,
        events: list[tuple[NormalizedInputEvent, ActionResult | None]],
        result: LiveSessionResult,
    ) -> None:
        self.events = events
        self.result = result
        self.kwargs: dict[str, Any] = {}

    def __call__(
        self,
        spec: LiveSessionSpec,
        node: str,
        key_map: Any,
        engine: ActionEngine,
        *,
        input_backend: Any,
        transport: Any,
        on_event: Any,
        on_dispatch_start: Any = None,
    ) -> LiveSessionResult:
        self.kwargs = {
            "spec": spec,
            "node": node,
            "key_map": key_map,
            "engine": engine,
            "input_backend": input_backend,
            "transport": transport,
            "on_dispatch_start": on_dispatch_start,
        }
        for event, result in self.events:
            if on_dispatch_start is not None:
                on_dispatch_start(event)
            on_event(event, result)
        return self.result


def test_parser_exposes_live_flags() -> None:
    parser = build_parser()
    actions = {
        option: action
        for action in parser._actions
        for option in action.option_strings
    }

    assert "--bindings" in actions
    assert "--duration-ms" in actions
    assert "--no-init" in actions
    assert "--dry-run" in actions
    assert "--feedback" in actions
    assert "--timeout-seconds" in actions
    args = parser.parse_args([])
    assert args.bindings is None
    assert args.duration_ms == 60_000
    assert args.no_init is False
    assert args.dry_run is False
    assert args.feedback is False
    assert args.timeout_seconds == 5.0


def test_dry_run_with_shipped_sample(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.config_dir", lambda: tmp_path)

    code, out = _run(["--dry-run"], capsys)

    assert code == 0
    rendered = json.loads(out)
    assert rendered["schema_version"] == 1
    assert rendered["status"] == "ok"
    assert rendered["node_resolved"] is True
    assert rendered["key_map_entries"] == 18
    assert rendered["bindings_source"] == "shipped"
    assert rendered["bindings_count"] == 30
    assert rendered["duration_ms"] == 60_000
    assert rendered["init"] is True


def test_dry_run_with_xdg_bindings_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_bindings(tmp_path, _bindings_payload())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.config_dir", lambda: tmp_path)

    code, out = _run(["--dry-run"], capsys)

    assert code == 0
    rendered = json.loads(out)
    assert rendered["bindings_source"] == "xdg"
    assert rendered["bindings_count"] == 1


def test_dry_run_with_explicit_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bindings = _write_bindings(tmp_path, _bindings_payload())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )

    code, out = _run(["--dry-run", "--bindings", str(bindings)], capsys)

    assert code == 0
    rendered = json.loads(out)
    assert rendered["bindings_source"] == "explicit"
    assert rendered["bindings_count"] == 1


def test_missing_explicit_bindings_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(["--bindings", str(tmp_path / "missing.json"), "--dry-run"], capsys)

    assert code == 1
    rendered = json.loads(out)
    assert rendered["schema_version"] == 1
    assert rendered["status"] == "error"
    assert "not found" in rendered["detail"]


def test_bad_bindings_file_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bindings = tmp_path / "bindings.json"
    bindings.write_text("{not json", encoding="utf-8")

    code, out = _run(["--bindings", str(bindings), "--dry-run"], capsys)

    assert code == 1
    rendered = json.loads(out)
    assert rendered["status"] == "error"
    assert "invalid JSON" in rendered["detail"]


@pytest.mark.parametrize("duration_ms", (0, MAX_DEADLINE_MS + 1))
def test_duration_out_of_bounds_is_rejected(
    duration_ms: int, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(["--duration-ms", str(duration_ms), "--dry-run"], capsys)

    assert code == 1
    rendered = json.loads(out)
    assert rendered["status"] == "error"
    assert "duration_ms" in rendered["detail"]


def test_live_mode_emits_event_lines_and_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bindings = _write_bindings(tmp_path, _bindings_payload())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    events: list[tuple[NormalizedInputEvent, ActionResult | None]] = [
        (_button_event(), ActionResult(ActionStatus.OK, "log_event", "logged", 1)),
        (
            NormalizedInputEvent(InputKind.KNOB_ROTATE, 1, InputAction.LEFT, 2_000),
            None,
        ),
    ]
    expected_result = LiveSessionResult(
        status=LiveSessionStatus.SUCCEEDED,
        events=2,
        dispatched=2,
        unknown=0,
        disconnected=False,
        init_ok=True,
        duration_ms=12,
    )
    loop = ScriptedLoop(events, expected_result)
    monkeypatch.setattr("streamdock_n3.actions.live_cli.run_live_loop", loop)

    code, out = _run(["--bindings", str(bindings), "--duration-ms", "500"], capsys)

    lines = out.splitlines()
    assert code == 0
    assert len(lines) == 3
    first = json.loads(lines[0])
    assert first["schema_version"] == 1
    assert first["event_key"] == "button.1.press"
    assert first["control_id"] == 1
    assert first["kind"] == "button"
    assert first["action"] == "press"
    assert first["status"] == "ok"
    assert first["plugin"] == "log_event"
    assert first["duration_ms"] == 1
    second = json.loads(lines[1])
    assert second["event_key"] == "knob.1.left"
    assert second["status"] == "unbound"
    assert "plugin" not in second
    summary = json.loads(lines[2])
    assert summary == expected_result.to_dict()
    # the real backend and transport were wired in, but never opened
    assert isinstance(loop.kwargs["input_backend"], VendorHidReadOnlyBackend)
    assert isinstance(loop.kwargs["transport"], _HidrawTransport)
    assert isinstance(loop.kwargs["engine"], ActionEngine)
    assert loop.kwargs["node"] == "vendor-node"
    assert loop.kwargs["spec"].duration_ms == 500
    assert loop.kwargs["spec"].init is True


def test_no_init_flag_reaches_the_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bindings = _write_bindings(tmp_path, _bindings_payload())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    loop = ScriptedLoop(
        [],
        LiveSessionResult(LiveSessionStatus.SUCCEEDED, 0, 0, 0, False, True, 0),
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.run_live_loop", loop)

    code, out = _run(["--no-init", "--bindings", str(bindings)], capsys)

    assert code == 0
    assert loop.kwargs["spec"].init is False
    assert len(out.splitlines()) == 1  # summary only, no events


def test_live_mode_rejected_result_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bindings = _write_bindings(tmp_path, _bindings_payload())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    loop = ScriptedLoop(
        [],
        LiveSessionResult(LiveSessionStatus.REJECTED, 0, 0, 0, False, True, 0),
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.run_live_loop", loop)

    code, out = _run(["--bindings", str(bindings)], capsys)

    assert code == 1
    summary = json.loads(out.splitlines()[-1])
    assert summary["status"] == "rejected"


def test_node_resolution_failure_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failing() -> str:
        raise NodeResolutionError("no node")

    monkeypatch.setattr("streamdock_n3.actions.live_cli.resolve_vendor_node", failing)

    code, out = _run(["--dry-run"], capsys)

    assert code == 1
    rendered = json.loads(out)
    assert rendered["status"] == "error"
    assert "no node" in rendered["detail"]


@pytest.mark.parametrize("timeout_seconds", ("0", "-1", "0.0", "nan"))
def test_timeout_seconds_non_positive_is_rejected(
    timeout_seconds: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(["--timeout-seconds", timeout_seconds, "--dry-run"], capsys)

    assert code == 1
    rendered = json.loads(out)
    assert rendered["status"] == "error"
    assert "positive" in rendered["detail"]


def test_timeout_seconds_plumbed_into_the_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bindings = _write_bindings(tmp_path, _bindings_payload())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    loop = ScriptedLoop(
        [],
        LiveSessionResult(LiveSessionStatus.SUCCEEDED, 0, 0, 0, False, True, 0),
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.run_live_loop", loop)

    code, out = _run(
        ["--timeout-seconds", "15", "--bindings", str(bindings)], capsys
    )

    assert code == 0
    assert loop.kwargs["engine"]._timeout_seconds == 15.0

    code, out = _run(["--bindings", str(bindings)], capsys)

    assert code == 0
    assert loop.kwargs["engine"]._timeout_seconds == 5.0


def test_dry_run_accepts_feedback_and_timeout_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.config_dir", lambda: tmp_path)

    code, out = _run(["--dry-run", "--feedback", "--timeout-seconds", "12.5"], capsys)

    assert code == 0
    rendered = json.loads(out)
    assert rendered["status"] == "ok"
    assert rendered["bindings_source"] == "shipped"


class _FeedbackRecorder:
    """Records render_state_image/write_key_image calls; never opens devices."""

    def __init__(self) -> None:
        self.rendered: list[tuple[object, str | None]] = []
        self.written: list[tuple[str, int, bytes]] = []
        self.render_raises = False
        self.write_returns = True

    def render(self, state: object, text: str | None = None) -> bytes:
        if self.render_raises:
            raise RuntimeError("render boom")
        self.rendered.append((state, text))
        return b"\xff\xd8fake-jpeg"

    def write(self, node: str, key: int, jpeg: bytes, transport: Any = None) -> bool:
        del transport
        self.written.append((node, key, jpeg))
        return self.write_returns


def test_feedback_wires_callbacks_and_maps_status_to_colors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bindings = _write_bindings(tmp_path, _bindings_payload())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    events: list[tuple[NormalizedInputEvent, ActionResult | None]] = [
        (_button_event(), ActionResult(ActionStatus.OK, "log_event", "logged", 1)),
        (
            _button_event(),
            ActionResult(ActionStatus.ERROR, "ai_text", "ai: request failed", 2),
        ),
        (
            _button_event(),
            ActionResult(ActionStatus.TIMEOUT, "ai_text", "request timed out", 3),
        ),
        (
            _button_event(),
            ActionResult(ActionStatus.SKIPPED, "launch_app", "skipped", 0),
        ),
        (_button_event(), None),  # unbound
        (
            NormalizedInputEvent(InputKind.KNOB_ROTATE, 1, InputAction.LEFT, 6_000),
            ActionResult(ActionStatus.OK, "log_event", "logged", 1),
        ),
    ]
    loop = ScriptedLoop(
        events,
        LiveSessionResult(LiveSessionStatus.SUCCEEDED, 6, 5, 0, False, True, 9),
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.run_live_loop", loop)
    recorder = _FeedbackRecorder()
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.render_state_image", recorder.render
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.write_key_image", recorder.write)

    code, out = _run(["--feedback", "--bindings", str(bindings)], capsys)

    assert code == 0
    assert loop.kwargs["on_dispatch_start"] is not None
    # RUNNING precedes the result image for the first button event.
    assert recorder.rendered[0] == (FeedbackState.RUNNING, None)
    assert recorder.rendered[1] == (FeedbackState.SUCCESS, "logged")
    # ok -> SUCCESS (with detail text), error -> FAILURE, timeout -> TIMEOUT.
    assert (FeedbackState.FAILURE, None) in recorder.rendered
    assert (FeedbackState.TIMEOUT, None) in recorder.rendered
    # 5 button events -> 5 RUNNING renders, then ok/error/timeout -> 3 more.
    # skipped and unbound write nothing; the knob event is skipped silently.
    assert recorder.rendered.count((FeedbackState.RUNNING, None)) == 5
    assert len(recorder.rendered) == 8
    assert len(recorder.written) == 8
    assert all(node == "vendor-node" and key == 1 for node, key, _ in recorder.written)
    # the JSONL event lines and summary are still printed alongside feedback.
    lines = out.splitlines()
    assert len(lines) == 7
    assert json.loads(lines[-1])["status"] == "succeeded"


def test_feedback_render_failure_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bindings = _write_bindings(tmp_path, _bindings_payload())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    loop = ScriptedLoop(
        [(_button_event(), ActionResult(ActionStatus.OK, "log_event", "logged", 1))],
        LiveSessionResult(LiveSessionStatus.SUCCEEDED, 1, 1, 0, False, True, 1),
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.run_live_loop", loop)
    recorder = _FeedbackRecorder()
    recorder.render_raises = True
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.render_state_image", recorder.render
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.write_key_image", recorder.write)

    code, out = _run(["--feedback", "--bindings", str(bindings)], capsys)

    assert code == 0
    lines = out.splitlines()
    assert len(lines) == 2  # event line and summary are still emitted
    assert json.loads(lines[0])["status"] == "ok"
    assert len(recorder.written) == 0


def test_feedback_write_failure_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bindings = _write_bindings(tmp_path, _bindings_payload())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    loop = ScriptedLoop(
        [(_button_event(), ActionResult(ActionStatus.OK, "log_event", "logged", 1))],
        LiveSessionResult(LiveSessionStatus.SUCCEEDED, 1, 1, 0, False, True, 1),
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.run_live_loop", loop)
    recorder = _FeedbackRecorder()
    recorder.write_returns = False
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.render_state_image", recorder.render
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.write_key_image", recorder.write)

    code, out = _run(["--feedback", "--bindings", str(bindings)], capsys)

    assert code == 0
    assert len(recorder.rendered) == 2  # RUNNING and SUCCESS were still rendered
    assert len(recorder.written) == 2  # both writes attempted, both returned False
    lines = out.splitlines()
    assert len(lines) == 2
    assert json.loads(lines[-1])["status"] == "succeeded"


def test_main_configures_line_buffered_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSONL log lines must flush immediately when stdout is a pipe/journald."""

    reconfigure_calls: list[dict[str, bool]] = []

    class FakeStdout:
        def reconfigure(self, **kwargs: object) -> None:
            reconfigure_calls.append(kwargs)

        def write(self, text: str) -> None:
            return None

        def flush(self) -> None:
            return None

    monkeypatch.setattr(live_cli.sys, "stdout", FakeStdout())
    monkeypatch.setattr(
        "streamdock_n3.actions.live_cli.resolve_vendor_node", lambda: "vendor-node"
    )
    monkeypatch.setattr("streamdock_n3.actions.live_cli.config_dir", lambda: tmp_path)

    assert live_cli.main(["--dry-run"]) == 0

    assert reconfigure_calls == [{"line_buffering": True}]
