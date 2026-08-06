"""G8 background service console CLI (`n3-ai-deck-service`).

P3 of the G8 design (section 4.3 of
docs/superpowers/specs/2026-08-05-g8-service-design.md): wires the validated
in-process service loop (P2, actions/service.py) to the real vendor hardware
and prints the two owner-gated system assets. `--print-unit` and
`--print-udev-rule` print to stdout only and never install, enable, or write
anything; the service loop itself reuses the validated live flags
`--bindings`/`--feedback`/`--timeout-seconds` plus `--session-duration-ms`.
Lifecycle output is JSONL with redacted fields (no serials, node paths,
absolute paths, or credentials); dispatch event lines match the live CLI.
The process never daemonizes, never imports `_vendor`, and never uses a shell.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast

from streamdock_n3.actions.builtins import builtin_registry
from streamdock_n3.actions.config import BindingsError, load_bindings
from streamdock_n3.actions.contracts import ActionBinding, ActionResult
from streamdock_n3.actions.engine import DEFAULT_TIMEOUT_SECONDS, ActionEngine
from streamdock_n3.actions.live import (
    LiveSessionResult,
    LiveSessionSpec,
    run_live_loop,
)
from streamdock_n3.actions.live_cli import (
    _compose_event_callback,
    _feedback_callbacks,
    _print_event_line,
    _resolve_bindings_path,
)
from streamdock_n3.actions.service import (
    ServiceSpec,
    ServiceStatus,
    run_service,
)
from streamdock_n3.hardware.contracts import (
    MAX_DEADLINE_MS,
    HidInterface,
    InterfaceRole,
    KeyMap,
    NormalizedInputEvent,
)
from streamdock_n3.hardware.input_session import VendorHidReadOnlyBackend
from streamdock_n3.hardware.permissions import persistent_rule
from streamdock_n3.hardware.vendor_backend import _HidrawTransport
from streamdock_n3.input_cli import NodeResolutionError, _load_key_map, resolve_vendor_node

SCHEMA_VERSION = 1
DEFAULT_SESSION_DURATION_MS = 60_000

_VENDOR_ID = 0x6602
_PRODUCT_ID = 0x1000
_INPUT_INTERFACE = HidInterface(1, 0x03, 0x01, 0x01)
_CONTROL_INTERFACE = HidInterface(0, 0x03, 0x00, 0x00)

# The systemd user unit: `%h` placeholders only, no absolute paths. ExecStart
# carries --feedback so LCD state images follow dispatched actions. Print
# only; the owner installs it with systemctl themselves (G8 design section 4.4).
USER_UNIT_TEXT = """\
[Unit]
Description=N3 AI Deck background service
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/bin/n3-ai-deck-service --feedback
EnvironmentFile=-%h/.config/streamdock-n3/service.env
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""

# The G2-approved lazy udev rules (permissions.persistent_rule): precise
# 6602:1000 + the approved interface triple + TAG+="uaccess", never 0666.
UDEV_RULE_TEXT = "\n".join(
    (
        "# N3 AI Deck: approved input interface (6602:1000, class 03/01/01)",
        persistent_rule(_VENDOR_ID, _PRODUCT_ID, _INPUT_INTERFACE, InterfaceRole.INPUT).rendered,
        "",
        "# N3 AI Deck: approved control interface (6602:1000, class 03/00/00)",
        persistent_rule(_VENDOR_ID, _PRODUCT_ID, _CONTROL_INTERFACE, InterfaceRole.CONTROL).rendered,
        "",
    )
)


