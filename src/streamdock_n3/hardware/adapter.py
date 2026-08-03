"""Sole public coordinator for in-process transactional G0 validation."""

from __future__ import annotations

from streamdock_n3.hardware.backend import Backend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    CapabilitySnapshot,
    DeviceProfile,
    ErrorCode,
    OperationResult,
    ResultStatus,
    StageManifest,
    StageSessionSnapshot,
)
from streamdock_n3.hardware.evidence import (
    EvidenceRecord,
    EvidenceRecorder,
    EvidenceSink,
    operation_evidence,
    stage_evidence,
)
from streamdock_n3.hardware.gate import GateViolation, _CapabilityGate


class N3Adapter:
    """Coordinate one backend attempt, evidence transaction, and gate settlement."""

    __slots__ = (
        "_profile",
        "_current_commit",
        "_backend",
        "_gate",
        "_evidence",
        "_external_evidence",
        "_busy",
    )

    def __init__(
        self,
        profile: DeviceProfile,
        current_commit: str,
        backend: Backend,
        external_evidence: EvidenceSink | None = None,
    ) -> None:
        if not isinstance(profile, DeviceProfile):
            raise TypeError("profile must be a DeviceProfile")
        self._profile = profile
        self._current_commit = current_commit
        self._backend = backend
        self._gate = _CapabilityGate()
        self._evidence = EvidenceRecorder()
        self._external_evidence = external_evidence
        self._busy = False

    @property
    def state(self) -> AdapterState:
        return self._gate.state

    @property
    def profile(self) -> DeviceProfile:
        return self._profile

    @property
    def capability_snapshot(self) -> CapabilitySnapshot:
        return self._gate.capability_snapshot

    @property
    def session_snapshot(self) -> StageSessionSnapshot | None:
        return self._gate.session_snapshot

    @property
    def evidence_records(self) -> tuple[EvidenceRecord, ...]:
        return self._evidence.records

    def begin_stage(self, manifest: StageManifest) -> None:
        self._enter()
        try:
            self._gate.begin(self._profile, manifest, self._current_commit)
        finally:
            self._leave()

    def execute(self, command: AdapterCommand) -> OperationResult:
        self._enter()
        try:
            return self._execute(command, recovery=False)
        finally:
            self._leave()

    def recover(self, command: AdapterCommand) -> OperationResult:
        self._enter()
        try:
            return self._execute(command, recovery=True)
        finally:
            self._leave()

    def complete_stage(
        self,
        manual_confirmation: bool,
        recovery_confirmation: bool | None = None,
    ) -> AdapterState:
        self._enter()
        try:
            preview = self._gate.preview_completion(
                manual_confirmation,
                recovery_confirmation,
            )
            record = stage_evidence(
                self._profile,
                self._gate.active_manifest,
                preview.next_state,
                preview.recovery_status,
                preview.epoch,
            )
            token = self._evidence.begin(record)

            def write_external_evidence() -> None:
                if self._external_evidence is not None:
                    self._external_evidence.record(record)

            try:
                state = self._gate.commit(preview, write_external_evidence)
            except GateViolation as error:
                self._evidence.fail(token, error.code)
                raise
            except Exception:
                self._evidence.fail(token, ErrorCode.EVIDENCE_FAILURE)
                raise GateViolation(ErrorCode.EVIDENCE_FAILURE) from None
            else:
                self._evidence.commit(token)
            return state
        finally:
            self._leave()

    def disconnect(self) -> AdapterState:
        self._enter()
        try:
            return self._gate.disconnect()
        finally:
            self._leave()

    def _execute(self, command: AdapterCommand, recovery: bool) -> OperationResult:
        reservation = (
            self._gate.reserve_recovery(command)
            if recovery
            else self._gate.reserve_forward(command)
        )
        manifest = self._gate.active_manifest
        try:
            result = self._backend.execute(command, manifest)
        except Exception:
            result = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0)
        if not isinstance(result, OperationResult):
            result = OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.RESULT_MISSING, 0)
        record = operation_evidence(
            self._profile,
            manifest,
            command,
            result,
            self._gate.capability_snapshot.epoch,
        )
        token = self._evidence.begin(record)
        try:
            if self._external_evidence is not None:
                self._external_evidence.record(record)
        except Exception:
            self._evidence.fail(token, ErrorCode.EVIDENCE_FAILURE)
            self._gate.fail_evidence(reservation)
            return OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.EVIDENCE_FAILURE, 0)
        try:
            self._gate.settle(reservation, result)
        except GateViolation as error:
            self._evidence.fail(token, error.code)
            raise
        else:
            self._evidence.commit(token)
        return result

    def _enter(self) -> None:
        if self._busy:
            self._gate.block_reentrant()
        self._busy = True

    def _leave(self) -> None:
        self._busy = False
