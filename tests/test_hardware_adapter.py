from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from typing import cast

import pytest

from streamdock_n3.hardware.adapter import N3Adapter
from streamdock_n3.hardware.backend import FakeBackend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    CommandSpec,
    ErrorCode,
    Operation,
    OperationResult,
    ResultStatus,
    Stage,
    StageManifest,
)
from streamdock_n3.hardware.evidence import (
    EvidenceDisposition,
    EvidenceKind,
    EvidenceRecord,
)
from streamdock_n3.hardware.gate import GateViolation
from tests.hardware_fixtures import (
    TEST_COMMIT,
    TEST_IMAGE,
    make_g1_manifest,
    make_incomplete_g1_manifest,
    make_manifest,
    make_profile,
    make_resolved_roles,
    make_swapped_roles,
)

STAGES = (
    Stage.G1_PROFILE,
    Stage.G2_PERMISSION,
    Stage.G3_INPUT,
    Stage.G4_INITIALIZATION,
    Stage.G5_BRIGHTNESS,
    Stage.G6_ONE_LCD,
    Stage.G7_SIX_LCD,
)


def success() -> OperationResult:
    return OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0)


def backend_failure() -> OperationResult:
    return OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)


def image_command(key: int, prefix: str) -> AdapterCommand:
    return AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"{prefix}-{key}".encode())


def forward_commands(stage: Stage) -> tuple[AdapterCommand, ...]:
    return {
        Stage.G1_PROFILE: (AdapterCommand(Operation.APPROVE_PROFILE),),
        Stage.G2_PERMISSION: (AdapterCommand(Operation.RECORD_PERMISSION),),
        Stage.G3_INPUT: (AdapterCommand(Operation.OBSERVE_INPUTS),),
        Stage.G4_INITIALIZATION: (AdapterCommand(Operation.INITIALIZE),),
        Stage.G5_BRIGHTNESS: (AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),),
        Stage.G6_ONE_LCD: (
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE),
        ),
        Stage.G7_SIX_LCD: tuple(image_command(key, "test") for key in range(1, 7)),
    }[stage]


def recovery_commands(stage: Stage) -> tuple[AdapterCommand, ...]:
    return {
        Stage.G1_PROFILE: (),
        Stage.G2_PERMISSION: (),
        Stage.G3_INPUT: (),
        Stage.G4_INITIALIZATION: (),
        Stage.G5_BRIGHTNESS: (AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50),),
        Stage.G6_ONE_LCD: (
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"g0-baseline"),
        ),
        Stage.G7_SIX_LCD: tuple(image_command(key, "base") for key in range(6, 0, -1)),
    }[stage]


def hardware_manifest(stage: Stage) -> StageManifest:
    if stage is Stage.G1_PROFILE:
        return make_g1_manifest()
    return make_manifest(stage, role_resolution=make_resolved_roles())


def complete_stage(adapter: N3Adapter, stage: Stage) -> AdapterState:
    adapter.begin_stage(hardware_manifest(stage))
    for command in forward_commands(stage):
        assert adapter.execute(command).succeeded
    for command in recovery_commands(stage):
        assert adapter.recover(command).succeeded
    return adapter.complete_stage(True, True if recovery_commands(stage) else None)


def adapter_advanced_to(stage: Stage, backend: FakeBackend) -> N3Adapter:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)
    for current in STAGES:
        if current is stage:
            break
        complete_stage(adapter, current)
    return adapter


def test_adapter_has_no_live_gate_or_arbitrary_initial_state() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend())

    assert adapter.state is AdapterState.CANDIDATE
    assert not hasattr(adapter, "gate")
    assert not hasattr(adapter, "backend")
    with pytest.raises(AttributeError):
        adapter.profile = replace(make_profile(), bcd_device=0x0301)  # type: ignore[misc]
    with pytest.raises(TypeError):
        N3Adapter(  # type: ignore[call-arg]
            make_profile(),
            TEST_COMMIT,
            FakeBackend(),
            initial_state=AdapterState.SIX_LCD_VALIDATED,
        )


def test_complete_without_backend_result_cannot_advance() -> None:
    backend = FakeBackend()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)
    adapter.begin_stage(make_g1_manifest())

    with pytest.raises(GateViolation) as raised:
        adapter.complete_stage(True)

    assert raised.value.code is ErrorCode.RESULT_MISSING
    assert adapter.state is AdapterState.CANDIDATE
    assert backend.calls == []


def test_execute_before_begin_is_rejected_without_backend_call() -> None:
    backend = FakeBackend()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)

    with pytest.raises(GateViolation) as raised:
        adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED
    assert backend.calls == []


def test_adapter_advances_g1_to_g7_with_ordered_recovery() -> None:
    backend = FakeBackend()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)

    for stage in STAGES:
        complete_stage(adapter, stage)

    assert adapter.state is AdapterState.SIX_LCD_VALIDATED
    assert adapter.session_snapshot is None
    assert len(backend.calls) == 20


