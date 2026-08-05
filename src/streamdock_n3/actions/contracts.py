"""Immutable, side-effect-free contracts for the M3 action engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

MIN_CONTROL_ID = 1
MAX_CONTROL_ID = 9


class ActionStatus(StrEnum):
    """Outcome of one action execution, distinct from hardware ResultStatus."""

    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


def _validate_int(value: object, field: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")


def _validate_nonempty_str(value: object, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class PluginMetadata:
    """Metadata a plugin declares about itself."""

    name: str
    version: str
    description: str

    def __post_init__(self) -> None:
        _validate_nonempty_str(self.name, "name")
        _validate_nonempty_str(self.version, "version")
        _validate_nonempty_str(self.description, "description")


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Transport-neutral view of one normalized event passed to a plugin."""

    event_key: str
    control_id: int
    kind: str
    action: str
    monotonic_ns: int

    def __post_init__(self) -> None:
        _validate_nonempty_str(self.event_key, "event_key")
        _validate_int(self.control_id, "control_id", MIN_CONTROL_ID, MAX_CONTROL_ID)
        _validate_nonempty_str(self.kind, "kind")
        _validate_nonempty_str(self.action, "action")
        _validate_int(self.monotonic_ns, "monotonic_ns", 0, 2**63 - 1)


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Structured outcome of one action execution."""

    status: ActionStatus
    plugin: str
    detail: str
    duration_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.status, ActionStatus):
            raise TypeError("status must be an ActionStatus")
        _validate_nonempty_str(self.plugin, "plugin")
        if not isinstance(self.detail, str):
            raise TypeError("detail must be a string")
        _validate_int(self.duration_ms, "duration_ms", 0, 2**63 - 1)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "plugin": self.plugin,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class ActionBinding:
    """One event key mapped to a plugin name plus its config."""

    event_key: str
    plugin: str
    config: object

    def __post_init__(self) -> None:
        _validate_nonempty_str(self.event_key, "event_key")
        _validate_nonempty_str(self.plugin, "plugin")


@runtime_checkable
class ActionPlugin(Protocol):
    """In-process plugin contract: metadata, config validation, execution."""

    def metadata(self) -> PluginMetadata:
        """Declare the plugin's name, version, and description."""
        ...

    def validate_config(self, config: object) -> list[str]:
        """Return a list of config problems; an empty list means valid."""
        ...

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        """Run the action for one event and return a structured result."""
        ...
