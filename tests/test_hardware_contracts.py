from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    CommandRule,
    ErrorCode,
    HidInterface,
    InputAction,
    InputKind,
    NormalizedInputEvent,
    Operation,
    OperationResult,
    ResultStatus,
    Stage,
)
from tests.hardware_fixtures import make_manifest, make_profile


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


def test_manifest_digest_changes_for_commit_profile_or_rules() -> None:
    manifest = make_manifest(Stage.G3_INPUT)
    changed_commit = replace(manifest, commit="fedcba9876543210")
    changed_rule = replace(
        manifest,
        allowed_commands=(CommandRule(Operation.OBSERVE_INPUTS, 1, 2),),
    )

    assert manifest.digest() != changed_commit.digest()
    assert manifest.digest() != changed_rule.digest()


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
        lambda: replace(
            make_manifest(Stage.G3_INPUT),
            allowed_commands=(
                CommandRule(Operation.OBSERVE_INPUTS, 1, 1),
                CommandRule(Operation.OBSERVE_INPUTS, 1, 1),
            ),
        ),
        lambda: OperationResult(ResultStatus.SUCCEEDED, ErrorCode.BACKEND_FAILURE, 0),
        lambda: OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.NONE, 0),
    ),
)
def test_invalid_contract_values_fail_closed(factory: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()  # type: ignore[operator]
