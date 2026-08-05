# N3 V3.0 (6602:1000) Display Validation — Init, Brightness, Single LCD Key Image

| Field | Result |
|---|---|
| Date | 2026-08-05 |
| Tested commit | `268528d` |
| Context | Follow-up to `2026-08-05-g3-vendor-channel-input-observation.md`. Same device, same owner-approved temporary ACL, same vendor HID channel |
| Scope | Owner-approved display writes: standard init sequence, brightness 50 %, one 64×64 JPEG to LCD key 1, one 320×240 background probe |
| Transport facts (from vendored SDK + disassembly) | Key image: `"CRT\0\0BAT"` + len(be32) + key(1–6) header, then raw JPEG bytes in ≤1024-byte output reports, no trailer; device counts bytes from the header length. Reports are unnumbered (Linux hidraw writes carry a leading `0x00`) |

## Approved writes and observed results (in order)

1. **Init trio** `CRT\0\0DIS`, `CRT\0\0LIG 00 00 32` (brightness 50 %), `CRT\0\0STP` — previously approved for G3b; screens lit with factory demo imagery. **G4/G5 behavior validated.**
2. **Key image, rotated −90°** (per SDK `key_image_format`): displayed **sideways** → this variant displays JPEG data as-is; the SDK's −90° rotation does not apply.
3. **Key image, unrotated 64×64 blue with white "1"** → displayed **upright and correct** on LCD key 1. **G6 behavior validated** (later fully covered the window after re-init; owner photo archived outside the repo).
4. **128×128 ruler probe to key 1** → visible through key 1's window (~64 px wide × ~72 px tall of the image) **and spilling into key 4's window** (~64 × 32 px below) → strong evidence that the six key windows are **regions of one shared display panel** (consistent with the HANVON UGEE CS06 signature-pad platform), not six independent displays.
5. **320×240 background probe** (`"CRT\0\0BGPIC"` + len(be32), chunked) → screen went **black**; the command cleared the framebuffer without rendering the image on this variant. Background/full-screen addressing therefore differs from the SDK's N3 assumptions and needs separate study (G7).
6. **Recovery**: init trio + key-1 image re-sent → key 1 again displays the test image perfectly; factory demo fragments visible on other keys. No persistent change; unplug restores factory state.

## Conclusions

- G4 (init), G5 (brightness), and G6 (single LCD key image) are physically validated on `6602:1000` via the vendor HID channel with owner-approved minimal writes.
- This variant: no image rotation needed; key images anchor at the key window and overflow into the shared panel rather than scaling; window pitch measured approximately 64 px wide × ~72 px tall per key region (needs exact mapping for G7).
- G7 (all six LCDs) is **not** validated: full-screen/background addressing on this variant behaves differently (`BGPIC` clears to black) and requires a revised plan — candidates: per-key `BAT` images once exact window geometry is known, or the `LOG`/frame-stream background paths.

## Constraints honored / redaction

- Every write was explicitly owner-approved before sending; all writes are non-persistent.
- No sudo beyond the owner-typed `setfacl`; no system changes.
- This record contains no serial, bus location, `/dev` node name, absolute path, or username. The owner's screen photo is kept outside the repository.
