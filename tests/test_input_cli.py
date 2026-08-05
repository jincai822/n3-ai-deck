from __future__ import annotations

from pathlib import Path

from streamdock_n3.hardware.contracts import (
    ErrorCode,
    InputSessionResult,
    ObservedCode,
    OperationResult,
    ResultStatus,
)
from streamdock_n3.hardware.ipc import IpcSessionRequest, IpcSessionResponse
from streamdock_n3.input_cli import (
    NodeResolutionError,
    _load_key_map,
    build_parser,
    main,
    resolve_vendor_node,
    run_session_flow,
)
from tests.hardware_fixtures import make_session_spec, meeting_session_result


class FakeSessionRunner:
    def __init__(self, result: InputSessionResult | None = None) -> None:
        self.result = result if result is not None else meeting_session_result()
        self.calls = 0

    def run(self, request: IpcSessionRequest, timeout_ms: int) -> IpcSessionResponse:
        self.calls += 1
        return IpcSessionResponse(
            OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, timeout_ms),
            self.result,
        )


def test_session_flow_advances_g1_g2_g3_to_input_validated() -> None:
    runner = FakeSessionRunner()

    rendered = run_session_flow(
        "/dev/input/event12",
        make_session_spec().key_map,
        5_000,
        session_runner=runner,
    )

    assert runner.calls == 1
    assert rendered["state"] == "input_validated"
    assert rendered["status"] == "succeeded"
    assert rendered["session"] is not None


def test_session_flow_blocks_when_requirements_unmet() -> None:
    partial = meeting_session_result()
    counts = tuple(
        count if count.control_id != 1 else count.__class__(
            count.control_id, count.kind, 0, 0, 0, 0
        )
        for count in partial.counts
    )
    from dataclasses import replace

    unmet = replace(partial, counts=counts)
    runner = FakeSessionRunner(unmet)

    rendered = run_session_flow(
        "/dev/input/event12",
        make_session_spec().key_map,
        5_000,
        session_runner=runner,
    )

    assert rendered["state"] == "blocked"
    assert rendered["status"] == "succeeded"
    assert rendered["session"] is not None


def test_main_reports_node_resolution_failure(
    monkeypatch,
    capsys,
) -> None:
    def failing_resolve() -> str:
        raise NodeResolutionError("no node")

    monkeypatch.setattr("streamdock_n3.input_cli.resolve_input_node", failing_resolve)

    code = main(["--json"])

    assert code == 1
    assert "rejected" in capsys.readouterr().out


def test_parser_has_no_system_mutation_flags() -> None:
    parser = build_parser()

    actions = {
        option
        for action in parser._actions
        for option in action.option_strings
    }

    assert not {"--install", "--reload", "--systemctl", "--write"} & actions
    assert "--json" in actions
    assert "--duration-ms" in actions


def test_calibrate_flag_reports_distinct_codes() -> None:
    class CalibrationRunner:
        def run(self, request: IpcSessionRequest, timeout_ms: int) -> IpcSessionResponse:
            return IpcSessionResponse(
                OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, timeout_ms),
                InputSessionResult(
                    counts=(),
                    latency_p95_ms=5,
                    unknown_count=3,
                    disconnected=False,
                    mapping=(),
                    distinct_codes=(ObservedCode(1, 42), ObservedCode(1, 43)),
                ),
            )

    from streamdock_n3.input_cli import run_session_flow

    rendered = run_session_flow(
        "/dev/input/event12",
        make_session_spec().key_map,
        5_000,
        session_runner=CalibrationRunner(),
    )

    assert rendered["session"]["distinct_codes"] == [
        {"event_type": 1, "event_code": 42},
        {"event_type": 1, "event_code": 43},
    ]


def test_calibration_spec_validation_rejects_mixed_key_map() -> None:
    import pytest

    from streamdock_n3.hardware.contracts import InputSessionSpec
    from tests.hardware_fixtures import make_session_spec

    with pytest.raises(ValueError, match="empty key map"):
        InputSessionSpec(
            duration_ms=5_000,
            expected_press_count=10,
            expected_rotation_count=20,
            latency_p95_target_ms=250,
            disconnect_grace_ms=2_000,
            key_map=make_session_spec().key_map,
            calibration=True,
        )


