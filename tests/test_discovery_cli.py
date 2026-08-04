from __future__ import annotations

import json
from pathlib import Path

import pytest

import streamdock_n3.discovery as discovery


def write_attr(parent: Path, name: str, value: str) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    (parent / name).write_text(value + "\n", encoding="ascii")


def add_target(root: Path, *, bcd: str | None = "0300", with_hid: bool = False) -> None:
    for name, value in (("idVendor", "6602"), ("idProduct", "1000")):
        write_attr(root / "1-2", name, value)
    if bcd is not None:
        write_attr(root / "1-2", "bcdDevice", bcd)
    if with_hid:
        for name, value in (
            ("bInterfaceNumber", "00"),
            ("bInterfaceClass", "03"),
            ("bInterfaceSubClass", "00"),
            ("bInterfaceProtocol", "00"),
        ):
            write_attr(root / "1-2:1.0", name, value)


def add_upstream_reference(root: Path) -> None:
    for name, value in (
        ("idVendor", "6603"),
        ("idProduct", "1003"),
        ("bcdDevice", "0100"),
    ):
        write_attr(root / "2-1", name, value)


def test_json_output_has_closed_deterministic_schema(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_target(tmp_path, bcd=None, with_hid=True)

    first_exit = discovery.main(["--sysfs-root", str(tmp_path), "--json"])
    first_output = capsys.readouterr().out
    second_exit = discovery.main(["--sysfs-root", str(tmp_path), "--json"])
    second_output = capsys.readouterr().out

    assert (first_exit, second_exit) == (0, 0)
    assert first_output == second_output
    payload = json.loads(first_output)
    assert tuple(payload) == ("schema_version", "target", "devices", "warnings")
    assert payload["target"] == {"vid": "6602", "pid": "1000"}
    assert payload["devices"][0]["bcd_device"] is None
    assert payload["warnings"] == [
        {
            "code": "missing_bcd_device",
            "sysfs_name": "1-2",
            "attribute": "bcdDevice",
        }
    ]
    assert set(payload["warnings"][0]) == {"code", "sysfs_name", "attribute"}


def test_human_output_is_explicitly_candidate_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_target(tmp_path, with_hid=True)

    assert discovery.main(["--sysfs-root", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "USB ID match" in output
    assert "identity not confirmed" in output
    assert "protocol unvalidated" in output
    assert "read-only sysfs" in output
    assert "supported" not in output.lower()


def test_json_output_reports_resolved_interface_roles(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_target(tmp_path, with_hid=True)
    boot = tmp_path / "1-2:1.1"
    for name, value in (
        ("bInterfaceNumber", "01"),
        ("bInterfaceClass", "03"),
        ("bInterfaceSubClass", "01"),
        ("bInterfaceProtocol", "01"),
    ):
        write_attr(boot, name, value)
    capabilities = boot / "input" / "input5" / "capabilities"
    capabilities.mkdir(parents=True)
    (capabilities / "ev").write_text("180000000000003f 0 0 0\n", encoding="ascii")
    (capabilities / "key").write_text("1 0 0 0\n", encoding="ascii")

    assert discovery.main(["--sysfs-root", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    device = payload["devices"][0]
    assert device["interface_selection"] == "resolved"
    roles = {item["number"]: item for item in device["hid_interfaces"]}
    assert roles["00"]["role"] == "control"
    assert roles["01"]["role"] == "input"
    assert "no_input_association" in roles["00"]["role_basis"]
    assert "boot_keyboard" in roles["01"]["role_basis"]


def test_upstream_reference_human_protocol_status_matches_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add_upstream_reference(tmp_path)

    assert discovery.main(["--sysfs-root", str(tmp_path)]) == 1
    human_output = capsys.readouterr().out
    assert discovery.main(["--sysfs-root", str(tmp_path), "--json"]) == 1
    json_output = json.loads(capsys.readouterr().out)

    assert json_output["devices"][0]["protocol_status"] == "upstream_reference"
    assert "protocol status: upstream_reference" in human_output
    assert "protocol unvalidated (upstream_reference)" not in human_output


@pytest.mark.parametrize(
    ("target", "with_hid", "expected_exit"),
    ((False, False, 1), (True, False, 3), (True, True, 0)),
)
def test_main_uses_discovery_exit_contract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    target: bool,
    with_hid: bool,
    expected_exit: int,
) -> None:
    if target:
        add_target(tmp_path, with_hid=with_hid)

    assert discovery.main(["--sysfs-root", str(tmp_path), "--json"]) == expected_exit
    json.loads(capsys.readouterr().out)


def test_unavailable_root_still_emits_json_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing_root = tmp_path / "missing"

    assert discovery.main(["--sysfs-root", str(missing_root), "--json"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert tuple(payload) == ("schema_version", "target", "devices", "warnings")
    assert payload["devices"] == []
    assert payload["warnings"] == [
        {"code": "root_unavailable", "sysfs_name": None, "attribute": None}
    ]


def test_invalid_argument_uses_standard_argparse_exit_code() -> None:
    with pytest.raises(SystemExit) as raised:
        discovery.main(["--not-a-real-option"])

    assert raised.value.code == 2


@pytest.mark.parametrize("json_output", (False, True))
def test_control_character_entry_name_is_never_echoed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    json_output: bool,
) -> None:
    unsafe_name = "device\x1b[31m"
    add_target(tmp_path / unsafe_name, with_hid=True)
    argv = ["--sysfs-root", str(tmp_path)]
    if json_output:
        argv.append("--json")

    assert discovery.main(argv) == 1

    output = capsys.readouterr().out
    assert unsafe_name not in output
    assert "\x1b" not in output
    assert "invalid_sysfs_name" in output


def test_main_scans_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = discovery.DiscoveryReport(devices=(), warnings=(), root_available=True)
    calls: list[Path] = []

    def fake_scanner(root: Path) -> discovery.DiscoveryReport:
        calls.append(root)
        return report

    monkeypatch.setattr(discovery, "discover_usb_devices", fake_scanner)

    assert discovery.main(["--sysfs-root", str(tmp_path), "--json"]) == 1
    capsys.readouterr()
    assert calls == [tmp_path]


def test_help_describes_sysfs_only_protocol_limit() -> None:
    help_text = discovery.build_parser().format_help().lower()

    assert "sysfs-only" in help_text
    assert "read-only" in help_text
    assert "does not confirm" in help_text
    assert "protocol" in help_text
