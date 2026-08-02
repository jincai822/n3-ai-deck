from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import streamdock_n3.discovery as discovery
from streamdock_n3.discovery import WarningCode, discover_usb_devices, exit_code_for


def write_attr(parent: Path, name: str, value: str) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    (parent / name).write_text(value + "\n", encoding="ascii")


def add_usb_device(
    root: Path, name: str, vid: str, pid: str, bcd: str | None = None
) -> Path:
    device = root / name
    write_attr(device, "idVendor", vid)
    write_attr(device, "idProduct", pid)
    if bcd is not None:
        write_attr(device, "bcdDevice", bcd)
    return device


def add_interface(
    root: Path,
    device_name: str,
    suffix: str,
    number: str,
    class_code: str,
    subclass: str,
    protocol: str,
) -> Path:
    interface = root / f"{device_name}:{suffix}"
    for name, value in (
        ("bInterfaceNumber", number),
        ("bInterfaceClass", class_code),
        ("bInterfaceSubClass", subclass),
        ("bInterfaceProtocol", protocol),
    ):
        write_attr(interface, name, value)
    return interface


def warning_codes(report: discovery.DiscoveryReport) -> list[str]:
    return [warning.code for warning in report.warnings]


def test_target_with_two_hid_interfaces_is_ambiguous(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "1-2", "6602", "1000", "0300")
    add_interface(tmp_path, "1-2", "1.0", "00", "03", "00", "00")
    add_interface(tmp_path, "1-2", "1.1", "01", "03", "01", "01")
    add_interface(tmp_path, "1-2", "1.2", "02", "ff", "00", "00")

    report = discover_usb_devices(tmp_path)

    assert len(report.devices) == 1
    observation = report.devices[0]
    assert observation.vid == "6602"
    assert observation.pid == "1000"
    assert observation.catalog_match is True
    assert observation.target_match is True
    assert observation.identity_status == "user_reported_candidate"
    assert observation.protocol_status == "unvalidated"
    assert observation.bcd_device == "0300"
    assert observation.interface_selection == "ambiguous"
    assert [item.number for item in observation.hid_interfaces] == ["00", "01"]
    assert exit_code_for(report) == 0


@pytest.mark.parametrize(
    ("with_hid", "selection", "expected_exit"),
    ((True, "unique", 0), (False, "none", 3)),
)
def test_target_interface_selection_and_exit_code(
    tmp_path: Path, with_hid: bool, selection: str, expected_exit: int
) -> None:
    add_usb_device(tmp_path, "2-1", "6602", "1000", "0300")
    if with_hid:
        add_interface(tmp_path, "2-1", "1.0", "00", "03", "00", "00")

    report = discover_usb_devices(tmp_path)

    assert report.devices[0].interface_selection == selection
    assert exit_code_for(report) == expected_exit


def test_any_usable_target_takes_exit_precedence(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "3-1", "6602", "1000", "0300")
    add_usb_device(tmp_path, "3-2", "6602", "1000", "0300")
    add_interface(tmp_path, "3-1", "1.0", "00", "03", "00", "00")

    report = discover_usb_devices(tmp_path)

    assert [item.interface_selection for item in report.devices] == ["unique", "none"]
    assert exit_code_for(report) == 0


def test_upstream_reference_is_reported_but_does_not_satisfy_target(
    tmp_path: Path,
) -> None:
    add_usb_device(tmp_path, "4-1", "6603", "1003", "0100")
    add_interface(tmp_path, "4-1", "1.0", "00", "03", "00", "00")

    report = discover_usb_devices(tmp_path)

    assert len(report.devices) == 1
    assert report.devices[0].catalog_name == "N3 upstream reference variant"
    assert report.devices[0].target_match is False
    assert exit_code_for(report) == 1


def test_unknown_usb_ids_are_silently_ignored(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "5-1", "6602", "1001", "0300")
    add_usb_device(tmp_path, "5-2", "6603", "1000", "0300")

    report = discover_usb_devices(tmp_path)

    assert report.devices == ()
    assert report.warnings == ()
    assert exit_code_for(report) == 1


def test_devices_and_interfaces_have_deterministic_numeric_order(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "z-device", "6603", "1003", "0001")
    add_usb_device(tmp_path, "b-device", "6602", "1000", "0002")
    add_usb_device(tmp_path, "a-device", "6602", "1000", "0003")
    add_interface(tmp_path, "a-device", "1.10", "0A", "03", "00", "00")
    add_interface(tmp_path, "a-device", "1.2", "02", "03", "00", "00")

    report = discover_usb_devices(tmp_path)

    assert [(item.vid, item.pid, item.sysfs_name) for item in report.devices] == [
        ("6602", "1000", "a-device"),
        ("6602", "1000", "b-device"),
        ("6603", "1003", "z-device"),
    ]
    assert [item.number for item in report.devices[0].hid_interfaces] == ["02", "0a"]


