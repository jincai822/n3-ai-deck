"""Hardware-free demo CLI for the M3 action engine."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from streamdock_n3.actions.builtins import builtin_registry
from streamdock_n3.actions.config import default_bindings_path, load_bindings
from streamdock_n3.actions.contracts import (
    ActionBinding,
    ActionPlugin,
    ActionResult,
    ActionStatus,
)
from streamdock_n3.actions.engine import ActionEngine, event_key_for
from streamdock_n3.hardware.contracts import InputAction, InputKind, NormalizedInputEvent

SCHEMA_VERSION = 1


def parse_event_key(key: str) -> NormalizedInputEvent:
    """Parse a `button.1.press`-style key into a synthetic normalized event."""
    if not isinstance(key, str):
        raise ValueError("event must be a string")
    parts = key.split(".")
    if len(parts) != 3:
        raise ValueError(f"invalid event key: {key!r}")
    domain, raw_control_id, raw_action = parts
    try:
        control_id = int(raw_control_id)
    except ValueError:
        raise ValueError(f"invalid control id: {raw_control_id!r}") from None
    if domain == "button":
        kind = InputKind.BUTTON
        action = InputAction(raw_action)
    elif domain == "knob":
        if raw_action in ("press", "release"):
            kind = InputKind.KNOB_PRESS
            action = InputAction(raw_action)
        elif raw_action in ("left", "right"):
            kind = InputKind.KNOB_ROTATE
            action = InputAction(raw_action)
        else:
            raise ValueError(f"invalid knob action: {raw_action!r}")
    else:
        raise ValueError(f"invalid event domain: {domain!r}")
    return NormalizedInputEvent(kind, control_id, action, time.monotonic_ns())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="n3-ai-deck-run-action",
        description=(
            "Run one configured action for a standard event key without "
            "hardware. Never opens a device node and never loads the SDK."
        ),
    )
    parser.add_argument(
        "--event",
        required=True,
        metavar="KEY",
        help="standard event key, e.g. button.1.press or knob.2.left",
    )
    parser.add_argument(
        "--bindings",
        type=Path,
        default=None,
        metavar="PATH",
        help="JSON bindings file (default: shipped zero-side-effect sample)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve the binding and validate config without executing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    event_key = cast(str, args.event)
    dry_run = cast(bool, args.dry_run)
    bindings_path = cast(Path | None, args.bindings)
    if bindings_path is None:
        bindings_path = default_bindings_path()
    if bindings_path is None:
        return _emit_error("shipped default bindings are unavailable")
    try:
        event = parse_event_key(event_key)
        # BindingsError subclasses ValueError; parse and load failures are
        # both reported as structured error JSON, never a traceback.
        bindings = load_bindings(bindings_path)
    except ValueError as error:
        return _emit_error(str(error))
    key = event_key_for(event)
    registry = builtin_registry()
    if dry_run:
        rendered, code = _dry_run_result(registry, bindings, key)
    else:
        engine = ActionEngine(registry, bindings)
        rendered, code = _render_result(key, engine.handle_event(event))
    print(json.dumps(rendered, ensure_ascii=True, indent=2))
    return code


def _dry_run_result(
    registry: Mapping[str, ActionPlugin],
    bindings: Mapping[str, ActionBinding],
    key: str,
) -> tuple[dict[str, object], int]:
    binding = bindings.get(key)
    if binding is None:
        return {"schema_version": SCHEMA_VERSION, "event_key": key, "status": "unbound"}, 0
    plugin = registry.get(binding.plugin)
    if plugin is None:
        return _error_result(key, binding.plugin, f"unknown plugin: {binding.plugin}"), 1
    try:
        problems = plugin.validate_config(binding.config)
    except Exception as exc:
        return (
            _error_result(
                key,
                binding.plugin,
                f"validate_config raised {type(exc).__name__}: {exc}",
            ),
            1,
        )
    if problems:
        return _error_result(key, binding.plugin, "; ".join(problems)), 1
    return (
        {
            "schema_version": SCHEMA_VERSION,
            "event_key": key,
            "status": "skipped",
            "plugin": binding.plugin,
            "detail": "dry run: plugin not executed",
        },
        0,
    )


def _render_result(
    key: str,
    result: ActionResult | None,
) -> tuple[dict[str, object], int]:
    if result is None:
        return {"schema_version": SCHEMA_VERSION, "event_key": key, "status": "unbound"}, 0
    rendered: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "event_key": key,
        "status": result.status.value,
        "plugin": result.plugin,
        "detail": result.detail,
        "duration_ms": result.duration_ms,
    }
    code = 0 if result.status in (ActionStatus.OK, ActionStatus.SKIPPED) else 1
    return rendered, code


def _error_result(key: str, plugin: str, detail: str) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_key": key,
        "status": "error",
        "plugin": plugin,
        "detail": detail,
        "duration_ms": 0,
    }


def _emit_error(detail: str) -> int:
    print(
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "status": "error", "detail": detail},
            ensure_ascii=True,
            indent=2,
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
