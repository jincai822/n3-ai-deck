# N3 V3.0 (6602:1000) Vendor-Channel Input Observation — Evidence

| Field | Result |
|---|---|
| Date | 2026-08-05 |
| Tested commit | `5203ceb` |
| Context | Follow-up to `2026-08-05-g3-input-observation-blocked.md` (evdev path falsified). This record documents input observation over the **vendor HID interface** (interface `00`, usage page `0xFFA0/0xFFA1`, single 512-byte input report, 1024-byte output report, unnumbered reports) |
| Listener | Owner-approved raw `O_RDONLY` + `select` hidraw reader (no vendored SDK loaded); decode offsets `report[9]` = event code, `report[10]` = state, `0xFF` = write-ACK |
| Permission | Owner-authorized temporary single-node ACL (`setfacl -m u:<user>:rw <hidraw-node>`) per the G2-approved template; ephemeral (clears on unplug) |
| Device state | Functional under Windows with the vendor driver (owner report); unit confirmed physically to be the MiraBox N3 console (photo-verified layout: 6 LCD keys 3×2, 1 large + 2 small knobs, 3 round buttons) |

## Phase A — zero-write observation (approved as "G3a")

With **no writes of any kind**, the device spontaneously reported input on the
vendor channel. Reports carry an `ACK` prefix (`41 43 4B … 4F 4B`) and use
`report[9]`/ `report[10]` as documented in three independent sources (vendor
SDK `StreamDockN3.decode_input_event`, bitfocus companion module, mirajazz).

Observed with zero writes:

- Round buttons: `0x25`, `0x30`, `0x31`
- Knob presses: `0x33`, `0x34`, `0x35`
- Knob rotations: `0x90/0x91`, `0x60/0x61`, `0x50/0x51`
- **LCD keys (`0x01`–`0x06`): silent** across multiple confirmed-actuation
  sessions, both before and after the screen-wake command alone.

## Phase B — owner-approved minimal init writes (approved as "G3b")

The owner explicitly approved, in order, each exact write before it was sent:

1. `CRT\0\0DIS` (wake screen; 8-byte payload + report-ID `0x00`, zero-padded to
   the 1024-byte output report) — device screens lit up and showed imagery.
   LCD keys remained silent.
2. `CRT\0\0LIG 00 00 32` (brightness 50 %) and `CRT\0\0STP` (refresh) — after
   this standard init pair, **all six LCD keys began reporting** `0x01`–`0x06`.

No images, no clears, no heartbeats, no mode changes were sent. All writes are
non-persistent; unplugging restores the default state.

## Calibrated physical map (timestamped session)

| Physical control | Code(s) | Notes |
|---|---|---|
| LCD keys 1–6 (reading order) | `0x01`–`0x06` | Require the init sequence above before reporting |
| Round button — left | `0x25` | Spontaneous |
| Round button — middle | `0x30` | Spontaneous |
| Round button — right | `0x31` | Spontaneous |
| Small knob — left: rotate | `0x90` left / `0x91` right | Spontaneous |
| Small knob — left: press | `0x33` | Spontaneous |
| Small knob — right: rotate | `0x60` left / `0x61` right | Spontaneous |
| Small knob — right: press | `0x34` | Spontaneous |
| Large knob: rotate | `0x50` left / `0x51` right | Spontaneous |
| Large knob: press | `0x35` | Spontaneous |

Codes match the known N3-family table exactly.

## Protocol characteristics of this variant (6602:1000)

- Press-only semantics: every observed report carried state `0x00`; no release
  events were observed for buttons or knob presses (pv2-like behavior).
- Input report length 512 bytes; events at fixed offsets `report[9]`/`[10]`.
- Input flows on the vendor HID interface only; the boot-keyboard interface
  (interface `01`, evdev) emitted nothing under any tested condition.

## Conclusions

1. The input path of `6602:1000` is physically validated end-to-end for all 12
   controls via the vendor HID channel — not via the G1-approved evdev
   candidate interface (see the blocked record).
2. Round buttons and knobs report with zero writes; LCD keys require the
   minimal init sequence (`DIS` + `LIG` + `STP`) before reporting.
3. G3's acceptance intent (input validated with evidence) is met through this
   revised path; the G1 candidate profile and the G3 gate design need revision
   to adopt the vendor channel plus the minimal init writes as the approved
   input path. ROADMAP/checkbox updates await owner decision.

## Constraints honored / redaction

- Every write was individually and explicitly owner-approved before sending;
  approvals are recorded in the session transcript.
- No sudo beyond the owner-typed `setfacl`; no udev changes; no persistent
  system state.
- This record contains no serial, bus location, `/dev` node name, absolute
  path, or username.
