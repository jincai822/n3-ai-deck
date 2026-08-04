from __future__ import annotations

from streamdock_n3.device_catalog import IdentityStatus, ProtocolStatus
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    CommandSpec,
    CommandStep,
    DeviceProfile,
    HidInterface,
    InterfaceRoleResolution,
    Operation,
    Stage,
    StageManifest,
)
from streamdock_n3.hardware.interface_roles import (
    InterfaceRoleEvidence,
    resolve_roles,
)

TEST_COMMIT = "0123456789abcdef"
TEST_INTERFACE = HidInterface(0, 3, 0, 0)
TEST_IMAGE = b"g0-test-image"


def make_profile() -> DeviceProfile:
    return DeviceProfile(
        vendor_id=0x6602,
        product_id=0x1000,
        bcd_device=0x0300,
        interface=TEST_INTERFACE,
        identity_status=IdentityStatus.USER_REPORTED_CANDIDATE,
        protocol_status=ProtocolStatus.UNVALIDATED,
        source_commit=TEST_COMMIT,
    )


def make_resolved_roles() -> InterfaceRoleResolution:
    return resolve_roles(
        (
            InterfaceRoleEvidence(HidInterface(0, 3, 0, 0), False, None),
            InterfaceRoleEvidence(HidInterface(1, 3, 1, 1), True, "keyboard"),
        )
    )


def make_ambiguous_roles() -> InterfaceRoleResolution:
    return resolve_roles(
        (
            InterfaceRoleEvidence(HidInterface(0, 3, 1, 1), True, "keyboard"),
            InterfaceRoleEvidence(HidInterface(1, 3, 1, 1), True, "keyboard"),
        )
    )


def make_swapped_roles() -> InterfaceRoleResolution:
    return resolve_roles(
        (
            InterfaceRoleEvidence(HidInterface(0, 3, 1, 1), True, "keyboard"),
            InterfaceRoleEvidence(HidInterface(1, 3, 0, 0), False, None),
        )
    )


def make_g1_manifest(ambiguous: bool = False) -> StageManifest:
    return make_manifest(
        Stage.G1_PROFILE,
        role_resolution=make_ambiguous_roles() if ambiguous else make_resolved_roles(),
    )


def make_incomplete_g1_manifest() -> StageManifest:
    return make_manifest(Stage.G1_PROFILE, role_resolution=None)


def command_spec(command: AdapterCommand) -> CommandSpec:
    return CommandSpec.from_command(command)


def command_step(
    forward: AdapterCommand,
    recovery: AdapterCommand | None = None,
) -> CommandStep:
    return CommandStep(
        command_spec(forward), command_spec(recovery) if recovery is not None else None
    )


def make_manifest(
    stage: Stage,
    steps: tuple[CommandStep, ...] | None = None,
    role_resolution: InterfaceRoleResolution | None = None,
) -> StageManifest:
    defaults = {
        Stage.G1_PROFILE: (command_step(AdapterCommand(Operation.APPROVE_PROFILE)),),
        Stage.G2_PERMISSION: (command_step(AdapterCommand(Operation.RECORD_PERMISSION)),),
        Stage.G3_INPUT: (command_step(AdapterCommand(Operation.OBSERVE_INPUTS)),),
        Stage.G4_INITIALIZATION: (command_step(AdapterCommand(Operation.INITIALIZE)),),
        Stage.G5_BRIGHTNESS: (
            command_step(
                AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),
                AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50),
            ),
        ),
        Stage.G6_ONE_LCD: (
            command_step(
                AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE),
                AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"g0-baseline"),
            ),
        ),
        Stage.G7_SIX_LCD: tuple(
            command_step(
                AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"test-{key}".encode()),
                AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"base-{key}".encode()),
            )
            for key in range(1, 7)
        ),
    }
    return StageManifest(
        stage=stage,
        commit=TEST_COMMIT,
        profile_digest=make_profile().digest(),
        interface=TEST_INTERFACE,
        steps=steps if steps is not None else defaults[stage],
        deadline_ms=600_000 if stage is Stage.G3_INPUT else 5_000,
        expected_result=f"{stage.value}-validated",
        recovery_plan=f"{stage.value}-recovery",
        approval_reference=f"test:{stage.value}",
        role_resolution=role_resolution,
    )
