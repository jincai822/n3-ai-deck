"""Fail-closed, side-effect-free capability gate for staged hardware validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    DeviceProfile,
    ErrorCode,
    Operation,
    OperationResult,
    Stage,
    StageManifest,
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
        Stage.G3_INPUT: frozenset({Operation.OBSERVE_INPUTS, Operation.CLOSE_SESSION}),
        Stage.G4_INITIALIZATION: frozenset({Operation.INITIALIZE, Operation.CLOSE_SESSION}),
        Stage.G5_BRIGHTNESS: frozenset({Operation.SET_BRIGHTNESS, Operation.CLOSE_SESSION}),
        Stage.G6_ONE_LCD: frozenset({Operation.SET_KEY_IMAGE, Operation.CLOSE_SESSION}),
        Stage.G7_SIX_LCD: frozenset({Operation.SET_KEY_IMAGE, Operation.CLOSE_SESSION}),
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
    """A stable failure classification emitted by the capability gate."""

    def __init__(self, code: ErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class StageSession:
    """A read-only snapshot of the active manifest and authorization counts."""

    manifest: StageManifest
    call_counts: tuple[int, ...]


class CapabilityGate:
    """Advance a capability state only after a fully authorized stage completes."""

    __slots__ = ("_call_counts", "_manifest", "_state")

    def __init__(self, initial_state: AdapterState = AdapterState.CANDIDATE) -> None:
        if not isinstance(initial_state, AdapterState):
            raise TypeError("initial_state must be an AdapterState")
        self._state = initial_state
        self._manifest: StageManifest | None = None
        self._call_counts: list[int] | None = None

    @property
    def state(self) -> AdapterState:
        """Return the current capability state without exposing mutation."""
        return self._state

    @property
    def session(self) -> StageSession | None:
        """Return an immutable snapshot of the active stage, if any."""
        if self._manifest is None or self._call_counts is None:
            return None
        return StageSession(self._manifest, tuple(self._call_counts))

    def begin(self, profile: DeviceProfile, manifest: StageManifest, current_commit: str) -> None:
        """Open an authorized stage without changing its capability state."""
        if self._manifest is not None or self._call_counts is not None:
            raise GateViolation(ErrorCode.STATE_NOT_ALLOWED)
        if self._state in _TERMINAL_STATES:
            raise GateViolation(ErrorCode.STATE_NOT_ALLOWED)
        transition = _TRANSITIONS.get(manifest.stage)
        if transition is None:
            raise GateViolation(ErrorCode.MANIFEST_INVALID)
        expected_state, _next_state = transition
        if self._state is not expected_state:
            raise GateViolation(ErrorCode.STATE_NOT_ALLOWED)
        if manifest.commit != current_commit:
            raise GateViolation(ErrorCode.MANIFEST_INVALID)
        if manifest.profile_digest != profile.digest():
            raise GateViolation(ErrorCode.MANIFEST_INVALID)
        if manifest.interface != profile.interface:
            raise GateViolation(ErrorCode.MANIFEST_INVALID)
        if any(rule.operation not in _STAGE_OPERATIONS[manifest.stage] for rule in manifest.allowed_commands):
            raise GateViolation(ErrorCode.MANIFEST_INVALID)
        required_operation = _REQUIRED_OPERATION[manifest.stage]
        if not any(
            rule.operation is required_operation and rule.min_calls >= 1
            for rule in manifest.allowed_commands
        ):
            raise GateViolation(ErrorCode.MANIFEST_INVALID)
        self._manifest = manifest
        self._call_counts = [0] * len(manifest.allowed_commands)

    def authorize(self, command: AdapterCommand) -> None:
        """Authorize one exact command against the first matching rule with capacity."""
        manifest, call_counts = self._require_session()
        rules = manifest.allowed_commands
        if not any(rule.operation is command.operation for rule in rules):
            raise GateViolation(ErrorCode.OPERATION_NOT_ALLOWED)
        exact_match_found = False
        for index, rule in enumerate(rules):
            if not rule.matches(command):
                continue
            exact_match_found = True
            if call_counts[index] < rule.max_calls:
                call_counts[index] += 1
                return
        if exact_match_found:
            raise GateViolation(ErrorCode.CALL_LIMIT_EXCEEDED)
        raise GateViolation(ErrorCode.PARAMETER_NOT_ALLOWED)

    def record_result(self, result: OperationResult) -> None:
        """Record a backend result, blocking immediately on every non-success result."""
        self._require_session()
        if not result.succeeded:
            self._state = AdapterState.BLOCKED
            self._manifest = None
            self._call_counts = None

    def complete(self, manual_confirmation: bool) -> AdapterState:
        """Complete the active stage only after manual confirmation and required calls."""
        if not isinstance(manual_confirmation, bool):
            raise GateViolation(ErrorCode.PARAMETER_NOT_ALLOWED)
        manifest, call_counts = self._require_session()
        if not manual_confirmation:
            self._state = AdapterState.BLOCKED
            self._manifest = None
            self._call_counts = None
            return self._state
        if any(
            call_count < rule.min_calls
            for call_count, rule in zip(call_counts, manifest.allowed_commands, strict=True)
        ):
            raise GateViolation(ErrorCode.REQUIRED_CALL_MISSING)
        expected_state, next_state = _TRANSITIONS[manifest.stage]
        if self._state is not expected_state:
            self._state = AdapterState.BLOCKED
            self._manifest = None
            self._call_counts = None
            raise GateViolation(ErrorCode.STATE_NOT_ALLOWED)
        self._state = next_state
        self._manifest = None
        self._call_counts = None
        return self._state

    def disconnect(self) -> AdapterState:
        """Permanently disconnect every nonterminal state and clear its active session."""
        if self._state not in _TERMINAL_STATES:
            self._state = AdapterState.DISCONNECTED
        self._manifest = None
        self._call_counts = None
        return self._state

    def _require_session(self) -> tuple[StageManifest, list[int]]:
        if self._manifest is None or self._call_counts is None:
            raise GateViolation(ErrorCode.STATE_NOT_ALLOWED)
        return self._manifest, self._call_counts
