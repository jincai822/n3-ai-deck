"""Vendor-channel command backend for the validated G4-G6 display writes.

Translates AdapterCommand INITIALIZE/SET_BRIGHTNESS/SET_KEY_IMAGE into the
exact unnumbered vendor HID output reports validated on 2026-08-05. Only the
four validated commands (DIS/LIG/STP/BAT) can ever be written; image bytes are
size-capped and digest-checked against the manifest CommandSpec before any
write. The byte-level transport is injectable so tests never touch real nodes.
"""

from __future__ import annotations

import contextlib
import os
import select
import time
from typing import Protocol

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    ErrorCode,
    InterfaceRole,
    Operation,
    OperationResult,
    ResultStatus,
    RoleBasis,
    RoleResolutionStatus,
    StageManifest,
)
from streamdock_n3.hardware.ipc import is_vendor_hid_node

REPORT_PAYLOAD_BYTES = 1024
REPORT_FRAME_BYTES = REPORT_PAYLOAD_BYTES + 1
VENDOR_COMMAND_OPERATIONS = frozenset(
    {Operation.INITIALIZE, Operation.SET_BRIGHTNESS, Operation.SET_KEY_IMAGE}
)

_DIS = b"CRT\x00\x00DIS"
_LIG = b"CRT\x00\x00LIG"
_STP = b"CRT\x00\x00STP"
_BAT = b"CRT\x00\x00BAT"
_ALLOWED_COMMANDS = frozenset({_DIS, _LIG, _STP, _BAT})
_INITIAL_BRIGHTNESS = 50
_ACK_REPORT_BYTES = 512
_MAX_ACK_DRAIN = 64


def manifest_uses_vendor_channel(manifest: StageManifest) -> bool:
    """Return True when the approved role resolution marks a vendor-HID control interface."""
    if not isinstance(manifest, StageManifest):
        raise TypeError("manifest must be a StageManifest")
    resolution = manifest.role_resolution
    if resolution is None or resolution.status is not RoleResolutionStatus.RESOLVED:
        return False
    control_interface = resolution.control_interface
    if control_interface is None:
        return False
    return any(
        role.role is InterfaceRole.CONTROL
        and role.interface == control_interface
        and RoleBasis.VENDOR_HID in role.basis
        for role in resolution.roles
    )


class VendorHidTransport(Protocol):
    """Byte-level hidraw transport; injectable so tests never touch real nodes."""

    def open_read_write(self, node: str) -> int:
        """Open exactly one node O_RDWR and return its descriptor."""
        ...

    def write(self, fd: int, frame: bytes) -> None:
        """Write one complete output report frame."""
        ...

    def drain_acks(self, fd: int) -> int:
        """Discard pending write-ACK input reports; return how many were drained."""
        ...

    def close(self, fd: int) -> None:
        ...


class _HidrawTransport:
    """Real transport: one O_RDWR open, full writes, non-blocking ACK drain."""

    def open_read_write(self, node: str) -> int:
        if not isinstance(node, str) or not node:
            raise ValueError("device node must be a non-empty path")
        return os.open(node, os.O_RDWR)

    def write(self, fd: int, frame: bytes) -> None:
        view = memoryview(frame)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("hidraw write returned no progress")
            view = view[written:]

    def drain_acks(self, fd: int) -> int:
        drained = 0
        while drained < _MAX_ACK_DRAIN:
            readable, _, _ = select.select((fd,), (), (), 0)
            if not readable:
                break
            report = os.read(fd, _ACK_REPORT_BYTES)
            if not report:
                raise OSError("hidraw node returned no data")
            drained += 1
        return drained

    def close(self, fd: int) -> None:
        with contextlib.suppress(OSError):
            os.close(fd)


def _frame(payload: bytes) -> bytes:
    """Build one unnumbered output report: leading report id + zero-padded payload."""
    if len(payload) > REPORT_PAYLOAD_BYTES:
        raise ValueError("payload exceeds one output report")
    return b"\x00" + payload + bytes(REPORT_PAYLOAD_BYTES - len(payload))


