"""Safe builtin action plugins for the M3 action engine."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess

from streamdock_n3.actions.ai import AiTextPlugin
from streamdock_n3.actions.contracts import (
    ActionContext,
    ActionPlugin,
    ActionResult,
    ActionStatus,
    PluginMetadata,
)

ALLOWLISTED_EXECUTABLES: frozenset[str] = frozenset(
    {"alacritty", "firefox", "wpctl", "playerctl"}
)

logger = logging.getLogger(__name__)


class LaunchAppPlugin:
    """Launch an allowlisted executable as an argv list, never a shell string."""

    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            "launch_app", "1.0.0", "Launch an allowlisted application by name"
        )

    def validate_config(self, config: object) -> list[str]:
        problems: list[str] = []
        if not isinstance(config, dict):
            return ["config must be an object"]
        app = config.get("app")
        if not isinstance(app, str) or not app:
            problems.append("config.app must be a non-empty string")
        elif app not in ALLOWLISTED_EXECUTABLES:
            problems.append(f"config.app {app!r} is not allowlisted")
        args = config.get("args", [])
        if not isinstance(args, list) or not all(
            isinstance(arg, str) and arg for arg in args
        ):
            problems.append("config.args must be a list of non-empty strings")
        return problems

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        del context
        if not isinstance(config, dict):
            return self._error("invalid config: expected an object")
        app = config.get("app")
        args = config.get("args", [])
        if not isinstance(app, str) or not isinstance(args, list):
            return self._error("invalid config: expected app and args")
        path = shutil.which(app)
        if path is None:
            return self._error(f"{app} is not available on PATH")
        argv = [path, *args]
        try:
            subprocess.Popen(
                argv,
                shell=False,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return self._error(f"failed to launch {app}: {exc}")
        return ActionResult(ActionStatus.OK, "launch_app", f"launched {app}", 0)

    def _error(self, detail: str) -> ActionResult:
        return ActionResult(ActionStatus.ERROR, "launch_app", detail, 0)


class LogEventPlugin:
    """Zero-side-effect plugin: write one structured log line per event."""

    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            "log_event", "1.0.0", "Log the event as a structured line"
        )

    def validate_config(self, config: object) -> list[str]:
        del config
        return []

    def execute(self, context: ActionContext, config: object) -> ActionResult:
        del config
        payload = {
            "event_key": context.event_key,
            "kind": context.kind,
            "control_id": context.control_id,
            "action": context.action,
            "monotonic_ns": context.monotonic_ns,
        }
        logger.info("action event: %s", json.dumps(payload, sort_keys=True))
        return ActionResult(ActionStatus.OK, "log_event", "logged", 0)


def builtin_registry() -> dict[str, ActionPlugin]:
    """Return the builtin plugins keyed by name: launch_app, log_event, ai_text."""
    return {
        "launch_app": LaunchAppPlugin(),
        "log_event": LogEventPlugin(),
        "ai_text": AiTextPlugin(),
    }
