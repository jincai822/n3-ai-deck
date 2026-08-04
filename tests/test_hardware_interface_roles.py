from __future__ import annotations

import pytest

from streamdock_n3.hardware.contracts import (
    HidInterface,
    InterfaceRole,
    RoleBasis,
    RoleResolutionStatus,
)
from streamdock_n3.hardware.interface_roles import (
    InterfaceRoleEvidence,
    classify_interface_role,
    resolve_roles,
)


def test_boot_keyboard_class_is_input() -> None:
    evidence = InterfaceRoleEvidence(HidInterface(1, 3, 1, 1), True, "keyboard")
    role = classify_interface_role(evidence)
    assert role.role is InterfaceRole.INPUT
    assert RoleBasis.BOOT_KEYBOARD in role.basis


def test_input_subsystem_keyboard_without_boot_class_is_input() -> None:
    evidence = InterfaceRoleEvidence(HidInterface(1, 3, 0, 0), True, "keyboard")
    role = classify_interface_role(evidence)
    assert role.role is InterfaceRole.INPUT
    assert RoleBasis.INPUT_SUBSYSTEM in role.basis


def test_vendor_hid_without_input_association_is_control() -> None:
    evidence = InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None)
    role = classify_interface_role(evidence)
    assert role.role is InterfaceRole.CONTROL
    assert RoleBasis.VENDOR_HID in role.basis
    assert RoleBasis.NO_INPUT_ASSOCIATION in role.basis


def test_unknown_topology_is_unknown_role() -> None:
    evidence = InterfaceRoleEvidence(HidInterface(2, 3, 2, 0), False, None)
    role = classify_interface_role(evidence)
    assert role.role is InterfaceRole.UNKNOWN
    assert RoleBasis.HID_INTERFACE in role.basis


def test_boot_keyboard_without_input_association_is_still_input() -> None:
    evidence = InterfaceRoleEvidence(HidInterface(1, 3, 1, 1), False, None)
    role = classify_interface_role(evidence)
    assert role.role is InterfaceRole.INPUT
    assert RoleBasis.BOOT_KEYBOARD in role.basis


def test_m1_topology_resolves_input_and_control() -> None:
    evidence = (
        InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None),
        InterfaceRoleEvidence(HidInterface(1, 3, 1, 1), True, "keyboard"),
    )
    resolution = resolve_roles(evidence)
    assert resolution.status is RoleResolutionStatus.RESOLVED
    assert resolution.input_interface == HidInterface(1, 3, 1, 1)
    assert resolution.control_interface == HidInterface(0, 3, 0, 0)
    assert resolution.roles == (
        classify_interface_role(evidence[0]),
        classify_interface_role(evidence[1]),
    )


def test_two_input_candidates_are_ambiguous() -> None:
    evidence = (
        InterfaceRoleEvidence(HidInterface(0, 3, 1, 1), True, "keyboard"),
        InterfaceRoleEvidence(HidInterface(1, 3, 1, 1), True, "keyboard"),
    )
    resolution = resolve_roles(evidence)
    assert resolution.status is RoleResolutionStatus.AMBIGUOUS
    assert resolution.input_interface is None
    assert resolution.control_interface is None


def test_unknown_role_makes_resolution_ambiguous() -> None:
    evidence = (
        InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None),
        InterfaceRoleEvidence(HidInterface(2, 3, 0, 0), False, None),
    )
    assert resolve_roles(evidence).status is RoleResolutionStatus.AMBIGUOUS


def test_two_control_candidates_are_ambiguous() -> None:
    evidence = (
        InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None),
        InterfaceRoleEvidence(HidInterface(2, 3, 0, 0), False, None),
    )
    assert resolve_roles(evidence).status is RoleResolutionStatus.AMBIGUOUS


def test_zero_roles_are_invalid() -> None:
    with pytest.raises(ValueError):
        resolve_roles(())


def test_single_role_is_incomplete_and_invalid() -> None:
    with pytest.raises(ValueError):
        resolve_roles(
            (InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None),)
        )


def test_duplicate_interface_numbers_are_invalid() -> None:
    with pytest.raises(ValueError):
        resolve_roles(
            (
                InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None),
                InterfaceRoleEvidence(HidInterface(0, 3, 1, 1), True, "keyboard"),
            )
        )