def test_raw_attributes_are_normalized(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "6-1", " 6602 ", " 1000 ", " 0ABC ")
    add_interface(tmp_path, "6-1", "1.0", " A ", " 3 ", " B ", " C ")

    observation = discover_usb_devices(tmp_path).devices[0]

    assert (observation.vid, observation.pid, observation.bcd_device) == (
        "6602",
        "1000",
        "0abc",
    )
    assert observation.hid_interfaces[0].to_dict() == {
        "number": "0a",
        "class": "03",
        "subclass": "0b",
        "protocol": "0c",
    }


def test_report_schema_is_closed_and_report_values_are_immutable(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "7-1", "6602", "1000", "0300")
    add_interface(tmp_path, "7-1", "1.0", "00", "03", "00", "00")

    report = discover_usb_devices(tmp_path)

    assert report.to_dict() == {
        "schema_version": 1,
        "target": {"vid": "6602", "pid": "1000"},
        "devices": [
            {
                "sysfs_name": "7-1",
                "vid": "6602",
                "pid": "1000",
                "catalog_name": "N3 V3.0 candidate (owner-reported)",
                "catalog_match": True,
                "target_match": True,
                "identity_status": "user_reported_candidate",
                "protocol_status": "unvalidated",
                "bcd_device": "0300",
                "interface_selection": "unique",
                "hid_interfaces": [
                    {"number": "00", "class": "03", "subclass": "00", "protocol": "00"}
                ],
            }
        ],
        "warnings": [],
    }
    assert report.root_available is True
    with pytest.raises(FrozenInstanceError):
        report.root_available = False  # type: ignore[misc]


def test_missing_usb_attributes_are_silent_only_when_both_are_absent(tmp_path: Path) -> None:
    (tmp_path / "ordinary-entry").mkdir()
    write_attr(tmp_path / "missing-product", "idVendor", "6602")
    write_attr(tmp_path / "missing-vendor", "idProduct", "1000")

    report = discover_usb_devices(tmp_path)

    assert warning_codes(report) == [
        WarningCode.INCOMPLETE_USB_IDENTITY,
        WarningCode.INCOMPLETE_USB_IDENTITY,
    ]
    assert {warning.attribute for warning in report.warnings} == {"idProduct", "idVendor"}


@pytest.mark.parametrize(
    ("vid", "pid"),
    (("xyz", "1000"), ("6602", "10000"), ("", "1000")),
)
def test_invalid_usb_identity_fails_closed(tmp_path: Path, vid: str, pid: str) -> None:
    add_usb_device(tmp_path, "8-1", vid, pid, "0300")

    report = discover_usb_devices(tmp_path)

    assert report.devices == ()
    assert warning_codes(report) == [WarningCode.INVALID_USB_IDENTITY]


@pytest.mark.parametrize(
    ("bcd", "expected_code", "expected_value"),
    ((None, WarningCode.MISSING_BCD_DEVICE, None), ("nope", WarningCode.INVALID_BCD_DEVICE, None)),
)
def test_missing_or_invalid_bcd_device_warns_without_dropping_match(
    tmp_path: Path, bcd: str | None, expected_code: WarningCode, expected_value: str | None
) -> None:
    add_usb_device(tmp_path, "9-1", "6602", "1000", bcd)

    report = discover_usb_devices(tmp_path)

    assert report.devices[0].bcd_device == expected_value
    assert warning_codes(report) == [expected_code]
    assert report.warnings[0].attribute == "bcdDevice"


def test_incomplete_hid_interface_warns_and_is_not_selected(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "10-1", "6602", "1000", "0300")
    interface = add_interface(tmp_path, "10-1", "1.0", "00", "03", "00", "00")
    (interface / "bInterfaceProtocol").unlink()

    report = discover_usb_devices(tmp_path)

    assert report.devices[0].hid_interfaces == ()
    assert warning_codes(report) == [WarningCode.INCOMPLETE_HID_INTERFACE]
    assert report.warnings[0].attribute == "bInterfaceProtocol"


