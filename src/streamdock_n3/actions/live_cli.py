"""Owner-run foreground live dispatch CLI for the M3 action engine.

P3 of the live-dispatch design (section 4.3 of
docs/superpowers/specs/2026-08-05-live-dispatch-design.md): streams real
vendor events to the action engine in real time — logging by default and
launching allowlisted apps when the owner has created a bindings file. Output
is one JSONL line per dispatched event plus a final summary; the session ends
cleanly on deadline, Ctrl+C, or disconnect. Never daemonizes, never writes
config, and never exposes device node paths in output.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from streamdock_n3.actions.builtins import builtin_registry
from streamdock_n3.actions.config import BindingsError, default_bindings_path, load_bindings
from streamdock_n3.actions.contracts import ActionBinding, ActionResult
from streamdock_n3.actions.engine import ActionEngine, event_key_for
from streamdock_n3.actions.live import LiveSessionSpec, LiveSessionStatus, run_live_loop
from streamdock_n3.hardware.contracts import (
    MAX_DEADLINE_MS,
    KeyMap,
    NormalizedInputEvent,
)
from streamdock_n3.hardware.input_session import VendorHidReadOnlyBackend
from streamdock_n3.hardware.vendor_backend import _HidrawTransport
from streamdock_n3.input_cli import NodeResolutionError, _load_key_map, resolve_vendor_node
from streamdock_n3.paths import config_dir

SCHEMA_VERSION = 1
DEFAULT_DURATION_MS = 60_000


def _resolve_bindings_path(explicit: Path | None) -> tuple[Path, str]:
    """Resolve the bindings file and return (path, source) with a redacted label.

    The default is the owner's XDG file, falling back to the shipped
    zero-side-effect sample. The source label avoids echoing absolute config
    paths (which can embed a username) into output.
    """
    if explicit is not None:
        if not explicit.exists():
            raise BindingsError(f"bindings file not found: {explicit}")
        return explicit, "explicit"
    xdg = config_dir() / "bindings.json"
    if xdg.exists():
        return xdg, "xdg"
    shipped = default_bindings_path()
    if shipped is None:
        raise BindingsError("shipped default bindings are unavailable")
    return shipped, "shipped"


def _render_event_line(
    event: NormalizedInputEvent, result: ActionResult | None
) -> dict[str, object]:
    line: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "event_key": event_key_for(event),
        "control_id": event.control_id,
        "kind": event.kind.value,
        "action": event.action.value,
    }
    if result is None:
        line["status"] = "unbound"
    else:
        line["status"] = result.status.value
        line["plugin"] = result.plugin
        line["detail"] = result.detail
        line["duration_ms"] = result.duration_ms
    return line


def _print_event_line(event: NormalizedInputEvent, result: ActionResult | None) -> None:
    print(json.dumps(_render_event_line(event, result), ensure_ascii=True))


def _dry_run_summary(
    spec: LiveSessionSpec,
    bindings_source: str,
    key_map: KeyMap,
    bindings: Mapping[str, ActionBinding],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "node_resolved": True,
        "key_map_entries": len(key_map.entries),
        "bindings_source": bindings_source,
        "bindings_count": len(bindings),
        "duration_ms": spec.duration_ms,
        "init": spec.init,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="n3-ai-deck-live",
        description=(
            "Dispatch real physical events to the action engine in real time. "
            "Logs only by default; allowlisted apps launch when the owner has "
            "created a bindings file. Foreground only; never daemonizes."
        ),
    )
    parser.add_argument(
        "--bindings",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "JSON bindings file (default: the owner's bindings.json, "
            "else the shipped zero-side-effect sample)"
        ),
    )
    parser.add_argument(
        "--duration-ms",
        type=int,
        default=DEFAULT_DURATION_MS,
        metavar="MS",
        help=(
            f"bounded session window (default: {DEFAULT_DURATION_MS}, "
            f"max {MAX_DEADLINE_MS})"
        ),
    )
    parser.add_argument(
        "--no-init",
        action="store_true",
        help="skip the validated DIS/LIG/STP init trio at start",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "resolve node, key map, and bindings and print a summary "
            "without opening the device"
        ),
    )
    return parser


def _emit_error(detail: str) -> int:
    print(
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "status": "error", "detail": detail},
            ensure_ascii=True,
        )
    )
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    duration_ms = cast(int, args.duration_ms)
    explicit_bindings = cast(Path | None, args.bindings)
    no_init = cast(bool, args.no_init)
    dry_run = cast(bool, args.dry_run)

    try:
        bindings_path, bindings_source = _resolve_bindings_path(explicit_bindings)
        bindings = load_bindings(bindings_path)
        key_map = _load_key_map(None, "vendor")
        spec = LiveSessionSpec(duration_ms=duration_ms, init=not no_init)
        node = resolve_vendor_node()
    except (NodeResolutionError, ValueError) as error:
        return _emit_error(str(error))

    if dry_run:
        print(
            json.dumps(
                _dry_run_summary(spec, bindings_source, key_map, bindings),
                ensure_ascii=True,
                indent=2,
            )
        )
        return 0

    engine = ActionEngine(builtin_registry(), bindings)
    try:
        result = run_live_loop(
            spec,
            node,
            key_map,
            engine,
            input_backend=VendorHidReadOnlyBackend(),
            transport=_HidrawTransport(),
            on_event=_print_event_line,
        )
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "interrupted",
                    "detail": "session stopped by Ctrl+C",
                },
                ensure_ascii=True,
            )
        )
        return 0
    print(json.dumps(result.to_dict(), ensure_ascii=True))
    return 0 if result.status is LiveSessionStatus.SUCCEEDED else 1


if __name__ == "__main__":
    raise SystemExit(main())
