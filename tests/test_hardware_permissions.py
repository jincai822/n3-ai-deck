from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamdock_n3.hardware.contracts import (
    InterfaceRole,
    PermissionArtifact,
    PermissionKind,
)
from streamdock_n3.hardware.permissions import (
    InstallTransaction,
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
        persistent_rule(0x6602, 0x1000, InterfaceRole.UNKNOWN)


def test_persistent_rule_is_exact_and_uaccess_only() -> None:
    rule = persistent_rule(0x6602, 0x1000, InterfaceRole.CONTROL)

    assert 'ATTRS{idVendor}=="6602"' in rule.rendered
    assert 'ATTRS{idProduct}=="1000"' in rule.rendered
    assert 'TAG+="uaccess"' in rule.rendered
    assert 'MODE="0666"' not in rule.rendered
    assert 'SUBSYSTEM=="hidraw"' in rule.rendered
    assert rule.role is InterfaceRole.CONTROL
    assert rule.subsystem == "hidraw"


def test_persistent_rule_is_usb_device_level_only() -> None:
    control = persistent_rule(0x6602, 0x1000, InterfaceRole.CONTROL)
    assert control.rendered == (
        'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="6602", '
        'ATTRS{idProduct}=="1000", TAG+="uaccess"'
    )
    for rendered in (
        control.rendered,
        persistent_rule(0x6602, 0x1000, InterfaceRole.INPUT).rendered,
    ):
        # A udev rule's ATTRS{} matches one parent device only: never mix the
        # usb_device-level idVendor/idProduct with usb_interface attributes.
        assert "bInterfaceClass" not in rendered
        assert "bInterfaceSubClass" not in rendered
        assert "bInterfaceProtocol" not in rendered


def test_persistent_input_rule_targets_input_event_subsystem() -> None:
    rule = persistent_rule(0x6602, 0x1000, InterfaceRole.INPUT)

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


def make_artifact(kind: str = "rule", subsystem: str = "input") -> PermissionArtifact:
    if kind == "rule":
        return persistent_rule(0x6602, 0x1000, InterfaceRole.INPUT)
    return temporary_acl_plan(InterfaceRole.INPUT)


def test_transaction_requires_explicit_root() -> None:
    with pytest.raises(ValueError, match="explicit target root"):
        InstallTransaction(None)


@pytest.mark.parametrize("root", ("/etc", "/usr", "/etc/udev", "/usr/lib"))
def test_transaction_rejects_system_roots(tmp_path: Path, root: str) -> None:
    with pytest.raises(ValueError, match="system roots"):
        InstallTransaction(Path(root))


def test_transaction_rejects_path_filenames(tmp_path: Path) -> None:
    transaction = InstallTransaction(tmp_path / "root")

    with pytest.raises(ValueError, match="plain file name"):
        transaction.plan_install(make_artifact(), "../escape")


def test_verify_target_reports_symlink_owner_and_content_violations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("secret\n", encoding="ascii")
    (root / "rule").symlink_to(outside)

    transaction = InstallTransaction(root)
    transaction.plan_install(make_artifact(), "rule")

    violations = transaction.verify_target()

    assert any("symlink" in violation for violation in violations)


def test_commit_writes_rendered_artifact_and_rollback_restores_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "99-n3.rules"
    target.write_text("original-bytes\n", encoding="ascii")

    transaction = InstallTransaction(root)
    artifact = make_artifact()
    transaction.plan_install(artifact, "99-n3.rules")
    assert transaction.verify_target() == []
    assert artifact.rendered.encode() in transaction.diff().encode()

    transaction.commit()

    assert target.read_text(encoding="ascii") == artifact.rendered + "\n"

    transaction.rollback()

    assert target.read_text(encoding="ascii") == "original-bytes\n"


def test_rollback_without_prior_file_removes_new_target(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    transaction = InstallTransaction(root)
    transaction.plan_install(make_artifact(), "99-n3.rules")
    transaction.commit()
    assert (root / "99-n3.rules").exists()

    transaction.rollback()

    assert not (root / "99-n3.rules").exists()


def test_commit_fails_on_verification_violations(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("x\n", encoding="ascii")
    (root / "rule").symlink_to(outside)

    transaction = InstallTransaction(root)
    transaction.plan_install(make_artifact(), "rule")

    with pytest.raises(ValueError, match="target verification failed"):
        transaction.commit()

    assert (root / "rule").is_symlink()


def test_commit_rejects_empty_plan_and_double_commit(tmp_path: Path) -> None:
    transaction = InstallTransaction(tmp_path / "root")

    with pytest.raises(ValueError, match="nothing planned"):
        transaction.commit()

    transaction.plan_install(make_artifact(), "rule")
    transaction.commit()

    with pytest.raises(ValueError, match="already committed"):
        transaction.commit()


def test_rollback_failure_is_reported_not_fabricated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "rule"
    target.write_text("original\n", encoding="ascii")
    transaction = InstallTransaction(root)
    transaction.plan_install(make_artifact(), "rule")
    transaction.commit()

    def failing_write_bytes(self: Path, data: bytes) -> None:
        del self, data
        raise OSError("simulated disk failure")

    monkeypatch.setattr(type(target), "write_bytes", failing_write_bytes)

    with pytest.raises(OSError, match="rollback incomplete"):
        transaction.rollback()


def test_no_write_occurs_without_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    calls: list[str] = []

    original = Path.write_text
    monkeypatch.setattr(
        Path,
        "write_text",
        lambda self, *args, **kwargs: calls.append(str(self)),
    )

    transaction = InstallTransaction(root)
    transaction.plan_install(make_artifact(), "rule")
    transaction.verify_target()

    assert calls == []
    original(root / "rule", "direct-check\n", encoding="ascii")
    monkeypatch.undo()
    assert (root / "rule").read_text(encoding="ascii") == "direct-check\n"
