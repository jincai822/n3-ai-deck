from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from streamdock_n3.hardware import helper_main
from streamdock_n3.hardware.backend import FakeBackend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    CapabilitySnapshot,
    ErrorCode,
    HidInterface,
    HidInterfaceRole,
    InterfaceRole,
    InterfaceRoleResolution,
    Operation,
    OperationResult,
    ResultStatus,
    RoleBasis,
    RoleResolutionStatus,
    Stage,
    StageManifest,
    StagePhase,
)
from streamdock_n3.hardware.gate import GateViolation
from streamdock_n3.hardware.ipc import (
    IpcSessionRequest,
    IpcSessionResponse,
    encode_session_request,
)
from streamdock_n3.hardware.vendor_backend import (
    REPORT_FRAME_BYTES,
    REPORT_PAYLOAD_BYTES,
    VendorHidCommandBackend,
    VendorHidTransport,
    manifest_uses_vendor_channel,
)
from tests.hardware_fixtures import (
    TEST_COMMIT,
    TEST_INTERFACE,
    command_step,
    make_manifest,
    make_profile,
    make_resolved_roles,
)

_DIS = b"CRT\x00\x00DIS"
_LIG = b"CRT\x00\x00LIG"
_STP = b"CRT\x00\x00STP"
_BAT = b"CRT\x00\x00BAT"

_VENDOR_NODE = "/dev/hidraw3"
_EVDEV_NODE = "/dev/input/event3"


def frame(payload: bytes) -> bytes:
    """Build the expected hidraw write: leading report id + zero-padded payload."""
    return b"\x00" + payload + bytes(REPORT_PAYLOAD_BYTES - len(payload))


def brightness_frame(level: int) -> bytes:
    return frame(_LIG + b"\x00\x00" + bytes((level,)))


def image_header(image: bytes, key: int) -> bytes:
    return _BAT + len(image).to_bytes(4, "big") + bytes((key,))


def image_frames(image: bytes, key: int) -> list[bytes]:
    frames = [frame(image_header(image, key))]
    for offset in range(0, len(image), REPORT_PAYLOAD_BYTES):
        frames.append(frame(image[offset : offset + REPORT_PAYLOAD_BYTES]))
    frames.append(frame(_STP))
    return frames


class ScriptedTransport:
    """Scripted fake transport; records every byte and never touches real nodes."""

    def __init__(
        self,
        *,
        open_error: OSError | None = None,
        write_error_at: int | None = None,
        ack_reports: tuple[bytes, ...] = (),
    ) -> None:
        self.open_error = open_error
        self.write_error_at = write_error_at
        self.ack_queue = list(ack_reports)
        self.open_calls: list[str] = []
        self.frames: list[bytes] = []
        self.drain_calls = 0
        self.close_calls = 0

    def open_read_write(self, node: str) -> int:
        self.open_calls.append(node)
        if self.open_error is not None:
            raise self.open_error
        return 997

    def write(self, fd: int, data: bytes) -> None:
        if self.write_error_at is not None and len(self.frames) == self.write_error_at:
            raise OSError("scripted write failure")
        self.frames.append(bytes(data))

    def drain_acks(self, fd: int) -> int:
        self.drain_calls += 1
        drained = len(self.ack_queue)
        self.ack_queue.clear()
        return drained

    def close(self, fd: int) -> None:
        self.close_calls += 1


def make_non_vendor_roles() -> InterfaceRoleResolution:
    input_interface = HidInterface(1, 3, 1, 1)
    control_interface = HidInterface(0, 3, 0, 0)
    return InterfaceRoleResolution(
        roles=(
            HidInterfaceRole(
                control_interface,
                InterfaceRole.CONTROL,
                (RoleBasis.NO_INPUT_ASSOCIATION,),
            ),
            HidInterfaceRole(input_interface, InterfaceRole.INPUT, (RoleBasis.BOOT_KEYBOARD,)),
        ),
        status=RoleResolutionStatus.RESOLVED,
        input_interface=input_interface,
        control_interface=control_interface,
    )


_UNSET = object()


def vendor_manifest(
    stage: Stage,
    command: AdapterCommand,
    *,
    recovery: AdapterCommand | None = None,
    role_resolution: InterfaceRoleResolution | None | object = _UNSET,
) -> StageManifest:
    return make_manifest(
        stage,
        steps=(command_step(command, recovery),),
        role_resolution=make_resolved_roles() if role_resolution is _UNSET else role_resolution,  # type: ignore[arg-type]
    )


def execute(
    command: AdapterCommand,
    manifest: StageManifest,
    transport: ScriptedTransport,
    node: str = _VENDOR_NODE,
):
    backend = VendorHidCommandBackend(node, transport)
    return backend.execute(command, manifest)


