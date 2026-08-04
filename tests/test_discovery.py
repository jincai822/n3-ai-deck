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


def add_input_association(
    interface: Path,
    name: str = "input5",
    ev: str = "180000000000003f 0 0 0",
    key: str = "1 0 0 0",
    nested_hid_dir: str | None = None,
) -> None:
    parent = interface / (nested_hid_dir or "")
    capabilities = parent / "input" / name / "capabilities"
    capabilities.mkdir(parents=True, exist_ok=True)
    (capabilities / "ev").write_text(ev + "\n", encoding="ascii")
    (capabilities / "key").write_text(key + "\n", encoding="ascii")


def warning_codes(report: discovery.DiscoveryReport) -> list[str]:
    return [warning.code for warning in report.warnings]


def test_target_with_two_hid_interfaces_resolves_roles(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "1-2", "6602", "1000", "0300")
    add_interface(tmp_path, "1-2", "1.0", "00", "03", "00", "00")
    input_interface = add_interface(tmp_path, "1-2", "1.1", "01", "03", "01", "01")
    add_input_association(input_interface)
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
    assert observation.interface_selection == "resolved"
    assert [item.number for item in observation.hid_interfaces] == ["00", "01"]
    control, input_role = observation.hid_interfaces
    assert control.role == "control"
    assert control.role_basis == ("no_input_association", "vendor_hid")
    assert control.input_associated is False
    assert control.input_kind is None
    assert input_role.role == "input"
    assert input_role.role_basis == ("boot_keyboard", "input_subsystem")
    assert input_role.input_associated is True
    assert input_role.input_kind == "keyboard"
    assert exit_code_for(report) == 0


def test_two_keyboard_input_associations_are_ambiguous(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "1-3", "6602", "1000", "0300")
    first = add_interface(tmp_path, "1-3", "1.0", "00", "03", "00", "00")
    second = add_interface(tmp_path, "1-3", "1.1", "01", "03", "01", "01")
    add_input_association(first)
    add_input_association(second)

    observation = discover_usb_devices(tmp_path).devices[0]

    assert observation.interface_selection == "ambiguous"
    assert [item.role for item in observation.hid_interfaces] == ["input", "input"]


def test_boot_keyboard_resolves_without_readable_capabilities(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "1-4", "6602", "1000", "0300")
    add_interface(tmp_path, "1-4", "1.0", "00", "03", "00", "00")
    input_interface = add_interface(tmp_path, "1-4", "1.1", "01", "03", "01", "01")
    (input_interface / "input" / "input5").mkdir(parents=True)

    observation = discover_usb_devices(tmp_path).devices[0]

    assert observation.interface_selection == "resolved"
    assert observation.hid_interfaces[1].role == "input"


def test_multiple_input_associations_any_keyboard_wins(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "1-5", "6602", "1000", "0300")
    add_interface(tmp_path, "1-5", "1.0", "00", "03", "00", "00")
    input_interface = add_interface(tmp_path, "1-5", "1.1", "01", "03", "01", "01")
    add_input_association(input_interface, name="input3", ev="0 0 0 0", key="0 0 0 0")
    add_input_association(input_interface, name="input9")

    observation = discover_usb_devices(tmp_path).devices[0]

    assert observation.hid_interfaces[1].input_associated is True
    assert observation.hid_interfaces[1].input_kind == "keyboard"
    assert observation.interface_selection == "resolved"


def test_nested_hid_device_input_association_is_detected(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "1-6", "6602", "1000", "0300")
    add_interface(tmp_path, "1-6", "1.0", "00", "03", "00", "00")
    input_interface = add_interface(tmp_path, "1-6", "1.1", "01", "03", "01", "01")
    add_input_association(input_interface, nested_hid_dir="0003:6602:1000.0010")

    observation = discover_usb_devices(tmp_path).devices[0]
    interface = observation.hid_interfaces[1]

    assert interface.input_associated is True
    assert interface.input_kind == "keyboard"
    assert interface.role == "input"
    assert interface.role_basis == ("boot_keyboard", "input_subsystem")


def test_non_hid_device_subdirectory_is_not_scanned_for_inputs(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "1-7", "6602", "1000", "0300")
    control = add_interface(tmp_path, "1-7", "1.0", "00", "03", "00", "00")
    add_input_association(control, nested_hid_dir="hidraw")
    add_interface(tmp_path, "1-7", "1.1", "01", "03", "01", "01")

    observation = discover_usb_devices(tmp_path).devices[0]

    assert observation.hid_interfaces[0].input_associated is False


def test_single_hid_interface_cannot_resolve_roles(tmp_path: Path) -> None:
    add_usb_device(tmp_path, "2-2", "6602", "1000", "0300")
    add_interface(tmp_path, "2-2", "1.0", "00", "03", "00", "00")

    report = discover_usb_devices(tmp_path)

    assert report.devices[0].interface_selection == "ambiguous"
    assert exit_code_for(report) == 0


@pytest.mark.parametrize(
    ("with_hid", "selection", "expected_exit"),
    ((True, "ambiguous", 0), (False, "none", 3)),
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

    assert [item.interface_selection for item in report.devices] == ["ambiguous", "none"]
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
        "input_associated": False,
        "input_kind": None,
        "role": "unknown",
        "role_basis": ["hid_interface"],
    }


def test_uppercase_usb_identity_with_surrounding_whitespace_is_valid_hex(
    tmp_path: Path,
) -> None:
    add_usb_device(tmp_path, "6-2", " ABCD ", " EF01 ", "0300")

    report = discover_usb_devices(tmp_path)

    assert report.devices == ()
    assert report.warnings == ()