def test_wrong_order_never_reaches_backend() -> None:
    backend = FakeBackend()
    adapter = adapter_advanced_to(Stage.G7_SIX_LCD, backend)
    adapter.begin_stage(hardware_manifest(Stage.G7_SIX_LCD))
    calls = len(backend.calls)

    with pytest.raises(GateViolation) as raised:
        adapter.execute(image_command(2, "test"))

    assert raised.value.code is ErrorCode.ORDER_VIOLATION
    assert len(backend.calls) == calls


def test_g7_failure_cancels_forward_and_allows_only_lifo_recovery() -> None:
    prior_stage_results = (success(),) * 8
    backend = FakeBackend(
        scripted_results=prior_stage_results
        + (success(), success(), backend_failure(), success(), success())
    )
    adapter = adapter_advanced_to(Stage.G7_SIX_LCD, backend)
    adapter.begin_stage(hardware_manifest(Stage.G7_SIX_LCD))

    assert adapter.execute(image_command(1, "test")).succeeded
    assert adapter.execute(image_command(2, "test")).succeeded
    assert not adapter.execute(image_command(3, "test")).succeeded
    assert adapter.state is AdapterState.BLOCKED
    with pytest.raises(GateViolation) as raised:
        adapter.execute(image_command(4, "test"))
    assert raised.value.code is ErrorCode.ORDER_VIOLATION

    assert adapter.recover(image_command(2, "base")).succeeded
    assert adapter.recover(image_command(1, "base")).succeeded
    assert adapter.complete_stage(True, True) is AdapterState.BLOCKED
    assert [call.key for call in backend.calls[-5:]] == [1, 2, 3, 2, 1]


def test_recovery_failure_stops_remaining_recovery_and_never_advances() -> None:
    prior_stage_results = (success(),) * 8
    backend = FakeBackend(
        scripted_results=prior_stage_results + (success(), success(), backend_failure())
    )
    adapter = adapter_advanced_to(Stage.G7_SIX_LCD, backend)
    adapter.begin_stage(hardware_manifest(Stage.G7_SIX_LCD))
    adapter.execute(image_command(1, "test"))
    adapter.execute(image_command(2, "test"))

    assert not adapter.recover(image_command(2, "base")).succeeded
    with pytest.raises(GateViolation):
        adapter.recover(image_command(1, "base"))
    assert adapter.complete_stage(True, False) is AdapterState.BLOCKED


def test_unknown_recovery_confirmation_never_advances() -> None:
    adapter = adapter_advanced_to(Stage.G5_BRIGHTNESS, FakeBackend())
    adapter.begin_stage(hardware_manifest(Stage.G5_BRIGHTNESS))
    adapter.execute(AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40))
    adapter.recover(AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50))

    assert adapter.complete_stage(True, None) is AdapterState.BLOCKED


def test_backend_disconnect_is_disconnected_and_never_recovers() -> None:
    disconnected = OperationResult(
        ResultStatus.DISCONNECTED,
        ErrorCode.DEVICE_DISCONNECTED,
        0,
    )
    backend = FakeBackend(scripted_results=(disconnected,))
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)
    adapter.begin_stage(make_g1_manifest())

    assert adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE)) == disconnected
    assert adapter.state is AdapterState.DISCONNECTED
    assert adapter.session_snapshot is None
    assert len(backend.calls) == 1


class ThrowingSink:
    def record(self, record: EvidenceRecord) -> None:
        del record
        raise RuntimeError("private sink failure")


class ArmedThrowingSink:
    def __init__(self) -> None:
        self.armed = False

    def record(self, record: EvidenceRecord) -> None:
        del record
        if self.armed:
            raise RuntimeError("armed sink failure")


class ArmedReentrantSink:
    def __init__(self) -> None:
        self.adapter: N3Adapter | None = None
        self.armed = False

    def record(self, record: EvidenceRecord) -> None:
        del record
        if self.armed:
            assert self.adapter is not None
            with pytest.raises(GateViolation) as raised:
                self.adapter.recover(image_command(2, "base"))
            assert raised.value.code is ErrorCode.STALE_RESERVATION


