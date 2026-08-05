# N3 V3.0 (6602:1000) Six-LCD Key Validation and Production Input Regression

| Field | Result |
|---|---|
| Date | 2026-08-05 |
| Tested commit | `46f962a` |
| Context | Follow-up to `2026-08-05-g4-g6-display-validation.md` (single-key image, shared-panel geometry probe) and `2026-08-05-g3-vendor-channel-input-observation.md` (input baseline). Same device, same owner-approved temporary ACL, same vendor HID channel |
| Scope | Owner-approved writes through production code paths only: frame-level `_frames_for_command` + `_HidrawTransport` for the init triple and six per-key `BAT` images; the production CLI `n3-ai-deck-observe-inputs --channel vendor --calibrate --press-only` for the input regression |
| Transport facts (from vendored SDK + disassembly) | Key image: `"CRT\0\0BAT"` + len(be32) + key(1–6) header, then raw JPEG bytes in ≤1024-byte output reports, no trailer; device counts bytes from the header length. Reports are unnumbered (Linux hidraw writes carry a leading `0x00`). This variant displays JPEG data as-is (no SDK −90° rotation) and anchors each image at its key window, overflowing into the shared panel instead of scaling |

## Production-code input regression (formal CLI)

1. **A/B experiment**: `VendorHidReadOnlyBackend` behind the formal CLI
   (`n3-ai-deck-observe-inputs --channel vendor --calibrate --press-only`)
   received **38 reports** while a bare script on the same node received
   **38 reports** under identical actuation — identical behavior, **38:38**.
2. **Real hardware reports observed through the CLI**: the round left button
   code `0x25` was received **19 times** through the formal CLI when the key
   was actually pressed during the capture window.
3. **Root cause of earlier zero-signal runs**: all earlier zero-signal runs of
   the formal CLI were caused by the operator not pressing keys during the
   capture window (operator confirmed). No code defect; the formal CLI and its
   `VendorHidReadOnlyBackend` are validated for input.

## G7 write validation (production code)

Frame-level writes used the production functions `_frames_for_command` and
`_HidrawTransport` (the frame pipeline of the production display path, not the
full transactional gate flow):

1. **Init triple** `CRT\0\0DIS`, `CRT\0\0LIG` (brightness), `CRT\0\0STP` — sent
   as in prior validated sessions; screens lit and the six LCD keys became
   responsive.
2. **Six per-key images** — one numbered color image per key (`"CRT\0\0BAT"`
   header + key 1–6), in three image-size iterations: **64×64 → 72×72 → 80×80**.

## Measured geometry conclusions

- Key window ≈ **64 × 72 px**; vertical gap between rows ≈ **24 px**.
- Images are **not scaled**; they overflow from an anchor point into the shared
  panel.
- 64×64 leaves an ~8 px gap around the window; 72×72 mostly covers it; 80×80
  gives no further improvement.
- Each key's anchor has individual **1–2 px deviations** (key 4 top edge, keys
  2/3/6 corners) — recorded as a follow-up per-key offset calibration task.
- `BGPIC` full-screen background **clears the screen on this variant — do not
  use it** (consistent with the G4–G6 record).

## Six-key display result

All six keys correctly displayed their own numbered color image — red 1,
orange 2, yellow 3, green 4, blue 5, purple 6 — with upright digits and **no
cross-key bleed**. **G7 passed.**

## Conclusions

- G7 (all six LCDs) is physically validated on `6602:1000` via production
  code paths with owner-approved minimal writes.
- The production input path (formal CLI + `VendorHidReadOnlyBackend`) is
  validated end-to-end on real hardware; earlier zero-signal runs were operator
  error, not a code bug.
- Follow-up (optimization, not required): per-key anchor offset calibration for
  the individual 1–2 px deviations.

## Constraints honored / redaction

- Every write was explicitly owner-approved before sending; all writes are
  non-persistent.
- No sudo beyond the owner-typed `setfacl`; no system changes.
- This record contains no serial, bus location, `/dev` node name, absolute
  path, or username. The owner's screen photos are kept outside the repository.