@pytest.mark.parametrize(
    ("vid", "pid"),
    (("0x6602", "1000"), ("6602", "0X1000")),
)
def test_prefixed_usb_identity_is_invalid_sysfs_hex(
    tmp_path: Path, vid: str, pid: str
) -> None:
    add_usb_device(tmp_path, "6-3", vid, pid, "0300")

    report = discover_usb_devices(tmp_path)

    assert report.devices == ()
    assert warning_codes(report) == [WarningCode.INVALID_USB_IDENTITY]


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
                "interface_selection": "ambiguous",
                "hid_interfaces": [
                    {
                        "number": "00",
                        "class": "03",
                        "subclass": "00",
                        "protocol": "00",
                        "input_associated": False,
                        "input_kind": None,
                        "role": "control",
                        "role_basis": ["no_input_association", "vendor_hid"],
                    }
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


def test_symlink_loop_root_runtime_error_has_one_stable_unavailable_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "loop-root"
    root.symlink_to(root, target_is_directory=True)
    original_resolve = Path.resolve

    def raise_runtime_error_for_loop(
        self: Path, *args: object, **kwargs: object
    ) -> Path:
        if self == root:
            raise RuntimeError("private symlink loop detail")
        return original_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", raise_runtime_error_for_loop)

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
    assert report.devices[0].interface_selection == "ambiguous"
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


def test_trusted_out_of_scope_interface_is_never_read_as_a_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus_root, devices_root = configure_trusted_roots(tmp_path, monkeypatch)
    resolved_device = add_usb_device(devices_root, "20-1", "6602", "1000", "0300")
    other_device = add_usb_device(devices_root, "20-2", "6603", "1003", "0100")
    (bus_root / "20-1").symlink_to(resolved_device, target_is_directory=True)
    (bus_root / "20-1:1.0").symlink_to(other_device, target_is_directory=True)
    original_reader = discovery._read_attribute
    read_entries: list[str] = []

    def recording_reader(
        logical_entry: Path,
        resolved_entry: Path,
        attribute: str,
        allowed_attributes: frozenset[str],
        trusted_sysfs: bool,
        warnings: list[discovery.DiscoveryWarning],
    ) -> str | None:
        read_entries.append(logical_entry.name)
        return original_reader(
            logical_entry,
            resolved_entry,
            attribute,
            allowed_attributes,
            trusted_sysfs,
            warnings,
        )

    monkeypatch.setattr(discovery, "_read_attribute", recording_reader)

    report = discover_usb_devices(bus_root)

    assert [item.sysfs_name for item in report.devices] == ["20-1"]
    assert "20-1:1.0" not in read_entries
    assert [warning.to_dict() for warning in report.warnings] == [
        {"code": "unsafe_symlink", "sysfs_name": "20-1:1.0", "attribute": None}
    ]


@pytest.mark.parametrize("entry_kind", ("device", "interface"))
def test_trusted_mode_rejects_symlink_loop_entries_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry_kind: str
) -> None:
    bus_root, devices_root = configure_trusted_roots(tmp_path, monkeypatch)
    if entry_kind == "device":
        loop_entry = bus_root / "loop-device"
        expected_devices: list[str] = []
    else:
        resolved_device = add_usb_device(devices_root, "21-1", "6602", "1000", "0300")
        (bus_root / "21-1").symlink_to(resolved_device, target_is_directory=True)
        loop_entry = bus_root / "21-1:1.0"
        expected_devices = ["21-1"]
    loop_entry.symlink_to(loop_entry, target_is_directory=True)
    original_resolve = Path.resolve

    def raise_runtime_error_for_loop(
        self: Path, *args: object, **kwargs: object
    ) -> Path:
        if self == loop_entry:
            raise RuntimeError("private symlink loop detail")
        return original_resolve(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "resolve", raise_runtime_error_for_loop)

    report = discover_usb_devices(bus_root)

    assert [item.sysfs_name for item in report.devices] == expected_devices
    assert any(
        warning.code is WarningCode.UNSAFE_SYMLINK
        and warning.sysfs_name == loop_entry.name
        and warning.attribute is None
        for warning in report.warnings
    )


@pytest.mark.parametrize("entry_kind", ("device", "interface"))
@pytest.mark.parametrize(
    "target_location", ("inside_entry", "outside_entry", "outside_devices")
)
def test_trusted_mode_rejects_all_leaf_symlink_targets_without_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    entry_kind: str,
    target_location: str,
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
    if target_location == "inside_entry":
        target = entry / f"{attribute}.copy"
    elif target_location == "outside_entry":
        target = devices_root / "shared-attributes" / f"{entry_kind}-{attribute}"
    else:
        target = tmp_path / "outside-devices" / f"{entry_kind}-{attribute}"
    write_attr(target.parent, target.name, value)
    (entry / attribute).symlink_to(target)
    logical_entry = bus_root / ("17-1" if entry_kind == "device" else "17-1:1.0")
    logical_attribute = logical_entry / attribute
    original_read_text = Path.read_text
    read_attempts: list[Path] = []

    def recording_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == logical_attribute:
            read_attempts.append(self)
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", recording_read_text)

    report = discover_usb_devices(bus_root)

    assert any(
        warning.code is WarningCode.UNSAFE_SYMLINK and warning.attribute == attribute
        for warning in report.warnings
    )
    assert read_attempts == []
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
