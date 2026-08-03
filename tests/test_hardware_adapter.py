from __future__ import annotations

from typing import cast

import pytest

from streamdock_n3.hardware.adapter import N3Adapter
from streamdock_n3.hardware.backend import FakeBackend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    ErrorCode,
    Operation,
    OperationResult,
    RecoveryStatus,
    ResultStatus,
    Stage,
    StageManifest,
)
from streamdock_n3.hardware.gate import CapabilityGate, GateViolation
from tests.hardware_fixtures import TEST_COMMIT, make_manifest, make_profile


def stage_commands(stage: Stage) -> tuple[AdapterCommand, ...]:
    return tuple(
        AdapterCommand(command.operation, command.brightness, command.key, command.image)
        for command in original_commands(stage)
    )


def original_commands(stage: Stage) -> tuple[AdapterCommand, ...]:
    return {
        Stage.G1_PROFILE: (AdapterCommand(Operation.APPROVE_PROFILE),),
        Stage.G2_PERMISSION: (AdapterCommand(Operation.RECORD_PERMISSION),),
        Stage.G3_INPUT: (AdapterCommand(Operation.OBSERVE_INPUTS),),
        Stage.G4_INITIALIZATION: (AdapterCommand(Operation.INITIALIZE),),
        Stage.G5_BRIGHTNESS: (
            AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),
            AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50),
        ),
        Stage.G6_ONE_LCD: (
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"g0-test-image"),
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"g0-baseline"),
        ),
        Stage.G7_SIX_LCD: tuple(
            AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"test-{key}".encode())
            for key in range(1, 7)
        )
        + tuple(
            AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"base-{key}".encode())
            for key in range(1, 7)
        ),
    }[stage]


def make_adapter(
    backend: FakeBackend | None = None,
    initial_state: AdapterState = AdapterState.CANDIDATE,
) -> tuple[N3Adapter, FakeBackend]:
    fake_backend = backend if backend is not None else FakeBackend()
    return N3Adapter(make_profile(), TEST_COMMIT, fake_backend, initial_state), fake_backend


def test_adapter_advances_through_explicit_g1_to_g7_fake_sequence() -> None:
    adapter, backend = make_adapter()
    stages = (
        Stage.G1_PROFILE,
        Stage.G2_PERMISSION,
        Stage.G3_INPUT,
        Stage.G4_INITIALIZATION,
        Stage.G5_BRIGHTNESS,
        Stage.G6_ONE_LCD,
        Stage.G7_SIX_LCD,
    )
    expected_states = (
        AdapterState.PROFILE_APPROVED,
        AdapterState.PROFILE_APPROVED,
        AdapterState.INPUT_VALIDATED,
        AdapterState.INITIALIZATION_VALIDATED,
        AdapterState.BRIGHTNESS_VALIDATED,
        AdapterState.ONE_LCD_VALIDATED,
        AdapterState.SIX_LCD_VALIDATED,
    )

    states: list[AdapterState] = []
    for stage in stages:
        calls_before_begin = len(backend.calls)
        adapter.begin_stage(make_manifest(stage))
        assert len(backend.calls) == calls_before_begin
        for command in stage_commands(stage):
            calls_before_execute = len(backend.calls)
            assert adapter.execute(command).succeeded is True
            assert len(backend.calls) == calls_before_execute + 1
        states.append(adapter.complete_stage(True))
        assert len(backend.calls) == calls_before_begin + len(stage_commands(stage))

    assert tuple(states) == expected_states
    assert [call.operation for call in backend.calls] == [
        Operation.APPROVE_PROFILE,
        Operation.RECORD_PERMISSION,
        Operation.OBSERVE_INPUTS,
        Operation.INITIALIZE,
        Operation.SET_BRIGHTNESS,
        Operation.SET_BRIGHTNESS,
        Operation.SET_KEY_IMAGE,
        Operation.SET_KEY_IMAGE,
        *([Operation.SET_KEY_IMAGE] * 12),
    ]
    assert all(call.operation is not Operation.CLOSE_SESSION for call in backend.calls)


def test_execute_before_begin_is_rejected_without_a_backend_call() -> None:
    adapter, backend = make_adapter()

    with pytest.raises(GateViolation) as raised:
        adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED
    assert backend.calls == []


def test_command_absent_from_manifest_never_reaches_backend() -> None:
    adapter, backend = make_adapter(initial_state=AdapterState.PROFILE_APPROVED)
    adapter.begin_stage(make_manifest(Stage.G3_INPUT))

    with pytest.raises(GateViolation) as raised:
        adapter.execute(AdapterCommand(Operation.CLOSE_SESSION))

    assert raised.value.code is ErrorCode.OPERATION_NOT_ALLOWED
    assert backend.calls == []


@pytest.mark.parametrize(
    "status",
    (ResultStatus.TIMEOUT, ResultStatus.BACKEND_ERROR, ResultStatus.DISCONNECTED),
)
def test_backend_failure_blocks_adapter_and_prevents_completion(status: ResultStatus) -> None:
    adapter, backend = make_adapter(FakeBackend(outcomes={Operation.OBSERVE_INPUTS: status}))
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))
    adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))
    adapter.complete_stage(True)
    adapter.begin_stage(make_manifest(Stage.G2_PERMISSION))
    adapter.execute(AdapterCommand(Operation.RECORD_PERMISSION))
    adapter.complete_stage(True)
    adapter.begin_stage(make_manifest(Stage.G3_INPUT))

    result = adapter.execute(AdapterCommand(Operation.OBSERVE_INPUTS))

    assert result.status is status
    assert adapter.state is AdapterState.BLOCKED
    assert len(backend.calls) == 3
    with pytest.raises(GateViolation) as raised:
        adapter.complete_stage(True)
    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED


