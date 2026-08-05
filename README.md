# N3 AI Deck

[![CI](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml)
[![Status: Early Preview](https://img.shields.io/badge/status-Early%20Preview-orange)](ROADMAP.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

[简体中文](README.zh-CN.md)

**N3 AI Deck is an open-source, local-first AI productivity console for the Mirabox/妙联宝 N3 V3.0 on Linux.** It aims to turn six LCD keys, three round buttons, and three knobs into visible, repeatable AI and desktop automation workflows.

> **Early Preview:** `6602:1000` is an owner-reported N3 V3.0 USB ID candidate. Its physical identity is not confirmed, and its protocol compatibility, initialization, input controls, brightness, and LCD writes are not yet validated. Do not install this branch as a device driver yet.

## What it is for

- Trigger an AI assistant or repeatable workflow with one physical action.
- Use knobs to adjust parameters, change modes, or control desktop applications.
- Show running, success, and failure state on LCD keys.
- Keep credentials and execution local by default.
- Add integrations through the documented plugin contract and safe builtin plugins.

## Current status

| Hardware | USB ID | Status |
|---|---:|---|
| Owner-reported N3 V3.0 candidate | `6602:1000` | USB ID candidate; identity not confirmed; protocol and write operations not yet validated |
| FHOOU/Mirabox N3 reference variant | `6603:1003` | Supported by upstream; N3 AI Deck revalidation pending |

The current source retains the Linux daemon and GTK4 GUI from the upstream project. M1 implements a separate read-only discovery path; the target architecture still plans the active device boundary. M3 implements the action engine contract, safe builtin plugins, and a hardware-free demo CLI; hardware-triggered wiring remains planned. See [ROADMAP.md](ROADMAP.md) for release gates.

> **Early Preview naming:** the Python distribution and CLI identifiers still retain the upstream `streamdock-n3-linux` and `streamdock-n3` names. The inherited `0.2.5` version records upstream lineage and is not an N3 AI Deck release. Naming and versioning will be resolved before `v0.1.0`.

## Safe read-only discovery (M1)

Use the dedicated M1 command to inspect the approved sysfs USB and HID attributes without opening device nodes:

```bash
uv run n3-ai-deck-detect
uv run n3-ai-deck-detect --json
```

`6602:1000` is only a USB ID candidate: identity is not confirmed and the command does not prove protocol compatibility. The report may show multiple HID candidates, and it deliberately does not select one for device access. This M1 path reads only allowlisted sysfs attributes; it does not initialize hardware or access `/dev` nodes.

The inherited daemon, probe, debug, GUI, and install commands are outside M1's read-only guarantee and must not be used for `6602:1000` in M1. Their corresponding legacy entry points are not safe substitutes for this command.

G1 extends this passive discovery to resolve interface responsibility: the same sysfs-only command now reports a role (`input` / `control` / `unknown`) and its redacted evidence basis for each HID interface, and an `interface_selection` of `resolved` / `ambiguous` / `none`. A resolved candidate profile and its roles are approved explicitly through the `N3Adapter` G1 gate; approval is a candidate-profile decision, not a compatibility claim. Roles remain approved candidate roles pending G3 physical validation, and `6602:1000` remains a candidate with unvalidated protocol.

G2 designs permissions entirely offline and grants nothing: a temporary single-node ACL plan (placeholders only) and precise `6602:1000`-exact `TAG+="uaccess"` udev rule templates, plus an install transaction that only ever targets an explicit non-system root. No permission was granted, no system file was written, and no permission command was executed; any real ACL or udev installation stays a separate manual action.

G3 observes physical inputs through one bounded, read-only session (`n3-ai-deck-observe-inputs`): the helper opens exactly one approved input node `O_RDONLY`, never writes, never grabs, never loads the SDK, and stops at disconnect with zero automatic recovery writes. The session counts per-control presses/rotations, measures p95 latency, and records redacted evidence; the gate advances only on machine-backed results. Automated tests never open `/dev`; the real-device session is an owner-gated manual action.

## Action engine (M3)

M3 implements the action engine without touching hardware: an in-process
plugin contract, a timeout-enforcing engine, safe builtin plugins (an
allowlisted launcher and structured logging), and file-based JSON bindings.
Try it without a device:

```bash
uv run n3-ai-deck-run-action --event button.1.press --dry-run
```

The shipped default binds every standard event to structured logging with no
side effects; executing actions from physical events remains planned.

## Planned flow

```text
N3 key or knob
  -> device adapter
  -> normalized event
  -> action engine
  -> AI or automation plugin
  -> structured result
  -> UI and optional LCD feedback
```

## Planned Open Core model

The planned public core is intended to contain device communication, local actions, plugin contracts, local configuration, diagnostics, UI, documentation, and tests. The target boundary keeps hosted synchronization, enterprise administration, paid integrations, and customer-specific deployment in private commercial extensions.

## Development

M1 automated development does not access attached hardware:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
```

Hardware work follows the manual gates in [CONTRIBUTING.md](CONTRIBUTING.md). Architecture details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and security reports follow [SECURITY.md](SECURITY.md).

## Upstream and license

N3 AI Deck is derived from [asad-albadi/streamdock-n3](https://github.com/asad-albadi/streamdock-n3) and includes portions of the Mirabox StreamDock Device SDK. See [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) and [LICENSE](LICENSE). No affiliation with or endorsement by Mirabox is implied.
