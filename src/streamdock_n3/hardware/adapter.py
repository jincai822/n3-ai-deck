"""Explicit, in-memory orchestration for staged N3 validation."""

from __future__ import annotations

from typing import Protocol

from streamdock_n3.hardware.backend import Backend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    DeviceProfile,
    ErrorCode,
    OperationResult,
    RecoveryStatus,
    ResultStatus,
    StageManifest,
)
from streamdock_n3.hardware.gate import CapabilityGate


class EvidenceSink(Protocol):
    """Receives only validated contract data from an adapter session."""

    def record_operation(
        self,
        profile: DeviceProfile,
        manifest: StageManifest,
        command: AdapterCommand,
        result: OperationResult,
    ) -> None:
        raise NotImplementedError

    def record_stage(
        self,
        profile: DeviceProfile,
        manifest: StageManifest,
        state: AdapterState,
        recovery_status: RecoveryStatus,
    ) -> None:
        raise NotImplementedError


class N3Adapter:
    """Authorize explicit backend commands and advance only through the capability gate."""

    def __init__(
        self,
        profile: DeviceProfile,
        current_commit: str,
        backend: Backend,
        initial_state: AdapterState = AdapterState.CANDIDATE,
        evidence: EvidenceSink | None = None,
    ) -> None:
        self.profile = profile
        self.current_commit = current_commit
        self.backend = backend
        self.evidence = evidence
        self._gate = CapabilityGate(initial_state)

    @property
    def gate(self) -> CapabilityGate:
        """Return the adapter-owned gate without allowing reference replacement."""
        return self._gate

    @property
    def state(self) -> AdapterState:
        """Return the gate's current capability state."""
        return self.gate.state

    def begin_stage(self, manifest: StageManifest) -> None:
        """Begin one manifest-authorized stage without doing backend work."""
        self.gate.begin(self.profile, manifest, self.current_commit)

    def execute(self, command: AdapterCommand) -> OperationResult:
        """Run one pre-authorized command exactly once and record its normalized result."""
        self.gate.authorize(command)
        manifest = self._active_manifest()
        try:
            result = self.backend.execute(command, manifest)
        except Exception:
            result = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)
        if not isinstance(result, OperationResult):
            result = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)
        self.gate.record_result(result)
        if self.evidence is not None:
            self.evidence.record_operation(self.profile, manifest, command, result)
        return result

    def complete_stage(
        self,
        manual_confirmation: bool,
        recovery_status: RecoveryStatus = RecoveryStatus.NOT_REQUIRED,
    ) -> AdapterState:
        """Complete the active stage after explicit manual confirmation."""
        session = self.gate.session
        if session is None:
            return self.gate.complete(manual_confirmation)
        manifest = session.manifest
        state = self.gate.complete(manual_confirmation)
        if self.evidence is not None:
            self.evidence.record_stage(self.profile, manifest, state, recovery_status)
        return state

    def disconnect(self) -> AdapterState:
        """Disconnect the gate without issuing a backend close command."""
        return self.gate.disconnect()

    def _active_manifest(self) -> StageManifest:
        session = self.gate.session
        if session is None:
            raise AssertionError("authorized command has no active stage")
        return session.manifest