def _command_frame(command_tag: bytes, parameters: bytes = b"") -> bytes:
    """Build a command report; only the validated DIS/LIG/STP/BAT tags are writable."""
    if command_tag not in _ALLOWED_COMMANDS:
        raise ValueError("unvalidated vendor command")
    return _frame(command_tag + parameters)


def _frames_for_command(command: AdapterCommand) -> tuple[bytes, ...]:
    if command.operation is Operation.INITIALIZE:
        return (
            _command_frame(_DIS),
            _command_frame(_LIG, b"\x00\x00" + bytes((_INITIAL_BRIGHTNESS,))),
            _command_frame(_STP),
        )
    if command.operation is Operation.SET_BRIGHTNESS:
        brightness = command.brightness
        if brightness is None:
            raise ValueError("set_brightness requires brightness")
        return (_command_frame(_LIG, b"\x00\x00" + bytes((brightness,))),)
    image = command.image
    key = command.key
    if image is None or key is None:
        raise ValueError("set_key_image requires key and image")
    header = len(image).to_bytes(4, "big") + bytes((key,))
    frames = [_command_frame(_BAT, header)]
    for offset in range(0, len(image), REPORT_PAYLOAD_BYTES):
        frames.append(_frame(image[offset : offset + REPORT_PAYLOAD_BYTES]))
    frames.append(_command_frame(_STP))
    return tuple(frames)


def _rejected(code: ErrorCode) -> OperationResult:
    return OperationResult(ResultStatus.REJECTED, code, 0)


def _backend_failure(started_ns: int) -> OperationResult:
    duration_ms = int((time.monotonic_ns() - started_ns) / 1_000_000)
    return OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, duration_ms)


class VendorHidCommandBackend:
    """Execute validated vendor-channel commands; the node is open only per execute()."""

    def __init__(self, node: str, transport: VendorHidTransport | None = None) -> None:
        if not isinstance(node, str):
            raise TypeError("node must be a string")
        self._node = node
        self._transport = transport if transport is not None else _HidrawTransport()

    def execute(self, command: AdapterCommand, manifest: StageManifest) -> OperationResult:
        if not isinstance(command, AdapterCommand):
            raise TypeError("command must be an AdapterCommand")
        if not isinstance(manifest, StageManifest):
            raise TypeError("manifest must be a StageManifest")
        if command.operation not in VENDOR_COMMAND_OPERATIONS:
            return _rejected(ErrorCode.OPERATION_NOT_ALLOWED)
        if not is_vendor_hid_node(self._node):
            return _rejected(ErrorCode.PARAMETER_NOT_ALLOWED)
        if not manifest_uses_vendor_channel(manifest):
            return _rejected(ErrorCode.MANIFEST_INVALID)
        specs = (
            spec
            for step in manifest.steps
            for spec in (step.forward, step.recovery)
            if spec is not None
        )
        if not any(spec.matches(command) for spec in specs):
            return _rejected(ErrorCode.PARAMETER_NOT_ALLOWED)
        frames = _frames_for_command(command)
        started_ns = time.monotonic_ns()
        transport = self._transport
        try:
            fd = transport.open_read_write(self._node)
        except PermissionError:
            return OperationResult(
                ResultStatus.REJECTED,
                ErrorCode.PERMISSION_DENIED,
                int((time.monotonic_ns() - started_ns) / 1_000_000),
            )
        except OSError:
            return _backend_failure(started_ns)
        try:
            for frame in frames:
                transport.write(fd, frame)
                transport.drain_acks(fd)
        except OSError:
            return _backend_failure(started_ns)
        finally:
            transport.close(fd)
        return OperationResult(
            ResultStatus.SUCCEEDED,
            ErrorCode.NONE,
            int((time.monotonic_ns() - started_ns) / 1_000_000),
        )
