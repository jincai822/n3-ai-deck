from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import cast

import pytest

from streamdock_n3.hardware.contracts import (
    AdapterCommand,
    AdapterState,
    ErrorCode,
    HidInterface,
    Operation,
    OperationResult,
    ResultStatus,
    Stage,
    StageManifest,
)
from streamdock_n3.hardware.gate import CapabilityGate, GateViolation
from tests.hardware_fixtures import TEST_COMMIT, TEST_IMAGE, make_manifest, make_profile


def make_gate(state: AdapterState) -> CapabilityGate:
    return CapabilityGate(state)


def commands_for(stage: Stage) -> tuple[AdapterCommand, ...]:
    commands = {
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
    return commands[stage]


def begin(gate: CapabilityGate, stage: Stage, commands: tuple[AdapterCommand, ...] | None = None) -> None:
    gate.begin(make_profile(), make_manifest(stage, commands), TEST_COMMIT)


def succeed(gate: CapabilityGate, command: AdapterCommand) -> None:
    gate.authorize(command)
    gate.record_result(OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, 0))


def test_g3_cannot_begin_before_profile_is_approved() -> None:
    gate = CapabilityGate()

    with pytest.raises(GateViolation) as raised:
        begin(gate, Stage.G3_INPUT)

    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED
    assert gate.state is AdapterState.CANDIDATE


@pytest.mark.parametrize(
    "mutation",
    (
        lambda manifest: replace(manifest, commit="fedcba9876543210"),
        lambda manifest: replace(manifest, profile_digest="0" * 64),
        lambda manifest: replace(manifest, interface=HidInterface(1, 3, 1, 1)),
    ),
)
def test_manifest_must_match_commit_profile_and_interface(
    mutation: Callable[[StageManifest], StageManifest],
) -> None:
    gate = make_gate(AdapterState.PROFILE_APPROVED)

    with pytest.raises(GateViolation) as raised:
        gate.begin(make_profile(), mutation(make_manifest(Stage.G3_INPUT)), TEST_COMMIT)

    assert raised.value.code is ErrorCode.MANIFEST_INVALID
    assert gate.state is AdapterState.PROFILE_APPROVED


def test_permission_gate_does_not_advance_capability_state() -> None:
    gate = make_gate(AdapterState.PROFILE_APPROVED)
    command = AdapterCommand(Operation.RECORD_PERMISSION)

    begin(gate, Stage.G2_PERMISSION)
    succeed(gate, command)

    assert gate.complete(manual_confirmation=True) is AdapterState.PROFILE_APPROVED


def test_command_absent_from_manifest_is_rejected_before_execution() -> None:
    gate = make_gate(AdapterState.PROFILE_APPROVED)
    begin(gate, Stage.G3_INPUT)

    with pytest.raises(GateViolation) as raised:
        gate.authorize(AdapterCommand(Operation.CLOSE_SESSION))

    assert raised.value.code is ErrorCode.OPERATION_NOT_ALLOWED


@pytest.mark.parametrize(
    ("stage", "commands", "unauthorized"),
    (
        (
            Stage.G5_BRIGHTNESS,
            (AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40),),
            AdapterCommand(Operation.SET_BRIGHTNESS, brightness=41),
        ),
        (
            Stage.G6_ONE_LCD,
            (AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE),),
            AdapterCommand(Operation.SET_KEY_IMAGE, key=2, image=TEST_IMAGE),
        ),
        (
            Stage.G6_ONE_LCD,
            (AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=TEST_IMAGE),),
            AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=b"different-image"),
        ),
    ),
)
def test_command_parameters_must_exactly_match_a_rule(
    stage: Stage,
    commands: tuple[AdapterCommand, ...],
    unauthorized: AdapterCommand,
) -> None:
    initial_state = {
        Stage.G5_BRIGHTNESS: AdapterState.INITIALIZATION_VALIDATED,
        Stage.G6_ONE_LCD: AdapterState.BRIGHTNESS_VALIDATED,
    }[stage]
    gate = make_gate(initial_state)
    begin(gate, stage, commands)

    with pytest.raises(GateViolation) as raised:
        gate.authorize(unauthorized)

    assert raised.value.code is ErrorCode.PARAMETER_NOT_ALLOWED


def test_rule_cannot_exceed_maximum_call_count() -> None:
    command = AdapterCommand(Operation.OBSERVE_INPUTS)
    gate = make_gate(AdapterState.PROFILE_APPROVED)
    begin(gate, Stage.G3_INPUT, (command,))

    gate.authorize(command)
    with pytest.raises(GateViolation) as raised:
        gate.authorize(command)

    assert raised.value.code is ErrorCode.CALL_LIMIT_EXCEEDED


