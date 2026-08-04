"""Passive USB discovery using only allowlisted sysfs text attributes."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, cast

from streamdock_n3.device_catalog import (
    TARGET_USB_ID,
    find_known_usb_device,
    format_usb_id,
)
from streamdock_n3.hardware.contracts import HidInterface, RoleResolutionStatus
from streamdock_n3.hardware.interface_roles import (
    InterfaceRoleEvidence,
    classify_interface_role,
    resolve_roles,
)

DEFAULT_SYSFS_ROOT = Path("/sys/bus/usb/devices")
SYS_DEVICES_ROOT = Path("/sys/devices")
ALLOWED_DEVICE_ATTRIBUTES = frozenset({"idVendor", "idProduct", "bcdDevice"})
ALLOWED_INTERFACE_ATTRIBUTES = frozenset(
    {
        "bInterfaceNumber",
        "bInterfaceClass",
        "bInterfaceSubClass",
        "bInterfaceProtocol",
    }
)
ALLOWED_INPUT_ATTRIBUTES = frozenset({"ev", "key"})

_SAFE_SYSFS_NAME: Final = re.compile(r"[A-Za-z0-9._:-]+")
_INPUT_ASSOCIATION_RE: Final = re.compile(r"input[0-9]+")
_HEX_4: Final = re.compile(r"[0-9A-Fa-f]{1,4}")
_HEX_2: Final = re.compile(r"[0-9A-Fa-f]{1,2}")


class WarningCode(StrEnum):
    ROOT_UNAVAILABLE = "root_unavailable"
    INVALID_SYSFS_NAME = "invalid_sysfs_name"
    INCOMPLETE_USB_IDENTITY = "incomplete_usb_identity"
    INVALID_USB_IDENTITY = "invalid_usb_identity"
    MISSING_BCD_DEVICE = "missing_bcd_device"
    INVALID_BCD_DEVICE = "invalid_bcd_device"
    INCOMPLETE_HID_INTERFACE = "incomplete_hid_interface"
    INVALID_HID_INTERFACE = "invalid_hid_interface"
    UNSAFE_SYMLINK = "unsafe_symlink"
    UNREADABLE_ATTRIBUTE = "unreadable_attribute"


@dataclass(frozen=True, slots=True)
class DiscoveryWarning:
    code: WarningCode
    sysfs_name: str | None
    attribute: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "sysfs_name": self.sysfs_name,
            "attribute": self.attribute,
        }


@dataclass(frozen=True, slots=True)
class HidInterfaceObservation:
    number: str
    class_code: str
    subclass: str
    protocol: str
    input_associated: bool
    input_kind: str | None
    role: str
    role_basis: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "class": self.class_code,
            "subclass": self.subclass,
            "protocol": self.protocol,
            "input_associated": self.input_associated,
            "input_kind": self.input_kind,
            "role": self.role,
            "role_basis": list(self.role_basis),
        }


@dataclass(frozen=True, slots=True)
class UsbObservation:
    sysfs_name: str
    vid: str
    pid: str
    catalog_name: str
    catalog_match: bool
    target_match: bool
    identity_status: str
    protocol_status: str
    bcd_device: str | None
    interface_selection: str
    hid_interfaces: tuple[HidInterfaceObservation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "sysfs_name": self.sysfs_name,
            "vid": self.vid,
            "pid": self.pid,
            "catalog_name": self.catalog_name,
            "catalog_match": self.catalog_match,
            "target_match": self.target_match,
            "identity_status": self.identity_status,
            "protocol_status": self.protocol_status,
            "bcd_device": self.bcd_device,
            "interface_selection": self.interface_selection,
            "hid_interfaces": [item.to_dict() for item in self.hid_interfaces],
        }


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    devices: tuple[UsbObservation, ...]
    warnings: tuple[DiscoveryWarning, ...]
    root_available: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "target": {
                "vid": format_usb_id(TARGET_USB_ID[0]),
                "pid": format_usb_id(TARGET_USB_ID[1]),
            },
            "devices": [device.to_dict() for device in self.devices],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


def _warning(
    code: WarningCode, sysfs_name: str | None = None, attribute: str | None = None
) -> DiscoveryWarning:
    return DiscoveryWarning(code=code, sysfs_name=sysfs_name, attribute=attribute)


def _read_attribute(
    logical_entry: Path,
    resolved_entry: Path,
    attribute: str,
    allowed_attributes: frozenset[str],
    trusted_sysfs: bool,
    warnings: list[DiscoveryWarning],
) -> str | None:
    """Read one allowlisted regular attribute scoped to its resolved entry."""
    if attribute not in allowed_attributes:
        return None

    logical_attribute = logical_entry / attribute
    try:
        if logical_attribute.is_symlink():
            warnings.append(
                _warning(WarningCode.UNSAFE_SYMLINK, logical_entry.name, attribute)
            )
            return None
        try:
            resolved_attribute = logical_attribute.resolve(strict=True)
        except FileNotFoundError:
            return None
        if not resolved_attribute.is_relative_to(resolved_entry):
            warnings.append(
                _warning(WarningCode.UNSAFE_SYMLINK, logical_entry.name, attribute)
            )
            return None
        if not resolved_attribute.is_file():
            warnings.append(
                _warning(WarningCode.UNREADABLE_ATTRIBUTE, logical_entry.name, attribute)
            )
            return None
        if not trusted_sysfs and logical_entry != resolved_entry:
            warnings.append(
                _warning(WarningCode.UNSAFE_SYMLINK, logical_entry.name, attribute)
            )
            return None
        return logical_attribute.read_text(encoding="ascii")
    except (OSError, RuntimeError, UnicodeError):
        warnings.append(
            _warning(WarningCode.UNREADABLE_ATTRIBUTE, logical_entry.name, attribute)
        )
        return None


def _resolve_entry(
    entry: Path,
    *,
    trusted_sysfs: bool,
    trusted_parent: Path,
    warnings: list[DiscoveryWarning],
) -> Path | None:
    is_link = False
    try:
        is_link = entry.is_symlink()
        if is_link and not trusted_sysfs:
            warnings.append(_warning(WarningCode.UNSAFE_SYMLINK, entry.name))
            return None
        resolved = entry.resolve(strict=True)
        if not resolved.is_dir():
            return None
        if is_link and not resolved.is_relative_to(trusted_parent):
            warnings.append(_warning(WarningCode.UNSAFE_SYMLINK, entry.name))
            return None
        return resolved
    except (OSError, RuntimeError):
        if is_link:
            warnings.append(_warning(WarningCode.UNSAFE_SYMLINK, entry.name))
        return None


def _read_with_status(
    logical_entry: Path,
    resolved_entry: Path,
    attribute: str,
    allowed_attributes: frozenset[str],
    trusted_sysfs: bool,
    warnings: list[DiscoveryWarning],
) -> tuple[str | None, bool]:
    warning_count = len(warnings)
    value = _read_attribute(
        logical_entry,
        resolved_entry,
        attribute,
        allowed_attributes,
        trusted_sysfs,
        warnings,
    )
    return value, len(warnings) != warning_count


def _normalize_hex(value: str, pattern: re.Pattern[str], width: int) -> str | None:
    text = value.strip()
    if pattern.fullmatch(text) is None:
        return None
    return f"{int(text, 16):0{width}x}"


def _read_input_attribute(
    resolved_interface: Path,
    association: str,
    attribute: str,
    warnings: list[DiscoveryWarning],
) -> str | None:
    """Read one allowlisted capability bitmap scoped to its resolved interface."""
    if attribute not in ALLOWED_INPUT_ATTRIBUTES:
        return None
    logical = resolved_interface / "input" / association / "capabilities" / attribute
    try:
        if logical.is_symlink():
            warnings.append(_warning(WarningCode.UNSAFE_SYMLINK, association, attribute))
            return None
        resolved = logical.resolve(strict=True)
        if not resolved.is_relative_to(resolved_interface):
            warnings.append(_warning(WarningCode.UNSAFE_SYMLINK, association, attribute))
            return None
        if not resolved.is_file():
            warnings.append(_warning(WarningCode.UNREADABLE_ATTRIBUTE, association, attribute))
            return None
        return logical.read_text(encoding="ascii")
    except (OSError, RuntimeError, UnicodeError):
        warnings.append(_warning(WarningCode.UNREADABLE_ATTRIBUTE, association, attribute))
        return None


def _input_kind_from_bitmaps(ev: str | None, key: str | None) -> str | None:
    """Summarize input capabilities as 'keyboard', 'other', or None."""
    if ev is None:
        return None
    ev_tokens = ev.strip().split()
    if not ev_tokens:
        return None
    try:
        has_key_events = int(ev_tokens[0], 16) & (1 << 1)
    except ValueError:
        return None
    if not has_key_events:
        return "other"
    key_tokens = (key or "").strip().split()
    if not key_tokens:
        return None
    try:
        has_key_codes = any(int(token, 16) for token in key_tokens)
    except ValueError:
        return None
    return "keyboard" if has_key_codes else "other"


def _scan_input_association(
    resolved_interface: Path,
    warnings: list[DiscoveryWarning],
) -> tuple[bool, str | None]:
    """Return (input_associated, input_kind) from passive sysfs input data."""
    input_dir = resolved_interface / "input"
    try:
        if not input_dir.is_dir():
            return False, None
        associations = tuple(
            sorted(
                entry.name
                for entry in input_dir.iterdir()
                if _INPUT_ASSOCIATION_RE.fullmatch(entry.name)
            )
        )
    except (OSError, RuntimeError):
        return False, None
    if not associations:
        return False, None
    kinds: list[str | None] = []
    for association in associations:
        ev = _read_input_attribute(resolved_interface, association, "ev", warnings)
        key = _read_input_attribute(resolved_interface, association, "key", warnings)
        kinds.append(_input_kind_from_bitmaps(ev, key))
    if any(kind == "keyboard" for kind in kinds):
        return True, "keyboard"
    if any(kind == "other" for kind in kinds):
        return True, "other"
    return True, None


def _interface_selection(
    hid_interfaces: tuple[HidInterfaceObservation, ...],
) -> str:
    if not hid_interfaces:
        return "none"
    if len(hid_interfaces) < 2:
        return "ambiguous"
    resolution = resolve_roles(
        tuple(
            InterfaceRoleEvidence(
                HidInterface(
                    int(item.number, 16),
                    int(item.class_code, 16),
                    int(item.subclass, 16),
                    int(item.protocol, 16),
                ),
                item.input_associated,
                item.input_kind,
            )
            for item in hid_interfaces
        )
    )
    if resolution.status is RoleResolutionStatus.RESOLVED:
        return "resolved"
    return "ambiguous"


def _scan_hid_interfaces(
    device_entry: Path,
    resolved_device: Path,
    entries: tuple[Path, ...],
    trusted_sysfs: bool,
    warnings: list[DiscoveryWarning],
) -> tuple[HidInterfaceObservation, ...]:
    observations: list[HidInterfaceObservation] = []
    prefix = f"{device_entry.name}:"
    attributes = (
        "bInterfaceNumber",
        "bInterfaceClass",
        "bInterfaceSubClass",
        "bInterfaceProtocol",
    )

    for interface_entry in entries:
        if not interface_entry.name.startswith(prefix):
            continue
        resolved_interface = _resolve_entry(
            interface_entry,
            trusted_sysfs=trusted_sysfs,
            trusted_parent=resolved_device,
            warnings=warnings,
        )
        if resolved_interface is None:
            continue

        raw_values: list[str | None] = []
        had_read_failure = False
        for attribute in attributes:
            value, read_failed = _read_with_status(
                interface_entry,
                resolved_interface,
                attribute,
                ALLOWED_INTERFACE_ATTRIBUTES,
                trusted_sysfs,
                warnings,
            )
            raw_values.append(value)
            had_read_failure = had_read_failure or read_failed

        if any(value is None for value in raw_values):
            if not had_read_failure:
                missing_index = raw_values.index(None)
                warnings.append(
                    _warning(
                        WarningCode.INCOMPLETE_HID_INTERFACE,
                        interface_entry.name,
                        attributes[missing_index],
                    )
                )
            continue

        normalized = [
            _normalize_hex(value, _HEX_2, 2) if value is not None else None
            for value in raw_values
        ]
        if any(value is None for value in normalized):
            invalid_index = normalized.index(None)
            warnings.append(
                _warning(
                    WarningCode.INVALID_HID_INTERFACE,
                    interface_entry.name,
                    attributes[invalid_index],
                )
            )
            continue
        number, class_code, subclass, protocol = normalized
        if class_code != "03":
            continue
        assert number is not None
        assert subclass is not None
        assert protocol is not None
        input_associated, input_kind = _scan_input_association(resolved_interface, warnings)
        role = classify_interface_role(
            InterfaceRoleEvidence(
                HidInterface(
                    int(number, 16),
                    int(class_code, 16),
                    int(subclass, 16),
                    int(protocol, 16),
                ),
                input_associated,
                input_kind,
            )
        )
        observations.append(
            HidInterfaceObservation(
                number=number,
                class_code=class_code,
                subclass=subclass,
                protocol=protocol,
                input_associated=input_associated,
                input_kind=input_kind,
                role=role.role.value,
                role_basis=tuple(basis.value for basis in role.basis),
            )
        )

    return tuple(sorted(observations, key=lambda item: int(item.number, 16)))


def _sorted_warnings(
    warnings: list[DiscoveryWarning],
) -> tuple[DiscoveryWarning, ...]:
    return tuple(
        sorted(
            warnings,
            key=lambda item: (
                item.code.value,
                item.sysfs_name or "",
                item.attribute or "",
            ),
        )
    )


def _unavailable_report() -> DiscoveryReport:
    return DiscoveryReport(
        devices=(),
        warnings=(_warning(WarningCode.ROOT_UNAVAILABLE),),
        root_available=False,
    )


def discover_usb_devices(sysfs_root: Path = DEFAULT_SYSFS_ROOT) -> DiscoveryReport:
    """Scan allowlisted USB metadata without opening any device node."""
    warnings: list[DiscoveryWarning] = []
    try:
        resolved_root = sysfs_root.resolve(strict=True)
        if not resolved_root.is_dir():
            return _unavailable_report()
        entries = tuple(sorted(resolved_root.iterdir(), key=lambda item: item.name))
    except (OSError, RuntimeError):
        return _unavailable_report()

    trusted_sysfs = resolved_root == DEFAULT_SYSFS_ROOT
    resolved_devices: dict[Path, Path] = {}
    valid_entries: list[Path] = []
    for entry in entries:
        if _SAFE_SYSFS_NAME.fullmatch(entry.name) is None:
            warnings.append(_warning(WarningCode.INVALID_SYSFS_NAME))
            continue
        valid_entries.append(entry)
        if ":" in entry.name:
            continue
        resolved_entry = _resolve_entry(
            entry,
            trusted_sysfs=trusted_sysfs,
            trusted_parent=SYS_DEVICES_ROOT,
            warnings=warnings,
        )
        if resolved_entry is not None:
            resolved_devices[entry] = resolved_entry

    observations: list[UsbObservation] = []
    valid_entry_tuple = tuple(valid_entries)
    for entry in valid_entry_tuple:
        resolved_entry = resolved_devices.get(entry)
        if resolved_entry is None:
            continue
        raw_vid, vid_failed = _read_with_status(
            entry,
            resolved_entry,
            "idVendor",
            ALLOWED_DEVICE_ATTRIBUTES,
            trusted_sysfs,
            warnings,
        )
        raw_pid, pid_failed = _read_with_status(
            entry,
            resolved_entry,
            "idProduct",
            ALLOWED_DEVICE_ATTRIBUTES,
            trusted_sysfs,
            warnings,
        )
        if raw_vid is None and raw_pid is None:
            continue
        if raw_vid is None or raw_pid is None:
            if not (vid_failed or pid_failed):
                missing_attribute = "idVendor" if raw_vid is None else "idProduct"
                warnings.append(
                    _warning(
                        WarningCode.INCOMPLETE_USB_IDENTITY,
                        entry.name,
                        missing_attribute,
                    )
                )
            continue

        vid = _normalize_hex(raw_vid, _HEX_4, 4)
        pid = _normalize_hex(raw_pid, _HEX_4, 4)
        if vid is None or pid is None:
            warnings.append(_warning(WarningCode.INVALID_USB_IDENTITY, entry.name))
            continue
        catalog_entry = find_known_usb_device(vid, pid)
        if catalog_entry is None:
            continue

        raw_bcd, bcd_failed = _read_with_status(
            entry,
            resolved_entry,
            "bcdDevice",
            ALLOWED_DEVICE_ATTRIBUTES,
            trusted_sysfs,
            warnings,
        )
        bcd_device: str | None = None
        if raw_bcd is None:
            if not bcd_failed:
                warnings.append(
                    _warning(WarningCode.MISSING_BCD_DEVICE, entry.name, "bcdDevice")
                )
        else:
            bcd_device = _normalize_hex(raw_bcd, _HEX_4, 4)
            if bcd_device is None:
                warnings.append(
                    _warning(WarningCode.INVALID_BCD_DEVICE, entry.name, "bcdDevice")
                )

        hid_interfaces = _scan_hid_interfaces(
            entry,
            resolved_entry,
            valid_entry_tuple,
            trusted_sysfs,
            warnings,
        )
        interface_selection = _interface_selection(hid_interfaces)
        observations.append(
            UsbObservation(
                sysfs_name=entry.name,
                vid=vid,
                pid=pid,
                catalog_name=catalog_entry.catalog_name,
                catalog_match=True,
                target_match=(catalog_entry.vendor_id, catalog_entry.product_id)
                == TARGET_USB_ID,
                identity_status=catalog_entry.identity_status.value,
                protocol_status=catalog_entry.protocol_status.value,
                bcd_device=bcd_device,
                interface_selection=interface_selection,
                hid_interfaces=hid_interfaces,
            )
        )

    return DiscoveryReport(
        devices=tuple(
            sorted(
                observations,
                key=lambda item: (item.vid, item.pid, item.sysfs_name),
            )
        ),
        warnings=_sorted_warnings(warnings),
        root_available=True,
    )


def exit_code_for(report: DiscoveryReport) -> int:
    """Aggregate the process result using the versioned discovery precedence."""
    if not report.root_available:
        return 2
    if any(device.target_match and device.hid_interfaces for device in report.devices):
        return 0
    if any(device.target_match for device in report.devices):
        return 3
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Build the sysfs-only command-line parser without scanning hardware."""
    parser = argparse.ArgumentParser(
        prog="n3-ai-deck-detect",
        description=(
            "Inspect cataloged USB IDs using read-only sysfs metadata. This sysfs-only "
            "command does not confirm device identity or protocol compatibility."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the stable JSON discovery contract",
    )
    parser.add_argument(
        "--sysfs-root",
        type=Path,
        default=DEFAULT_SYSFS_ROOT,
        metavar="PATH",
        help="read USB metadata from PATH (default: /sys/bus/usb/devices)",
    )
    return parser


def render_human(report: DiscoveryReport) -> str:
    """Render a deterministic report containing only public schema fields."""
    lines = ["N3 AI Deck read-only sysfs discovery"]
    if not report.root_available:
        lines.append("Discovery root unavailable.")
    elif not report.devices:
        lines.append("No cataloged USB ID matches found.")

    for device in report.devices:
        protocol_line = (
            f"  protocol unvalidated ({device.protocol_status})"
            if device.protocol_status == "unvalidated"
            else f"  protocol status: {device.protocol_status}"
        )
        lines.extend(
            (
                f"USB ID match {device.vid}:{device.pid}: {device.catalog_name}",
                f"  sysfs name: {device.sysfs_name}",
                f"  identity not confirmed ({device.identity_status})",
                protocol_line,
                f"  bcdDevice: {device.bcd_device or 'unknown'}",
                f"  interface selection: {device.interface_selection}",
            )
        )
        if device.hid_interfaces:
            lines.append("  HID interfaces:")
            for interface in device.hid_interfaces:
                lines.append(
                    "    "
                    f"{interface.number}: class {interface.class_code}, "
                    f"subclass {interface.subclass}, protocol {interface.protocol}, "
                    f"role {interface.role}"
                )
        else:
            lines.append("  HID interfaces: none")

    if report.warnings:
        lines.append("Warnings:")
        for warning in report.warnings:
            detail = f" (attribute: {warning.attribute})" if warning.attribute else ""
            lines.append(f"  {warning.code.value}{detail}")

    lines.append(
        "Safety note: read-only sysfs discovery; identity not confirmed; "
        "protocol unvalidated and compatibility not established."
    )
    return "\n".join(lines)


def render_json(report: DiscoveryReport) -> str:
    """Render the stable, closed JSON discovery contract."""
    return json.dumps(report.to_dict(), ensure_ascii=True, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one passive sysfs scan and return the discovery contract exit code."""
    args = build_parser().parse_args(argv)
    sysfs_root = cast(Path, args.sysfs_root)
    use_json = cast(bool, args.json)
    report = discover_usb_devices(sysfs_root)
    print(render_json(report) if use_json else render_human(report))
    return exit_code_for(report)
