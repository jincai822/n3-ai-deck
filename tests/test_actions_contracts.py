from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from streamdock_n3.actions.contracts import (
    ActionBinding,
    ActionContext,
    ActionPlugin,
    ActionResult,
    ActionStatus,
    PluginMetadata,
)


def test_action_status_values_are_stable() -> None:
    assert tuple(status.value for status in ActionStatus) == (
        "ok",
        "error",
        "timeout",
        "skipped",
    )


def test_plugin_metadata_accepts_valid_values() -> None:
    metadata = PluginMetadata("launch_app", "1.0.0", "Launch an allowlisted application")

    assert metadata.name == "launch_app"
    assert metadata.version == "1.0.0"
    assert metadata.description == "Launch an allowlisted application"
    with pytest.raises(FrozenInstanceError):
        metadata.name = "other"  # type: ignore[misc]


def test_action_context_accepts_valid_values() -> None:
    context = ActionContext("button.1.press", 1, "button", "press", 1_000_000)

    assert context.event_key == "button.1.press"
    assert context.control_id == 1
    assert context.kind == "button"
    assert context.action == "press"
    assert context.monotonic_ns == 1_000_000


def test_action_result_is_frozen_and_to_dict_is_stable() -> None:
    result = ActionResult(ActionStatus.OK, "launch_app", "launched", 12)

    assert result.to_dict() == {
        "status": "ok",
        "plugin": "launch_app",
        "detail": "launched",
        "duration_ms": 12,
    }
    with pytest.raises(FrozenInstanceError):
        result.detail = "changed"  # type: ignore[misc]


def test_action_binding_accepts_arbitrary_config() -> None:
    binding = ActionBinding("button.1.press", "launch_app", {"app": "alacritty"})

    assert binding.event_key == "button.1.press"
    assert binding.plugin == "launch_app"
    assert binding.config == {"app": "alacritty"}
    assert replace(binding, config=None).config is None


def test_action_plugin_is_runtime_checkable() -> None:
    class FakePlugin:
        def metadata(self) -> PluginMetadata:
            return PluginMetadata("fake", "1.0.0", "fake plugin")

        def validate_config(self, config: object) -> list[str]:
            return []

        def execute(self, context: ActionContext, config: object) -> ActionResult:
            return ActionResult(ActionStatus.OK, "fake", "", 0)

    assert isinstance(FakePlugin(), ActionPlugin)


@pytest.mark.parametrize(
    "factory",
    (
        lambda: PluginMetadata("", "1.0.0", "desc"),
        lambda: PluginMetadata("name", "", "desc"),
        lambda: PluginMetadata("name", "1.0.0", ""),
        lambda: PluginMetadata(1, "1.0.0", "desc"),
        lambda: ActionContext("", 1, "button", "press", 0),
        lambda: ActionContext("button.1.press", 0, "button", "press", 0),
        lambda: ActionContext("button.1.press", 10, "button", "press", 0),
        lambda: ActionContext("button.1.press", True, "button", "press", 0),
        lambda: ActionContext("button.1.press", 1, "", "press", 0),
        lambda: ActionContext("button.1.press", 1, "button", "", 0),
        lambda: ActionContext("button.1.press", 1, "button", "press", -1),
        lambda: ActionContext("button.1.press", 1, "button", "press", True),
        lambda: ActionResult("ok", "plugin", "", 0),
        lambda: ActionResult(ActionStatus.OK, "", "", 0),
        lambda: ActionResult(ActionStatus.OK, "plugin", 1, 0),
        lambda: ActionResult(ActionStatus.OK, "plugin", "", -1),
        lambda: ActionResult(ActionStatus.OK, "plugin", "", True),
        lambda: ActionBinding("", "plugin", None),
        lambda: ActionBinding("button.1.press", "", None),
        lambda: ActionBinding("button.1.press", 1, None),
    ),
)
def test_invalid_contract_values_fail_closed(factory: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()  # type: ignore[operator]
