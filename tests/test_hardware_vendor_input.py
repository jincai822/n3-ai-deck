from __future__ import annotations

import time
from pathlib import Path

import pytest

from streamdock_n3.hardware.contracts import (
    InputAction,
    InputKind,
    InputSessionSpec,
    KeyMap,
    KeyMapEntry,
    RawInputEvent,
)
from streamdock_n3.hardware.input_session import (
    VENDOR_EVENT_TYPE,
    VENDOR_REPORT_SIZE,
    InputFileHandle,
    InputSessionError,
    VendorHidReadOnlyBackend,
    parse_vendor_report,
    run_input_session,
)
from streamdock_n3.input_cli import _load_key_map

CALIBRATED_CODES = (
    0x01,
    0x02,
    0x03,
    0x04,
    0x05,
    0x06,
    0x25,
    0x30,
    0x31,
    0x33,
    0x34,
    0x35,
    0x90,
    0x91,
    0x60,
    0x61,
    0x50,
    0x51,
)


def vendor_report(code: int, state: int = 0x00) -> bytes:
    report = bytearray(VENDOR_REPORT_SIZE)
    report[9] = code
    report[10] = state
    return bytes(report)


def vendor_key_map() -> KeyMap:
    return KeyMap(
        (
            KeyMapEntry(VENDOR_EVENT_TYPE, 0x01, 1, InputKind.BUTTON, InputAction.PRESS),
            KeyMapEntry(VENDOR_EVENT_TYPE, 0x25, 7, InputKind.BUTTON, InputAction.PRESS),
            KeyMapEntry(VENDOR_EVENT_TYPE, 0x33, 1, InputKind.KNOB_PRESS, InputAction.PRESS),
            KeyMapEntry(VENDOR_EVENT_TYPE, 0x90, 1, InputKind.KNOB_ROTATE, InputAction.LEFT),
            KeyMapEntry(VENDOR_EVENT_TYPE, 0x91, 1, InputKind.KNOB_ROTATE, InputAction.RIGHT),
        )
    )


