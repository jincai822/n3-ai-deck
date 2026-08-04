"""Transactional, deterministic, redacted evidence for adapter activity."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from streamdock_n3.hardware.contracts import (
    SCHEMA_VERSION,
    AdapterCommand,
    AdapterState,
    DeviceProfile,
    ErrorCode,
    HidInterface,
    Operation,
    OperationResult,
    RecoveryStatus,
    ResultStatus,
    Stage,
    StageManifest,
)


class EvidenceDisposition(StrEnum):
    ATTEMPT = "attempt"
    COMMITTED = "committed"
    FAILED = "failed"


class EvidenceKind(StrEnum):
    OPERATION = "operation"
    STAGE = "stage"
    PROFILE_APPROVAL = "profile_approval"
    PERMISSION_APPROVAL = "permission_approval"


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    schema_version: int
    kind: EvidenceKind
    disposition: EvidenceDisposition
    epoch: int
    stage: Stage
    commit: str
    profile_digest: str
    interface: HidInterface
    operation: Operation | None
    brightness: int | None
    key: int | None
    payload_size: int
    status: ResultStatus | None
    error_code: ErrorCode | None
    duration_ms: int
    event_count: int
    expected_result: str
    recovery_plan: str
    approval_reference: str
    adapter_state: AdapterState | None
    recovery_status: RecoveryStatus | None
    role_resolution_digest: str | None = None
    permission_plan_digest: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != SCHEMA_VERSION
        ):
            raise ValueError("invalid schema version")
        if not isinstance(self.kind, EvidenceKind):
            raise TypeError("kind must be an EvidenceKind")
        if not isinstance(self.disposition, EvidenceDisposition):
            raise TypeError("disposition must be an EvidenceDisposition")
        for value, field in (
            (self.epoch, "epoch"),
            (self.payload_size, "payload_size"),
            (self.duration_ms, "duration_ms"),
            (self.event_count, "event_count"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if not isinstance(self.stage, Stage):
            raise TypeError("stage must be a Stage")
        if not isinstance(self.interface, HidInterface):
            raise TypeError("interface must be a HidInterface")
        if self.kind is EvidenceKind.OPERATION:
            if self.role_resolution_digest is not None:
                raise ValueError("role_resolution_digest only applies to profile approval")
            if self.permission_plan_digest is not None:
                raise ValueError("permission_plan_digest only applies to permission approval")
            if not isinstance(self.operation, Operation):
                raise TypeError("operation evidence requires an Operation")
            if not isinstance(self.status, ResultStatus):
                raise TypeError("operation evidence requires a ResultStatus")
            if not isinstance(self.error_code, ErrorCode):
                raise TypeError("operation evidence requires an ErrorCode")
            if self.adapter_state is not None or self.recovery_status is not None:
                raise ValueError("operation evidence cannot include stage outcome")
        elif self.kind is EvidenceKind.PROFILE_APPROVAL:
            if any(
                value is not None
                for value in (
                    self.operation,
                    self.brightness,
                    self.key,
                    self.status,
                )
            ):
                raise ValueError("profile approval evidence cannot include operation outcome")
            if self.error_code is not None and not isinstance(self.error_code, ErrorCode):
                raise TypeError("error_code must be an ErrorCode or None")
            if self.payload_size or self.duration_ms or self.event_count:
                raise ValueError("profile approval evidence counters must be zero")
            if self.permission_plan_digest is not None:
                raise ValueError("permission_plan_digest only applies to permission approval")
            if (
                not isinstance(self.role_resolution_digest, str)
                or len(self.role_resolution_digest) != 64
            ):
                raise ValueError("profile approval evidence requires a role resolution digest")
            if self.adapter_state is not AdapterState.PROFILE_APPROVED:
                raise ValueError("profile approval evidence requires PROFILE_APPROVED state")
            if self.recovery_status is not RecoveryStatus.NOT_REQUIRED:
                raise ValueError("profile approval evidence requires NOT_REQUIRED recovery")
        elif self.kind is EvidenceKind.PERMISSION_APPROVAL:
            if any(
                value is not None
                for value in (
                    self.operation,
                    self.brightness,
                    self.key,
                    self.status,
                )
            ):
                raise ValueError("permission approval evidence cannot include operation outcome")
            if self.error_code is not None and not isinstance(self.error_code, ErrorCode):
                raise TypeError("error_code must be an ErrorCode or None")
            if self.payload_size or self.duration_ms or self.event_count:
                raise ValueError("permission approval evidence counters must be zero")
            if self.role_resolution_digest is not None:
                raise ValueError("role_resolution_digest only applies to profile approval")
            if (
                not isinstance(self.permission_plan_digest, str)
                or len(self.permission_plan_digest) != 64
            ):
                raise ValueError("permission approval evidence requires a permission plan digest")
            if self.adapter_state is not AdapterState.PROFILE_APPROVED:
                raise ValueError("permission approval evidence requires PROFILE_APPROVED state")
            if self.recovery_status is not RecoveryStatus.NOT_REQUIRED:
                raise ValueError("permission approval evidence requires NOT_REQUIRED recovery")
        else:
            if self.role_resolution_digest is not None:
                raise ValueError("role_resolution_digest only applies to profile approval")
            if self.permission_plan_digest is not None:
                raise ValueError("permission_plan_digest only applies to permission approval")
            if any(
                value is not None
                for value in (
                    self.operation,
                    self.brightness,
                    self.key,
                    self.status,
                )
            ):
                raise ValueError("stage evidence cannot include operation outcome")
            if self.payload_size or self.duration_ms or self.event_count:
                raise ValueError("stage evidence counters must be zero")
            if not isinstance(self.adapter_state, AdapterState):
                raise TypeError("stage evidence requires an AdapterState")
            if not isinstance(self.recovery_status, RecoveryStatus):
                raise TypeError("stage evidence requires a RecoveryStatus")
            if self.error_code is not None and not isinstance(self.error_code, ErrorCode):
                raise TypeError("error_code must be an ErrorCode or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "disposition": self.disposition.value,
            "epoch": self.epoch,
            "stage": self.stage.value,
            "commit": self.commit,
            "profile_digest": self.profile_digest,
            "interface": self.interface.to_dict(),
            "operation": self.operation.value if self.operation is not None else None,
            "brightness": self.brightness,
            "key": self.key,
            "payload_size": self.payload_size,
            "status": self.status.value if self.status is not None else None,
            "error_code": self.error_code.value if self.error_code is not None else None,
            "duration_ms": self.duration_ms,
            "event_count": self.event_count,
            "expected_result": self.expected_result,
            "recovery_plan": self.recovery_plan,
            "approval_reference": self.approval_reference,
            "adapter_state": self.adapter_state.value if self.adapter_state is not None else None,
            "recovery_status": (
                self.recovery_status.value if self.recovery_status is not None else None
            ),
            "role_resolution_digest": self.role_resolution_digest,
            "permission_plan_digest": self.permission_plan_digest,
        }


class EvidenceSink(Protocol):
    def record(self, record: EvidenceRecord) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _EvidenceToken:
    index: int
    epoch: int
    kind: EvidenceKind


class EvidenceRecorder:
    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(self._records)

    def begin(self, record: EvidenceRecord) -> _EvidenceToken:
        if not isinstance(record, EvidenceRecord):
            raise TypeError("record must be an EvidenceRecord")
        if record.disposition is not EvidenceDisposition.ATTEMPT:
            raise ValueError("evidence must begin as an attempt")
        token = _EvidenceToken(len(self._records), record.epoch, record.kind)
        self._records.append(record)
        return token

    def commit(self, token: _EvidenceToken) -> None:
        record = self._require_attempt(token)
        self._records[token.index] = replace(record, disposition=EvidenceDisposition.COMMITTED)

    def fail(self, token: _EvidenceToken, code: ErrorCode) -> None:
        if not isinstance(code, ErrorCode) or code is ErrorCode.NONE:
            raise ValueError("failure evidence requires a non-NONE ErrorCode")
        record = self._require_attempt(token)
        self._records[token.index] = replace(
            record,
            disposition=EvidenceDisposition.FAILED,
            error_code=code,
        )

    def _require_attempt(self, token: _EvidenceToken) -> EvidenceRecord:
        if (
            not isinstance(token, _EvidenceToken)
            or isinstance(token.index, bool)
            or not 0 <= token.index < len(self._records)
        ):
            raise ValueError("stale_evidence_token")
        record = self._records[token.index]
        if (
            record.disposition is not EvidenceDisposition.ATTEMPT
            or record.epoch != token.epoch
            or record.kind is not token.kind
        ):
            raise ValueError("stale_evidence_token")
        return record

    def to_json(self) -> str:
        return json.dumps(
            [record.to_dict() for record in self._records],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def operation_evidence(
    profile: DeviceProfile,
    manifest: StageManifest,
    command: AdapterCommand,
    result: OperationResult,
    epoch: int,
) -> EvidenceRecord:
    return EvidenceRecord(
        schema_version=SCHEMA_VERSION,
        kind=EvidenceKind.OPERATION,
        disposition=EvidenceDisposition.ATTEMPT,
        epoch=epoch,
        stage=manifest.stage,
        commit=manifest.commit,
        profile_digest=profile.digest(),
        interface=manifest.interface,
        operation=command.operation,
        brightness=command.brightness,
        key=command.key,
        payload_size=len(command.image) if command.image is not None else 0,
        status=result.status,
        error_code=result.error_code,
        duration_ms=result.duration_ms,
        event_count=len(result.events),
        expected_result=manifest.expected_result,
        recovery_plan=manifest.recovery_plan,
        approval_reference=manifest.approval_reference,
        adapter_state=None,
        recovery_status=None,
    )


def stage_evidence(
    profile: DeviceProfile,
    manifest: StageManifest,
    state: AdapterState,
    recovery_status: RecoveryStatus,
    epoch: int,
) -> EvidenceRecord:
    return EvidenceRecord(
        schema_version=SCHEMA_VERSION,
        kind=EvidenceKind.STAGE,
        disposition=EvidenceDisposition.ATTEMPT,
        epoch=epoch,
        stage=manifest.stage,
        commit=manifest.commit,
        profile_digest=profile.digest(),
        interface=manifest.interface,
        operation=None,
        brightness=None,
        key=None,
        payload_size=0,
        status=None,
        error_code=None,
        duration_ms=0,
        event_count=0,
        expected_result=manifest.expected_result,
        recovery_plan=manifest.recovery_plan,
        approval_reference=manifest.approval_reference,
        adapter_state=state,
        recovery_status=recovery_status,
    )


def profile_approval_evidence(
    profile: DeviceProfile,
    manifest: StageManifest,
    epoch: int,
) -> EvidenceRecord:
    resolution = manifest.role_resolution
    if resolution is None:
        raise ValueError("profile approval requires a role resolution")
    return EvidenceRecord(
        schema_version=SCHEMA_VERSION,
        kind=EvidenceKind.PROFILE_APPROVAL,
        disposition=EvidenceDisposition.ATTEMPT,
        epoch=epoch,
        stage=manifest.stage,
        commit=manifest.commit,
        profile_digest=profile.digest(),
        interface=manifest.interface,
        operation=None,
        brightness=None,
        key=None,
        payload_size=0,
        status=None,
        error_code=None,
        duration_ms=0,
        event_count=0,
        expected_result=manifest.expected_result,
        recovery_plan=manifest.recovery_plan,
        approval_reference=manifest.approval_reference,
        adapter_state=AdapterState.PROFILE_APPROVED,
        recovery_status=RecoveryStatus.NOT_REQUIRED,
        role_resolution_digest=resolution.digest(),
    )


def permission_approval_evidence(
    profile: DeviceProfile,
    manifest: StageManifest,
    epoch: int,
) -> EvidenceRecord:
    plan = manifest.permission_plan
    if plan is None:
        raise ValueError("permission approval requires a permission plan")
    return EvidenceRecord(
        schema_version=SCHEMA_VERSION,
        kind=EvidenceKind.PERMISSION_APPROVAL,
        disposition=EvidenceDisposition.ATTEMPT,
        epoch=epoch,
        stage=manifest.stage,
        commit=manifest.commit,
        profile_digest=profile.digest(),
        interface=manifest.interface,
        operation=None,
        brightness=None,
        key=None,
        payload_size=0,
        status=None,
        error_code=None,
        duration_ms=0,
        event_count=0,
        expected_result=manifest.expected_result,
        recovery_plan=manifest.recovery_plan,
        approval_reference=manifest.approval_reference,
        adapter_state=AdapterState.PROFILE_APPROVED,
        recovery_status=RecoveryStatus.NOT_REQUIRED,
        permission_plan_digest=plan.digest(),
    )