@pytest.mark.parametrize("attribute", ("bInterfaceNumber", "bInterfaceClass", "bInterfaceSubClass", "bInterfaceProtocol"))
def test_invalid_hid_interface_warns_and_is_not_selected(
    tmp_path: Path, attribute: str
) -> None:
    add_usb_device(tmp_path, "11-1", "6602", "1000", "0300")
    interface = add_interface(tmp_path, "11-1", "1.0", "00", "03", "00", "00")
    write_attr(interface, attribute, "xyz")

    report = discover_usb_devices(tmp_path)

    assert report.devices[0].hid_interfaces == ()
    assert warning_codes(report) == [WarningCode.INVALID_HID_INTERFACE]
    assert report.warnings[0].attribute == attribute


def test_invalid_entry_name_is_not_echoed(tmp_path: Path) -> None:
    unsafe_name = "device\x1b[31m"
    add_usb_device(tmp_path, unsafe_name, "6602", "1000", "0300")

    report = discover_usb_devices(tmp_path)

    assert report.devices == ()
    assert warning_codes(report) == [WarningCode.INVALID_SYSFS_NAME]
    assert report.warnings[0].sysfs_name is None
    assert unsafe_name not in str(report.to_dict())


@pytest.mark.parametrize("failure", ("missing", "resolve", "iterdir"))
def test_unavailable_root_has_one_stable_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    root = tmp_path / "usb-root"
    if failure != "missing":
        root.mkdir()

    if failure == "resolve":
        original_resolve = Path.resolve

        def fail_exact_resolve(self: Path, *args: object, **kwargs: object) -> Path:
            if self == root:
                raise OSError("private path detail")
            return original_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "resolve", fail_exact_resolve)
    elif failure == "iterdir":
        original_iterdir = Path.iterdir

        def fail_exact_iterdir(self: Path):  # type: ignore[no-untyped-def]
            if self == root:
                raise PermissionError("private path detail")
            return original_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", fail_exact_iterdir)

    report = discover_usb_devices(root)

    assert report.root_available is False
    assert report.devices == ()
    assert [warning.to_dict() for warning in report.warnings] == [
        {"code": "root_unavailable", "sysfs_name": None, "attribute": None}
    ]
    assert exit_code_for(report) == 2


