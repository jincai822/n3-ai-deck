# N3 AI Deck

[![CI](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml)
[![Status: Early Preview](https://img.shields.io/badge/status-Early%20Preview-orange)](ROADMAP.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

[简体中文](README.zh-CN.md)

**N3 AI Deck is an open-source, local-first AI productivity console for the Mirabox/妙联宝 N3 V3.0 on Linux.** It aims to turn six LCD keys, three round buttons, and three knobs into visible, repeatable AI and desktop automation workflows.

> **Early Preview:** the connected N3 V3.0 (`6602:1000`) has been identified at the USB/HID level, but initialization, input controls, brightness, and LCD writes are not yet validated. Do not install this branch as a device driver yet.

## What it is for

- Trigger an AI assistant or repeatable workflow with one physical action.
- Use knobs to adjust parameters, change modes, or control desktop applications.
- Show running, success, and failure state on LCD keys.
- Keep credentials and execution local by default.
- Add integrations through the planned plugin contract when that contract is implemented.

## Current status

| Hardware | USB ID | Status |
|---|---:|---|
| 妙联宝 N3 V3.0 | `6602:1000` | Detected; write operations not yet validated |
| FHOOU/Mirabox N3 reference variant | `6603:1003` | Supported by upstream; N3 AI Deck revalidation pending |

The current source retains the working Linux daemon and GTK4 GUI from the upstream project. The target architecture plans a safer device boundary and an AI-oriented action/plugin architecture; those N3 AI Deck layers are not implemented in M0. See [ROADMAP.md](ROADMAP.md) for release gates.

> **Early Preview naming:** the Python distribution and CLI identifiers still retain the upstream `streamdock-n3-linux` and `streamdock-n3` names. The inherited `0.2.5` version records upstream lineage and is not an N3 AI Deck release. Naming and versioning will be resolved before `v0.1.0`.

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

M0 development does not access attached hardware:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
```

Hardware work follows the manual gates in [CONTRIBUTING.md](CONTRIBUTING.md). Architecture details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and security reports follow [SECURITY.md](SECURITY.md).

## Upstream and license

N3 AI Deck is derived from [asad-albadi/streamdock-n3](https://github.com/asad-albadi/streamdock-n3) and includes portions of the Mirabox StreamDock Device SDK. See [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) and [LICENSE](LICENSE). No affiliation with or endorsement by Mirabox is implied.