def test_failed_adapter_gate_reference_cannot_be_replaced() -> None:
    adapter, backend = make_adapter(
        FakeBackend(outcomes={Operation.APPROVE_PROFILE: ResultStatus.BACKEND_ERROR})
    )
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))
    adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    with pytest.raises(AttributeError):
        adapter.gate = CapabilityGate()  # type: ignore[misc]

    assert adapter.state is AdapterState.BLOCKED
    assert len(backend.calls) == 1
    with pytest.raises(GateViolation) as raised:
        adapter.begin_stage(make_manifest(Stage.G1_PROFILE))
    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED


def test_completion_without_confirmation_blocks_even_when_recovery_is_unknown() -> None:
    adapter, backend = make_adapter()
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))
    adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert adapter.complete_stage(False, RecoveryStatus.UNKNOWN) is AdapterState.BLOCKED
    assert len(backend.calls) == 1


def test_disconnect_does_not_close_backend_and_prevents_new_stages() -> None:
    adapter, backend = make_adapter()
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))
    adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))
    calls_before_disconnect = list(backend.calls)

    assert adapter.disconnect() is AdapterState.DISCONNECTED
    assert backend.calls == calls_before_disconnect
    with pytest.raises(GateViolation) as raised:
        adapter.begin_stage(make_manifest(Stage.G1_PROFILE))
    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED


class ExplodingBackend:
    def execute(self, command: AdapterCommand, manifest: StageManifest) -> OperationResult:
        del command, manifest
        raise RuntimeError("secret backend exception detail")


def test_backend_exception_is_sanitized_and_blocks_the_gate() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, ExplodingBackend())
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))

    result = adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert result.status is ResultStatus.BACKEND_ERROR
    assert result.error_code is ErrorCode.BACKEND_FAILURE
    assert result.duration_ms == 0
    assert result.events == ()
    assert adapter.state is AdapterState.BLOCKED
    assert "secret backend exception detail" not in repr(adapter)
    assert "secret backend exception detail" not in repr(result)


class MaliciousResult:
    succeeded = True
    events = ("unvalidated event",)


class MaliciousBackend:
    def __init__(self) -> None:
        self.execute_calls = 0

    def execute(self, command: AdapterCommand, manifest: StageManifest) -> OperationResult:
        del command, manifest
        self.execute_calls += 1
        return cast(OperationResult, MaliciousResult())


class ResultCapturingEvidence:
    def __init__(self) -> None:
        self.operation_results: list[OperationResult] = []

    def record_operation(
        self,
        profile: object,
        manifest: object,
        command: object,
        result: OperationResult,
    ) -> None:
        del profile, manifest, command
        self.operation_results.append(result)

    def record_stage(
        self,
        profile: object,
        manifest: object,
        state: object,
        recovery_status: object,
    ) -> None:
        del profile, manifest, state, recovery_status


def test_non_contract_backend_result_is_normalized_and_blocks_completion() -> None:
    backend = MaliciousBackend()
    evidence = ResultCapturingEvidence()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend, evidence=evidence)
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))

    result = adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert result == OperationResult(
        ResultStatus.BACKEND_ERROR,
        ErrorCode.BACKEND_FAILURE,
        0,
    )
    assert isinstance(result, OperationResult)
    assert result.events == ()
    assert backend.execute_calls == 1
    assert adapter.state is AdapterState.BLOCKED
    assert evidence.operation_results == [result]
    assert all(isinstance(item, OperationResult) for item in evidence.operation_results)
    with pytest.raises(GateViolation) as raised:
        adapter.complete_stage(True)
    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED
    assert adapter.state is AdapterState.BLOCKED
    assert backend.execute_calls == 1


@pytest.mark.parametrize("manual_confirmation", ("false", 1, object()))
def test_adapter_rejects_non_bool_confirmation_without_mutating_session(
    manual_confirmation: object,
) -> None:
    adapter, backend = make_adapter()
    adapter.begin_stage(make_manifest(Stage.G1_PROFILE))
    adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))
    session = adapter.gate.session
    assert session is not None
    call_counts = session.call_counts
    backend_calls = list(backend.calls)

    with pytest.raises(GateViolation) as raised:
        adapter.complete_stage(cast(bool, manual_confirmation))

    assert raised.value.code is ErrorCode.PARAMETER_NOT_ALLOWED
    assert adapter.state is AdapterState.CANDIDATE
    assert adapter.gate.session == session
    assert session.call_counts == call_counts
    assert backend.calls == backend_calls


class CountingBackend:
    def __init__(self) -> None:
        self.execute_calls = 0

    def execute(self, command: AdapterCommand, manifest: StageManifest) -> OperationResult:
        del command, manifest
        self.execute_calls += 1
        raise AssertionError("construction must not execute a backend")


def test_construction_only_assigns_fields_without_backend_work() -> None:
    backend = CountingBackend()

    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)

    assert adapter.state is AdapterState.CANDIDATE
    assert backend.execute_calls == 0