def test_manifest_marker_requires_vendor_hid_control_basis() -> None:
    assert manifest_uses_vendor_channel(vendor_manifest(Stage.G4_INITIALIZATION, AdapterCommand(Operation.INITIALIZE))) is True
    assert (
        manifest_uses_vendor_channel(
            vendor_manifest(
                Stage.G4_INITIALIZATION,
                AdapterCommand(Operation.INITIALIZE),
                role_resolution=make_non_vendor_roles(),
            )
        )
        is False
    )
    assert (
        manifest_uses_vendor_channel(
            vendor_manifest(
                Stage.G4_INITIALIZATION,
                AdapterCommand(Operation.INITIALIZE),
                role_resolution=None,
            )
        )
        is False
    )


def test_initialize_writes_exact_validated_trio() -> None:
    transport = ScriptedTransport()
    command = AdapterCommand(Operation.INITIALIZE)

    result = execute(command, vendor_manifest(Stage.G4_INITIALIZATION, command), transport)

    assert result.status is ResultStatus.SUCCEEDED
    assert result.error_code is ErrorCode.NONE
    assert transport.open_calls == [_VENDOR_NODE]
    assert transport.frames == [
        frame(_DIS),
        frame(_LIG + b"\x00\x00\x32"),
        frame(_STP),
    ]
    assert all(len(data) == REPORT_FRAME_BYTES for data in transport.frames)
    assert transport.drain_calls == 3
    assert transport.close_calls == 1


@pytest.mark.parametrize("level", (0, 1, 50, 99, 100))
def test_set_brightness_writes_exact_frame_including_boundaries(level: int) -> None:
    transport = ScriptedTransport()
    command = AdapterCommand(Operation.SET_BRIGHTNESS, brightness=level)

    result = execute(command, vendor_manifest(Stage.G5_BRIGHTNESS, command), transport)

    assert result.status is ResultStatus.SUCCEEDED
    assert transport.frames == [brightness_frame(level)]
    assert transport.drain_calls == 1
    assert transport.close_calls == 1


@pytest.mark.parametrize("key", (1, 6))
def test_set_key_image_writes_header_then_image_then_stop(key: int) -> None:
    image = bytes((index * 7) % 256 for index in range(300))
    transport = ScriptedTransport()
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=image)

    result = execute(command, vendor_manifest(Stage.G6_ONE_LCD, command), transport)

    assert result.status is ResultStatus.SUCCEEDED
    assert transport.frames == image_frames(image, key)
    assert transport.frames[0][1:14] == image_header(image, key)
    assert transport.frames[-1] == frame(_STP)
    assert transport.close_calls == 1


@pytest.mark.parametrize("size", (1023, 1024, 1025))
def test_set_key_image_chunks_payloads_at_report_boundary(size: int) -> None:
    image = bytes((index * 13) % 256 for index in range(size))
    transport = ScriptedTransport()
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=2, image=image)

    result = execute(command, vendor_manifest(Stage.G6_ONE_LCD, command), transport)

    assert result.status is ResultStatus.SUCCEEDED
    expected_chunk_count = 1 + (size > REPORT_PAYLOAD_BYTES)
    # one header report + chunk reports + one STP report
    assert len(transport.frames) == expected_chunk_count + 2
    assert transport.frames[0] == frame(image_header(image, 2))
    reassembled = b"".join(
        data[1 : 1 + min(REPORT_PAYLOAD_BYTES, size - index * REPORT_PAYLOAD_BYTES)]
        for index, data in enumerate(transport.frames[1:-1])
    )
    assert reassembled == image
    assert transport.frames[-1] == frame(_STP)
    assert all(len(data) == REPORT_FRAME_BYTES for data in transport.frames)


@pytest.mark.parametrize(
    "operation",
    (
        Operation.APPROVE_PROFILE,
        Operation.RECORD_PERMISSION,
        Operation.OBSERVE_INPUTS,
        Operation.CLOSE_SESSION,
    ),
)
def test_forbidden_operations_are_rejected_without_any_write(operation: Operation) -> None:
    transport = ScriptedTransport()
    command = AdapterCommand(operation)

    result = execute(
        command,
        vendor_manifest(Stage.G4_INITIALIZATION, AdapterCommand(Operation.INITIALIZE)),
        transport,
    )

    assert result.status is ResultStatus.REJECTED
    assert result.error_code is ErrorCode.OPERATION_NOT_ALLOWED
    assert transport.open_calls == []
    assert transport.frames == []
    assert transport.close_calls == 0


def test_digest_mismatch_is_rejected_before_any_write() -> None:
    transport = ScriptedTransport()
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"actual-image")
    manifest = vendor_manifest(
        Stage.G6_ONE_LCD,
        AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"manifest-image"),
    )

    result = execute(command, manifest, transport)

    assert result.status is ResultStatus.REJECTED
    assert result.error_code is ErrorCode.PARAMETER_NOT_ALLOWED
    assert transport.open_calls == []
    assert transport.frames == []


