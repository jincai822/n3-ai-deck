"""Pure offline permission generators and staged install transaction for G2."""

from __future__ import annotations

from pathlib import Path

from streamdock_n3.hardware.contracts import (
    HidInterface,
    InterfaceRole,
    InterfaceRoleResolution,
    PermissionArtifact,
    PermissionKind,
    PermissionPlan,
    RoleResolutionStatus,
)

_FORBIDDEN_ROOTS = (Path("/etc"), Path("/usr"))


def temporary_acl_plan(role: InterfaceRole) -> PermissionArtifact:
    """Render the temporary single-node ACL plan for one approved role."""
    if role is InterfaceRole.INPUT:
        return PermissionArtifact(
            PermissionKind.TEMPORARY_ACL,
            "input",
            role,
            "setfacl -m u:{current_user}:rw {node}",
        )
    if role is InterfaceRole.CONTROL:
        return PermissionArtifact(
            PermissionKind.TEMPORARY_ACL,
            "hidraw",
            role,
            "setfacl -m u:{current_user}:rw {node}",
        )
    raise ValueError("UNKNOWN role cannot justify a permission artifact")


def persistent_rule(
    vendor_id: int,
    product_id: int,
    interface: HidInterface,
    role: InterfaceRole,
) -> PermissionArtifact:
    """Render the precise lazy udev rule template for one approved role."""
    if role is InterfaceRole.INPUT:
        subsystem_match = 'SUBSYSTEM=="input", KERNEL=="event*"'
        subsystem = "input"
    elif role is InterfaceRole.CONTROL:
        subsystem_match = 'SUBSYSTEM=="hidraw"'
        subsystem = "hidraw"
    else:
        raise ValueError("UNKNOWN role cannot justify a permission artifact")
    rendered = (
        f'{subsystem_match}, '
        f'ATTRS{{idVendor}}=="{vendor_id:04x}", '
        f'ATTRS{{idProduct}}=="{product_id:04x}", '
        f'ATTRS{{bInterfaceClass}}=="{interface.interface_class:02x}", '
        f'ATTRS{{bInterfaceSubClass}}=="{interface.subclass:02x}", '
        f'ATTRS{{bInterfaceProtocol}}=="{interface.protocol:02x}", '
        f'TAG+="uaccess"'
    )
    return PermissionArtifact(PermissionKind.PERSISTENT_RULE, subsystem, role, rendered)


def make_permission_plan(
    resolution: InterfaceRoleResolution,
    approval_reference: str,
) -> PermissionPlan:
    """Build the offline permission plan from the G1-approved role resolution."""
    if resolution.status is not RoleResolutionStatus.RESOLVED:
        raise ValueError("permission plan requires a RESOLVED role resolution")
    input_interface = resolution.input_interface
    control_interface = resolution.control_interface
    if input_interface is None or control_interface is None:
        raise ValueError("permission plan requires bound input and control interfaces")
    artifacts = (
        temporary_acl_plan(InterfaceRole.INPUT),
        temporary_acl_plan(InterfaceRole.CONTROL),
        persistent_rule(0x6602, 0x1000, input_interface, InterfaceRole.INPUT),
        persistent_rule(0x6602, 0x1000, control_interface, InterfaceRole.CONTROL),
    )
    return PermissionPlan(artifacts, approval_reference)


class InstallTransaction:
    """Stage and apply artifacts against one explicit target root, never the system."""

    def __init__(self, root: Path | None) -> None:
        if root is None:
            raise ValueError("install transaction requires an explicit target root")
        self._root = root
        if any(
            root == forbidden or root.is_relative_to(forbidden)
            for forbidden in _FORBIDDEN_ROOTS
        ):
            raise ValueError("install transaction must not target system roots")
        self._planned: list[tuple[PermissionArtifact, str]] = []
        self._snapshots: dict[str, bytes | None] = {}
        self._committed = False

    def plan_install(self, artifact: PermissionArtifact, filename: str) -> None:
        if not isinstance(artifact, PermissionArtifact):
            raise TypeError("artifact must be a PermissionArtifact")
        if not isinstance(filename, str) or not filename or "/" in filename:
            raise ValueError("filename must be a plain file name")
        self._planned.append((artifact, filename))

    def verify_target(self) -> list[str]:
        violations: list[str] = []
        for _artifact, filename in self._planned:
            target = self._root / filename
            if target.is_symlink():
                violations.append(f"{filename}: target is a symlink")
                continue
            if target.exists():
                self._snapshots[filename] = target.read_bytes()
                if not target.is_file():
                    violations.append(f"{filename}: target is not a regular file")
        return violations

    def diff(self) -> str:
        lines: list[str] = []
        for artifact, filename in self._planned:
            before = self._snapshots.get(filename)
            lines.append(f"{filename}: before={before!r} after={artifact.rendered.encode()!r}")
        return "\n".join(lines)

    def commit(self) -> None:
        if self._committed:
            raise ValueError("transaction already committed")
        if not self._planned:
            raise ValueError("nothing planned")
        violations = self.verify_target()
        if violations:
            raise ValueError("target verification failed: " + "; ".join(violations))
        self._root.mkdir(parents=True, exist_ok=True)
        for artifact, filename in self._planned:
            (self._root / filename).write_text(artifact.rendered + "\n", encoding="ascii")
        self._committed = True

    def rollback(self) -> None:
        if not self._committed:
            return
        failures: list[str] = []
        for _artifact, filename in self._planned:
            original = self._snapshots.get(filename)
            target = self._root / filename
            if original is None:
                target.unlink(missing_ok=True)
            else:
                try:
                    target.write_bytes(original)
                except OSError as error:
                    failures.append(f"{filename}: {error}")
        self._committed = False
        if failures:
            raise OSError("rollback incomplete: " + "; ".join(failures))
