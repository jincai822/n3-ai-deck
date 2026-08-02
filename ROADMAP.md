# N3 AI Deck Roadmap

N3 AI Deck is an Early Preview. Milestone completion requires evidence; dates are intentionally secondary to safe hardware validation.

The formal product baseline is in [the N3 AI Deck PRD](tasks/prd-n3-ai-deck.md).
M1's approved testable scope and safety boundary are defined in
[the read-only discovery PRD](tasks/prd-n3-v3-read-only-discovery.md).

## M0 — Public foundation

**Status:** Complete

- [x] Independent repository identity and bilingual landing pages.
- [x] Attribution, governance, and passing public CI.
- [x] No device writes, tags, or release artifacts.

## M1 — Safe N3 V3.0 discovery

**Status:** In progress — safety amendment approved

- Add a passive `6602:1000` catalog entry without activating the vendored SDK.
- Prove sysfs-only discovery and report the matching candidate's HID interface topology.
- Do not open `/dev`, install permissions, or select an active HID interface in M1.

## M2 — Hardware controls

- Design the exact udev permission and activate the SDK mapping only after manual approval.
- Validate keys, round buttons, knobs, brightness, and all six LCD keys in staged manual tests.

## M3 — Extensible action engine

- Publish the plugin contract and safe local example actions.

## M4 — AI workflow demonstration

- Record one useful end-to-end AI workflow with visible device feedback and local credentials.

## M5 — v0.1.0

- Publish reproducible artifacts only after CI and the physical validation checklist pass.
