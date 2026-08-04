from __future__ import annotations

import json

import pytest

from streamdock_n3.hardware.contracts import (
    HidInterface,
    InterfaceRole,
    PermissionKind,
)
from streamdock_n3.hardware.permissions import (
    make_permission_plan,
    persistent_rule,
    temporary_acl_plan,
)
from tests.hardware_fixtures import make_ambiguous_roles, make_resolved_roles


def test_input_role_justifies_input_subsystem() -> None:
    artifact = temporary_acl_plan(InterfaceRole.INPUT)

    assert artifact.kind is PermissionKind.TEMPORARY_ACL
    assert artifact.subsystem == "input"
    assert artifact.role is InterfaceRole.INPUT


def test_control_role_justifies_hidraw_subsystem() -> None:
    artifact = temporary_acl_plan(InterfaceRole.CONTROL)

    assert artifact.kind is PermissionKind.TEMPORARY_ACL
    assert artifact.subsystem == "hidraw"
    assert artifact.role is InterfaceRole.CONTROL


def test_unknown_role_cannot_generate_artifacts() -> None:
    with pytest.raises(ValueError):
        temporary_acl_plan(InterfaceRole.UNKNOWN)
    with pytest.raises(ValueError):
        persistent_rule(0x6602, 0x1000, HidInterface(0, 3, 0, 0), InterfaceRole.UNKNOWN)


def test_persistent_rule_is_exact_and_uaccess_only() -> None:
    rule = persistent_rule(0x6602, 0x1000, HidInterface(0, 3, 0, 0), InterfaceRole.CONTROL)

    assert 'ATTRS{idVendor}=="6602"' in rule.rendered
    assert 'ATTRS{idProduct}=="1000"' in rule.rendered
    assert 'TAG+="uaccess"' in rule.rendered
    assert 'MODE="0666"' not in rule.rendered
    assert 'SUBSYSTEM=="hidraw"' in rule.rendered
    assert rule.role is InterfaceRole.CONTROL
    assert rule.subsystem == "hidraw"


def test_persistent_input_rule_targets_input_event_subsystem() -> None:
    rule = persistent_rule(0x6602, 0x1000, HidInterface(1, 3, 1, 1), InterfaceRole.INPUT)

    assert 'SUBSYSTEM=="input"' in rule.rendered
    assert 'KERNEL=="event*"' in rule.rendered
    assert rule.subsystem == "input"


def test_acl_plan_uses_only_placeholders() -> None:
    artifact = temporary_acl_plan(InterfaceRole.INPUT)

    assert "{node}" in artifact.rendered
    assert "{current_user}" in artifact.rendered
    for forbidden in ("/dev/input", "/dev/hidraw", "event", "input12", "user"):
        assert forbidden not in artifact.rendered.replace("{current_user}", "")


def test_plan_contains_both_artifacts_for_approved_roles() -> None:
    plan = make_permission_plan(make_resolved_roles(), "test:g2")

    assert {item.subsystem for item in plan.artifacts} == {"input", "hidraw"}
    assert len(plan.digest()) == 64
    assert plan.digest() == make_permission_plan(make_resolved_roles(), "test:g2").digest()


def test_plan_digest_changes_with_approval_reference() -> None:
    plan = make_permission_plan(make_resolved_roles(), "test:g2")
    changed = make_permission_plan(make_resolved_roles(), "owner:2026-08-04:g2")

    assert plan.digest() != changed.digest()


def test_plan_rendering_is_redacted() -> None:
    plan = make_permission_plan(make_resolved_roles(), "test:g2")

    rendered = json.dumps(plan.to_dict(), sort_keys=True)
    for forbidden in ("/dev/", "/home", "/srv", "input12", "serial"):
        assert forbidden not in rendered


def test_plan_requires_resolved_roles() -> None:
    with pytest.raises(ValueError):
        make_permission_plan(make_ambiguous_roles(), "test:g2")
