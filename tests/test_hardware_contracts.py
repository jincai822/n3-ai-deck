from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    CapabilitySnapshot,
    CommandSpec,
    CommandStep,
    ErrorCode,
    HidInterface,
    InputAction,
    InputKind,
    NormalizedInputEvent,
    Operation,
    OperationResult,
    ResultStatus,
    Stage,
    StagePhase,
    StageSessionSnapshot,
)
from tests.hardware_fixtures import TEST_IMAGE, make_manifest, make_profile


def test_profile_is_frozen_canonical_and_digest_stable() -> None:
    profile = make_profile()

    assert profile.to_dict() == {
        "schema_version": 1,
        "vid": "6602",
        "pid": "1000",
        "bcd_device": "0300",
        "interface": {"number": "00", "class": "03", "subclass": "00", "protocol": "00"},
        "identity_status": "user_reported_candidate",
        "protocol_status": "unvalidated",
        "source_commit": "0123456789abcdef",
    }
    assert len(profile.digest()) == 64
    assert profile.digest() == make_profile().digest()
    with pytest.raises(FrozenInstanceError):
        profile.vendor_id = 1  # type: ignore[misc]


def test_manifest_digest_changes_for_commit() -> None:
    manifest = make_manifest(Stage.G3_INPUT)
    changed_commit = replace(manifest, commit="fedcba9876543210")

    assert manifest.digest() != changed_commit.digest()


def test_command_step_is_exact_ordered_and_frozen() -> None:
    forward = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE)
    recovery = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"baseline-1")
    step = CommandStep(CommandSpec.from_command(forward), CommandSpec.from_command(recovery))

    assert step.forward.matches(forward)
    assert step.recovery is not None and step.recovery.matches(recovery)
    assert step.forward.matches(recovery) is False
    with pytest.raises(FrozenInstanceError):
        step.forward = CommandSpec.from_command(recovery)  # type: ignore[misc]


def test_manifest_digest_preserves_repeated_steps_and_order() -> None:
    first = CommandStep(CommandSpec(Operation.SET_BRIGHTNESS, brightness=40))
    second = CommandStep(CommandSpec(Operation.SET_BRIGHTNESS, brightness=50))
    manifest = make_manifest(Stage.G5_BRIGHTNESS, steps=(first, second, first))

    assert len(manifest.steps) == 3
    assert manifest.digest() != replace(manifest, steps=(second, first, first)).digest()


def test_manifest_rejects_empty_step_tuple_directly() -> None:
    with pytest.raises(ValueError, match="^steps must be a non-empty tuple$"):
        replace(make_manifest(Stage.G1_PROFILE), steps=())


def test_manifest_rejects_step_list_directly() -> None:
    manifest = make_manifest(Stage.G1_PROFILE)

    with pytest.raises(ValueError, match="^steps must be a non-empty tuple$"):
        replace(manifest, steps=list(manifest.steps))  # type: ignore[arg-type]


def test_manifest_rejects_non_command_step_directly() -> None:
    with pytest.raises(TypeError, match="^steps must contain CommandStep values$"):
        replace(
            make_manifest(Stage.G1_PROFILE),
            steps=(object(),),  # type: ignore[arg-type]
        )


def test_capability_and_session_snapshots_are_closed_immutable_values() -> None:
    capability = CapabilitySnapshot(
        state=AdapterState.CANDIDATE,
        profile_digest=None,
        bcd_device=None,
        interface=None,
        epoch=0,
        stage=Stage.G1_PROFILE,
        phase=StagePhase.FORWARD,
    )
    session = StageSessionSnapshot(Stage.G1_PROFILE, StagePhase.FORWARD, 0, 0, False)

    assert capability.profile_digest is None
    assert session.pending_reservation is False
    with pytest.raises(FrozenInstanceError):
        capability.epoch = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "factory",
    (
        lambda: CapabilitySnapshot(
            AdapterState.CANDIDATE,
            make_profile().digest(),
            "0300",  # type: ignore[arg-type]
            make_profile().interface,
            0,
            Stage.G1_PROFILE,
            StagePhase.FORWARD,
        ),
        lambda: CapabilitySnapshot(
            AdapterState.CANDIDATE,
            make_profile().digest(),
            None,
            None,
            0,
            Stage.G1_PROFILE,
            StagePhase.FORWARD,
        ),
        lambda: CapabilitySnapshot(
            AdapterState.CANDIDATE,
            None,
            None,
            None,
            True,  # type: ignore[arg-type]
            Stage.G1_PROFILE,
            StagePhase.FORWARD,
        ),
        lambda: CapabilitySnapshot(
            AdapterState.CANDIDATE,
            None,
            None,
            None,
            0,
            None,
            StagePhase.FORWARD,
        ),
        lambda: StageSessionSnapshot(Stage.G1_PROFILE, StagePhase.FORWARD, -1, 0, False),
        lambda: StageSessionSnapshot(Stage.G1_PROFILE, StagePhase.FORWARD, 0, -1, False),
        lambda: StageSessionSnapshot(
            Stage.G1_PROFILE,
            StagePhase.FORWARD,
            0,
            0,
            0,  # type: ignore[arg-type]
        ),
    ),
)
def test_snapshot_validation_fails_closed(factory: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()  # type: ignore[operator]


def test_transaction_error_codes_are_stable() -> None:
    assert tuple(
        code.value
        for code in (
            ErrorCode.RESULT_MISSING,
            ErrorCode.PROFILE_MISMATCH,
            ErrorCode.ORDER_VIOLATION,
            ErrorCode.RECOVERY_REQUIRED,
            ErrorCode.STALE_RESERVATION,
            ErrorCode.EVIDENCE_FAILURE,
        )
    ) == (
        "result_missing",
        "profile_mismatch",
        "order_violation",
        "recovery_required",
        "stale_reservation",
        "evidence_failure",
    )


def test_operation_result_success_requires_none_error() -> None:
    success = OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 3)
    failure = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 3)

    assert success.succeeded is True
    assert failure.succeeded is False


@pytest.mark.parametrize(
    "factory",
    (
        lambda: HidInterface(-1, 3, 0, 0),
        lambda: HidInterface(256, 3, 0, 0),
        lambda: AdapterCommand(Operation.SET_BRIGHTNESS),
        lambda: AdapterCommand(Operation.SET_BRIGHTNESS, brightness=101),
        lambda: AdapterCommand(Operation.SET_KEY_IMAGE, key=0, image=b"image"),
        lambda: AdapterCommand(Operation.OBSERVE_INPUTS, brightness=10),
        lambda: NormalizedInputEvent(InputKind.BUTTON, 10, InputAction.PRESS, 1),
        lambda: NormalizedInputEvent(InputKind.KNOB_PRESS, 4, InputAction.PRESS, 1),
        lambda: NormalizedInputEvent(InputKind.KNOB_ROTATE, 1, InputAction.PRESS, 1),
        lambda: replace(make_profile(), source_commit="not-a-commit"),
        lambda: replace(make_manifest(Stage.G3_INPUT), stage=Stage.G0_SIMULATION),
        lambda: replace(make_manifest(Stage.G3_INPUT), profile_digest="short"),
        lambda: replace(make_manifest(Stage.G3_INPUT), deadline_ms=0),
        lambda: replace(make_manifest(Stage.G3_INPUT), expected_result="unsafe value"),
        lambda: OperationResult(ResultStatus.SUCCEEDED, ErrorCode.BACKEND_FAILURE, 0),
        lambda: OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.NONE, 0),
    ),
)
def test_invalid_contract_values_fail_closed(factory: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()  # type: ignore[operator]
