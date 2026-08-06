"""Tests for the G8 background service console CLI (P3 of the G8 design, section 4.3).

The print flags run without any mocking (no bindings, no node, no device);
the service-mode tests stub `resolve_vendor_node` and `run_service` so nothing
touches a real node, and the session-runner wiring tests stub `run_live_loop`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from streamdock_n3.actions import service_cli
from streamdock_n3.actions.contracts import ActionBinding
from streamdock_n3.actions.engine import DEFAULT_TIMEOUT_SECONDS, ActionEngine
from streamdock_n3.actions.live import (
    LiveSessionResult,
    LiveSessionSpec,
    LiveSessionStatus,
)
from streamdock_n3.actions.service import ServiceResult, ServiceSpec, ServiceStatus
from streamdock_n3.hardware.contracts import MAX_DEADLINE_MS, KeyMap
from streamdock_n3.hardware.input_session import VendorHidReadOnlyBackend
from streamdock_n3.hardware.vendor_backend import _HidrawTransport

_EMPTY_BINDINGS: dict[str, ActionBinding] = {}


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = service_cli.main(argv)
    return code, capsys.readouterr().out


def _write_bindings(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "bindings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _bindings_path(tmp_path: Path) -> Path:
    return _write_bindings(tmp_path, {"button.1.press": {"plugin": "log_event", "config": {}}})


def _session_result() -> LiveSessionResult:
    return LiveSessionResult(LiveSessionStatus.SUCCEEDED, 0, 0, 0, False, True, 0)


class TestParser:
    def test_parser_exposes_service_flags(self) -> None:
        parser = service_cli.build_parser()
        actions = {
            option: action
            for action in parser._actions
            for option in action.option_strings
        }

        assert "--bindings" in actions
        assert "--session-duration-ms" in actions
        assert "--feedback" in actions
        assert "--timeout-seconds" in actions
        assert "--print-unit" in actions
        assert "--print-udev-rule" in actions
        # The live-CLI --no-init/--dry-run flags are out of scope for the service.
        assert "--no-init" not in actions
        assert "--dry-run" not in actions
        args = parser.parse_args([])
        assert args.bindings is None
        assert args.session_duration_ms == 60_000
        assert args.feedback is False
        assert args.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
        assert args.print_unit is False
        assert args.print_udev_rule is False


class TestPrintUnit:
    def test_print_unit_emits_full_unit_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = _run(["--print-unit"], capsys)

        assert code == 0
        assert out.startswith("[Unit]\n")
        assert "Description=N3 AI Deck background service" in out
        assert "After=graphical-session.target" in out
        assert "[Service]\nType=simple" in out
        assert "ExecStart=%h/.local/bin/n3-ai-deck-service --feedback" in out
        assert "EnvironmentFile=-%h/.config/streamdock-n3/service.env" in out
        assert "Restart=on-failure" in out
        assert "RestartSec=2" in out
        assert "WantedBy=default.target" in out
        assert out.endswith("\n")

    def test_print_unit_has_no_absolute_paths(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = _run(["--print-unit"], capsys)

        assert code == 0
        for forbidden in ("/home", "/Users", "/srv", "/usr", "/etc"):
            assert forbidden not in out

    def test_print_unit_matches_module_template(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = _run(["--print-unit"], capsys)

        assert code == 0
        assert out == service_cli.USER_UNIT_TEXT


class TestPrintUdevRule:
    def test_print_udev_rule_emits_both_approved_rules(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = _run(["--print-udev-rule"], capsys)

        assert code == 0
        # Two rules, one per approved interface, each with a comment line.
        assert out.count('SUBSYSTEM=="input", KERNEL=="event*"') == 1
        assert out.count('SUBSYSTEM=="hidraw"') == 1
        assert out.count('TAG+="uaccess"') == 2
        assert out.count('ATTRS{idVendor}=="6602"') == 2
        assert out.count('ATTRS{idProduct}=="1000"') == 2
        assert out.count('ATTRS{bInterfaceClass}=="03"') == 2
        # Input triple 03/01/01 and control triple 03/00/00.
        assert 'ATTRS{bInterfaceSubClass}=="01"' in out
        assert 'ATTRS{bInterfaceProtocol}=="01"' in out
        assert 'ATTRS{bInterfaceSubClass}=="00"' in out
        assert 'ATTRS{bInterfaceProtocol}=="00"' in out

    def test_print_udev_rule_never_world_writable(self, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = _run(["--print-udev-rule"], capsys)

        assert code == 0
        assert "0666" not in out


class TestFlagValidation:
    @pytest.mark.parametrize("timeout_seconds", ("0", "-1", "0.0", "nan"))
    def test_timeout_seconds_non_positive_is_rejected(
        self, timeout_seconds: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = _run(["--timeout-seconds", timeout_seconds], capsys)

        assert code == 1
        rendered = json.loads(out)
        assert rendered["status"] == "error"
        assert "positive" in rendered["detail"]

    @pytest.mark.parametrize("duration_ms", ("0", "-100", str(MAX_DEADLINE_MS + 1)))
    def test_session_duration_ms_out_of_bounds_is_rejected(
        self, duration_ms: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = _run(["--session-duration-ms", duration_ms], capsys)

        assert code == 1
        rendered = json.loads(out)
        assert rendered["status"] == "error"

    def test_missing_explicit_bindings_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = _run(["--bindings", str(tmp_path / "missing.json")], capsys)

        assert code == 1
        rendered = json.loads(out)
        assert rendered["status"] == "error"
        assert "not found" in rendered["detail"]


class TestServiceWiring:
    def test_main_wires_spec_and_dependencies(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        bindings = _bindings_path(tmp_path)
        captured: dict[str, Any] = {}
        resolver_calls: list[str] = []

        def fake_resolver() -> str:
            resolver_calls.append("resolved")
            return "fake-node"

        def fake_run_service(
            spec: ServiceSpec,
            *,
            node_resolver: Any,
            session_runner: Any,
            sleep: Any,
            on_lifecycle: Any = None,
        ) -> ServiceResult:
            captured["spec"] = spec
            captured["node_resolver"] = node_resolver
            captured["session_runner"] = session_runner
            captured["sleep"] = sleep
            captured["on_lifecycle"] = on_lifecycle
            return ServiceResult(ServiceStatus.STOPPED, 2, 1, True)

        monkeypatch.setattr(service_cli, "resolve_vendor_node", fake_resolver)
        monkeypatch.setattr(service_cli, "run_service", fake_run_service)

        code, out = _run(
            [
                "--bindings",
                str(bindings),
                "--session-duration-ms",
                "5000",
                "--feedback",
                "--timeout-seconds",
                "3.5",
            ],
            capsys,
        )

        assert code == 0
        spec = captured["spec"]
        assert spec.session_duration_ms == 5000
        assert spec.init is True
        assert spec.feedback is True
        assert spec.timeout_seconds == 3.5
        assert captured["node_resolver"] is fake_resolver
        assert callable(captured["session_runner"])
        assert captured["sleep"] is time.sleep
        assert callable(captured["on_lifecycle"])
        # The lifecycle hook prints redacted JSONL events.
        captured["on_lifecycle"]({"event": "started", "session_duration_ms": 5000})
        lifecycle_line = json.loads(capsys.readouterr().out)
        assert lifecycle_line == {"event": "started", "session_duration_ms": 5000}
        # The final summary is printed and the stopped status exits 0.
        assert json.loads(out) == ServiceResult(ServiceStatus.STOPPED, 2, 1, True).to_dict()

    def test_main_interrupted_by_keyboard_interrupt_exits_0(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        bindings = _bindings_path(tmp_path)

        def raising(spec: ServiceSpec, **kwargs: Any) -> ServiceResult:
            raise KeyboardInterrupt()

        monkeypatch.setattr(service_cli, "resolve_vendor_node", lambda: "fake-node")
        monkeypatch.setattr(service_cli, "run_service", raising)

        code, out = _run(["--bindings", str(bindings)], capsys)

        assert code == 0
        rendered = json.loads(out)
        assert rendered["status"] == "interrupted"
        assert "Ctrl+C" in rendered["detail"]


class TestSessionRunnerWiring:
    def test_runner_wires_fresh_engine_and_key_map(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake_run_live_loop(
            spec: LiveSessionSpec,
            node: str,
            key_map: KeyMap,
            engine: ActionEngine,
            **kwargs: Any,
        ) -> LiveSessionResult:
            captured["spec"] = spec
            captured["node"] = node
            captured["key_map"] = key_map
            captured["engine"] = engine
            captured["kwargs"] = kwargs
            return _session_result()

        monkeypatch.setattr(service_cli, "run_live_loop", fake_run_live_loop)
        key_map = KeyMap(())
        runner = service_cli._build_session_runner(
            _EMPTY_BINDINGS, key_map, feedback=False, timeout_seconds=2.5
        )

        result = runner("fake-node", ServiceSpec(session_duration_ms=5_000))

        assert result.status is LiveSessionStatus.SUCCEEDED
        assert captured["node"] == "fake-node"
        assert captured["key_map"] is key_map
        assert isinstance(captured["spec"], LiveSessionSpec)
        assert captured["spec"].duration_ms == 5_000
        assert captured["spec"].init is True
        assert isinstance(captured["engine"], ActionEngine)
        assert isinstance(captured["kwargs"]["input_backend"], VendorHidReadOnlyBackend)
        assert isinstance(captured["kwargs"]["transport"], _HidrawTransport)
        assert captured["kwargs"]["on_event"] is service_cli._print_event_line
        assert captured["kwargs"]["on_dispatch_start"] is None

    def test_runner_wires_feedback_callbacks_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_run_live_loop(
            spec: LiveSessionSpec,
            node: str,
            key_map: KeyMap,
            engine: ActionEngine,
            **kwargs: Any,
        ) -> LiveSessionResult:
            captured.update(kwargs)
            return _session_result()

        def fake_start(event: Any) -> None:
            return None

        def fake_event(event: Any, result: Any) -> None:
            return None

        def fake_compose(feedback_event: Any) -> Any:
            return feedback_event

        monkeypatch.setattr(service_cli, "run_live_loop", fake_run_live_loop)
        monkeypatch.setattr(service_cli, "_feedback_callbacks", lambda node: (fake_start, fake_event))
        monkeypatch.setattr(service_cli, "_compose_event_callback", fake_compose)

        runner = service_cli._build_session_runner(
            _EMPTY_BINDINGS, KeyMap(()), feedback=True, timeout_seconds=2.0
        )

        runner("fake-node", ServiceSpec(session_duration_ms=5_000))

        assert captured["on_dispatch_start"] is fake_start
        # The feedback event callback is wrapped by _compose_event_callback,
        # which prints the event line before applying the LCD feedback.
        assert captured["on_event"] is fake_event
