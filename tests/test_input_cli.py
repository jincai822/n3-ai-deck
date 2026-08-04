from __future__ import annotations

from streamdock_n3.hardware.contracts import (
    ErrorCode,
    InputSessionResult,
    OperationResult,
    ResultStatus,
)
from streamdock_n3.hardware.ipc import IpcSessionRequest, IpcSessionResponse
from streamdock_n3.input_cli import (
    NodeResolutionError,
    build_parser,
    main,
    run_session_flow,
)
from tests.hardware_fixtures import make_session_spec, meeting_session_result


class FakeSessionRunner:
    def __init__(self, result: InputSessionResult | None = None) -> None:
        self.result = result if result is not None else meeting_session_result()
        self.calls = 0

    def run(self, request: IpcSessionRequest, timeout_ms: int) -> IpcSessionResponse:
        self.calls += 1
        return IpcSessionResponse(
            OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, timeout_ms),
            self.result,
        )


def test_session_flow_advances_g1_g2_g3_to_input_validated() -> None:
    runner = FakeSessionRunner()

    rendered = run_session_flow(
        "/dev/input/event12",
        make_session_spec().key_map,
        5_000,
        session_runner=runner,
    )

    assert runner.calls == 1
    assert rendered["state"] == "input_validated"
    assert rendered["status"] == "succeeded"
    assert rendered["session"] is not None


def test_session_flow_blocks_when_requirements_unmet() -> None:
    partial = meeting_session_result()
    counts = tuple(
        count if count.control_id != 1 else count.__class__(
            count.control_id, count.kind, 0, 0, 0, 0
        )
        for count in partial.counts
    )
    from dataclasses import replace

    unmet = replace(partial, counts=counts)
    runner = FakeSessionRunner(unmet)

    rendered = run_session_flow(
        "/dev/input/event12",
        make_session_spec().key_map,
        5_000,
        session_runner=runner,
    )

    assert rendered["state"] == "blocked"
    assert rendered["status"] == "succeeded"
    assert rendered["session"] is not None


def test_main_reports_node_resolution_failure(
    monkeypatch,
    capsys,
) -> None:
    def failing_resolve() -> str:
        raise NodeResolutionError("no node")

    monkeypatch.setattr("streamdock_n3.input_cli.resolve_input_node", failing_resolve)

    code = main(["--json"])

    assert code == 1
    assert "rejected" in capsys.readouterr().out


def test_parser_has_no_system_mutation_flags() -> None:
    parser = build_parser()

    actions = {
        option
        for action in parser._actions
        for option in action.option_strings
    }

    assert not {"--install", "--reload", "--systemctl", "--write"} & actions
    assert "--json" in actions
    assert "--duration-ms" in actions
