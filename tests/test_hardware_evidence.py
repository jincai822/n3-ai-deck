from __future__ import annotations

import json
from dataclasses import replace

import pytest

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    ErrorCode,
    Operation,
    OperationResult,
    RecoveryStatus,
    ResultStatus,
    Stage,
)
from streamdock_n3.hardware.evidence import (
    EvidenceDisposition,
    EvidenceKind,
    EvidenceRecorder,
    operation_evidence,
    stage_evidence,
)
from tests.hardware_fixtures import make_manifest, make_profile


def test_internal_record_moves_from_attempt_to_committed() -> None:
    recorder = EvidenceRecorder()
    record = operation_evidence(
        make_profile(),
        make_manifest(Stage.G1_PROFILE),
        AdapterCommand(Operation.APPROVE_PROFILE),
        OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0),
        epoch=1,
    )

    token = recorder.begin(record)
    assert recorder.records[-1].disposition is EvidenceDisposition.ATTEMPT
    recorder.commit(token)
    assert recorder.records[-1].disposition is EvidenceDisposition.COMMITTED


def test_failed_attempt_cannot_look_like_a_committed_transition() -> None:
    recorder = EvidenceRecorder()
    record = stage_evidence(
        make_profile(),
        make_manifest(Stage.G1_PROFILE),
        AdapterState.PROFILE_APPROVED,
        RecoveryStatus.NOT_REQUIRED,
        epoch=1,
    )

    token = recorder.begin(record)
    recorder.fail(token, ErrorCode.EVIDENCE_FAILURE)

    failed = recorder.records[-1]
    assert failed.disposition is EvidenceDisposition.FAILED
    assert failed.error_code is ErrorCode.EVIDENCE_FAILURE
    assert failed.adapter_state is AdapterState.PROFILE_APPROVED


@pytest.mark.parametrize("action", ("commit", "fail"))
def test_stale_or_reused_evidence_tokens_are_rejected(action: str) -> None:
    recorder = EvidenceRecorder()
    record = operation_evidence(
        make_profile(),
        make_manifest(Stage.G1_PROFILE),
        AdapterCommand(Operation.APPROVE_PROFILE),
        OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0),
        epoch=1,
    )
    token = recorder.begin(record)
    recorder.commit(token)

    with pytest.raises(ValueError, match="^stale_evidence_token$"):
        if action == "commit":
            recorder.commit(token)
        else:
            recorder.fail(token, ErrorCode.EVIDENCE_FAILURE)


def test_token_must_match_index_epoch_and_kind() -> None:
    recorder = EvidenceRecorder()
    first = recorder.begin(
        operation_evidence(
            make_profile(),
            make_manifest(Stage.G1_PROFILE),
            AdapterCommand(Operation.APPROVE_PROFILE),
            OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0),
            epoch=1,
        )
    )

    for stale in (
        replace(first, index=1),
        replace(first, epoch=2),
        replace(first, kind=EvidenceKind.STAGE),
    ):
        with pytest.raises(ValueError, match="^stale_evidence_token$"):
            recorder.commit(stale)


def test_json_remains_deterministic_closed_and_redacted() -> None:
    recorder = EvidenceRecorder()
    command = AdapterCommand(
        Operation.SET_KEY_IMAGE,
        key=1,
        image=b"serial=SECRET /home/user /dev/hidraw0 image-bytes",
    )
    record = operation_evidence(
        make_profile(),
        make_manifest(Stage.G6_ONE_LCD),
        command,
        OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0),
        epoch=8,
    )
    recorder.commit(recorder.begin(record))

    rendered = recorder.to_json()
    parsed = json.loads(rendered)
    assert rendered == json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert set(parsed[0]) == {
        "schema_version",
        "kind",
        "disposition",
        "epoch",
        "stage",
        "commit",
        "profile_digest",
        "interface",
        "operation",
        "brightness",
        "key",
        "payload_size",
        "status",
        "error_code",
        "duration_ms",
        "event_count",
        "expected_result",
        "recovery_plan",
        "approval_reference",
        "adapter_state",
        "recovery_status",
    }
    assert parsed[0]["disposition"] == "committed"
    assert parsed[0]["epoch"] == 8
    assert parsed[0]["payload_size"] == len(command.image or b"")
    for forbidden in (
        "SECRET",
        "/home/user",
        "/dev/hidraw0",
        "image-bytes",
        command.image_digest(),
    ):
        assert forbidden not in rendered


def test_evidence_must_begin_as_an_attempt() -> None:
    recorder = EvidenceRecorder()
    record = stage_evidence(
        make_profile(),
        make_manifest(Stage.G1_PROFILE),
        AdapterState.PROFILE_APPROVED,
        RecoveryStatus.NOT_REQUIRED,
        epoch=1,
    )

    with pytest.raises(ValueError, match="evidence must begin as an attempt"):
        recorder.begin(replace(record, disposition=EvidenceDisposition.COMMITTED))
