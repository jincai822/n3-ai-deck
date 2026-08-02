"""Static USB device identities with independently tracked protocol evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

_HEX_USB_ID = re.compile(r"[0-9A-Fa-f]{1,4}")


def normalize_usb_id(value: int | str) -> int:
    """Convert a USB ID to an integer, accepting only 16-bit hexadecimal values."""
    if isinstance(value, bool):
        raise TypeError("USB ID must not be a boolean")
    if isinstance(value, int):
        if 0 <= value <= 0xFFFF:
            return value
        raise ValueError("USB ID must be between 0x0000 and 0xffff")
    if isinstance(value, str):
        text = value.strip()
        if text[:2].lower() == "0x":
            text = text[2:]
        if _HEX_USB_ID.fullmatch(text):
            return int(text, 16)
        raise ValueError("USB ID must contain one to four hexadecimal digits")
    raise TypeError("USB ID must be an integer or string")


def format_usb_id(value: int | str) -> str:
    """Format a USB ID as four lowercase hexadecimal digits."""
    return f"{normalize_usb_id(value):04x}"


class IdentityStatus(StrEnum):
    USER_REPORTED_CANDIDATE = "user_reported_candidate"
    UPSTREAM_REFERENCE = "upstream_reference"


class ProtocolStatus(StrEnum):
    UNVALIDATED = "unvalidated"
    UPSTREAM_REFERENCE = "upstream_reference"


@dataclass(frozen=True, slots=True)
class KnownUsbDevice:
    vendor_id: int
    product_id: int
    catalog_name: str
    identity_status: IdentityStatus
    protocol_status: ProtocolStatus

    def __post_init__(self) -> None:
        normalize_usb_id(self.vendor_id)
        normalize_usb_id(self.product_id)
        if not self.catalog_name.strip():
            raise ValueError("catalog_name must not be empty")


TARGET_USB_ID: Final = (0x6602, 0x1000)
KNOWN_USB_DEVICES: Final = (
    KnownUsbDevice(
        0x6602,
        0x1000,
        "N3 V3.0 candidate (owner-reported)",
        IdentityStatus.USER_REPORTED_CANDIDATE,
        ProtocolStatus.UNVALIDATED,
    ),
    KnownUsbDevice(
        0x6603,
        0x1003,
        "N3 upstream reference variant",
        IdentityStatus.UPSTREAM_REFERENCE,
        ProtocolStatus.UPSTREAM_REFERENCE,
    ),
)


def _build_known_usb_device_lookup() -> MappingProxyType[tuple[int, int], KnownUsbDevice]:
    lookup: dict[tuple[int, int], KnownUsbDevice] = {}
    for device in KNOWN_USB_DEVICES:
        key = (device.vendor_id, device.product_id)
        if key in lookup:
            raise ValueError(f"duplicate USB ID in catalog: {key!r}")
        lookup[key] = device
    return MappingProxyType(lookup)


_KNOWN_USB_DEVICE_LOOKUP = _build_known_usb_device_lookup()


def find_known_usb_device(vendor_id: int | str, product_id: int | str) -> KnownUsbDevice | None:
    """Return a catalog entry only for an exact known vendor/product ID pair."""
    key = (normalize_usb_id(vendor_id), normalize_usb_id(product_id))
    return _KNOWN_USB_DEVICE_LOOKUP.get(key)
