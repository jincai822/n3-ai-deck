# N3 V3.0 G3 Read-Only Input Observation — Blocked Evidence

| Field | Result |
|---|---|
| Date | 2026-08-05 |
| Tested commit | `5203ceb` |
| Commands | `uv run n3-ai-deck-observe-inputs --json --calibrate --duration-ms {30000,60000}` plus an independent raw `O_RDONLY` + `select` reader cross-check on the approved input node |
| Sessions run | 6 bounded read-only sessions (30 s, 30 s, 45 s raw, 60 s, 60 s raw, 60 s after cable swap with an explicit temporary ACL) |
| Events observed | **0** across all sessions (`distinct_codes: []`, `unknown_count: 0`, `disconnected: false`) |
| Physical actuation | Operator pressed LCD keys / round buttons and rotated / pressed knobs during the confirmed sessions (the 60 s raw cross-check, the first 60 s CLI session, and the post-ACL 60 s session); earlier sessions had unconfirmed actuation and are listed for completeness only |
| Cross-checks | USB cable swapped and device re-enumerated mid-test (result unchanged); after the replug the session user lacked node access, so the owner authorized the exact temporary command `sudo setfacl -m u:<user>:rw <node>` per the G2-approved template, read access was verified, and the session still observed zero events. The device works under Windows with the vendor driver installed (owner report), confirming the unit is functional and consistent with input requiring the vendor protocol path |
| Device identity strings | USB `6602:1000`, `bcdDevice 0300`; product string `HANVON UGEE CS06 for signing`, manufacturer `HANVON UGEE` — consistent with OEM firmware on the N3 V3.0 variant; the owner confirmed the physical unit is the N3 console |
| Interface topology | Unchanged from the G1 record: interface `00/03/00/00` (control), interface `01/03/01/01` (input, boot keyboard, single event node) |
| Permission changes | One owner-authorized temporary single-node ACL (`setfacl -m u:<user>:rw <node>`) after the replug, matching the G2-approved template; it is ephemeral (clears on unplug) and can be removed with `setfacl -b <node>`. No udev rules, no group changes, nothing else |
| Exit behavior | All sessions completed cleanly; CLI exit code `0`, no disconnect, no crash |

## Outcome

**G3 remains BLOCKED.** The approved candidate input interface (interface `01`,
boot keyboard, evdev) emitted zero input events while the operator physically
actuated the device's keys and knobs in two independent, confirmed sessions —
one through the approved `n3-ai-deck-observe-inputs` calibration path and one
through an independent raw reader on the same node.

This falsifies the G1 candidate assumption that key and knob input is observable
on the interface-`01` evdev node under read-only conditions. Input likely
requires the vendor HID path (interface `00` and/or interface `01`'s HID
report channel) and may additionally require an initialization exchange, which
is a hardware write and therefore outside the approved G3 boundary. This record
is evidence, not a protocol claim.

## Constraints honored

- Zero hardware writes: no init, no brightness, no LCD data, no heartbeat, no
  grab; only `O_RDONLY` reads on the approved input node.
- No vendored SDK or native transport was loaded; no legacy tools were run.
- No permission, group, or udev changes; no sudo.
- Redaction: no serial, bus location, `/dev` node name, absolute path, or
  username is recorded here.

## Recommended next decisions (owner)

1. Approve a revised G3 design: investigate the input path on the vendor HID
   interface under a read-only report listener, or
2. Approve reordering: run a minimal, separately-approved initialization gate
   (G4 subset) before input observation, if the device only reports input
   after init, or
3. Obtain vendor/community protocol documentation for the `6602:1000` variant
   to ground the next plan.