@pytest.mark.parametrize("target_location", ("inside", "outside"))
def test_strict_mode_rejects_device_directory_links(
    tmp_path: Path, target_location: str
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = (root / "backing") if target_location == "inside" else (tmp_path / "outside")
    add_usb_device(target.parent, target.name, "6602", "1000", "0300")
    (root / "linked-device").symlink_to(target, target_is_directory=True)

    report = discover_usb_devices(root)

    assert "linked-device" not in {item.sysfs_name for item in report.devices}
    assert any(
        warning.code is WarningCode.UNSAFE_SYMLINK
        and warning.sysfs_name == "linked-device"
        and warning.attribute is None
        for warning in report.warnings
    )


@pytest.mark.parametrize("target_location", ("inside", "outside"))
def test_strict_mode_rejects_interface_directory_links(
    tmp_path: Path, target_location: str
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    add_usb_device(root, "12-1", "6602", "1000", "0300")
    backing_root = root if target_location == "inside" else tmp_path
    backing = add_interface(backing_root, "backing", "1.0", "00", "03", "00", "00")
    (root / "12-1:1.0").symlink_to(backing, target_is_directory=True)

    report = discover_usb_devices(root)

    assert report.devices[0].hid_interfaces == ()
    assert any(
        warning.code is WarningCode.UNSAFE_SYMLINK
        and warning.sysfs_name == "12-1:1.0"
        and warning.attribute is None
        for warning in report.warnings
    )


@pytest.mark.parametrize("entry_kind", ("device", "interface"))
@pytest.mark.parametrize("target_location", ("inside", "outside"))
def test_strict_mode_rejects_attribute_file_links(
    tmp_path: Path, entry_kind: str, target_location: str
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    device = add_usb_device(root, "13-1", "6602", "1000", "0300")
    interface = add_interface(root, "13-1", "1.0", "00", "03", "00", "00")
    entry = device if entry_kind == "device" else interface
    attribute = "idVendor" if entry_kind == "device" else "bInterfaceClass"
    value = "6602" if entry_kind == "device" else "03"
    (entry / attribute).unlink()
    target = (
        entry / f"{attribute}.copy"
        if target_location == "inside"
        else tmp_path / f"{entry_kind}-{attribute}.copy"
    )
    target.write_text(value + "\n", encoding="ascii")
    (entry / attribute).symlink_to(target)

    report = discover_usb_devices(root)

    assert any(
        warning.code is WarningCode.UNSAFE_SYMLINK and warning.attribute == attribute
        for warning in report.warnings
    )
    if entry_kind == "interface":
        assert report.devices[0].hid_interfaces == ()
    else:
        assert report.devices == ()


def configure_trusted_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    bus_root = tmp_path / "bus" / "usb" / "devices"
    devices_root = tmp_path / "devices"
    bus_root.mkdir(parents=True)
    devices_root.mkdir()
    monkeypatch.setattr(discovery, "DEFAULT_SYSFS_ROOT", bus_root.resolve())
    monkeypatch.setattr(discovery, "SYS_DEVICES_ROOT", devices_root.resolve())
    return bus_root, devices_root


def test_trusted_mode_accepts_scoped_device_and_interface_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus_root, devices_root = configure_trusted_roots(tmp_path, monkeypatch)
    resolved_device = add_usb_device(devices_root / "pci0000:00", "14-1", "6602", "1000", "0300")
    resolved_interface = add_interface(
        resolved_device, "14-1", "1.0", "00", "03", "00", "00"
    )
    (bus_root / "14-1").symlink_to(resolved_device, target_is_directory=True)
    (bus_root / "14-1:1.0").symlink_to(resolved_interface, target_is_directory=True)

    report = discover_usb_devices(bus_root)

    assert len(report.devices) == 1
    assert report.devices[0].interface_selection == "unique"
    assert report.warnings == ()


def test_trusted_mode_rejects_device_link_outside_devices_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus_root, _ = configure_trusted_roots(tmp_path, monkeypatch)
    outside = add_usb_device(tmp_path / "outside", "15-1", "6602", "1000", "0300")
    (bus_root / "15-1").symlink_to(outside, target_is_directory=True)

    report = discover_usb_devices(bus_root)

    assert report.devices == ()
    assert warning_codes(report) == [WarningCode.UNSAFE_SYMLINK]


@pytest.mark.parametrize("target_location", ("other_device", "outside_devices"))
def test_trusted_mode_rejects_interface_link_outside_resolved_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_location: str
) -> None:
    bus_root, devices_root = configure_trusted_roots(tmp_path, monkeypatch)
    resolved_device = add_usb_device(devices_root, "16-1", "6602", "1000", "0300")
    interface_parent = (
        devices_root / "other-device"
        if target_location == "other_device"
        else tmp_path / "outside-devices"
    )
    outside_interface = add_interface(
        interface_parent, "16-1", "1.0", "00", "03", "00", "00"
    )
    (bus_root / "16-1").symlink_to(resolved_device, target_is_directory=True)
    (bus_root / "16-1:1.0").symlink_to(outside_interface, target_is_directory=True)

    report = discover_usb_devices(bus_root)

    assert report.devices[0].hid_interfaces == ()
    assert warning_codes(report) == [WarningCode.UNSAFE_SYMLINK]


@pytest.mark.parametrize("entry_kind", ("device", "interface"))
def test_trusted_mode_rejects_leaf_symlink_within_its_resolved_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_kind: str
) -> None:
    bus_root, devices_root = configure_trusted_roots(tmp_path, monkeypatch)
    resolved_device = add_usb_device(devices_root, "17-1", "6602", "1000", "0300")
    resolved_interface = add_interface(
        resolved_device, "17-1", "1.0", "00", "03", "00", "00"
    )
    (bus_root / "17-1").symlink_to(resolved_device, target_is_directory=True)
    (bus_root / "17-1:1.0").symlink_to(resolved_interface, target_is_directory=True)
    entry = resolved_device if entry_kind == "device" else resolved_interface
    attribute = "idVendor" if entry_kind == "device" else "bInterfaceClass"
    value = "6602" if entry_kind == "device" else "03"
    (entry / attribute).unlink()
    write_attr(entry, f"{attribute}.copy", value)
    (entry / attribute).symlink_to(entry / f"{attribute}.copy")

    report = discover_usb_devices(bus_root)

    assert any(
        warning.code is WarningCode.UNSAFE_SYMLINK and warning.attribute == attribute
        for warning in report.warnings
    )
    if entry_kind == "interface":
        assert report.devices[0].hid_interfaces == ()
    else:
        assert report.devices == ()


def test_unreadable_attribute_produces_stable_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = add_usb_device(tmp_path, "18-1", "6602", "1000", "0300")
    unreadable = device / "bcdDevice"
    original_read_text = Path.read_text

    def fail_exact_read(self: Path, *args: object, **kwargs: object) -> str:
        if self == unreadable:
            raise PermissionError("private path detail")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", fail_exact_read)

    report = discover_usb_devices(tmp_path)

    assert report.devices[0].bcd_device is None
    assert warning_codes(report) == [WarningCode.UNREADABLE_ATTRIBUTE]
    assert report.warnings[0].attribute == "bcdDevice"
