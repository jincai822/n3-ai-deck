# M2 Vendor-Channel Backend Design

**Date:** 2026-08-05
**Status:** Draft for owner review
**Supersedes (partially):** the evdev input path assumed by
`2026-08-03-m2-hardware-controls-design.md` and
`2026-08-04-m2-g3-input-observation.md`
**Evidence base:** `docs/validation/2026-08-05-g3-input-observation-blocked.md`,
`docs/validation/2026-08-05-g3-vendor-channel-input-observation.md`,
`docs/validation/2026-08-05-g4-g6-display-validation.md`

## 1. Why this design exists

Real-device validation on 2026-08-05 falsified the G1 candidate assumption
that input is observable on the interface-`01` evdev node: six bounded
read-only sessions observed zero events there. Input and display control
actually flow over the **vendor HID interface** (interface `00`, usage page
`0xFFA0/0xFFA1`, unnumbered 512-byte input reports, 1024-byte output reports,
`report[9]` = event code, `report[10]` = state, `0xFF` = write-ACK).

This design folds that validated path into the formal `hardware/` architecture
(Adapter + capability gate + isolated helper) with minimal intrusion. The
transactional safety model is unchanged; only the transport backends, node
resolution, and a small number of shape validators gain a vendor-channel
variant.

## 2. Validated protocol facts (ground truth for implementation)

- Input events arrive spontaneously for round buttons and knobs
  (`0x25/0x30/0x31`, `0x33/0x34/0x35`, `0x90/0x91`, `0x60/0x61`, `0x50/0x51`).
- LCD keys (`0x01`–`0x06`) report only after the init trio
  `CRT\0\0DIS`, `CRT\0\0LIG 00 00 <level>`, `CRT\0\0STP`.
- This variant is **press-only**: state byte is always `0x00`; no release
  events exist. Rotation direction is encoded in the code itself.
- Key image: `"CRT\0\0BAT"` + len(be32) + key(1–6) header, then raw JPEG in
  ≤1024-byte output reports; no trailer; no image rotation on this variant.
- Linux hidraw writes carry a leading `0x00` report-ID byte; output report
  payload is 1024 bytes.
- `CRT\0\0BGPIC` (full-screen background) clears the panel to black on this
  variant — **out of scope**; G7 uses per-key `BAT` writes only.

## 3. Scope

**In scope (M2 completion):**
1. Passive hidraw node discovery bound to the approved control interface.
2. A vendor-channel `ReadOnlyInputBackend` (G3 revised path) incl. press-only
   session semantics and the calibrated key map for `6602:1000`.
3. A vendor-channel command `Backend` for `INITIALIZE`, `SET_BRIGHTNESS`,
   `SET_KEY_IMAGE` (G4–G6), executed inside the isolated helper process.
4. Tests first (RED→GREEN), fake-protocol fixtures; no real-device access in
   the test suite.

**Out of scope:** G7 window geometry (needs a measured panel map; planned as a
separate owner-gated hardware session), `BGPIC`/frame-stream backgrounds,
heartbeat/keepalive, LCD sleep/wake management, legacy daemon integration.

## 4. Design

### 4.1 Discovery: bind the hidraw node to the control interface

`discovery.py` stays sysfs-only and read-only. For each HID interface we
additionally walk `/sys/class/hidraw/hidraw*/device` symlinks and record the
hidraw node whose device chain resolves to that interface (same technique as
`debug_tool.py:90-100`, reimplemented sysfs-pure). The discovery report gains
an optional per-interface `hidraw_node` field. Node names remain runtime data:
they must never enter committed evidence (redaction rules unchanged).

### 4.2 Vendor input backend (G3 revised)

- New `VendorHidReadOnlyBackend` implementing the existing
  `ReadOnlyInputBackend` protocol (`input_session.py:80-94`): `O_RDONLY` open,
  `select`-bounded reads of 512-byte reports, exactly-once close.
- A pure report parser maps each report to the transport-neutral
  `RawInputEvent(type, code, value, monotonic_ns)`:
  - `report[9] == 0xFF` (write-ACK) → skipped as a meta event (joins
    `_META_EVENT_TYPES` handling).
  - Buttons/knob-press → synthetic `(type=VENDOR_EVENT_TYPE, code=report[9],
    value=1)` (press-only).
  - Rotations → `(VENDOR_EVENT_TYPE, code=report[9], value=+1)`; the key map
    already encodes direction per code, so no signed values are needed.
- `KeyMap` is reused unchanged. The calibrated `6602:1000` map ships as a
  versioned JSON artifact (12 controls, physical positions documented in the
  G3 vendor-channel evidence) plus a test fixture.
