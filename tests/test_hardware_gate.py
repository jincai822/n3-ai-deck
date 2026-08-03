from __future__ import annotations

from dataclasses import replace

import pytest

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    CapabilitySnapshot,
    CommandSpec,
    DeviceProfile,
    ErrorCode,
    HidInterface,
    Operation,
    OperationResult,
    RecoveryStatus,
    ResultStatus,
    Stage,
    StageManifest,
    StagePhase,
    StageSessionSnapshot,
)
from streamdock_n3.hardware.gate import (
    CommandPolicy,
    GateViolation,
    _CapabilityGate,
)
from tests.hardware_fixtures import TEST_COMMIT, TEST_IMAGE, make_manifest, make_profile


def success() -> OperationResult:
    return OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0)


def forward_commands(stage: Stage) -> tuple[AdapterCommand, ...]:
    commands = {
        Stage.G1_PROFILE: (AdapterCommand(Operation.APPROVE_PROFILE),),
        Stage.G2_PERMISSION: (AdapterCommand(Operation.RECORD_PERMISSION),),
        Stage.G3_INPUT: (AdapterCommand(Operation.OBSERVE_INPUTS),),
        Stage.G4_INITIALIZATION: (AdapterCommand(Operation.INITIALIZE),),
        Stage.G5_BRIGHTNESS: (AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),),
        Stage.G6_ONE_LCD: (
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE),
        ),
        Stage.G7_SIX_LCD: tuple(
            AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"test-{key}".encode())
            for key in range(1, 7)
        ),
    }
    return commands[stage]


def recovery_commands(stage: Stage) -> tuple[AdapterCommand, ...]:
    commands = {
        Stage.G1_PROFILE: (),
        Stage.G2_PERMISSION: (),
        Stage.G3_INPUT: (),
        Stage.G4_INITIALIZATION: (),
        Stage.G5_BRIGHTNESS: (AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50),),
        Stage.G6_ONE_LCD: (
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"g0-baseline"),
        ),
        Stage.G7_SIX_LCD: tuple(
            AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"base-{key}".encode())
            for key in range(6, 0, -1)
        ),
    }
    return commands[stage]


def complete_stage(gate: _CapabilityGate, stage: Stage) -> AdapterState:
    gate.begin(make_profile(), make_manifest(stage), TEST_COMMIT)
    for command in forward_commands(stage):
        reservation = gate.reserve_forward(command)
        gate.settle(reservation, success())
    for command in recovery_commands(stage):
        reservation = gate.reserve_recovery(command)
        gate.settle(reservation, success())
    preview = gate.preview_completion(True, True if recovery_commands(stage) else None)
    return gate.commit(preview, lambda: None)


def advance_through_g1() -> _CapabilityGate:
    gate = _CapabilityGate()
    assert complete_stage(gate, Stage.G1_PROFILE) is AdapterState.PROFILE_APPROVED
    return gate


def advance_to(stage: Stage) -> _CapabilityGate:
    gate = _CapabilityGate()
    for current in (
        Stage.G1_PROFILE,
        Stage.G2_PERMISSION,
        Stage.G3_INPUT,
        Stage.G4_INITIALIZATION,
        Stage.G5_BRIGHTNESS,
        Stage.G6_ONE_LCD,
    ):
        if current is stage:
            break
        complete_stage(gate, current)
    return gate


def ready_g1_gate() -> _CapabilityGate:
    gate = _CapabilityGate()
    gate.begin(make_profile(), make_manifest(Stage.G1_PROFILE), TEST_COMMIT)
    reservation = gate.reserve_forward(AdapterCommand(Operation.APPROVE_PROFILE))
    gate.settle(reservation, success())
    return gate


def test_reservation_does_not_count_as_success_without_a_result() -> None:
    gate = _CapabilityGate()
    manifest = make_manifest(Stage.G1_PROFILE)
    command = AdapterCommand(Operation.APPROVE_PROFILE)
    gate.begin(make_profile(), manifest, TEST_COMMIT)

    reservation = gate.reserve_forward(command)

    assert gate.state is AdapterState.CANDIDATE
    assert gate.session_snapshot == StageSessionSnapshot(
        Stage.G1_PROFILE, StagePhase.FORWARD, 0, 0, True
    )
    with pytest.raises(GateViolation) as raised:
        gate.preview_completion(True, None)
    assert raised.value.code is ErrorCode.RESULT_MISSING
    assert reservation.command == CommandSpec.from_command(command)


