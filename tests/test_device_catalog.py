from __future__ import annotations

import pytest

from streamdock_n3.device_catalog import (
    KNOWN_USB_DEVICES,
    IdentityStatus,
    ProtocolStatus,
    find_known_usb_device,
    format_usb_id,
    normalize_usb_id,
)


def test_catalog_keeps_identity_and_protocol_evidence_separate() -> None:
    candidate = find_known_usb_device("6602", "1000")
    reference = find_known_usb_device(0x6603, 0x1003)

    assert candidate is not None
    assert candidate.catalog_name == "N3 V3.0 candidate (owner-reported)"
    assert candidate.identity_status is IdentityStatus.USER_REPORTED_CANDIDATE
    assert candidate.protocol_status is ProtocolStatus.UNVALIDATED
    assert reference is not None
    assert reference.identity_status is IdentityStatus.UPSTREAM_REFERENCE
    assert reference.protocol_status is ProtocolStatus.UPSTREAM_REFERENCE


@pytest.mark.parametrize(
    ("value", "normalized", "formatted"),
    ((0x2, 2, "0002"), ("6602", 0x6602, "6602"), (" 0XABCD ", 0xABCD, "abcd")),
)
def test_usb_ids_normalize_as_four_digit_hex(
    value: int | str, normalized: int, formatted: str
) -> None:
    assert normalize_usb_id(value) == normalized
    assert format_usb_id(value) == formatted


@pytest.mark.parametrize("value", (True, -1, 0x10000, "", "10000", "xyz", object()))
def test_invalid_usb_ids_fail_closed(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        normalize_usb_id(value)  # type: ignore[arg-type]


def test_catalog_has_no_duplicate_usb_ids() -> None:
    ids = [(item.vendor_id, item.product_id) for item in KNOWN_USB_DEVICES]
    assert len(ids) == len(set(ids))


def test_unknown_usb_id_is_not_promoted_to_known() -> None:
    assert find_known_usb_device("6602", "1001") is None
    assert find_known_usb_device("6603", "1000") is None