- **Press-only semantics:** `InputSessionSpec` gains `press_only: bool = False`.
  When true, `meets_requirements` checks press counts (and rotation counts,
  latency) but does not require release counts. Default false keeps the evdev
  behavior bit-for-bit.
- Node plumbing: `_DEVICE_NODE_RE` (`ipc.py:153`) additionally accepts
  `/dev/hidraw[0-9]+`; `helper_main` selects `EvdevReadOnlyBackend` vs
  `VendorHidReadOnlyBackend` from the node path. No new wire keys.

### 4.3 Vendor command backend (G4–G6)

- New `VendorHidCommandBackend` implementing the narrow `Backend` protocol
  (`backend.py:19-26`). It translates `AdapterCommand` into the exact byte
  sequences validated on 2026-08-05:
  - `INITIALIZE` → `DIS` + `LIG 00 00 32` + `STP`
  - `SET_BRIGHTNESS` → `LIG 00 00 <level>` (level range-checked 0–100)
  - `SET_KEY_IMAGE` → `BAT` header + JPEG chunks (≤1024 B) + `STP`; image
    bytes are size-capped by `MAX_IMAGE_BYTES` and digest-checked against
    `CommandSpec.image_sha256` before any write.
- The backend opens the hidraw node `O_RDWR` **only inside the helper
  process**, only for the approved control-interface node, and only for the
  duration of one command step. Write-ACK frames are drained and discarded.
- `helper_main` currently executes non-session commands with `FakeBackend`
  (`helper_main.py:93`). It gains an explicit dispatch: when the manifest
  profile's protocol marker selects the vendor channel, the real
  `VendorHidCommandBackend` is constructed for `INITIALIZE`/`SET_BRIGHTNESS`/
  `SET_KEY_IMAGE`; everything else stays fake-only. `CommandPolicy.validate`
  gains the vendor node path allowance alongside the evdev one.
- Gate tables (`gate.py:31-71`) are unchanged: stage order and allowed
  operations already match the validated flow (G3 observe → G4 init → G5
  brightness → G6 one LCD). LCD-key input (post-init) is re-observed during
  the owner-gated G7 hardware session, not as a new gate.

### 4.4 CLI surface

- `n3-ai-deck-observe-inputs` gains `--channel {evdev,vendor}` (default
  `evdev`, preserving current behavior) and `--press-only`.
- No new CLIs in this design; G4–G6 are exercised through manifests and the
  existing helper path. A thin `n3-ai-deck-display` CLI is deferred to the G7
  plan.

## 5. Safety invariants (unchanged + new)

- All existing invariants hold: staged gate, fail-closed, exactly-once backend
  attempts, redacted evidence, isolated helper, no sudo/system changes.
- New: the vendor backend writes **only** the validated command set
  (`DIS/LIG/STP/BAT`); any other payload is a contract violation.
- New: the vendor hidraw node must resolve to the manifest's approved control
  interface at execution time (re-resolved, never cached across stages).
- New: `BGPIC`, mode changes, LED commands, and image data larger than
  `MAX_IMAGE_BYTES` are rejected by construction.
- Unplugging the device restores factory state; no persistent device writes
  exist in this design.

## 6. Test plan (RED→GREEN, no real device)

- Report parser: golden 512-byte fixtures for every calibrated code, ACK
  filtering, truncated/oversized reports.
- Press-only sessions: `meets_requirements` with/without releases; regression
  for the evdev path.
- Command backend: scripted-transport fake asserting exact byte sequences for
  each operation, chunk boundaries (1023/1024/1025-byte images), digest
  mismatch rejection, ACK draining.
- IPC/helper: hidraw node acceptance, backend dispatch by node path, fake
  path untouched.
- Discovery: hidraw binding fixtures (symlink graphs), drift → fail-closed.
- Public-project guards: updated alongside the docs (pattern of
  `test_public_project.py`).

## 7. Implementation order

1. **P1** discovery hidraw binding (read-only).
2. **P2** report parser + vendor input backend + press-only spec + IPC/helper
   plumbing + key-map artifact → G3 revised path runnable end-to-end.
3. **P3** vendor command backend `INITIALIZE`/`SET_BRIGHTNESS` (G4/G5).
4. **P4** `SET_KEY_IMAGE` (G6).
5. **P5** owner-gated hardware session: regression of G3–G6 through the formal
   path, then G7 window-geometry measurement (separate plan).

Each phase lands as its own small commit series with the quality gate
(`uv run pytest`, `uv run ruff check .`, `uv build`) green before the next.