def test_parser_exposes_channel_and_press_only_flags() -> None:
    parser = build_parser()

    actions = {
        option: action
        for action in parser._actions
        for option in action.option_strings
    }

    assert "--channel" in actions
    assert actions["--channel"].choices == ["evdev", "vendor"]
    assert parser.parse_args([]).channel == "evdev"
    assert parser.parse_args([]).press_only is False
    assert parser.parse_args(["--channel", "vendor", "--press-only"]).press_only is True


def test_session_flow_wires_press_only_into_spec() -> None:
    captured: list[IpcSessionRequest] = []

    class CapturingRunner:
        def run(self, request: IpcSessionRequest, timeout_ms: int) -> IpcSessionResponse:
            captured.append(request)
            return IpcSessionResponse(
                OperationResult(ResultStatus.SUCCEEDED, ErrorCode.NONE, timeout_ms),
                meeting_session_result(),
            )

    run_session_flow(
        "/dev/hidraw7",
        make_session_spec().key_map,
        5_000,
        session_runner=CapturingRunner(),
        press_only=True,
    )

    assert len(captured) == 1
    spec = captured[0].manifest.session_spec
    assert spec is not None
    assert spec.press_only is True
    assert captured[0].device_node == "/dev/hidraw7"


def test_load_key_map_defaults_to_artifact_for_vendor_channel() -> None:
    from streamdock_n3.hardware.input_session import VENDOR_EVENT_TYPE

    vendor_map = _load_key_map(None, "vendor")
    evdev_map = _load_key_map(None, "evdev")

    assert len(vendor_map.entries) == 18
    assert all(entry.event_type == VENDOR_EVENT_TYPE for entry in vendor_map.entries)
    assert evdev_map.entries == ()


def _make_vendor_sysfs(tmp_path: Path) -> tuple[Path, Path, Path]:
    devices_root = tmp_path / "devices"
    interface = devices_root / "usb1/1-2/1-2:1.0"
    hid_device = interface / "0003:6602:1000.0001"
    hid_device.mkdir(parents=True)
    (interface / "bInterfaceClass").write_text("03", encoding="ascii")
    (interface / "bInterfaceSubClass").write_text("00", encoding="ascii")
    (interface / "bInterfaceProtocol").write_text("00", encoding="ascii")
    (devices_root / "usb1/1-2/idVendor").write_text("6602", encoding="ascii")
    (devices_root / "usb1/1-2/idProduct").write_text("1000", encoding="ascii")
    sysfs_root = tmp_path / "sysfs"
    sysfs_root.mkdir()
    (sysfs_root / "1-2").symlink_to(devices_root / "usb1/1-2")
    (sysfs_root / "1-2:1.0").symlink_to(interface)
    hidraw_root = tmp_path / "hidraw"
    (hidraw_root / "hidraw7").mkdir(parents=True)
    (hidraw_root / "hidraw7/device").symlink_to(hid_device)
    return sysfs_root, devices_root, hidraw_root


def test_resolve_vendor_node_binds_hidraw_to_control_interface(tmp_path: Path) -> None:
    sysfs_root, devices_root, hidraw_root = _make_vendor_sysfs(tmp_path)

    node = resolve_vendor_node(sysfs_root, devices_root, hidraw_root)

    assert node == "/dev/hidraw7"


def test_resolve_vendor_node_rejects_unbound_hidraw_devices(tmp_path: Path) -> None:
    sysfs_root, devices_root, hidraw_root = _make_vendor_sysfs(tmp_path)
    outsider = tmp_path / "devices/other/hid"
    outsider.mkdir(parents=True)
    (hidraw_root / "hidraw8").mkdir()
    (hidraw_root / "hidraw8/device").symlink_to(outsider)

    node = resolve_vendor_node(sysfs_root, devices_root, hidraw_root)

    assert node == "/dev/hidraw7"
