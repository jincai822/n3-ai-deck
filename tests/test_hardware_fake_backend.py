from __future__ import annotations

from collections.abc import MutableMapping

import pytest

from streamdock_n3.hardware.backend import Backend, FakeBackend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    ErrorCode,
    InputAction,
    InputKind,
    NormalizedInputEvent,
    Operation,
    ResultStatus,
    Stage,
)
from tests.hardware_fixtures import TEST_IMAGE, make_manifest


def all_input_events() -> tuple[NormalizedInputEvent, ...]:
    button_events = tuple(
        NormalizedInputEvent(InputKind.BUTTON, key, action, key * 10 + offset)
        for key in range(1, 10)
        for offset, action in enumerate((InputAction.PRESS, InputAction.RELEASE))
    )
    knob_events = tuple(
        NormalizedInputEvent(kind, knob, action, 1_000 + knob * 10 + offset)
        for knob in range(1, 4)
        for kind, action in (
            (InputKind.KNOB_PRESS, InputAction.PRESS),
            (InputKind.KNOB_PRESS, InputAction.RELEASE),
            (InputKind.KNOB_ROTATE, InputAction.LEFT),
            (InputKind.KNOB_ROTATE, InputAction.RIGHT),
        )
        for offset in (0,)
    )
    return button_events + knob_events


def test_fake_backend_returns_injected_normalized_events() -> None:
    backend = FakeBackend(events=all_input_events())
    result = backend.execute(
        AdapterCommand(Operation.OBSERVE_INPUTS),
        make_manifest(Stage.G3_INPUT),
    )

    assert isinstance(backend, Backend)
    assert result.succeeded is True
    assert result.events == all_input_events()
    assert backend.calls[0].operation is Operation.OBSERVE_INPUTS


def test_fake_backend_records_only_image_digest_and_size() -> None:
    backend = FakeBackend()
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE)

    backend.execute(command, make_manifest(Stage.G6_ONE_LCD))

    call = backend.calls[0]
    assert call.key == 1
    assert call.payload_size == len(TEST_IMAGE)
    assert call.payload_sha256 == command.image_digest()
    assert not hasattr(call, "image")
    assert TEST_IMAGE not in repr(call).encode()


@pytest.mark.parametrize(
    ("status", "error_code"),
    (
        (ResultStatus.REJECTED, ErrorCode.OPERATION_NOT_ALLOWED),
        (ResultStatus.TIMEOUT, ErrorCode.DEADLINE_EXCEEDED),
        (ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE),
        (ResultStatus.DISCONNECTED, ErrorCode.DEVICE_DISCONNECTED),
    ),
)
def test_fake_backend_returns_stable_errors_without_events(
    status: ResultStatus,
    error_code: ErrorCode,
) -> None:
    backend = FakeBackend(
        events=all_input_events(),
        outcomes={Operation.OBSERVE_INPUTS: status},
    )

    result = backend.execute(
        AdapterCommand(Operation.OBSERVE_INPUTS),
        make_manifest(Stage.G3_INPUT),
    )

    assert result.status is status
    assert result.error_code is error_code
    assert result.events == ()


def test_fake_backend_copies_outcomes_on_construction() -> None:
    outcomes: MutableMapping[Operation, ResultStatus] = {}
    backend = FakeBackend(outcomes=outcomes)
    outcomes[Operation.INITIALIZE] = ResultStatus.BACKEND_ERROR

    result = backend.execute(
        AdapterCommand(Operation.INITIALIZE),
        make_manifest(Stage.G4_INITIALIZATION),
    )

    assert result.succeeded is True
