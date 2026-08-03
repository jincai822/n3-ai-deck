# N3 AI Deck Roadmap

N3 AI Deck is an Early Preview. Milestone completion requires evidence; dates are intentionally secondary to safe hardware validation.

The formal product baseline is in [the N3 AI Deck PRD](tasks/prd-n3-ai-deck.md).
M1's approved testable scope and safety boundary are defined in
[the read-only discovery PRD](tasks/prd-n3-v3-read-only-discovery.md).
M2's approved scope and G0 design are defined in
[the hardware-controls PRD](tasks/prd-m2-n3-v3-hardware-controls.md) and
[the hardware-controls design](docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md).

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

**Status:** In progress — G0 foundation only

- [x] Define and test the hardware-free Adapter contracts, capability gate, FakeBackend,
  fake-only helper isolation, and redacted evidence.
- [ ] G1: approve an exact active profile and resolve interface responsibility.
- [ ] G2: approve any permission change separately.
- [ ] G3–G7: validate input, initialization, brightness, one LCD, and all six LCDs through
  their independent manual gates.

## M3 — Extensible action engine

- Publish the plugin contract and safe local example actions.

## M4 — AI workflow demonstration

- Record one useful end-to-end AI workflow with visible device feedback and local credentials.

## M5 — v0.1.0

- Publish reproducible artifacts only after CI and the physical validation checklist pass.
