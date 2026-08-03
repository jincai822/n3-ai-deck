from __future__ import annotations

from hashlib import sha256

from streamdock_n3.device_catalog import IdentityStatus, ProtocolStatus
from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    CommandRule,
    DeviceProfile,
    HidInterface,
    Operation,
    Stage,
    StageManifest,
)

TEST_COMMIT = "0123456789abcdef"
TEST_INTERFACE = HidInterface(0, 3, 0, 0)
TEST_IMAGE = b"g0-test-image"
TEST_IMAGE_DIGEST = sha256(TEST_IMAGE).hexdigest()


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


def command_rule(command: AdapterCommand, min_calls: int = 1, max_calls: int = 1) -> CommandRule:
    return CommandRule(
        operation=command.operation,
        min_calls=min_calls,
        max_calls=max_calls,
        brightness=command.brightness,
        key=command.key,
        image_sha256=command.image_digest(),
    )


def make_manifest(
    stage: Stage,
    commands: tuple[AdapterCommand, ...] | None = None,
) -> StageManifest:
    defaults = {
        Stage.G1_PROFILE: (AdapterCommand(Operation.APPROVE_PROFILE),),
        Stage.G2_PERMISSION: (AdapterCommand(Operation.RECORD_PERMISSION),),
        Stage.G3_INPUT: (AdapterCommand(Operation.OBSERVE_INPUTS),),
        Stage.G4_INITIALIZATION: (AdapterCommand(Operation.INITIALIZE),),
        Stage.G5_BRIGHTNESS: (
            AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),
            AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50),
        ),
        Stage.G6_ONE_LCD: (
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE),
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"g0-baseline"),
        ),
        Stage.G7_SIX_LCD: tuple(
            AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"test-{key}".encode())
            for key in range(1, 7)
        )
        + tuple(
            AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=f"base-{key}".encode())
            for key in range(1, 7)
        ),
    }
    selected = commands if commands is not None else defaults[stage]
    return StageManifest(
        stage=stage,
        commit=TEST_COMMIT,
        profile_digest=make_profile().digest(),
        interface=TEST_INTERFACE,
        allowed_commands=tuple(command_rule(command) for command in selected),
        deadline_ms=600_000 if stage is Stage.G3_INPUT else 5_000,
        expected_result=f"{stage.value}-validated",
        recovery_plan=f"{stage.value}-recovery",
        approval_reference=f"test:{stage.value}",
    )