def vendor_spec(duration_ms: int = 60_000, **overrides: object) -> InputSessionSpec:
    values: dict[str, object] = dict(
        duration_ms=duration_ms,
        expected_press_count=2,
        expected_rotation_count=2,
        latency_p95_target_ms=250,
        disconnect_grace_ms=2_000,
        key_map=vendor_key_map(),
        press_only=True,
    )
    values.update(overrides)
    return InputSessionSpec(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("code", CALIBRATED_CODES)
def test_parser_maps_every_calibrated_code(code: int) -> None:
    event = parse_vendor_report(vendor_report(code), 123)

    assert event == RawInputEvent(VENDOR_EVENT_TYPE, code, 1, 123)


def test_parser_skips_write_ack_frames() -> None:
    assert parse_vendor_report(vendor_report(0xFF), 123) is None


@pytest.mark.parametrize(
    "report",
    (
        b"",
        bytes(VENDOR_REPORT_SIZE - 1),
        bytes(VENDOR_REPORT_SIZE + 1),
        bytes(8),
    ),
)
def test_parser_ignores_truncated_and_oversized_reports(report: bytes) -> None:
    assert parse_vendor_report(report, 123) is None


def test_parser_rejects_non_bytes_reports() -> None:
    assert parse_vendor_report("not-bytes", 123) is None  # type: ignore[arg-type]


def test_vendor_backend_reads_reports_until_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import select as select_module

    import streamdock_n3.hardware.input_session as input_session_module

    payloads = iter((vendor_report(0x01), vendor_report(0x90)))
    backend = VendorHidReadOnlyBackend()
    handle = InputFileHandle(999, opened_read_only=True)

    def fake_read(fd: int, size: int) -> bytes:
        try:
            return next(payloads)
        except StopIteration:
            return vendor_report(0xFF)

    monkeypatch.setattr(input_session_module.os, "read", fake_read)
    monkeypatch.setattr(
        select_module,
        "select",
        lambda *args, **kwargs: ([args[0][0]], [], []),
    )

    events = list(backend.read_events(handle, time.monotonic_ns() + 10**9))

    assert [(event.type, event.code, event.value) for event in events] == [
        (VENDOR_EVENT_TYPE, 0x01, 1),
        (VENDOR_EVENT_TYPE, 0x90, 1),
    ]


def test_vendor_backend_treats_empty_read_as_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import select as select_module

    import streamdock_n3.hardware.input_session as input_session_module

    backend = VendorHidReadOnlyBackend()
    handle = InputFileHandle(999, opened_read_only=True)

    monkeypatch.setattr(input_session_module.os, "read", lambda fd, size: b"")
    monkeypatch.setattr(
        select_module,
        "select",
        lambda *args, **kwargs: ([args[0][0]], [], []),
    )

    with pytest.raises(OSError):
        list(backend.read_events(handle, time.monotonic_ns() + 10**9))


def test_vendor_backend_open_failure_raises_session_classification() -> None:
    backend = VendorHidReadOnlyBackend()

    with pytest.raises(InputSessionError) as raised:
        run_input_session(vendor_spec(duration_ms=10), "/dev/nonexistent-hidraw", backend)

    assert raised.value.code.value in ("permission_denied", "backend_failure")


def test_key_map_resolves_vendor_rotation_direction_from_entry() -> None:
    key_map = vendor_key_map()

    left = key_map.lookup(RawInputEvent(VENDOR_EVENT_TYPE, 0x90, 1, 0))
    right = key_map.lookup(RawInputEvent(VENDOR_EVENT_TYPE, 0x91, 1, 0))

    assert left is not None and left[1] is InputAction.LEFT
    assert right is not None and right[1] is InputAction.RIGHT


def test_key_map_keeps_evdev_value_sign_behavior() -> None:
    evdev_entry = KeyMapEntry(3, 8, 1, InputKind.KNOB_ROTATE, InputAction.LEFT)
    key_map = KeyMap((evdev_entry,))

    assert key_map.lookup(RawInputEvent(3, 8, 1, 0)) == (evdev_entry, InputAction.LEFT)
    assert key_map.lookup(RawInputEvent(3, 8, -1, 0)) == (evdev_entry, InputAction.RIGHT)


def test_key_map_rejects_duplicate_vendor_type_code_pairs() -> None:
    with pytest.raises(ValueError, match="unique"):
        KeyMap(
            (
                KeyMapEntry(VENDOR_EVENT_TYPE, 0x90, 1, InputKind.KNOB_ROTATE, InputAction.LEFT),
                KeyMapEntry(VENDOR_EVENT_TYPE, 0x90, 1, InputKind.KNOB_ROTATE, InputAction.LEFT),
            )
        )


def vendor_events() -> list[RawInputEvent]:
    now = time.monotonic_ns()
    events: list[RawInputEvent] = []
    for code in (0x01, 0x25, 0x33):
        events.extend(RawInputEvent(VENDOR_EVENT_TYPE, code, 1, now) for _ in range(2))
    for code in (0x90, 0x91):
        events.extend(RawInputEvent(VENDOR_EVENT_TYPE, code, 1, now) for _ in range(2))
    return events


class FixtureVendorBackend:
    def __init__(self, events: list[RawInputEvent]) -> None:
        self.events = events
        self.calls: list[str] = []

    def open_read_only(self, node: str) -> InputFileHandle:
        self.calls.append(f"open:{node}")
        return InputFileHandle(999, opened_read_only=True)

    def read_events(
        self,
        handle: InputFileHandle,
        deadline_ns: int,
    ) -> object:
        self.calls.append("read")
        yield from self.events

    def close(self, handle: InputFileHandle) -> None:
        self.calls.append("close")


def test_press_only_session_meets_requirements_without_releases() -> None:
    backend = FixtureVendorBackend(vendor_events())

    result = run_input_session(vendor_spec(), "/dev/hidraw7", backend)

    assert result.disconnected is False
    assert all(count.release_count == 0 for count in result.counts)
    assert result.meets_requirements(vendor_spec()) is True
    assert backend.calls.count("close") == 1


def test_press_only_session_fails_when_release_counts_are_required() -> None:
    backend = FixtureVendorBackend(vendor_events())

    result = run_input_session(vendor_spec(), "/dev/hidraw7", backend)

    assert result.meets_requirements(vendor_spec(press_only=False)) is False


def test_press_only_session_still_enforces_press_and_rotation_counts() -> None:
    now = time.monotonic_ns()
    backend = FixtureVendorBackend(
        [RawInputEvent(VENDOR_EVENT_TYPE, 0x01, 1, now)],
    )

    result = run_input_session(vendor_spec(), "/dev/hidraw7", backend)

    assert result.meets_requirements(vendor_spec()) is False


KEY_MAP_ARTIFACT = (
    Path(__file__).resolve().parents[1] / "src/streamdock_n3/resources/keymaps/6602-1000.json"
)


def test_calibrated_key_map_artifact_matches_validated_codes() -> None:
    key_map = _load_key_map(KEY_MAP_ARTIFACT)

    assert len(key_map.entries) == 18
    assert all(entry.event_type == VENDOR_EVENT_TYPE for entry in key_map.entries)
    by_code = {entry.event_code: entry for entry in key_map.entries}
    expected = {
        **{code: (code, InputKind.BUTTON, InputAction.PRESS) for code in range(0x01, 0x07)},
        0x25: (7, InputKind.BUTTON, InputAction.PRESS),
        0x30: (8, InputKind.BUTTON, InputAction.PRESS),
        0x31: (9, InputKind.BUTTON, InputAction.PRESS),
        0x33: (1, InputKind.KNOB_PRESS, InputAction.PRESS),
        0x34: (2, InputKind.KNOB_PRESS, InputAction.PRESS),
        0x35: (3, InputKind.KNOB_PRESS, InputAction.PRESS),
        0x90: (1, InputKind.KNOB_ROTATE, InputAction.LEFT),
        0x91: (1, InputKind.KNOB_ROTATE, InputAction.RIGHT),
        0x60: (2, InputKind.KNOB_ROTATE, InputAction.LEFT),
        0x61: (2, InputKind.KNOB_ROTATE, InputAction.RIGHT),
        0x50: (3, InputKind.KNOB_ROTATE, InputAction.LEFT),
        0x51: (3, InputKind.KNOB_ROTATE, InputAction.RIGHT),
    }
    assert set(by_code) == set(expected)
    for code, (control_id, kind, press_action) in expected.items():
        entry = by_code[code]
        assert entry.control_id == control_id
        assert entry.kind is kind
        assert entry.press_action is press_action