def test_only_the_exact_pending_reservation_can_settle() -> None:
    gate = _CapabilityGate()
    gate.begin(make_profile(), make_manifest(Stage.G1_PROFILE), TEST_COMMIT)
    reservation = gate.reserve_forward(AdapterCommand(Operation.APPROVE_PROFILE))
    stale = replace(reservation, epoch=reservation.epoch + 1)

    with pytest.raises(GateViolation) as raised:
        gate.settle(stale, success())

    assert raised.value.code is ErrorCode.STALE_RESERVATION
    assert gate.state is AdapterState.BLOCKED


@pytest.mark.parametrize(
    ("profile", "manifest", "current_commit"),
    (
        (
            replace(make_profile(), bcd_device=0x0301),
            make_manifest(Stage.G2_PERMISSION),
            TEST_COMMIT,
        ),
        (
            replace(make_profile(), interface=HidInterface(1, 3, 1, 1)),
            make_manifest(Stage.G2_PERMISSION),
            TEST_COMMIT,
        ),
        (
            make_profile(),
            replace(make_manifest(Stage.G2_PERMISSION), profile_digest="0" * 64),
            TEST_COMMIT,
        ),
        (make_profile(), make_manifest(Stage.G2_PERMISSION), "fedcba9876543210"),
    ),
)
def test_g1_commit_pins_identity_and_later_drift_blocks(
    profile: DeviceProfile,
    manifest: StageManifest,
    current_commit: str,
) -> None:
    gate = advance_through_g1()

    with pytest.raises(GateViolation) as raised:
        gate.begin(profile, manifest, current_commit)

    assert raised.value.code is ErrorCode.PROFILE_MISMATCH
    assert gate.state is AdapterState.BLOCKED


def test_forward_and_recovery_are_exact_and_lifo() -> None:
    gate = advance_to(Stage.G7_SIX_LCD)
    manifest = make_manifest(Stage.G7_SIX_LCD)
    gate.begin(make_profile(), manifest, TEST_COMMIT)

    for key, _step in enumerate(manifest.steps, start=1):
        command = AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"test-{key}".encode())
        reservation = gate.reserve_forward(command)
        gate.settle(reservation, success())

    with pytest.raises(GateViolation) as raised:
        gate.reserve_recovery(AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"base-1"))
    assert raised.value.code is ErrorCode.ORDER_VIOLATION
    assert gate.state is AdapterState.BLOCKED


def test_disconnect_is_distinct_and_clears_all_queues() -> None:
    gate = _CapabilityGate()
    gate.begin(make_profile(), make_manifest(Stage.G1_PROFILE), TEST_COMMIT)
    reservation = gate.reserve_forward(AdapterCommand(Operation.APPROVE_PROFILE))

    gate.settle(
        reservation,
        OperationResult(ResultStatus.DISCONNECTED, ErrorCode.DEVICE_DISCONNECTED, 0),
    )

    assert gate.state is AdapterState.DISCONNECTED
    assert gate.session_snapshot is None


def test_precommit_callback_failure_never_advances_state() -> None:
    gate = ready_g1_gate()
    preview = gate.preview_completion(True, None)

    with pytest.raises(RuntimeError):
        gate.commit(preview, lambda: (_ for _ in ()).throw(RuntimeError("sink")))

    assert gate.state is AdapterState.BLOCKED
    assert gate.capability_snapshot.profile_digest is None


def test_forward_machine_failure_keeps_only_earned_recovery() -> None:
    gate = advance_to(Stage.G7_SIX_LCD)
    gate.begin(make_profile(), make_manifest(Stage.G7_SIX_LCD), TEST_COMMIT)
    first = gate.reserve_forward(forward_commands(Stage.G7_SIX_LCD)[0])
    gate.settle(first, success())
    second = gate.reserve_forward(forward_commands(Stage.G7_SIX_LCD)[1])
    gate.settle(
        second,
        OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0),
    )

    assert gate.state is AdapterState.BLOCKED
    assert gate.session_snapshot == StageSessionSnapshot(
        Stage.G7_SIX_LCD, StagePhase.RECOVERY, 1, 1, False
    )


def test_recovery_machine_failure_clears_recovery_and_becomes_ready() -> None:
    gate = advance_to(Stage.G5_BRIGHTNESS)
    gate.begin(make_profile(), make_manifest(Stage.G5_BRIGHTNESS), TEST_COMMIT)
    forward = gate.reserve_forward(forward_commands(Stage.G5_BRIGHTNESS)[0])
    gate.settle(forward, success())
    recovery = gate.reserve_recovery(recovery_commands(Stage.G5_BRIGHTNESS)[0])
    gate.settle(
        recovery,
        OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0),
    )

    preview = gate.preview_completion(True, True)
    assert preview.next_state is AdapterState.BLOCKED
    assert preview.recovery_status is RecoveryStatus.FAILED