def _build_session_runner(
    bindings: Mapping[str, ActionBinding],
    key_map: KeyMap,
    feedback: bool,
    timeout_seconds: float,
) -> Callable[[str, ServiceSpec], LiveSessionResult]:
    """Wire one bounded live session per call with a fresh engine.

    The engine is recreated per session so a hung plugin (G8 design section
    2.1) can never leak state across sessions; the key map and bindings are
    loaded once by main. Feedback callbacks are attached only when
    ``--feedback`` is on.
    """

    def runner(node: str, spec: ServiceSpec) -> LiveSessionResult:
        engine = ActionEngine(builtin_registry(), bindings, timeout_seconds=timeout_seconds)
        on_event: Callable[[NormalizedInputEvent, ActionResult | None], None] = _print_event_line
        on_dispatch_start: Callable[[NormalizedInputEvent], None] | None = None
        if feedback:
            feedback_start, feedback_event = _feedback_callbacks(node)
            on_dispatch_start = feedback_start
            on_event = _compose_event_callback(feedback_event)
        return run_live_loop(
            LiveSessionSpec(duration_ms=spec.session_duration_ms, init=spec.init),
            node,
            key_map,
            engine,
            input_backend=VendorHidReadOnlyBackend(),
            transport=_HidrawTransport(),
            on_event=on_event,
            on_dispatch_start=on_dispatch_start,
        )

    return runner


def _emit_error(detail: str) -> int:
    print(
        json.dumps(
            {"schema_version": SCHEMA_VERSION, "status": "error", "detail": detail},
            ensure_ascii=True,
        )
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="n3-ai-deck-service",
        description=(
            "Run the N3 AI Deck background service in the foreground: reconnect "
            "to the approved hidraw node with backoff, run bounded live sessions, "
            "and stop cleanly on SIGTERM. --print-unit and --print-udev-rule "
            "print owner-gated system assets without installing anything."
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
        "--session-duration-ms",
        type=int,
        default=DEFAULT_SESSION_DURATION_MS,
        metavar="MS",
        help=(
            f"bounded session window in milliseconds "
            f"(default: {DEFAULT_SESSION_DURATION_MS}, max {MAX_DEADLINE_MS})"
        ),
    )
    parser.add_argument(
        "--feedback",
        action="store_true",
        help=(
            "write LCD state images (running/success/failure/timeout) to the "
            "triggering LCD key"
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=f"per-action engine timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS:g})",
    )
    parser.add_argument(
        "--print-unit",
        action="store_true",
        help="print the systemd user unit for n3-ai-deck.service to stdout and exit",
    )
    parser.add_argument(
        "--print-udev-rule",
        action="store_true",
        help=(
            "print the udev rules for the approved input and control interfaces "
            "to stdout and exit"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.print_unit:
        print(USER_UNIT_TEXT, end="")
        return 0
    if args.print_udev_rule:
        print(UDEV_RULE_TEXT, end="")
        return 0

    session_duration_ms = cast(int, args.session_duration_ms)
    explicit_bindings = cast(Path | None, args.bindings)
    feedback = cast(bool, args.feedback)
    timeout_seconds = cast(float, args.timeout_seconds)
    if not timeout_seconds > 0:
        return _emit_error("--timeout-seconds must be a positive number")
    try:
        spec = ServiceSpec(
            session_duration_ms=session_duration_ms,
            feedback=feedback,
            timeout_seconds=timeout_seconds,
        )
    except (TypeError, ValueError) as error:
        return _emit_error(str(error))

    try:
        bindings_path, _ = _resolve_bindings_path(explicit_bindings)
        bindings = load_bindings(bindings_path)
        key_map = _load_key_map(None, "vendor")
    except (BindingsError, ValueError, NodeResolutionError) as error:
        return _emit_error(str(error))

    session_runner = _build_session_runner(bindings, key_map, feedback, timeout_seconds)

    def on_lifecycle(event: dict[str, object]) -> None:
        print(json.dumps(event, ensure_ascii=True))

    try:
        result = run_service(
            spec,
            node_resolver=resolve_vendor_node,
            session_runner=session_runner,
            sleep=time.sleep,
            on_lifecycle=on_lifecycle,
        )
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "interrupted",
                    "detail": "service stopped by Ctrl+C",
                },
                ensure_ascii=True,
            )
        )
        return 0
    print(json.dumps(result.to_dict(), ensure_ascii=True))
    return 0 if result.status is ServiceStatus.STOPPED else 1


if __name__ == "__main__":
    raise SystemExit(main())