@pytest.mark.parametrize("sink_type", (ArmedThrowingSink, ArmedReentrantSink))
def test_disconnect_survives_evidence_failure_after_earned_g7_recovery(
    sink_type: type[ArmedThrowingSink] | type[ArmedReentrantSink],
) -> None:
    disconnected = OperationResult(
        ResultStatus.DISCONNECTED,
        ErrorCode.DEVICE_DISCONNECTED,
        0,
    )
    backend = FakeBackend(scripted_results=(success(),) * 10 + (disconnected,))
    sink = sink_type()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend, sink)
    for stage in STAGES:
        if stage is Stage.G7_SIX_LCD:
            break
        complete_stage(adapter, stage)
    if isinstance(sink, ArmedReentrantSink):
        sink.adapter = adapter
    adapter.begin_stage(hardware_manifest(Stage.G7_SIX_LCD))
    assert adapter.execute(image_command(1, "test")).succeeded
    assert adapter.execute(image_command(2, "test")).succeeded
    sink.armed = True

    if isinstance(sink, ArmedReentrantSink):
        with pytest.raises(GateViolation) as raised:
            adapter.execute(image_command(3, "test"))
        assert raised.value.code is ErrorCode.STALE_RESERVATION
        expected_evidence_error = ErrorCode.STALE_RESERVATION
    else:
        assert adapter.execute(image_command(3, "test")) == disconnected
        expected_evidence_error = ErrorCode.EVIDENCE_FAILURE

    assert adapter.state is AdapterState.DISCONNECTED
    assert adapter.session_snapshot is None
    failed = adapter.evidence_records[-1]
    assert failed.disposition is EvidenceDisposition.FAILED
    assert failed.error_code is expected_evidence_error
    calls = len(backend.calls)
    with pytest.raises(GateViolation) as raised:
        adapter.recover(image_command(2, "base"))
    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED
    assert len(backend.calls) == calls


def test_throwing_sink_blocks_before_operation_or_stage_advancement() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend(), ThrowingSink())
    adapter.begin_stage(make_g1_manifest())

    result = adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert result.error_code is ErrorCode.EVIDENCE_FAILURE
    assert adapter.state is AdapterState.BLOCKED
    assert adapter.evidence_records[-1].disposition is EvidenceDisposition.FAILED


class GateViolationSink:
    def __init__(self, code: ErrorCode, fail_on_call: int = 1) -> None:
        self._code = code
        self._fail_on_call = fail_on_call
        self.calls = 0

    def record(self, record: EvidenceRecord) -> None:
        del record
        self.calls += 1
        if self.calls == self._fail_on_call:
            raise GateViolation(self._code)


def test_callback_gate_violation_none_normalizes_and_finalizes_operation_evidence() -> None:
    sink = GateViolationSink(ErrorCode.NONE)
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend(), sink)
    adapter.begin_stage(make_g1_manifest())

    result = adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert result.error_code is ErrorCode.EVIDENCE_FAILURE
    assert adapter.state is AdapterState.BLOCKED
    failed = adapter.evidence_records[-1]
    assert failed.disposition is EvidenceDisposition.FAILED
    assert failed.error_code is ErrorCode.EVIDENCE_FAILURE


class SecondWriteThrowingSink:
    def __init__(self) -> None:
        self.calls = 0

    def record(self, record: EvidenceRecord) -> None:
        del record
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("stage sink failure")


def test_stage_sink_failure_occurs_before_profile_commit() -> None:
    sink = SecondWriteThrowingSink()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend(), sink)
    adapter.begin_stage(make_g1_manifest())
    assert adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE)).succeeded

    with pytest.raises(GateViolation) as raised:
        adapter.complete_stage(True)

    assert raised.value.code is ErrorCode.EVIDENCE_FAILURE
    assert adapter.state is AdapterState.BLOCKED
    assert adapter.capability_snapshot.profile_digest is None
    assert adapter.evidence_records[-1].disposition is EvidenceDisposition.FAILED


@pytest.mark.parametrize("callback_code", (ErrorCode.NONE, ErrorCode.PROFILE_MISMATCH))
def test_callback_gate_violation_normalizes_without_masking_evidence_failure(
    callback_code: ErrorCode,
) -> None:
    sink = GateViolationSink(callback_code, fail_on_call=2)
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend(), sink)
    adapter.begin_stage(make_g1_manifest())
    assert adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE)).succeeded

    with pytest.raises(GateViolation) as raised:
        adapter.complete_stage(True)

    assert raised.value.code is ErrorCode.EVIDENCE_FAILURE
    assert adapter.state is AdapterState.BLOCKED
    failed = adapter.evidence_records[-1]
    assert failed.disposition is EvidenceDisposition.FAILED
    assert failed.error_code is ErrorCode.EVIDENCE_FAILURE


class ReentrantSink:
    def __init__(self) -> None:
        self.adapter: N3Adapter | None = None
        self.calls = 0

    def record(self, record: EvidenceRecord) -> None:
        del record
        self.calls += 1
        if self.calls == 2:
            assert self.adapter is not None
            with pytest.raises(GateViolation):
                self.adapter.disconnect()


