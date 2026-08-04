"""Private transactional capability gate and stateless helper policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import NoReturn

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    CapabilitySnapshot,
    CommandSpec,
    DeviceProfile,
    ErrorCode,
    HidInterface,
    InputSessionResult,
    InterfaceRoleResolution,
    Operation,
    OperationResult,
    RecoveryStatus,
    ResultStatus,
    RoleResolutionStatus,
    Stage,
    StageManifest,
    StagePhase,
    StageSessionSnapshot,
)

_TRANSITIONS: Mapping[Stage, tuple[AdapterState, AdapterState]] = MappingProxyType(
    {
        Stage.G1_PROFILE: (AdapterState.CANDIDATE, AdapterState.PROFILE_APPROVED),
        Stage.G2_PERMISSION: (AdapterState.PROFILE_APPROVED, AdapterState.PROFILE_APPROVED),
        Stage.G3_INPUT: (AdapterState.PROFILE_APPROVED, AdapterState.INPUT_VALIDATED),
        Stage.G4_INITIALIZATION: (
            AdapterState.INPUT_VALIDATED,
            AdapterState.INITIALIZATION_VALIDATED,
        ),
        Stage.G5_BRIGHTNESS: (
            AdapterState.INITIALIZATION_VALIDATED,
            AdapterState.BRIGHTNESS_VALIDATED,
        ),
        Stage.G6_ONE_LCD: (AdapterState.BRIGHTNESS_VALIDATED, AdapterState.ONE_LCD_VALIDATED),
        Stage.G7_SIX_LCD: (AdapterState.ONE_LCD_VALIDATED, AdapterState.SIX_LCD_VALIDATED),
    }
)

_STAGE_OPERATIONS: Mapping[Stage, frozenset[Operation]] = MappingProxyType(
    {
        Stage.G1_PROFILE: frozenset({Operation.APPROVE_PROFILE}),
        Stage.G2_PERMISSION: frozenset({Operation.RECORD_PERMISSION}),
        Stage.G3_INPUT: frozenset({Operation.OBSERVE_INPUTS}),
        Stage.G4_INITIALIZATION: frozenset({Operation.INITIALIZE}),
        Stage.G5_BRIGHTNESS: frozenset({Operation.SET_BRIGHTNESS}),
        Stage.G6_ONE_LCD: frozenset({Operation.SET_KEY_IMAGE}),
        Stage.G7_SIX_LCD: frozenset({Operation.SET_KEY_IMAGE}),
    }
)

_REQUIRED_OPERATION: Mapping[Stage, Operation] = MappingProxyType(
    {
        Stage.G1_PROFILE: Operation.APPROVE_PROFILE,
        Stage.G2_PERMISSION: Operation.RECORD_PERMISSION,
        Stage.G3_INPUT: Operation.OBSERVE_INPUTS,
        Stage.G4_INITIALIZATION: Operation.INITIALIZE,
        Stage.G5_BRIGHTNESS: Operation.SET_BRIGHTNESS,
        Stage.G6_ONE_LCD: Operation.SET_KEY_IMAGE,
        Stage.G7_SIX_LCD: Operation.SET_KEY_IMAGE,
    }
)

_TERMINAL_STATES = frozenset({AdapterState.BLOCKED, AdapterState.DISCONNECTED})


class GateViolation(Exception):
    """A stable fail-closed classification from a gate or helper policy."""

    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class _Reservation:
    epoch: int
    phase: StagePhase
    step_index: int
    command: CommandSpec


@dataclass(frozen=True, slots=True)
class _TransitionPreview:
    epoch: int
    stage: Stage
    next_state: AdapterState
    recovery_status: RecoveryStatus


class _CapabilityGate:
    """Own ordered reservations, results, recovery, and capability commits."""

    def __init__(self) -> None:
        self._state = AdapterState.CANDIDATE
        self._epoch = 0
        self._profile_digest: str | None = None
        self._bcd_device: int | None = None
        self._interface: HidInterface | None = None
        self._pinned_commit: str | None = None
        self._approved_roles: InterfaceRoleResolution | None = None
        self._session_profile_bcd_device: int | None = None
        self._manifest: StageManifest | None = None
        self._phase: StagePhase | None = None
        self._forward_index = 0
        self._recovery: list[tuple[int, CommandSpec]] = []
        self._pending: _Reservation | None = None
        self._had_recovery = False
        self._recovery_machine_status = RecoveryStatus.NOT_REQUIRED
        self._committing = False
        self._session_result: InputSessionResult | None = None

    @property
    def state(self) -> AdapterState:
        return self._state

    @property
    def approved_roles(self) -> InterfaceRoleResolution | None:
        return self._approved_roles

    @property
    def session_result(self) -> InputSessionResult | None:
        return self._session_result

    @property
    def capability_snapshot(self) -> CapabilitySnapshot:
        return CapabilitySnapshot(
            self._state,
            self._profile_digest,
            self._bcd_device,
            self._interface,
            self._epoch,
            self._manifest.stage if self._manifest is not None else None,
            self._phase,
        )

    @property
    def session_snapshot(self) -> StageSessionSnapshot | None:
        if self._manifest is None or self._phase is None:
            return None
        return StageSessionSnapshot(
            self._manifest.stage,
            self._phase,
            self._forward_index,
            len(self._recovery),
            self._pending is not None,
        )

    @property
    def active_manifest(self) -> StageManifest:
        return self._require_manifest()

    def begin(
        self,
        profile: DeviceProfile,
        manifest: StageManifest,
        current_commit: str,
    ) -> None:
        if not isinstance(profile, DeviceProfile):
            raise TypeError("profile must be a DeviceProfile")
        if not isinstance(manifest, StageManifest):
            raise TypeError("manifest must be a StageManifest")
        if self._manifest is not None or self._state in _TERMINAL_STATES:
            self._violate(ErrorCode.STATE_NOT_ALLOWED)
        transition = _TRANSITIONS.get(manifest.stage)
        if transition is None or transition[0] is not self._state:
            self._violate(ErrorCode.STATE_NOT_ALLOWED)
        profile_digest = profile.digest()
        identity_matches = (
            manifest.commit == current_commit
            and manifest.profile_digest == profile_digest
            and manifest.interface == profile.interface
        )
        if self._profile_digest is None:
            if manifest.stage is not Stage.G1_PROFILE or not identity_matches:
                raise GateViolation(ErrorCode.MANIFEST_INVALID)
            role_resolution = manifest.role_resolution
            if role_resolution is None:
                raise GateViolation(ErrorCode.PROFILE_EVIDENCE_INCOMPLETE)
            if role_resolution.status is not RoleResolutionStatus.RESOLVED:
                raise GateViolation(ErrorCode.INTERFACE_AMBIGUITY)
        elif not (
            identity_matches
            and self._profile_digest == profile_digest
            and self._bcd_device == profile.bcd_device
            and self._interface == profile.interface
            and self._pinned_commit == current_commit
            and manifest.role_resolution == self._approved_roles
        ):
            self._block_and_clear()
            raise GateViolation(ErrorCode.PROFILE_MISMATCH)
        if manifest.stage is Stage.G2_PERMISSION:
            plan = manifest.permission_plan
            if plan is None or {
                artifact.subsystem for artifact in plan.artifacts
            } != {"input", "hidraw"}:
                self._block_and_clear()
                raise GateViolation(ErrorCode.PERMISSION_PLAN_INVALID)
        if manifest.stage is Stage.G3_INPUT:
            spec = manifest.session_spec
            if spec is None or not spec.key_map.entries:
                self._block_and_clear()
                raise GateViolation(ErrorCode.INPUT_SESSION_INVALID)
        allowed = _STAGE_OPERATIONS[manifest.stage]
        specs = tuple(
            spec
            for step in manifest.steps
            for spec in (step.forward, step.recovery)
            if spec is not None
        )
        if any(spec.operation not in allowed for spec in specs):
            raise GateViolation(ErrorCode.MANIFEST_INVALID)
        if not any(
            step.forward.operation is _REQUIRED_OPERATION[manifest.stage]
            for step in manifest.steps
        ):
            raise GateViolation(ErrorCode.MANIFEST_INVALID)
        self._epoch += 1
        self._manifest = manifest
        self._session_profile_bcd_device = profile.bcd_device
        self._phase = StagePhase.FORWARD
        self._forward_index = 0
        self._recovery = []
        self._pending = None
        self._had_recovery = False
        self._recovery_machine_status = RecoveryStatus.NOT_REQUIRED

    def reserve_forward(self, command: AdapterCommand) -> _Reservation:
        manifest = self._require_session(StagePhase.FORWARD)
        self._require_no_pending()
        if self._forward_index >= len(manifest.steps):
            self._violate(ErrorCode.ORDER_VIOLATION)
        expected = manifest.steps[self._forward_index].forward
        if not expected.matches(command):
            self._violate(ErrorCode.ORDER_VIOLATION)
        reservation = _Reservation(
            self._epoch,
            StagePhase.FORWARD,
            self._forward_index,
            CommandSpec.from_command(command),
        )
        self._pending = reservation
        return reservation

    def reserve_recovery(self, command: AdapterCommand) -> _Reservation:
        if self._phase is StagePhase.FORWARD and self._recovery:
            self._state = AdapterState.BLOCKED
            self._phase = StagePhase.RECOVERY
            self._epoch += 1
        self._require_session(StagePhase.RECOVERY)
        self._require_no_pending()
        if not self._recovery:
            self._violate(ErrorCode.RECOVERY_REQUIRED)
        step_index, expected = self._recovery[-1]
        if not expected.matches(command):
            self._violate(ErrorCode.ORDER_VIOLATION)
        reservation = _Reservation(
            self._epoch,
            StagePhase.RECOVERY,
            step_index,
            CommandSpec.from_command(command),
        )
        self._pending = reservation
        return reservation

    def settle(self, reservation: _Reservation, result: OperationResult) -> None:
        self._require_pending(reservation)
        if not isinstance(result, OperationResult):
            self._violate(ErrorCode.RESULT_MISSING)
        self._pending = None
        if result.status is ResultStatus.DISCONNECTED:
            self.disconnect()
            return
        if not result.succeeded:
            self._settle_machine_failure(reservation.phase)
            return
        if result.session is not None:
            if self._manifest is None or self._manifest.stage is not Stage.G3_INPUT:
                self._violate(ErrorCode.INPUT_SESSION_INVALID)
            self._session_result = result.session
        if reservation.phase is StagePhase.FORWARD:
            step = self._require_manifest().steps[reservation.step_index]
            self._forward_index += 1
            if step.recovery is not None:
                self._recovery.append((reservation.step_index, step.recovery))
                self._had_recovery = True
                self._recovery_machine_status = RecoveryStatus.SUCCEEDED
            if self._forward_index == len(self._require_manifest().steps):
                self._phase = StagePhase.RECOVERY if self._recovery else StagePhase.READY
            return
        self._recovery.pop()
        if not self._recovery:
            self._phase = StagePhase.READY

    def fail_evidence(self, reservation: _Reservation) -> None:
        self._require_pending(reservation)
        self._pending = None
        self._settle_machine_failure(reservation.phase)

    def block_reentrant(self) -> NoReturn:
        self._epoch += 1
        self._block_active_session()
        raise GateViolation(ErrorCode.STALE_RESERVATION)

    def preview_completion(
        self,
        manual_confirmation: bool,
        recovery_confirmation: bool | None,
    ) -> _TransitionPreview:
        if not isinstance(manual_confirmation, bool):
            raise GateViolation(ErrorCode.PARAMETER_NOT_ALLOWED)
        if recovery_confirmation is not None and not isinstance(recovery_confirmation, bool):
            raise GateViolation(ErrorCode.PARAMETER_NOT_ALLOWED)
        manifest = self._require_manifest()
        if self._pending is not None:
            raise GateViolation(ErrorCode.RESULT_MISSING)
        if self._phase is StagePhase.FORWARD:
            raise GateViolation(ErrorCode.RESULT_MISSING)
        if self._phase is StagePhase.RECOVERY:
            raise GateViolation(ErrorCode.RECOVERY_REQUIRED)
        if self._phase is not StagePhase.READY:
            raise GateViolation(ErrorCode.STATE_NOT_ALLOWED)
        if not self._had_recovery:
            if recovery_confirmation is not None:
                raise GateViolation(ErrorCode.PARAMETER_NOT_ALLOWED)
            recovery_status = RecoveryStatus.NOT_REQUIRED
        elif self._recovery_machine_status is RecoveryStatus.FAILED:
            recovery_status = RecoveryStatus.FAILED
        elif recovery_confirmation is True:
            recovery_status = RecoveryStatus.SUCCEEDED
        elif recovery_confirmation is False:
            recovery_status = RecoveryStatus.FAILED
        else:
            recovery_status = RecoveryStatus.UNKNOWN
        can_advance = (
            self._state is not AdapterState.BLOCKED
            and manual_confirmation
            and recovery_status in (RecoveryStatus.NOT_REQUIRED, RecoveryStatus.SUCCEEDED)
        )
        if manifest.stage is Stage.G3_INPUT:
            spec = manifest.session_spec
            session = self._session_result
            if (
                spec is None
                or session is None
                or not session.meets_requirements(spec)
            ):
                can_advance = False
        next_state = _TRANSITIONS[manifest.stage][1] if can_advance else AdapterState.BLOCKED
        return _TransitionPreview(self._epoch, manifest.stage, next_state, recovery_status)

    def commit(
        self,
        preview: _TransitionPreview,
        evidence_callback: Callable[[], None],
    ) -> AdapterState:
        if not isinstance(preview, _TransitionPreview):
            self._violate(ErrorCode.STALE_RESERVATION)
        if self._committing or preview.epoch != self._epoch:
            self._violate(ErrorCode.STALE_RESERVATION)
        manifest = self._require_manifest()
        if preview.stage is not manifest.stage or self._phase is not StagePhase.READY:
            self._violate(ErrorCode.STALE_RESERVATION)
        state_before_callback = self._state
        self._committing = True
        try:
            evidence_callback()
        except Exception:
            self._committing = False
            if preview.epoch != self._epoch:
                self._block_and_clear()
                raise GateViolation(ErrorCode.STALE_RESERVATION) from None
            self._block_and_clear()
            raise GateViolation(ErrorCode.EVIDENCE_FAILURE) from None
        self._committing = False
        if preview.epoch != self._epoch or self._state is not state_before_callback:
            self._violate(ErrorCode.STALE_RESERVATION)
        if manifest.stage is Stage.G1_PROFILE and preview.next_state is AdapterState.PROFILE_APPROVED:
            self._profile_digest = manifest.profile_digest
            self._bcd_device = self._session_profile_bcd_device
            self._interface = manifest.interface
            self._pinned_commit = manifest.commit
            self._approved_roles = manifest.role_resolution
        self._state = preview.next_state
        self._clear_session()
        self._epoch += 1
        return self._state

    def disconnect(self) -> AdapterState:
        self._state = AdapterState.DISCONNECTED
        self._clear_session()
        self._epoch += 1
        return self._state

    def _require_manifest(self) -> StageManifest:
        if self._manifest is None:
            raise GateViolation(ErrorCode.STATE_NOT_ALLOWED)
        return self._manifest

    def _require_session(self, phase: StagePhase) -> StageManifest:
        manifest = self._require_manifest()
        if self._phase is not phase:
            self._violate(ErrorCode.ORDER_VIOLATION)
        return manifest

    def _require_no_pending(self) -> None:
        if self._pending is not None:
            self._violate(ErrorCode.RESULT_MISSING)

    def _require_pending(self, reservation: _Reservation) -> None:
        if not isinstance(reservation, _Reservation) or reservation is not self._pending:
            self._violate(ErrorCode.STALE_RESERVATION)
        if reservation.epoch != self._epoch or reservation.phase is not self._phase:
            self._violate(ErrorCode.STALE_RESERVATION)

    def _settle_machine_failure(self, phase: StagePhase) -> None:
        self._state = AdapterState.BLOCKED
        self._epoch += 1
        if phase is StagePhase.FORWARD and self._recovery:
            self._phase = StagePhase.RECOVERY
            return
        if phase is StagePhase.RECOVERY:
            self._recovery_machine_status = RecoveryStatus.FAILED
            self._recovery = []
            self._phase = StagePhase.READY
            return
        self._clear_session()

    def _violate(self, code: ErrorCode) -> NoReturn:
        if self._manifest is not None:
            self._epoch += 1
            self._block_active_session()
        raise GateViolation(code)

    def _block_active_session(self) -> None:
        self._state = AdapterState.BLOCKED
        self._pending = None
        if self._recovery:
            self._phase = StagePhase.RECOVERY
        elif self._phase is not StagePhase.READY:
            self._clear_session()

    def _block_and_clear(self) -> None:
        self._state = AdapterState.BLOCKED
        self._clear_session()
        self._epoch += 1

    def _clear_session(self) -> None:
        self._manifest = None
        self._session_profile_bcd_device = None
        self._phase = None
        self._forward_index = 0
        self._recovery = []
        self._pending = None
        self._had_recovery = False
        self._recovery_machine_status = RecoveryStatus.NOT_REQUIRED
        self._committing = False
        self._session_result = None


class CommandPolicy:
    """Validate one helper command without owning or advancing state."""

    @staticmethod
    def validate(
        profile: DeviceProfile,
        capability: CapabilitySnapshot,
        manifest: StageManifest,
        step_index: int,
        command: AdapterCommand,
    ) -> None:
        if manifest.commit != profile.source_commit:
            raise GateViolation(ErrorCode.PROFILE_MISMATCH)
        profile_digest = profile.digest()
        if manifest.profile_digest != profile_digest or manifest.interface != profile.interface:
            raise GateViolation(ErrorCode.PROFILE_MISMATCH)
        if capability.state is AdapterState.CANDIDATE or manifest.stage is Stage.G1_PROFILE:
            if any(
                value is not None
                for value in (
                    capability.profile_digest,
                    capability.bcd_device,
                    capability.interface,
                )
            ):
                raise GateViolation(ErrorCode.PROFILE_MISMATCH)
        elif not (
            capability.profile_digest == profile_digest
            and capability.bcd_device == profile.bcd_device
            and capability.interface == profile.interface
        ):
            raise GateViolation(ErrorCode.PROFILE_MISMATCH)
        transition = _TRANSITIONS.get(manifest.stage)
        if transition is None or capability.state is not transition[0]:
            raise GateViolation(ErrorCode.STATE_NOT_ALLOWED)
        if capability.stage is not manifest.stage or capability.phase not in (
            StagePhase.FORWARD,
            StagePhase.RECOVERY,
        ):
            raise GateViolation(ErrorCode.ORDER_VIOLATION)
        if isinstance(step_index, bool) or not isinstance(step_index, int):
            raise GateViolation(ErrorCode.ORDER_VIOLATION)
        if not 0 <= step_index < len(manifest.steps):
            raise GateViolation(ErrorCode.ORDER_VIOLATION)
        step = manifest.steps[step_index]
        expected = step.forward if capability.phase is StagePhase.FORWARD else step.recovery
        if expected is None or not expected.matches(command):
            raise GateViolation(ErrorCode.ORDER_VIOLATION)
