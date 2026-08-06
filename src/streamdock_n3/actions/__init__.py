"""M3 action engine: plugin contract, timeout-enforcing engine, and safe builtins."""

from streamdock_n3.actions.ai import (
    DEFAULT_API_KEY_ENV,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_PROMPT,
    AiTextPlugin,
)
from streamdock_n3.actions.builtins import (
    ALLOWLISTED_EXECUTABLES,
    LaunchAppPlugin,
    LogEventPlugin,
    builtin_registry,
)
from streamdock_n3.actions.config import (
    BindingsError,
    default_bindings_path,
    load_bindings,
)
from streamdock_n3.actions.contracts import (
    ActionBinding,
    ActionContext,
    ActionPlugin,
    ActionResult,
    ActionStatus,
    PluginMetadata,
)
from streamdock_n3.actions.engine import DEFAULT_TIMEOUT_SECONDS, ActionEngine, event_key_for
from streamdock_n3.actions.feedback import (
    KEY_IMAGE_SIZE,
    STATE_COLORS,
    FeedbackState,
    render_state_image,
    write_key_image,
)
from streamdock_n3.actions.live import (
    LiveSessionResult,
    LiveSessionSpec,
    LiveSessionStatus,
    run_live_loop,
)

__all__ = [
    "ALLOWLISTED_EXECUTABLES",
    "DEFAULT_API_KEY_ENV",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_PROMPT",
    "DEFAULT_TIMEOUT_SECONDS",
    "ActionBinding",
    "ActionContext",
    "ActionEngine",
    "ActionPlugin",
    "ActionResult",
    "ActionStatus",
    "AiTextPlugin",
    "BindingsError",
    "FeedbackState",
    "KEY_IMAGE_SIZE",
    "LaunchAppPlugin",
    "LiveSessionResult",
    "LiveSessionSpec",
    "LiveSessionStatus",
    "LogEventPlugin",
    "PluginMetadata",
    "STATE_COLORS",
    "builtin_registry",
    "default_bindings_path",
    "event_key_for",
    "load_bindings",
    "render_state_image",
    "run_live_loop",
    "write_key_image",
]
