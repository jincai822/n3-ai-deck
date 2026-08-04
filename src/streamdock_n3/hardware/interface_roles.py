"""Pure interface-role classification and resolution for G1 profile approval."""

from __future__ import annotations

from dataclasses import dataclass

from streamdock_n3.hardware.contracts import (
    HidInterface,
    HidInterfaceRole,
    InterfaceRole,
    InterfaceRoleResolution,
    RoleBasis,
    RoleResolutionStatus,
)


@dataclass(frozen=True, slots=True)
class InterfaceRoleEvidence:
    interface: HidInterface
    input_associated: bool
    input_kind: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.interface, HidInterface):
            raise TypeError("interface must be a HidInterface")
        if not isinstance(self.input_associated, bool):
            raise TypeError("input_associated must be a bool")
        if self.input_kind not in (None, "keyboard", "other"):
            raise ValueError("input_kind must be None, 'keyboard', or 'other'")


_BOOT_KEYBOARD = (3, 1, 1)
_VENDOR_HID = (3, 0, 0)


def classify_interface_role(evidence: InterfaceRoleEvidence) -> HidInterfaceRole:
    """Classify one interface into INPUT, CONTROL, or UNKNOWN from passive evidence."""
    if not isinstance(evidence, InterfaceRoleEvidence):
        raise TypeError("evidence must be an InterfaceRoleEvidence")
    descriptor = (
        evidence.interface.interface_class,
        evidence.interface.subclass,
        evidence.interface.protocol,
    )
    if descriptor == _BOOT_KEYBOARD:
        return HidInterfaceRole(
            evidence.interface, InterfaceRole.INPUT, (RoleBasis.BOOT_KEYBOARD,)
        )
    if evidence.input_associated and evidence.input_kind == "keyboard":
        return HidInterfaceRole(
            evidence.interface, InterfaceRole.INPUT, (RoleBasis.INPUT_SUBSYSTEM,)
        )
    if descriptor == _VENDOR_HID and not evidence.input_associated:
        return HidInterfaceRole(
            evidence.interface,
            InterfaceRole.CONTROL,
            (RoleBasis.NO_INPUT_ASSOCIATION, RoleBasis.VENDOR_HID),
        )
    return HidInterfaceRole(
        evidence.interface,
        InterfaceRole.UNKNOWN,
        (RoleBasis.HID_INTERFACE,),
    )


def resolve_roles(
    evidence: tuple[InterfaceRoleEvidence, ...],
) -> InterfaceRoleResolution:
    """Resolve exactly one INPUT and one CONTROL interface, or report AMBIGUOUS."""
    if not isinstance(evidence, tuple) or not evidence:
        raise ValueError("evidence must be a non-empty tuple")
    if not all(isinstance(item, InterfaceRoleEvidence) for item in evidence):
        raise TypeError("evidence must contain InterfaceRoleEvidence values")
    roles = tuple(classify_interface_role(item) for item in evidence)
    input_roles = [role for role in roles if role.role is InterfaceRole.INPUT]
    control_roles = [role for role in roles if role.role is InterfaceRole.CONTROL]
    unknown_roles = [role for role in roles if role.role is InterfaceRole.UNKNOWN]
    if len(input_roles) == 1 and len(control_roles) == 1 and not unknown_roles:
        return InterfaceRoleResolution(
            roles,
            RoleResolutionStatus.RESOLVED,
            input_roles[0].interface,
            control_roles[0].interface,
        )
    return InterfaceRoleResolution(
        roles,
        RoleResolutionStatus.AMBIGUOUS,
        None,
        None,
    )