def test_fail_evidence_validates_and_settles_pending_reservation() -> None:
    gate = _CapabilityGate()
    gate.begin(make_profile(), make_manifest(Stage.G1_PROFILE), TEST_COMMIT)
    reservation = gate.reserve_forward(AdapterCommand(Operation.APPROVE_PROFILE))

    gate.fail_evidence(reservation)

    assert gate.state is AdapterState.BLOCKED
    assert gate.session_snapshot is None


def test_reentrant_block_invalidates_epoch_and_session() -> None:
    gate = ready_g1_gate()
    epoch = gate.capability_snapshot.epoch

    with pytest.raises(GateViolation) as raised:
        gate.block_reentrant()

    assert raised.value.code is ErrorCode.STALE_RESERVATION
    assert gate.state is AdapterState.BLOCKED
    assert gate.capability_snapshot.epoch == epoch + 1


def test_candidate_manifest_failure_does_not_mutate_state() -> None:
    gate = _CapabilityGate()

    with pytest.raises(GateViolation) as raised:
        gate.begin(
            make_profile(),
            replace(make_manifest(Stage.G1_PROFILE), commit="fedcba9876543210"),
            TEST_COMMIT,
        )

    assert raised.value.code is ErrorCode.MANIFEST_INVALID
    assert gate.state is AdapterState.CANDIDATE
    assert gate.session_snapshot is None


def test_all_stages_advance_only_after_ordered_results_and_precommit() -> None:
    gate = _CapabilityGate()

    for stage in (
        Stage.G1_PROFILE,
        Stage.G2_PERMISSION,
        Stage.G3_INPUT,
        Stage.G4_INITIALIZATION,
        Stage.G5_BRIGHTNESS,
        Stage.G6_ONE_LCD,
        Stage.G7_SIX_LCD,
    ):
        complete_stage(gate, stage)

    assert gate.state is AdapterState.SIX_LCD_VALIDATED
    assert gate.session_snapshot is None


def test_command_policy_accepts_candidate_g1_without_pinned_identity() -> None:
    profile = make_profile()
    capability = CapabilitySnapshot(
        AdapterState.CANDIDATE,
        None,
        None,
        None,
        1,
        Stage.G1_PROFILE,
        StagePhase.FORWARD,
    )

    assert (
        CommandPolicy.validate(
            profile,
            capability,
            make_manifest(Stage.G1_PROFILE),
            0,
            AdapterCommand(Operation.APPROVE_PROFILE),
        )
        is None
    )


def test_command_policy_rejects_wrong_order_or_profile_binding() -> None:
    gate = advance_through_g1()
    gate.begin(make_profile(), make_manifest(Stage.G2_PERMISSION), TEST_COMMIT)
    capability = gate.capability_snapshot

    with pytest.raises(GateViolation) as raised:
        CommandPolicy.validate(
            make_profile(),
            capability,
            make_manifest(Stage.G2_PERMISSION),
            True,  # type: ignore[arg-type]
            AdapterCommand(Operation.RECORD_PERMISSION),
        )
    assert raised.value.code is ErrorCode.ORDER_VIOLATION

    with pytest.raises(GateViolation) as raised:
        CommandPolicy.validate(
            replace(make_profile(), bcd_device=0x0301),
            capability,
            make_manifest(Stage.G2_PERMISSION),
            0,
            AdapterCommand(Operation.RECORD_PERMISSION),
        )
    assert raised.value.code is ErrorCode.PROFILE_MISMATCH


def test_command_policy_rejects_pinned_identity_for_g1() -> None:
    profile = make_profile()
    capability = CapabilitySnapshot(
        AdapterState.PROFILE_APPROVED,
        profile.digest(),
        profile.bcd_device,
        profile.interface,
        1,
        Stage.G1_PROFILE,
        StagePhase.FORWARD,
    )

    with pytest.raises(GateViolation) as raised:
        CommandPolicy.validate(
            profile,
            capability,
            make_manifest(Stage.G1_PROFILE),
            0,
            AdapterCommand(Operation.APPROVE_PROFILE),
        )

    assert raised.value.code is ErrorCode.PROFILE_MISMATCH
