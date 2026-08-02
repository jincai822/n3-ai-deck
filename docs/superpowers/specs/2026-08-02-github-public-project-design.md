# N3 AI Deck Public GitHub Project Design

**Date:** 2026-08-02  
**Status:** Approved design  
**Owner:** `jincai822`  
**Planned repository:** `jincai822/n3-ai-deck`

> **Proposed M1 safety amendment (2026-08-03):** Technical review found that the
> vendored SDK registry can lead to active device access. The formal
> [M1 read-only discovery PRD](../../../tasks/prd-n3-v3-read-only-discovery.md) proposes
> a passive sysfs-only M1 and moves active SDK registration and udev changes to M2.
> This proposal does not supersede the approved clauses below until the product owner
> explicitly approves the amendment.

## 1. Decision summary

N3 AI Deck will be an independent public GitHub project built from the history of
[`asad-albadi/streamdock-n3`](https://github.com/asad-albadi/streamdock-n3). It will
present a customer- and partner-facing product while keeping the reusable hardware
foundation open source.

The product is an AI productivity console for the Mirabox/妙联宝 N3 V3.0 on Linux.
Physical LCD keys and knobs trigger AI tools, applications, and automation workflows,
and the device displays useful execution state and results.

The project follows an Open Core model:

- The device integration, local action engine, plugin contract, basic plugins, local
  configuration UI, documentation, and tests are public.
- Cloud services, enterprise identity, paid integrations, customer-specific workflows,
  and managed deployment remain private commercial extensions.

The initial public status is **Early Preview**. The project will not claim complete
hardware compatibility or publish a product release before the physical device tests
defined in this document pass.

## 2. Goals and non-goals

### Goals

- Make the product purpose understandable to a potential customer or partner within one
  minute of opening the repository.
- Support the connected N3 V3.0 USB variant `6602:1000` without regressing the upstream
  N3 variants.
- Provide a local-first path from a physical device event to an AI or automation action
  and back to visible device feedback.
- Establish clean public extension points so useful plugins can be developed without
  access to private commercial code.
- Preserve upstream history, license notices, and explicit attribution.
- Keep the public repository safe to clone, test, and inspect without requiring API
  secrets or attached hardware.

### Non-goals for the first public release

- Windows or macOS support.
- Cloud synchronization, billing, enterprise accounts, or managed customer deployment.
- A marketplace for plugins.
- Support for every Stream Dock model.
- Claims of production readiness before real N3 V3.0 validation.

## 3. Product positioning

### Name

**N3 AI Deck**

### One-line description

> An open-source AI productivity console for the Mirabox/妙联宝 N3 V3.0 that turns
> physical LCD keys and knobs into AI and automation workflows.

### Primary audience

Potential customers and partners are the primary audience. Developers remain an
important secondary audience because the public core and plugin interface demonstrate
technical credibility and make integrations possible.

### Value shown on the repository landing page

- Trigger AI assistants and repeatable workflows with one physical action.
- Use knobs to adjust parameters, change modes, or control desktop applications.
- Show action state and useful feedback on LCD keys.
- Keep credentials and execution local by default.
- Extend the system through a documented plugin contract.

The README must distinguish implemented behavior, work in progress, and planned
capabilities. Product imagery must come from real builds and real hardware tests. Until
those assets exist, the repository uses an honest development-status section rather than
mock screenshots presented as completed functionality.

## 4. Open Core boundary

### Public repository

- USB/HID discovery and device communication.
- Exact N3 V3.0 `6602:1000` support and compatible upstream N3 identifiers.
- Button, knob, brightness, LCD image, and device lifecycle handling.
- Local event and action engine.
- Stable plugin interface and public example plugins.
- Basic local plugins such as application launch, keyboard shortcut, and HTTP/webhook
  actions, subject to explicit user configuration.
- Local configuration, diagnostics, and user interface.
- Installation tooling, tests, architecture documentation, and contributor guidance.

### Private commercial extensions

- Hosted synchronization and remote management.
- Enterprise authentication, policy, audit, and administration.
- Paid provider integrations and proprietary workflow packs.
- Customer-specific connectors, deployment, and support automation.
- Billing, licensing services, and commercial analytics.

Private extensions consume the public plugin or service interfaces. The public core must
not import, require, or contain placeholders for private packages.

## 5. Technical architecture

The first iterations evolve the existing `streamdock_n3` package instead of performing a
large rewrite. New boundaries are introduced incrementally around the upstream daemon,
event mapping, configuration, GUI, diagnostic tools, and vendored SDK.

### Components

1. **Device adapter**
   - Detects supported VID/PID combinations.
   - Encapsulates SDK/HID access and N3 V3.0-specific behavior.
   - Exposes normalized button, knob, display, and lifecycle operations.

2. **Event and action engine**
   - Converts device input into stable application events.
   - Resolves configured actions without embedding provider-specific logic.
   - Applies timeouts and reports structured success or failure results.

3. **Plugin interface**
   - Defines plugin metadata, configuration, validation, execution, and result contracts.
   - Supports public local automation and later private commercial integrations through
     the same boundary.

4. **Local configuration and UI**
   - Configures device pages, actions, icons, and plugin settings.
   - Shows device and action status without exposing stored secrets.

5. **Diagnostics and installation**
   - Separates read-only discovery from commands that initialize or write to hardware.
   - Installs narrowly scoped udev permissions for known devices.
   - Provides actionable diagnostics for missing hardware and access failures.

### Data flow

```text
N3 key or knob
  -> device adapter
  -> normalized event
  -> action engine
  -> selected AI or automation plugin
  -> structured result
  -> local log, UI state, and optional LCD feedback
```

The system remains usable for non-AI local automation when no AI credentials are
configured.

## 6. Safety, privacy, and error handling

- API keys are stored only in user-controlled local secret storage or environment-backed
  configuration. They are never committed, printed in diagnostics, or embedded in device
  images.
- Device serial numbers, local usernames, customer data, and machine-specific paths are
  removed from examples and test fixtures.
- Read-only device enumeration is the first hardware test. Initialization, brightness,
  icon, and display writes occur only in explicit later test stages.
- An unknown device identifier is rejected safely instead of being treated as a compatible
  N3 model.
- Missing udev permission produces an exact remediation message; it does not silently
  escalate privileges.
- Plugin failures and timeouts are isolated from the daemon, reported to the UI/device,
  and do not trigger unbounded automatic retries.
- Shell or application-launch actions require explicit user configuration. Public defaults
  do not execute downloaded or untrusted commands.
- A missing optional AI credential disables only the affected plugin and leaves local
  actions available.

## 7. Testing and hardware validation

### Automated tests

- Unit tests for VID/PID registration, event normalization, configuration migration,
  plugin contracts, and error paths.
- Protocol fixtures and fake device adapters so CI does not require physical hardware.
- Existing upstream tests remain passing during the compatibility work.
- CI runs formatting/lint checks, type checks where configured, and the full hardware-free
  test suite on supported Python versions.
- Secret scanning and dependency review are enabled before accepting outside contributions.

### Physical N3 V3.0 validation order

1. Confirm read-only enumeration of `6602:1000` and select only the intended HID interface.
2. Capture key, round-button, knob-rotation, and knob-press input without device writes.
3. Perform controlled initialization and brightness tests.
4. Display a single reversible test image, then verify all six LCD keys.
5. Run the daemon in dry-run mode and verify normalized events.
6. Execute a harmless local action and display its result.
7. Run one real AI workflow using a locally supplied credential.

Each stage records the device variant, software commit, expected result, actual result,
and recovery procedure. Failure at one stage blocks the later write stages until the
cause is understood.

## 8. GitHub presentation

### Repository identity

- Repository: `jincai822/n3-ai-deck`
- Visibility: public
- Default branch: `main`
- Initial status: `Early Preview`
- Suggested description: `Open-source AI productivity console for the Mirabox/妙联宝 N3 V3.0 on Linux.`
- Suggested topics: `ai`, `automation`, `hid`, `linux`, `mirabox`, `productivity`,
  `streamdock`

### Landing-page structure

1. Product name, one-line value, badges, and Early Preview notice.
2. Customer-oriented use cases and expected outcomes.
3. Real demonstration media when hardware validation produces it.
4. Hardware compatibility table with explicit validation status.
5. Architecture and Open Core explanation.
6. Safe installation or development instructions appropriate to the current milestone.
7. Public roadmap and current limitations.
8. License, upstream attribution, and acknowledgements.

`README.md` provides the primary international presentation and links prominently to a
complete `README.zh-CN.md`. Both versions carry the same status and compatibility claims.

### Supporting public documents

- `ROADMAP.md`
- `docs/ARCHITECTURE.md`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `ACKNOWLEDGEMENTS.md`
- Issue and pull-request templates

A GitHub Pages site, community discussion board, and plugin marketplace are deferred
until the core product has a real demonstration and recurring external interest.

## 9. Upstream relationship and licensing

The local checkout retains the upstream commit history. Git remotes use:

- `origin`: the future `jincai822/n3-ai-deck` repository.
- `upstream`: `asad-albadi/streamdock-n3`.

The original MIT license and copyright notices remain in all substantial reused portions.
The README and acknowledgements identify the upstream project and the Mirabox StreamDock
Device SDK. Changes made by N3 AI Deck are documented separately.

Because the repository vendors SDK code whose notice points back to its upstream terms,
those terms must be verified before the first commercial binary distribution. This does
not block local compatibility development or publication of correctly attributed source
under the currently documented terms.

## 10. Roadmap and release gates

### M0 — Public foundation

- Independent repository, `main` branch, attribution, bilingual landing page, architecture,
  contribution policy, CI, and public roadmap.

### M1 — Safe N3 V3.0 discovery

- Recognize `6602:1000`, install exact permissions, and complete read-only enumeration and
  diagnostics.

### M2 — Hardware controls

- Validate keys, round buttons, knobs, brightness, and all LCD keys on the physical device.

### M3 — Extensible action engine

- Define the plugin contract and ship safe local example actions.

### M4 — AI workflow demonstration

- Complete and record one useful end-to-end AI workflow with visible device feedback.

### M5 — `v0.1.0`

- Publish reproducible installation artifacts only after automated checks and the physical
  hardware validation checklist pass.

## 11. Launch acceptance criteria

The initial GitHub repository is ready to publicize when:

- A visitor can identify the product, target hardware, status, and primary use case from
  the first README screen.
- Reused code and assets have visible license and upstream attribution.
- Public versus private functionality is described without suggesting unavailable
  commercial features are already implemented.
- The repository contains no API keys, device serials, private customer data, or local-only
  paths.
- CI passes without physical hardware.
- Hardware claims match recorded tests.
- No GitHub Release is published before the `v0.1.0` release gate passes.

## 12. Publication sequence

1. Commit this approved design to the local `main` branch.
2. Write and approve an implementation plan.
3. Implement the M0 public foundation locally and verify it.
4. Create the empty public repository `jincai822/n3-ai-deck`.
5. Configure it as `origin`, retain the source repository as `upstream`, and push `main`.
6. Verify the public landing page, license, default branch, topics, and repository settings.
7. Begin M1 hardware compatibility work on a focused feature branch.
