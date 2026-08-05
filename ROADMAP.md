# N3 AI Deck Roadmap

N3 AI Deck is an Early Preview. Milestone completion requires evidence; dates are intentionally secondary to safe hardware validation.

The formal product baseline is in [the N3 AI Deck PRD](tasks/prd-n3-ai-deck.md).
M1's approved testable scope and safety boundary are defined in
[the read-only discovery PRD](tasks/prd-n3-v3-read-only-discovery.md).
M2's approved scope and G0 design are defined in
[the hardware-controls PRD](tasks/prd-m2-n3-v3-hardware-controls.md) and
[the hardware-controls design](docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md).
The transactional G0 safety boundary is defined in
[the transactional Adapter safety design](docs/superpowers/specs/2026-08-03-m2-g0-transactional-adapter-safety-design.md)
and its
[hardening plan](docs/superpowers/plans/2026-08-03-m2-g0-transactional-adapter-safety-hardening.md).
G1's candidate profile approval boundary is defined in
[the G1 profile approval plan](docs/superpowers/plans/2026-08-04-m2-g1-profile-approval.md).
G2's offline permission design is defined in
[the G2 minimal permissions plan](docs/superpowers/plans/2026-08-04-m2-g2-minimal-permissions.md).
G3's read-only input observation is defined in
[the G3 input observation plan](docs/superpowers/plans/2026-08-04-m2-g3-input-observation.md).

## M0 — Public foundation

**Status:** Complete

- [x] Independent repository identity and bilingual landing pages.
- [x] Attribution, governance, and passing public CI.
- [x] No device writes, tags, or release artifacts.

## M1 — Safe N3 V3.0 discovery

**Status:** Complete — read-only discovery only

- [x] Add a passive `6602:1000` catalog entry without activating the vendored SDK.
- [x] Prove sysfs-only discovery and report the matching candidate's HID interface topology.
- [x] Do not open `/dev`, install permissions, or select an active HID interface in M1.

## M2 — Hardware controls

**Status:** In progress — G0 foundation and G1 candidate profile approval complete

G0 is a hardware-free transactional simulation foundation. It proves ordered private
reservations, exactly-once fake backend attempts, redacted evidence acceptance, settlement,
recovery, and isolated stateless helper validation without activating hardware. Helper
snapshots are validation context, not state authority.

- [x] Define and test the hardware-free Adapter contracts, capability gate, FakeBackend,
  fake-only helper isolation, and redacted evidence.
- [x] G1: approve an exact active profile and resolve interface responsibility. Evidence:
  [the G1 profile approval record](docs/validation/2026-08-04-g1-profile-approval.md),
  approval reference `owner:2026-08-04:g1-profile-approval`. Interface `01` is the
  approved candidate input interface and interface `00` the approved candidate control
  interface; these remain candidate roles pending G3 physical validation.
- [x] G2: approve any permission change separately. Evidence:
  [the G2 permission approval record](docs/validation/2026-08-04-g2-permission-approval.md),
  approval reference `owner:2026-08-04:g2`. The approval grants nothing: the
  artifacts are offline templates, no permission was granted, and no system
  state was changed; any real ACL/udev installation remains a separate
  owner-gated manual action before G3.
- [x] G3: validate input through read-only observation. The original evdev path
  (designed in the [G3 plan](docs/superpowers/plans/2026-08-04-m2-g3-input-observation.md))
  was falsified on real hardware (see the
  [blocked record](docs/validation/2026-08-05-g3-input-observation-blocked.md));
  input was instead physically validated for all 12 controls over the vendor HID
  channel, with owner-approved minimal init writes required for the LCD keys (see the
  [vendor-channel record](docs/validation/2026-08-05-g3-vendor-channel-input-observation.md),
  approval reference `owner:2026-08-05:g3-vendor-input-observation`). The G1 candidate
  profile and the G3 gate design need revision to adopt this path.
- [x] G4–G6: initialization (DIS+LIG+STP), brightness, and one LCD key image validated
  through owner-approved minimal writes. Evidence:
  [the display validation record](docs/validation/2026-08-05-g4-g6-display-validation.md),
  approval reference `owner:2026-08-05:g4-g6-display-validation`.
- [x] G7: all six LCDs. The six key windows are regions of one shared panel on this
  variant; images are not scaled but overflow from each key's anchor point, and all
  six keys displayed their own numbered color image correctly (no cross-key bleed).
  Evidence:
  [the six-LCD and production regression record](docs/validation/2026-08-05-g7-six-lcd-and-production-regression.md),
  approval reference `owner:2026-08-05:g7-six-lcd`. Full-screen addressing differs
  from SDK assumptions (`BGPIC` clears to black) — do not use it on this variant.
  Follow-up optimization: per-key anchor offset calibration (individual 1–2 px
  deviations).

## M3 — Extensible action engine

**Status:** In progress — plugin contract, safe builtins, and demo CLI complete

- [x] Publish the plugin contract and safe local example actions. Evidence:
  [the M3 action engine design](docs/superpowers/specs/2026-08-05-m3-action-engine-design.md),
  approval reference `owner:2026-08-05:m3-action-engine`. The engine is
  hardware-free today: contract, safe builtins, JSON bindings, and the
  `n3-ai-deck-run-action` demo CLI. Wiring actions to physical events through
  the device daemon remains planned.

## M4 — AI workflow demonstration

- Record one useful end-to-end AI workflow with visible device feedback and local credentials.

## M5 — v0.1.0

- Publish reproducible artifacts only after CI and the physical validation checklist pass.
