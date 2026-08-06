# Physical Validation Checklist

This checklist is the release gate named in [ROADMAP.md](../../ROADMAP.md) (M5:
"Publish reproducible artifacts only after CI and the physical validation
checklist pass"). It is a living document: it aggregates the dated evidence
records in this directory into one reviewable list, and each row is Pass only
while its evidence record stands. When hardware or the active-device code
changes, re-validate and update both the affected record and this checklist in
the same pass. All rows refer to the owner-reported `6602:1000` unit; nothing
here is a compatibility claim for any other identifier or for general
`6602:1000` support.

| Check | What was verified | Evidence | Status |
|---|---|---|---|
| M1 passive discovery | `n3-ai-deck-detect --json` reports the target `6602:1000` with expected `bcdDevice` `0300`, HID interface topology (`00/03/00/00`, `01/03/01/01`), and an `ambiguous` selection; sysfs-only, no hardware access. | [2026-08-03-n3-v3-read-only-discovery.md](./2026-08-03-n3-v3-read-only-discovery.md) | Pass |
| G1 candidate profile approval | Role classifier resolves interface `01` as `input` (boot keyboard) and interface `00` as `control` (vendor HID) from passive sysfs evidence; candidate profile and roles pinned. | [2026-08-04-g1-profile-approval.md](./2026-08-04-g1-profile-approval.md) | Pass |
| G2 offline permission plan | Offline temporary-ACL and persistent-udev templates matching exactly `6602:1000` for the input and hidraw subsystems; the approval grants nothing and installs nothing. | [2026-08-04-g2-permission-approval.md](./2026-08-04-g2-permission-approval.md) | Pass |
| G3 input observation — evdev path falsified | The boot-keyboard evdev interface emitted zero input during confirmed physical actuation across bounded read-only sessions; the evdev hypothesis is falsified, not the device. | [2026-08-05-g3-input-observation-blocked.md](./2026-08-05-g3-input-observation-blocked.md) | Pass |
| G3 input observation — vendor channel, all 12 controls | All 12 controls report over the vendor HID channel: round buttons and knob presses/rotations with zero writes, LCD keys after the minimal init sequence (DIS + LIG + STP). | [2026-08-05-g3-vendor-channel-input-observation.md](./2026-08-05-g3-vendor-channel-input-observation.md) | Pass |
| G4–G6 display — init, brightness, single LCD key image | Init trio, 50 % brightness, and a single 64×64 LCD key image display correctly over the vendor HID channel with owner-approved minimal writes. | [2026-08-05-g4-g6-display-validation.md](./2026-08-05-g4-g6-display-validation.md) | Pass |
| G7 — six LCDs and production input regression | All six keys display their own numbered color image with no cross-key bleed through the production frame pipeline; the production input path (formal CLI + vendor backend) is validated end-to-end (38:38 A/B). | [2026-08-05-g7-six-lcd-and-production-regression.md](./2026-08-05-g7-six-lcd-and-production-regression.md) | Pass |
| M3 action-engine smoke | The hardware-free engine resolves a physical `button.1.press` to the shipped zero-side-effect builtin; dry-run and real run return structured results with no hardware attached. | [2026-08-05-m3-action-engine-smoke.md](./2026-08-05-m3-action-engine-smoke.md) | Pass |
| M3 live dispatch — 23/23 | Foreground live CLI dispatches 23/23 physical LCD key presses through the action engine in real time (0 ms engine latency per event) with a clean bounded exit. | [2026-08-05-live-dispatch.md](./2026-08-05-live-dispatch.md) | Pass |
| M4 AI workflow — interleaved read+write and golden run | Interleaved reads and LCD state writes on the same node are validated; the golden run achieved 11/11 (target 10/10) with on-device running/success states and zero failures or timeouts. | [2026-08-05-m4-ai-workflow.md](./2026-08-05-m4-ai-workflow.md) | Pass |

## Overall status

All 10 checks pass as of **2026-08-05** on the owner-reported `6602:1000`
unit, including the negative G3 evdev result (which is established evidence,
not a defect).

## Known follow-ups (not release-blocking)

- Per-key LCD anchor offset calibration (individual 1–2 px deviations).
- G8 daemon-managed background wiring: auto-restart, auto-reconnect, and
  daemon-managed live dispatch.
- Vendored-SDK commercial redistribution review.

## Standing redaction note

This checklist, like every record it links, contains no serial number, bus
location, `/dev` node name, absolute path, or username; the owner's screen
photos are kept outside the repository.
