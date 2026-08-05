"""File-based action bindings: JSON mapping of event keys to plugin bindings."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

from streamdock_n3.actions.contracts import ActionBinding

# Three dot-separated parts: a lower-case domain, an identifier, a state.
_EVENT_KEY_RE = re.compile(r"^[a-z]+\.[0-9A-Za-z_-]+\.[a-z]+$")


class BindingsError(ValueError):
    """A structured failure while loading or parsing a bindings file."""


def default_bindings_path() -> Path | None:
    """Locate the shipped zero-side-effect default bindings sample."""
    try:
        ref = resources.files("streamdock_n3").joinpath("resources/actions.default.json")
        with resources.as_file(ref) as p:
            if p.is_file():
                return Path(p)
    except (FileNotFoundError, ModuleNotFoundError):
        pass
    return None


def load_bindings(path: Path) -> dict[str, ActionBinding]:
    """Load bindings from a JSON file; a missing file yields an empty mapping."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise BindingsError(f"cannot read bindings file: {error}") from None
    try:
        wire = json.loads(text)
    except ValueError as error:
        raise BindingsError(f"invalid JSON: {error}") from None
    return _parse_bindings(wire)


def _parse_bindings(wire: object) -> dict[str, ActionBinding]:
    if not isinstance(wire, dict):
        raise BindingsError("bindings root must be a JSON object")
    bindings: dict[str, ActionBinding] = {}
    for key, value in wire.items():
        if not isinstance(key, str) or _EVENT_KEY_RE.fullmatch(key) is None:
            raise BindingsError(f"invalid event key: {key!r}")
        if not isinstance(value, dict):
            raise BindingsError(f"binding {key!r} must be an object")
        unknown = set(value) - {"plugin", "config"}
        if unknown:
            raise BindingsError(
                f"binding {key!r} has unsupported keys: {', '.join(sorted(unknown))}"
            )
        plugin = value.get("plugin")
        if not isinstance(plugin, str) or not plugin:
            raise BindingsError(f"binding {key!r} requires a non-empty plugin name")
        config = value.get("config")
        if config is not None and not isinstance(config, dict):
            raise BindingsError(f"binding {key!r} config must be an object or omitted")
        bindings[key] = ActionBinding(key, plugin, config)
    return bindings
