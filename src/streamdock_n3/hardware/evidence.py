"""Closed, in-memory evidence records for hardware validation stages."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

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


class EvidenceKind(StrEnum):
    """The two closed evidence record categories."""

    OPERATION = "operation"
    STAGE = "stage"


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """A safe, fixed-shape snapshot of one operation or completed stage."""

    schema_version: int
    kind: EvidenceKind
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

    def to_dict(self) -> dict[str, object]:
        """Return a fresh public dictionary containing only the closed schema."""
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
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
            "recovery_status": self.recovery_status.value if self.recovery_status is not None else None,
        }


class EvidenceRecorder:
    """Accumulate deterministic redacted evidence in process memory only."""

    def __init__(self) -> None:
        self._records: list[EvidenceRecord] = []

    @property
    def records(self) -> tuple[EvidenceRecord, ...]:
        """Return records in append order without exposing the backing list."""
        return tuple(self._records)

    def record_operation(
        self,
        profile: DeviceProfile,
        manifest: StageManifest,
        command: AdapterCommand,
        result: OperationResult,
    ) -> None:
        """Append one operation record without retaining image data or digests."""
        self._records.append(
            EvidenceRecord(
                schema_version=SCHEMA_VERSION,
                kind=EvidenceKind.OPERATION,
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
        )

    def record_stage(
        self,
        profile: DeviceProfile,
        manifest: StageManifest,
        state: AdapterState,
        recovery_status: RecoveryStatus,
    ) -> None:
        """Append one stage-completion record without backend-native data."""
        self._records.append(
            EvidenceRecord(
                schema_version=SCHEMA_VERSION,
                kind=EvidenceKind.STAGE,
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
        )

    def to_json(self) -> str:
        """Render the in-memory closed schema deterministically without writing files."""
        return json.dumps(
            [record.to_dict() for record in self._records],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
