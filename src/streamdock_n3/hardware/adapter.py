"""Sole public coordinator for in-process transactional G0 validation."""

from __future__ import annotations

from dataclasses import dataclass

from streamdock_n3.hardware.backend import Backend
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    CapabilitySnapshot,
    DeviceProfile,
    ErrorCode,
    HidInterface,
    OperationResult,
    ResultStatus,
    Stage,
    StageManifest,
    StageSessionSnapshot,
)
from streamdock_n3.hardware.evidence import (
    EvidenceRecord,
    EvidenceRecorder,
    EvidenceSink,
    operation_evidence,
    profile_approval_evidence,
    stage_evidence,
)
from streamdock_n3.hardware.gate import GateViolation, _CapabilityGate


@dataclass(frozen=True, slots=True)
class ApprovedProfile:
    """Redacted approved profile view bound by the G1 commit."""

    profile_digest: str
    bcd_device: int
    input_interface: HidInterface
    control_interface: HidInterface
    role_resolution_digest: str
    approval_reference: str
    pinned_commit: str

    def __post_init__(self) -> None:
        if not isinstance(self.profile_digest, str) or len(self.profile_digest) != 64:
            raise ValueError("profile_digest must be a 64-hex digest")
        if isinstance(self.bcd_device, bool) or not isinstance(self.bcd_device, int):
            raise ValueError("bcd_device must be an int")
        if not isinstance(self.input_interface, HidInterface):
            raise TypeError("input_interface must be a HidInterface")
        if not isinstance(self.control_interface, HidInterface):
            raise TypeError("control_interface must be a HidInterface")
        if not isinstance(self.role_resolution_digest, str) or len(
            self.role_resolution_digest
        ) != 64:
            raise ValueError("role_resolution_digest must be a 64-hex digest")
        if not isinstance(self.approval_reference, str) or not self.approval_reference:
            raise ValueError("approval_reference must be a non-empty string")
        if not isinstance(self.pinned_commit, str) or not self.pinned_commit:
            raise ValueError("pinned_commit must be a non-empty string")


class N3Adapter:
    """Coordinate one backend attempt, evidence transaction, and gate settlement."""

    __slots__ = (
        "_profile",
        "_current_commit",
        "_backend",
        "_gate",
        "_evidence",
        "_external_evidence",
        "_approved_profile",
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
        self._approved_profile: ApprovedProfile | None = None
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

    @property
    def approved_profile(self) -> ApprovedProfile | None:
        return self._approved_profile

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
            manifest = self._gate.active_manifest
            preview = self._gate.preview_completion(
                manual_confirmation,
                recovery_confirmation,
            )
            if (
                manifest.stage is Stage.G1_PROFILE
                and preview.next_state is AdapterState.PROFILE_APPROVED
            ):
                record = profile_approval_evidence(self._profile, manifest, preview.epoch)
            else:
                record = stage_evidence(
                    self._profile,
                    manifest,
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
            if state is AdapterState.PROFILE_APPROVED:
                resolution = manifest.role_resolution
                if resolution is None:
                    raise GateViolation(ErrorCode.PROFILE_EVIDENCE_INCOMPLETE)
                input_interface = resolution.input_interface
                control_interface = resolution.control_interface
                if input_interface is None or control_interface is None:
                    raise GateViolation(ErrorCode.INTERFACE_AMBIGUITY)
                self._approved_profile = ApprovedProfile(
                    profile_digest=manifest.profile_digest,
                    bcd_device=self._profile.bcd_device,
                    input_interface=input_interface,
                    control_interface=control_interface,
                    role_resolution_digest=resolution.digest(),
                    approval_reference=manifest.approval_reference,
                    pinned_commit=manifest.commit,
                )
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
        callback_epoch = self._gate.capability_snapshot.epoch
        try:
            if self._external_evidence is not None:
                self._external_evidence.record(record)
        except Exception:
            reentrant = self._gate.capability_snapshot.epoch != callback_epoch
            evidence_error = (
                ErrorCode.STALE_RESERVATION if reentrant else ErrorCode.EVIDENCE_FAILURE
            )
            self._evidence.fail(token, evidence_error)
            if result.status is ResultStatus.DISCONNECTED:
                self._gate.disconnect()
                if reentrant:
                    raise GateViolation(ErrorCode.STALE_RESERVATION) from None
                return result
            if reentrant:
                raise GateViolation(ErrorCode.STALE_RESERVATION) from None
            self._gate.fail_evidence(reservation)
            return OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.EVIDENCE_FAILURE, 0)
        if self._gate.capability_snapshot.epoch != callback_epoch:
            self._evidence.fail(token, ErrorCode.STALE_RESERVATION)
            if result.status is ResultStatus.DISCONNECTED:
                self._gate.disconnect()
            raise GateViolation(ErrorCode.STALE_RESERVATION)
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
