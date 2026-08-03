from __future__ import annotations

from streamdock_n3.hardware.backend import Backend, FakeBackend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    ErrorCode,
    InputAction,
    InputKind,
    NormalizedInputEvent,
    Operation,
    OperationResult,
    ResultStatus,
    Stage,
)
from tests.hardware_fixtures import TEST_IMAGE, make_manifest


def all_input_events() -> tuple[NormalizedInputEvent, ...]:
    return (
        NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 1),
        NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.RELEASE, 2),
        NormalizedInputEvent(InputKind.KNOB_PRESS, 1, InputAction.PRESS, 3),
        NormalizedInputEvent(InputKind.KNOB_ROTATE, 1, InputAction.RIGHT, 4),
    )


def success() -> OperationResult:
    return OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0)


def backend_failure() -> OperationResult:
    return OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)


def test_fake_backend_returns_injected_normalized_events() -> None:
    backend = FakeBackend(events=all_input_events())
    result = backend.execute(
        AdapterCommand(Operation.OBSERVE_INPUTS),
        make_manifest(Stage.G3_INPUT),
    )

    assert isinstance(backend, Backend)
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


def test_scripted_results_are_consumed_once_in_exact_call_order() -> None:
    timeout = OperationResult(ResultStatus.TIMEOUT, ErrorCode.DEADLINE_EXCEEDED, 4)
    backend = FakeBackend(scripted_results=(timeout, backend_failure()))

    first = backend.execute(
        AdapterCommand(Operation.APPROVE_PROFILE), make_manifest(Stage.G1_PROFILE)
    )
    second = backend.execute(
        AdapterCommand(Operation.APPROVE_PROFILE), make_manifest(Stage.G1_PROFILE)
    )
    third = backend.execute(
        AdapterCommand(Operation.APPROVE_PROFILE), make_manifest(Stage.G1_PROFILE)
    )

    assert (first, second, third) == (timeout, backend_failure(), success())
    assert len(backend.calls) == 3


def test_fake_backend_copies_constructor_inputs() -> None:
    events = [NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 1)]
    results = [backend_failure()]
    backend = FakeBackend(
        events=tuple(events),
        scripted_results=tuple(results),
    )
    events.clear()
    results.clear()

    assert (
        backend.execute(
            AdapterCommand(Operation.OBSERVE_INPUTS), make_manifest(Stage.G3_INPUT)
        )
        == backend_failure()
    )
    assert len(backend.calls) == 1


def test_backend_call_factory_copies_only_safe_scalar_metadata() -> None:
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE)
    backend = FakeBackend()

    backend.execute(command, make_manifest(Stage.G6_ONE_LCD))

    assert backend.calls == [type(backend.calls[0]).from_command(command)]
