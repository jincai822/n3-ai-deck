from __future__ import annotations

import json
from collections.abc import Iterator

from streamdock_n3.hardware.adapter import N3Adapter
from streamdock_n3.hardware.backend import FakeBackend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    Operation,
    RecoveryStatus,
    ResultStatus,
    Stage,
)
from streamdock_n3.hardware.evidence import EvidenceRecorder
from tests.hardware_fixtures import TEST_COMMIT, command_step, make_manifest, make_profile


def _execute_stage(
    adapter: N3Adapter,
    stage: Stage,
    commands: tuple[AdapterCommand, ...],
) -> None:
    adapter.begin_stage(make_manifest(stage, tuple(command_step(command) for command in commands)))
    for command in commands:
        assert adapter.execute(command).status is ResultStatus.SUCCEEDED
    adapter.complete_stage(True)


def _g3_adapter(recorder: EvidenceRecorder) -> N3Adapter:
    adapter = N3Adapter(
        make_profile(),
        TEST_COMMIT,
        FakeBackend(),
        initial_state=AdapterState.PROFILE_APPROVED,
        evidence=recorder,
    )
    adapter.begin_stage(make_manifest(Stage.G3_INPUT))
    return adapter


def _walk_keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            assert isinstance(key, str)
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def test_records_closed_g3_operation_and_stage_evidence() -> None:
    recorder = EvidenceRecorder()
    adapter = _g3_adapter(recorder)

    assert (
        adapter.execute(AdapterCommand(Operation.OBSERVE_INPUTS)).status is ResultStatus.SUCCEEDED
    )
    assert recorder.records[0].to_dict() == {
        "schema_version": 1,
        "kind": "operation",
        "stage": "g3_input",
        "commit": TEST_COMMIT,
        "profile_digest": make_profile().digest(),
        "interface": {"number": "00", "class": "03", "subclass": "00", "protocol": "00"},
        "operation": "observe_inputs",
        "brightness": None,
        "key": None,
        "payload_size": 0,
        "status": "succeeded",
        "error_code": "none",
        "duration_ms": 0,
        "event_count": 0,
        "expected_result": "g3_input-validated",
        "recovery_plan": "g3_input-recovery",
        "approval_reference": "test:g3_input",
        "adapter_state": None,
        "recovery_status": None,
    }

    adapter.complete_stage(True, RecoveryStatus.NOT_REQUIRED)

    stage_record = recorder.records[1].to_dict()
    assert stage_record["kind"] == "stage"
    assert stage_record["adapter_state"] == "input_validated"
    assert stage_record["recovery_status"] == "not_required"
    assert stage_record["operation"] is None
    assert stage_record["status"] is None
    assert stage_record["error_code"] is None
    assert stage_record["duration_ms"] == 0
    assert stage_record["event_count"] == 0
    assert stage_record["payload_size"] == 0


def test_image_evidence_is_redacted_deterministic_and_immutable() -> None:
    recorder = EvidenceRecorder()
    adapter = _g3_adapter(recorder)
    assert (
        adapter.execute(AdapterCommand(Operation.OBSERVE_INPUTS)).status is ResultStatus.SUCCEEDED
    )
    adapter.complete_stage(True)
    _execute_stage(adapter, Stage.G4_INITIALIZATION, (AdapterCommand(Operation.INITIALIZE),))
    _execute_stage(
        adapter,
        Stage.G5_BRIGHTNESS,
        (
            AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),
            AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50),
        ),
    )
    markers = tuple(
        part_a + part_b
        for part_a, part_b in (
            (b"LOCAL_", b"USER_PATH"),
            (b"WORKSPACE_", b"PATH"),
            (b"DEVICE_", b"NODE"),
            (b"serial_", b"number=SECRET"),
            (b"image-", b"bytes"),
        )
    )
    sensitive_image = b" ".join(markers)
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=sensitive_image)
    adapter.begin_stage(make_manifest(Stage.G6_ONE_LCD, (command_step(command),)))
    assert adapter.execute(command).status is ResultStatus.SUCCEEDED

    rendered = recorder.to_json()
    parsed = json.loads(rendered)
    assert rendered == json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert [record["kind"] for record in parsed] == [
        "operation",
        "stage",
        "operation",
        "stage",
        "operation",
        "operation",
        "stage",
        "operation",
    ]
    assert parsed[-1]["key"] == 1
    assert parsed[-1]["payload_size"] == len(sensitive_image)
    for marker in markers:
        assert marker.decode() not in rendered
    assert sensitive_image.decode() not in rendered
    assert command.image_digest() not in rendered
    assert set(_walk_keys(parsed)).isdisjoint(
        {
            "serial",
            "serial_number",
            "path",
            "device_node",
            "raw_payload",
            "image",
            "image_base64",
            "image_sha256",
        }
    )

    assert isinstance(recorder.records, tuple)
    returned = recorder.records[-1].to_dict()
    interface = returned["interface"]
    assert isinstance(interface, dict)
    interface["number"] = "ff"
    assert recorder.records[-1].to_dict()["interface"]["number"] == "00"