def test_caught_reentrant_sink_violation_still_blocks_commit() -> None:
    sink = ReentrantSink()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend(), sink)
    sink.adapter = adapter
    adapter.begin_stage(make_g1_manifest())
    adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    with pytest.raises(GateViolation) as raised:
        adapter.complete_stage(True)

    assert raised.value.code is ErrorCode.STALE_RESERVATION
    assert adapter.state is AdapterState.BLOCKED
    assert adapter.capability_snapshot.profile_digest is None


class ExplodingBackend:
    def execute(self, command: AdapterCommand, manifest: StageManifest) -> OperationResult:
        del command, manifest
        raise RuntimeError("secret backend exception detail")


def test_backend_exception_is_sanitized_without_retry() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, ExplodingBackend())
    adapter.begin_stage(make_g1_manifest())

    result = adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert result == backend_failure()
    assert adapter.state is AdapterState.BLOCKED
    assert "secret backend exception detail" not in repr(adapter)


class MaliciousResult:
    succeeded = True


class MaliciousBackend:
    def __init__(self) -> None:
        self.execute_calls = 0

    def execute(self, command: AdapterCommand, manifest: StageManifest) -> OperationResult:
        del command, manifest
        self.execute_calls += 1
        return cast(OperationResult, MaliciousResult())


def test_non_contract_backend_result_is_normalized_without_retry() -> None:
    backend = MaliciousBackend()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)
    adapter.begin_stage(make_g1_manifest())

    result = adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE))

    assert result == OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.RESULT_MISSING, 0)
    assert backend.execute_calls == 1
    assert adapter.state is AdapterState.BLOCKED


def test_snapshots_and_evidence_are_immutable_copies() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend())
    adapter.begin_stage(make_g1_manifest())
    capability = adapter.capability_snapshot
    session = adapter.session_snapshot

    with pytest.raises(FrozenInstanceError):
        capability.epoch = 99  # type: ignore[misc]
    assert session is not None
    with pytest.raises(FrozenInstanceError):
        session.forward_index = 1  # type: ignore[misc]
    assert isinstance(adapter.evidence_records, tuple)


class CountingBackend:
    def __init__(self) -> None:
        self.execute_calls = 0

    def execute(self, command: AdapterCommand, manifest: StageManifest) -> OperationResult:
        del command, manifest
        self.execute_calls += 1
        return success()


def test_construction_and_begin_do_no_backend_work() -> None:
    backend = CountingBackend()
    adapter = N3Adapter(make_profile(), TEST_COMMIT, backend)
    adapter.begin_stage(make_g1_manifest())

    assert adapter.state is AdapterState.CANDIDATE
    assert backend.execute_calls == 0


def test_command_spec_helper_asserts_fixture_values() -> None:
    manifest = make_manifest(Stage.G5_BRIGHTNESS)

    assert manifest.steps[0].forward == CommandSpec(Operation.SET_BRIGHTNESS, brightness=40)


def test_g1_approval_pins_approved_profile_with_roles() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend())
    adapter.begin_stage(make_g1_manifest())
    assert adapter.execute(AdapterCommand(Operation.APPROVE_PROFILE)).succeeded
    assert adapter.complete_stage(True) is AdapterState.PROFILE_APPROVED

    approved = adapter.approved_profile
    assert approved is not None
    assert approved.input_interface == make_resolved_roles().input_interface
    assert approved.control_interface == make_resolved_roles().control_interface
    assert approved.profile_digest == make_profile().digest()
    assert approved.bcd_device == 0x0300
    assert approved.pinned_commit == TEST_COMMIT
    assert len(approved.role_resolution_digest) == 64

    approval = adapter.evidence_records[-1]
    assert approval.kind is EvidenceKind.PROFILE_APPROVAL
    assert approval.disposition is EvidenceDisposition.COMMITTED
    assert approval.role_resolution_digest == approved.role_resolution_digest
    assert approval.approval_reference == "test:g1_profile"


def test_g1_without_role_resolution_rejects_and_stays_candidate() -> None:
    adapter = N3Adapter(make_profile(), TEST_COMMIT, FakeBackend())

    with pytest.raises(GateViolation) as raised:
        adapter.begin_stage(make_incomplete_g1_manifest())

    assert raised.value.code is ErrorCode.PROFILE_EVIDENCE_INCOMPLETE
    assert adapter.state is AdapterState.CANDIDATE
    assert adapter.approved_profile is None


def test_later_stage_with_drifted_roles_blocks_adapter() -> None:
    adapter = adapter_advanced_to(Stage.G2_PERMISSION, FakeBackend())
    assert adapter.state is AdapterState.PROFILE_APPROVED

    drifted = make_manifest(Stage.G3_INPUT, role_resolution=make_swapped_roles())
    with pytest.raises(GateViolation) as raised:
        adapter.begin_stage(drifted)

    assert raised.value.code is ErrorCode.PROFILE_MISMATCH
    assert adapter.state is AdapterState.BLOCKED