def test_key_mismatch_is_rejected_before_any_write() -> None:
    transport = ScriptedTransport()
    command = AdapterCommand(Operation.SET_KEY_IMAGE, key=2, image=b"same-image")
    manifest = vendor_manifest(
        Stage.G6_ONE_LCD,
        AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"same-image"),
    )

    result = execute(command, manifest, transport)

    assert result.status is ResultStatus.REJECTED
    assert result.error_code is ErrorCode.PARAMETER_NOT_ALLOWED
    assert transport.frames == []


def test_brightness_mismatch_is_rejected_before_any_write() -> None:
    transport = ScriptedTransport()
    command = AdapterCommand(Operation.SET_BRIGHTNESS, brightness=30)
    manifest = vendor_manifest(
        Stage.G5_BRIGHTNESS,
        AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),
    )

    result = execute(command, manifest, transport)

    assert result.status is ResultStatus.REJECTED
    assert result.error_code is ErrorCode.PARAMETER_NOT_ALLOWED
    assert transport.frames == []


@pytest.mark.parametrize("brightness", (-1, 101))
def test_brightness_out_of_range_is_rejected_by_construction(brightness: int) -> None:
    with pytest.raises(ValueError):
        AdapterCommand(Operation.SET_BRIGHTNESS, brightness=brightness)


@pytest.mark.parametrize("key", (0, 7))
def test_key_out_of_range_is_rejected_by_construction(key: int) -> None:
    with pytest.raises(ValueError):
        AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=b"x")


def test_non_vendor_manifest_is_rejected_without_any_write() -> None:
    transport = ScriptedTransport()
    command = AdapterCommand(Operation.INITIALIZE)
    manifest = vendor_manifest(
        Stage.G4_INITIALIZATION,
        command,
        role_resolution=make_non_vendor_roles(),
    )

    result = execute(command, manifest, transport)

    assert result.status is ResultStatus.REJECTED
    assert result.error_code is ErrorCode.MANIFEST_INVALID
    assert transport.open_calls == []
    assert transport.frames == []


@pytest.mark.parametrize("node", (_EVDEV_NODE, "/tmp/hidraw3", "hidraw3", ""))
def test_non_hidraw_node_is_rejected_without_any_write(node: str) -> None:
    transport = ScriptedTransport()
    command = AdapterCommand(Operation.INITIALIZE)

    result = execute(command, vendor_manifest(Stage.G4_INITIALIZATION, command), transport, node)

    assert result.status is ResultStatus.REJECTED
    assert result.error_code is ErrorCode.PARAMETER_NOT_ALLOWED
    assert transport.open_calls == []
    assert transport.frames == []


def test_open_permission_failure_maps_to_permission_denied() -> None:
    transport = ScriptedTransport(open_error=PermissionError("denied"))
    command = AdapterCommand(Operation.INITIALIZE)

    result = execute(command, vendor_manifest(Stage.G4_INITIALIZATION, command), transport)

    assert result.status is ResultStatus.REJECTED
    assert result.error_code is ErrorCode.PERMISSION_DENIED
    assert transport.frames == []
    assert transport.close_calls == 0


def test_open_transport_failure_maps_to_backend_failure() -> None:
    transport = ScriptedTransport(open_error=OSError("no such node"))
    command = AdapterCommand(Operation.INITIALIZE)

    result = execute(command, vendor_manifest(Stage.G4_INITIALIZATION, command), transport)

    assert result.status is ResultStatus.BACKEND_ERROR
    assert result.error_code is ErrorCode.BACKEND_FAILURE
    assert transport.close_calls == 0


def test_write_failure_maps_to_backend_failure_and_still_closes() -> None:
    transport = ScriptedTransport(write_error_at=1)
    command = AdapterCommand(Operation.INITIALIZE)

    result = execute(command, vendor_manifest(Stage.G4_INITIALIZATION, command), transport)

    assert result.status is ResultStatus.BACKEND_ERROR
    assert result.error_code is ErrorCode.BACKEND_FAILURE
    assert transport.frames == [frame(_DIS)]
    assert transport.close_calls == 1


def test_ack_reports_are_drained_and_discarded() -> None:
    ack = bytes(512)
    transport = ScriptedTransport(ack_reports=(ack, ack, ack))
    command = AdapterCommand(Operation.INITIALIZE)

    result = execute(command, vendor_manifest(Stage.G4_INITIALIZATION, command), transport)

    assert result.status is ResultStatus.SUCCEEDED
    assert transport.drain_calls == len(transport.frames) == 3
    assert transport.ack_queue == []


def test_backend_constructs_with_default_transport_without_io() -> None:
    backend = VendorHidCommandBackend(_VENDOR_NODE)

    assert isinstance(backend, VendorHidCommandBackend)


