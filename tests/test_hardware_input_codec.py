from __future__ import annotations

import struct

import pytest

from streamdock_n3.hardware.contracts import (
    InputAction,
    InputKind,
    KeyMap,
    KeyMapEntry,
    NormalizedInputEvent,
    RawInputEvent,
)
from streamdock_n3.hardware.input_session import (
    normalize_event,
    parse_raw_event,
)


def test_parse_raw_event_from_fixture_bytes() -> None:
    payload = struct.pack("qqHHi", 0, 123456, 1, 30, 1)

    raw = parse_raw_event(payload, monotonic_ns=42)

    assert raw.type == 1
    assert raw.code == 30
    assert raw.value == 1
    assert raw.monotonic_ns == 42


def test_parse_rejects_short_and_misaligned_payloads() -> None:
    with pytest.raises(ValueError):
        parse_raw_event(b"\x00" * 15, monotonic_ns=0)
    with pytest.raises(ValueError):
        parse_raw_event(b"\x00" * 25, monotonic_ns=0)


def test_key_map_rejects_duplicate_event_codes() -> None:
    with pytest.raises(ValueError):
        KeyMap(
            (
                KeyMapEntry(1, 30, 1, InputKind.BUTTON, InputAction.PRESS),
                KeyMapEntry(1, 30, 2, InputKind.BUTTON, InputAction.PRESS),
            )
        )


def test_key_map_lookup_maps_press_and_release() -> None:
    key_map = KeyMap((KeyMapEntry(1, 30, 1, InputKind.BUTTON, InputAction.PRESS),))

    press = key_map.lookup(RawInputEvent(1, 30, 1, 0))
    release = key_map.lookup(RawInputEvent(1, 30, 0, 0))

    assert press is not None
    entry, action = press
    assert entry.control_id == 1
    assert action is InputAction.PRESS
    assert release is not None
    assert release[1] is InputAction.RELEASE


def test_knob_rotation_direction_is_inferred_from_value() -> None:
    entry = KeyMapEntry(3, 8, 1, InputKind.KNOB_ROTATE, InputAction.LEFT)

    assert entry.action_for_value(1) is InputAction.LEFT
    assert entry.action_for_value(-1) is InputAction.RIGHT
    assert entry.action_for_value(0) is InputAction.LEFT


def test_normalize_event_returns_none_for_unmapped_codes() -> None:
    result = normalize_event(RawInputEvent(1, 999, 1, 0), KeyMap(()))

    assert result is None


def test_normalize_event_produces_contract_validated_event() -> None:
    key_map = KeyMap(
        (
            KeyMapEntry(1, 30, 1, InputKind.BUTTON, InputAction.PRESS),
            KeyMapEntry(3, 8, 1, InputKind.KNOB_ROTATE, InputAction.LEFT),
        )
    )

    button = normalize_event(RawInputEvent(1, 30, 1, 123), key_map)
    assert button == NormalizedInputEvent(InputKind.BUTTON, 1, InputAction.PRESS, 123)

    rotation = normalize_event(RawInputEvent(3, 8, -1, 124), key_map)
    assert rotation == NormalizedInputEvent(
        InputKind.KNOB_ROTATE, 1, InputAction.RIGHT, 124
    )
