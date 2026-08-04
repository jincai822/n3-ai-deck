# N3 V3.0 G1 Profile Approval Evidence

| Field | Result |
|---|---|
| Date | 2026-08-04 |
| Tested commit | `9bfb5d4` |
| Command | `uv run n3-ai-deck-detect --json` (passive sysfs only) |
| Actual USB ID | `6602:1000` |
| Actual `bcdDevice` | `0300` |
| HID interfaces | `00/03/00/00`; `01/03/01/01` |
| Interface `00` role | `control` — basis `no_input_association`, `vendor_hid` |
| Interface `01` role | `input` — basis `boot_keyboard`, `input_subsystem` |
| Input association | Interface `01` owns a keyboard input device (`ev` carries `EV_KEY`, non-empty `key` bitmap); interface `00` has none |
| Interface selection | `resolved` |
| Exit code | `0` |

The approved command performed passive, read-only USB metadata discovery only.
It never opened `/dev`, never loaded the vendored SDK or native transport, never
changed permissions, and never wrote hardware. No serial, bus location, `/dev`
name, or absolute path was read or recorded.

G1 candidate profile decision:

- **Approval reference:** `owner:2026-08-04:g1-profile-approval`
- VID `6602`, PID `1000`, `bcdDevice` `0300`.
- Interface `01` (`03/01/01`) is the approved candidate input interface.
- Interface `00` (`03/00/00`) is the approved candidate control interface.
- These are approved candidate roles pending G3 physical validation. The
  `6602:1000` identifier remains a candidate with unvalidated protocol, and this
  record is not a compatibility claim.
