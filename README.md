# N3 AI Deck

[![CI](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml)
[![Status: Early Preview](https://img.shields.io/badge/status-Early%20Preview-orange)](ROADMAP.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

[简体中文](README.zh-CN.md)

**N3 AI Deck is an open-source, local-first AI productivity console for the Mirabox/妙联宝 N3 V3.0 on Linux.** It aims to turn six LCD keys, three round buttons, and three knobs into visible, repeatable AI and desktop automation workflows.

> **Early Preview:** `6602:1000` is an owner-reported N3 V3.0 USB ID candidate whose physical identity is not independently confirmed. Its protocol compatibility, initialization, input controls, brightness, and LCD writes have been validated on the owner's `6602:1000` unit, with dated evidence records in `docs/validation/`. The G8 background service is implemented in the current source (see the Background service section); GUI configuration and entry-point discovery remain planned; do not rely on this branch as a production device driver yet.

## What it is for

- Trigger an AI assistant or repeatable workflow with one physical action.
- Use knobs to adjust parameters, change modes, or control desktop applications.
- Show running, success, and failure state on LCD keys.
- Keep credentials and execution local by default.
- Add integrations through the documented plugin contract and safe builtin plugins.

## Install (v0.1.0)

Install the v0.1.0 release wheel with pipx (requires [pipx](https://pipx.pypa.io/)):

```bash
pipx install https://github.com/jincai822/n3-ai-deck/releases/download/v0.1.0/streamdock_n3_linux-0.1.0-py3-none-any.whl
```

With the device plugged in, run the owner-run live dispatch CLI to stream physical events into the action engine in real time:

```bash
n3-ai-deck-live --feedback
```

`--feedback` writes per-key LCD state images (running / success / failure / timeout) through the validated key-image path. The release also installs `n3-ai-deck-run-action` for hardware-free action runs, plus the discovery and bounded read-only observation commands (`n3-ai-deck-detect`, `n3-ai-deck-observe-inputs`). See the [release notes](https://github.com/jincai822/n3-ai-deck/releases/tag/v0.1.0) and [CHANGELOG.md](CHANGELOG.md).

**v0.1.0 scope.** The v0.1.0 release ships the validated owner-run path. The G8 background service (auto-restart, auto-reconnect, background live dispatch) was **not included** in the v0.1.0 release artifacts; it landed after the v0.1.0 tag and ships in the next release.

**Upstream legacy commands.** The distribution also installs the inherited upstream console scripts — `streamdock-n3`, `streamdock-n3-gui`, `streamdock-n3-probe`, `streamdock-n3-debug`, and the legacy install command. They are upstream legacy, kept for continuity, and are **not part of the validated N3 AI Deck path**; do not use them for the validated `6602:1000` flow (see the M1 section).

## Current status

| Hardware | USB ID | Status |
|---|---:|---|
| Owner-reported N3 V3.0 candidate | `6602:1000` | USB ID candidate; identity not independently confirmed; protocol, init, inputs, brightness, and LCD writes validated on the owner's `6602:1000` unit |
| FHOOU/Mirabox N3 reference variant | `6603:1003` | Supported by upstream; N3 AI Deck revalidation pending |

The current source retains the Linux daemon and GTK4 GUI from the upstream project. M1 implements a separate read-only discovery path; the target architecture's active device boundary — adapter, vendor backends, and owner-run live dispatch — is implemented and hardware-validated (M2–M4). M3 implements the action engine contract, safe builtin plugins, a hardware-free demo CLI, and an owner-run live dispatch CLI (`n3-ai-deck-live`); hardware-triggered background wiring is implemented as the G8 background service (`n3-ai-deck-service`, see below). See [ROADMAP.md](ROADMAP.md) for release gates.

> **Early Preview naming:** the Python distribution and CLI identifiers still retain the upstream `streamdock-n3-linux` and `streamdock-n3` names, labeled as upstream legacy. Naming and versioning are resolved for v0.1.0: the distribution version is now `0.1.0`, and the inherited `0.2.5` lineage — which was not an N3 AI Deck release — is recorded in the CHANGELOG.

## Safe read-only discovery (M1)

Use the dedicated M1 command to inspect the approved sysfs USB and HID attributes without opening device nodes:

```bash
uv run n3-ai-deck-detect
uv run n3-ai-deck-detect --json
```

`6602:1000` is only a USB ID candidate: identity is not confirmed and the command does not prove protocol compatibility. The report may show multiple HID candidates, and it deliberately does not select one for device access. This M1 path reads only allowlisted sysfs attributes; it does not initialize hardware or access `/dev` nodes.

The inherited daemon, probe, debug, GUI, and install commands are outside M1's read-only guarantee and must not be used for `6602:1000` in M1. Their corresponding legacy entry points are not safe substitutes for this command.

G1 extends this passive discovery to resolve interface responsibility: the same sysfs-only command now reports a role (`input` / `control` / `unknown`) and its redacted evidence basis for each HID interface, and an `interface_selection` of `resolved` / `ambiguous` / `none`. A resolved candidate profile and its roles are approved explicitly through the `N3Adapter` G1 gate; approval is a candidate-profile decision, not a compatibility claim. Roles were hardware-validated in the G3 input observation session on the owner's `6602:1000` unit, and `6602:1000` remains an owner-reported candidate whose identity is not independently confirmed.

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
side effects; physical-event dispatch is implemented as the owner-run live
CLI below and as the G8 background service (see below).

## Live dispatch (`n3-ai-deck-live`)

With the device plugged in, stream physical events into the action engine in
real time:

```bash
uv run n3-ai-deck-live --duration-ms 60000
```

Each dispatched event prints one JSON line (`schema_version`, `event_key`,
`status`, `plugin`, `duration_ms`) and a final summary line reports the
session counters. The session is foreground and bounded, and exits cleanly on
deadline, Ctrl+C, or disconnect. Without a bindings file it only logs, with
zero side effects; to launch allowlisted applications, create
`~/.config/streamdock-n3/bindings.json`, for example binding `button.1.press`
to the allowlisted `launch_app` builtin. The CLI picks the file up
automatically, or pass `--bindings`. Preview the resolved setup without
opening the device:

```bash
uv run n3-ai-deck-live --dry-run
```

## AI workflow (M4)

M4 wires a real AI workflow to the device: pressing an LCD key reads the
current clipboard, summarizes it into one sentence through an
OpenAI-compatible endpoint, and shows the outcome on the key — yellow while
running, green on success, red on failure, orange on timeout.

```bash
uv run n3-ai-deck-live --feedback --timeout-seconds 15
```

Credentials are provided by you through an environment variable
(`N3_AI_DECK_API_KEY` — the name is configurable per binding, the value is
never stored in this repository); a missing credential disables only the
`ai_text` plugin and every local action keeps working. The AI plugin adds no
new runtime dependencies — it uses the Python standard library. Preview the
resolved setup without a device:

```bash
uv run n3-ai-deck-live --feedback --timeout-seconds 15 --dry-run
```

## Background service (G8)

The G8 background service (`n3-ai-deck-service`) runs the validated live
dispatch path automatically: it re-resolves the approved device node, runs
bounded live sessions back-to-back, reconnects with capped backoff after an
unplug or an absent node, and stops cleanly on SIGTERM. It prints the
owner-gated systemd user unit and udev rule and never installs anything —
install them yourself:

```bash
n3-ai-deck-service --print-unit > ~/.config/systemd/user/n3-ai-deck.service
n3-ai-deck-service --print-udev-rule | sudo tee /etc/udev/rules.d/90-n3-ai-deck.rules
sudo udevadm control --reload && sudo udevadm trigger
systemctl --user daemon-reload
systemctl --user enable --now n3-ai-deck
```

The AI credential is read from `~/.config/streamdock-n3/service.env`
(the `N3_AI_DECK_API_KEY` variable, file mode `0600`; a missing file is not
a failure). Stop the service with `systemctl --user stop n3-ai-deck`. The
service needs an active desktop session for the session-bound `uaccess`
permission; a hung plugin stalls its bounded session until the deadline, and
the systemd `Restart=on-failure` layer is the backstop.

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