class RecordingCommandBackend:
    instances: list[RecordingCommandBackend] = []

    def __init__(self, node: str, transport: VendorHidTransport | None = None) -> None:
        del transport
        self.node = node
        self.commands: list[AdapterCommand] = []
        RecordingCommandBackend.instances.append(self)

    def execute(self, command: AdapterCommand, manifest: StageManifest) -> OperationResult:
        del manifest
        self.commands.append(command)
        return OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 3)


def make_g4_request(
    node: str = _VENDOR_NODE,
    *,
    role_resolution: InterfaceRoleResolution | None = None,
) -> IpcSessionRequest:
    profile = make_profile()
    return IpcSessionRequest(
        profile=profile,
        capability=CapabilitySnapshot(
            AdapterState.INPUT_VALIDATED,
            profile.digest(),
            profile.bcd_device,
            TEST_INTERFACE,
            7,
            Stage.G4_INITIALIZATION,
            StagePhase.FORWARD,
        ),
        manifest=vendor_manifest(
            Stage.G4_INITIALIZATION,
            AdapterCommand(Operation.INITIALIZE),
            role_resolution=role_resolution,
        )
        if role_resolution is not None
        else make_manifest(Stage.G4_INITIALIZATION, role_resolution=make_resolved_roles()),
        step_index=0,
        command=AdapterCommand(Operation.INITIALIZE),
        device_node=node,
    )


def test_helper_selects_vendor_backend_for_vendor_command_request() -> None:
    backend = helper_main._select_command_backend(make_g4_request())

    assert isinstance(backend, VendorHidCommandBackend)


def test_helper_command_selection_stays_fake_for_evdev_node() -> None:
    backend = helper_main._select_command_backend(make_g4_request(_EVDEV_NODE))

    assert isinstance(backend, FakeBackend)


def test_helper_command_selection_stays_fake_without_vendor_marker() -> None:
    backend = helper_main._select_command_backend(
        make_g4_request(role_resolution=make_non_vendor_roles())
    )

    assert isinstance(backend, FakeBackend)


def test_helper_command_selection_stays_fake_for_other_operations() -> None:
    profile = make_profile()
    request = IpcSessionRequest(
        profile=profile,
        capability=CapabilitySnapshot(
            AdapterState.CANDIDATE,
            None,
            None,
            None,
            1,
            Stage.G1_PROFILE,
            StagePhase.FORWARD,
        ),
        manifest=make_manifest(Stage.G1_PROFILE, role_resolution=make_resolved_roles()),
        step_index=0,
        command=AdapterCommand(Operation.APPROVE_PROFILE),
        device_node=_VENDOR_NODE,
    )

    backend = helper_main._select_command_backend(request)

    assert isinstance(backend, FakeBackend)


def feed_helper(request: IpcSessionRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    framed = (encode_session_request(request) + "\n").encode("utf-8")
    monkeypatch.setattr(helper_main.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(framed)))


def test_helper_runs_vendor_command_request_through_real_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingCommandBackend.instances = []
    monkeypatch.setattr(helper_main, "VendorHidCommandBackend", RecordingCommandBackend)
    feed_helper(make_g4_request(), monkeypatch)

    handled = helper_main._handle_request()

    assert isinstance(handled, IpcSessionResponse)
    assert handled.result.status is ResultStatus.SUCCEEDED
    assert handled.session is None
    assert len(RecordingCommandBackend.instances) == 1
    backend = RecordingCommandBackend.instances[0]
    assert backend.node == _VENDOR_NODE
    assert backend.commands == [AdapterCommand(Operation.INITIALIZE)]


def test_helper_keeps_fake_backend_for_non_vendor_command_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingCommandBackend.instances = []
    monkeypatch.setattr(helper_main, "VendorHidCommandBackend", RecordingCommandBackend)
    feed_helper(make_g4_request(_EVDEV_NODE), monkeypatch)

    handled = helper_main._handle_request()

    assert isinstance(handled, IpcSessionResponse)
    assert handled.result.status is ResultStatus.SUCCEEDED
    assert RecordingCommandBackend.instances == []


def test_helper_rejects_vendor_command_request_with_stale_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = make_g4_request()
    stale = IpcSessionRequest(
        profile=request.profile,
        capability=CapabilitySnapshot(
            AdapterState.PROFILE_APPROVED,
            request.profile.digest(),
            request.profile.bcd_device,
            TEST_INTERFACE,
            7,
            Stage.G4_INITIALIZATION,
            StagePhase.FORWARD,
        ),
        manifest=request.manifest,
        step_index=0,
        command=request.command,
        device_node=request.device_node,
    )
    assert stale.profile.source_commit == TEST_COMMIT
    feed_helper(stale, monkeypatch)

    with pytest.raises(GateViolation):
        helper_main._handle_request()
