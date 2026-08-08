# N3 V3.0 G2 Permission Plan Approval

| Field | Result |
|---|---|
| Date | 2026-08-04 |
| Approval reference | `owner:2026-08-04:g2` |
| Software commit | `00c8b78` |
| Source | G1-approved candidate roles: interface `01` (`03/01/01`) input, interface `00` (`03/00/00`) control |
| Plan digest | `40f3ab1c6be3149d0274839e258a240a9ee6cf3834f0a66109265acd1e5d075a` |

Approved offline artifacts (rendered, redacted):

| Kind | Subsystem | Role | Rendered |
|---|---|---|---|
| `temporary_acl` | `input` | `input` | `setfacl -m u:{current_user}:rw {node}` |
| `temporary_acl` | `hidraw` | `control` | `setfacl -m u:{current_user}:rw {node}` |
| `persistent_rule` | `input` | `input` | `SUBSYSTEM=="input", KERNEL=="event*", ATTRS{idVendor}=="6602", ATTRS{idProduct}=="1000", TAG+="uaccess"` |
| `persistent_rule` | `hidraw` | `control` | `SUBSYSTEM=="hidraw", ATTRS{idVendor}=="6602", ATTRS{idProduct}=="1000", TAG+="uaccess"` |

Boundary statements:

- This approval grants nothing. The artifacts are offline templates only; no
  ACL or udev rule was installed, no system file was written, and no permission
  command was executed.
- The persistent rules are lazy templates to be installed, if ever, only as a
  separate owner-gated manual action; the default first strategy remains a
  temporary single-node ACL for the current user.
- The `6602:1000` identifier remains an owner-reported candidate with
  unvalidated protocol; this record is not a compatibility claim.
- No serial, bus location, `/dev` name, username, or absolute path was read or
  recorded.