def test_complete_requires_every_rule_minimum_call_count() -> None:
    first = AdapterCommand(Operation.SET_BRIGHTNESS, brightness=40)
    second = AdapterCommand(Operation.SET_BRIGHTNESS, brightness=50)
    gate = make_gate(AdapterState.INITIALIZATION_VALIDATED)
    begin(gate, Stage.G5_BRIGHTNESS, (first, second))
    succeed(gate, first)

    with pytest.raises(GateViolation) as raised:
        gate.complete(manual_confirmation=True)

    assert raised.value.code is ErrorCode.REQUIRED_CALL_MISSING
    succeed(gate, second)
    assert gate.complete(manual_confirmation=True) is AdapterState.BRIGHTNESS_VALIDATED


def test_completion_without_manual_confirmation_blocks_and_clears_session() -> None:
    gate = make_gate(AdapterState.PROFILE_APPROVED)
    begin(gate, Stage.G3_INPUT)

    assert gate.complete(manual_confirmation=False) is AdapterState.BLOCKED
    assert gate.session is None


@pytest.mark.parametrize("manual_confirmation", ("false", 1, object()))
def test_non_bool_confirmation_is_rejected_without_mutating_gate(
    manual_confirmation: object,
) -> None:
    gate = make_gate(AdapterState.CANDIDATE)
    command = AdapterCommand(Operation.APPROVE_PROFILE)
    begin(gate, Stage.G1_PROFILE)
    succeed(gate, command)
    session = gate.session
    assert session is not None
    call_counts = list(session.call_counts)

    with pytest.raises(GateViolation) as raised:
        gate.complete(cast(bool, manual_confirmation))

    assert raised.value.code is ErrorCode.PARAMETER_NOT_ALLOWED
    assert gate.state is AdapterState.CANDIDATE
    assert gate.session is session
    assert session.call_counts == call_counts


def test_non_success_result_blocks_and_clears_session() -> None:
    gate = make_gate(AdapterState.PROFILE_APPROVED)
    begin(gate, Stage.G3_INPUT)
    gate.authorize(AdapterCommand(Operation.OBSERVE_INPUTS))

    gate.record_result(OperationResult(ResultStatus.BACKEND_ERROR, ErrorCode.BACKEND_FAILURE, 0))

    assert gate.state is AdapterState.BLOCKED
    assert gate.session is None


@pytest.mark.parametrize(
    "state",
    (
        AdapterState.CANDIDATE,
        AdapterState.PROFILE_APPROVED,
        AdapterState.INPUT_VALIDATED,
        AdapterState.INITIALIZATION_VALIDATED,
        AdapterState.BRIGHTNESS_VALIDATED,
        AdapterState.ONE_LCD_VALIDATED,
    ),
)
def test_disconnect_moves_nonterminal_gate_to_disconnected_and_clears_session(state: AdapterState) -> None:
    gate = make_gate(state)

    assert gate.disconnect() is AdapterState.DISCONNECTED
    assert gate.session is None


@pytest.mark.parametrize("state", (AdapterState.BLOCKED, AdapterState.DISCONNECTED))
def test_terminal_gate_cannot_begin_another_stage(state: AdapterState) -> None:
    gate = make_gate(state)

    with pytest.raises(GateViolation) as raised:
        begin(gate, Stage.G1_PROFILE)

    assert raised.value.code is ErrorCode.STATE_NOT_ALLOWED
    assert gate.state is state


def test_approved_stages_advance_in_exact_sequence_with_permission_unchanged() -> None:
    gate = CapabilityGate()
    expected_states = (
        AdapterState.PROFILE_APPROVED,
        AdapterState.PROFILE_APPROVED,
        AdapterState.INPUT_VALIDATED,
        AdapterState.INITIALIZATION_VALIDATED,
        AdapterState.BRIGHTNESS_VALIDATED,
        AdapterState.ONE_LCD_VALIDATED,
        AdapterState.SIX_LCD_VALIDATED,
    )
    stages = (
        Stage.G1_PROFILE,
        Stage.G2_PERMISSION,
        Stage.G3_INPUT,
        Stage.G4_INITIALIZATION,
        Stage.G5_BRIGHTNESS,
        Stage.G6_ONE_LCD,
        Stage.G7_SIX_LCD,
    )

    states = []
    for stage in stages:
        commands = commands_for(stage)
        begin(gate, stage, commands)
        for command in commands:
            succeed(gate, command)
        states.append(gate.complete(manual_confirmation=True))

    assert tuple(states) == expected_states
