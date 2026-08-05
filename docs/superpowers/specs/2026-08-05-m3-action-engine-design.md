# M3 Action-Engine Design

**Date:** 2026-08-05
**Status:** Draft for owner review
**Supersedes:** None
**Evidence base:** `tasks/prd-n3-ai-deck.md` (US-03 and §10 open
question), `docs/ARCHITECTURE.md` ("Event and action engine" and "Plugin
contract" sections), `ROADMAP.md` (M3 line),
`src/streamdock_n3/hardware/contracts.py`,
`src/streamdock_n3/hardware/input_session.py`,
`src/streamdock_n3/hardware/backend.py`, `src/streamdock_n3/events.py`,
`src/streamdock_n3/input_cli.py`, `src/streamdock_n3/daemon.py`

## 1. Why this design exists

M3 is the extensible action engine milestone. The approved PRD baseline
(`tasks/prd-n3-ai-deck.md`, US-03) requires that standard events map to
configurable local actions: plugins declare metadata, configuration
validation, execution, and structured results; plugin failure, timeout, or
missing configuration must never crash the device service; the default
configuration must not execute arbitrary shell, downloaded, or untrusted
content; and standard events must not expose vendor protocol details.

This design formalizes the two ARCHITECTURE.md sections that are currently
planned — "Event and action engine" and "Plugin contract" — as one new
hardware-free package (`src/streamdock_n3/actions/`) with a small in-process
plugin contract, a timeout-enforcing engine, and two safe builtins. It also
resolves the PRD §10 open question about plugin configuration (file vs. GUI):
**file-based JSON for M3, GUI deferred to a later milestone**. The legacy
`daemon.py` shell executor stays untouched; the new engine is a separate
path, so M3 introduces no shell execution anywhere.

## 2. Validated facts (ground truth for implementation)

Unlike M2, M3 validates no new hardware protocol. The ground truth is the
approved PRD baseline and the existing code shapes this design must fit:

- **US-03 acceptance criteria** (`tasks/prd-n3-ai-deck.md`): standard events
  expose no vendor protocol details; plugins declare metadata, config
  validation, execution, and structured results; plugin failure/timeout/
  missing config never crash the device service; default config executes no
  arbitrary shell, downloaded content, or untrusted scripts.
- **Config open question** (`tasks/prd-n3-ai-deck.md` §10): "plugin config via
  file, GUI, or both?" is decided here — file-based JSON for M3, GUI later.
- **ARCHITECTURE.md** currently plans "Event and action engine" ("normalize
  physical events, resolve configured actions, apply timeouts, and return a
  structured result without provider-specific logic") and "Plugin contract"
  ("define metadata, configuration validation, execution, and result types"),
  and lists the failure boundary "isolates plugin failures and timeouts from
  the device daemon". M3 implements these; event normalization itself stays
  in the hardware layer, so the engine consumes already-normalized events.
- **ROADMAP.md** M3 line: "Publish the plugin contract and safe local example
  actions."
- **Existing input shapes** (`hardware/contracts.py`): `NormalizedInputEvent`
  is a frozen, slotted dataclass with `kind`, `control_id`, `action`,
  `monotonic_ns` (`contracts.py:621-644`); `InputAction` is the physical
  event enum (`PRESS`/`RELEASE`/`LEFT`/`RIGHT`, `contracts.py:72-76`) whose
  naming the new action vocabulary must not collide with. `ResultStatus`
  (`contracts.py:79-84`) is likewise distinct from the new action status.
- **Event key style** (`events.py:26-37`): `button.{n}.{press|release}`,
  `knob.{n}.{press|release}`, `knob.{n}.{left|right}`.
- **Protocol style** (`hardware/backend.py:19-26`): narrow in-process
  `typing.Protocol`; frozen/slotted dataclasses with `to_dict()` and strict
  `__post_init__` validation are the house contract style.
- **Legacy shell executor** (`daemon.py:41-71`): `run_actions`/`run_command`
  dispatch user action strings through `subprocess.Popen(..., shell=True)`.
  This is the path M3 deliberately does **not** wire in (G8 concern).
- **CLI convention** (`input_cli.py:391-434` and `pyproject.toml`
  `[project.scripts]`): `argparse` with `prog=` name, `main(argv) -> int`,
  deterministic JSON with `schema_version`.

## 3. Scope

**In scope (M3 completion):**
1. New `src/streamdock_n3/actions/` package: plugin contract, contract types,
   engine, registry, builtins, config loader, and demo CLI.
2. Two safe builtins — `LaunchAppPlugin` and `LogEventPlugin` — plus
   `builtin_registry()`.
3. File-based JSON bindings with a shipped `actions.default.json` sample and
   a `load_bindings(path)` loader.
4. `n3-ai-deck-run-action` console script for hardware-free demos.
5. Tests first (RED→GREEN) with fake plugins and mocked subprocess only; no
   real process spawning, no `/dev` access, no SDK import.

**Out of scope:** entry-point-based dynamic plugin discovery (registry stays
explicit), GUI configuration, AI plugins (M4), LCD/UI feedback of action
results, plugin market, and any wiring of the legacy `daemon.py` shell
executor (G8 concern — that path remains untouched and planned).

## 4. Design

### 4.1 Plugin contract

`src/streamdock_n3/actions/contracts.py` defines an in-process Python
protocol, following the pattern of `hardware/backend.py:19-26`:

```python
class ActionPlugin(Protocol):
    def metadata(self) -> PluginMetadata: ...
    def validate_config(self, config: object) -> list[str]: ...  # empty = valid
    def execute(self, context: ActionContext, config: object) -> ActionResult: ...
```

- `validate_config` returns a list of human-readable problems; an empty list
  means the config is valid.
- Plugins run in-process inside the engine's worker thread; entry-point
  dynamic discovery is explicitly out of scope, so the registry is an
  explicit mapping from plugin name to instance.

### 4.2 Contract types

All frozen, slotted dataclasses with `to_dict()`, matching the house style:

- `PluginMetadata(name, version, description)` — declared by the plugin.
- `ActionContext(event_key, control_id, kind, action, monotonic_ns)` —
  transport-neutral view of one normalized event; fields mirror
  `NormalizedInputEvent` plus the derived key. No raw codes, report bytes, or
  node names ever appear here.
- `ActionStatus(StrEnum)` with `{ok, error, timeout, skipped}` — distinct
  from `contracts.py:ResultStatus`.
- `ActionResult(status, plugin, detail, duration_ms, to_dict)` — the engine
  stamps `plugin` and `duration_ms` on every result; plugins supply
  `status`/`detail`. `plugin` is the binding's plugin name (may be
  `"<unbound>"`/`"<unknown>"` style only when the engine fabricates a result).
- `ActionBinding(event_key, plugin, config)` — one event key mapped to a
  plugin name plus its config.
- Naming deliberately uses the `Action*` prefix so none of these collide with
  the existing `InputAction` enum or `ResultStatus` in `hardware/contracts.py`.

### 4.3 Engine

`src/streamdock_n3/actions/engine.py`:

- `ActionEngine(registry, bindings, timeout_seconds=5.0)` where `registry`
  maps plugin name → `ActionPlugin` and `bindings` maps event key →
  `ActionBinding`.
- `handle_event(NormalizedInputEvent) -> ActionResult | None`:
  1. Derive the key with a pure `event_key_for(event)` mirroring
     `events.py:26-37` (`button.1.press`, `knob.2.left`, ...).
  2. Unbound key → return `None` (no result, no execution).
  3. Look up the plugin; unknown name → fabricated `error` result.
  4. Run `plugin.validate_config(binding.config)`; any problems → fabricated
     `error` result with the joined detail.
  5. Build `ActionContext`, then execute inside a shared
     `ThreadPoolExecutor(max_workers=1)`: `future.result(timeout_seconds)`.
     `TimeoutError` → cancel the future and return `timeout`; any plugin
     `Exception` → return `error`; both measured into `duration_ms`.
  6. Success → the plugin's `ActionResult` with engine-stamped `plugin` and
     `duration_ms`.
- `handle_event` **never raises** across the plugin boundary; every failure
  mode is a structured result. Plugins are additionally documented to
  self-limit their execution time, but the engine timeout is the enforcement
  backstop.

### 4.4 Safe builtins

`src/streamdock_n3/actions/builtins.py`:

- `LaunchAppPlugin` — `config = {"app": "<name>"}` where `name` must be on an
  explicit allowlist (examples: `alacritty`, `firefox`, `wpctl`,
  `playerctl`). At execution time the name is resolved via `shutil.which`
  to an absolute path, then launched with `subprocess.Popen(argv_list,
  shell=False, start_new_session=True)`. A shell string is never accepted;
  an unknown or unresolvable name fails as an `error` result before any
  process starts. `validate_config` rejects non-allowlisted names.
- `LogEventPlugin` — zero side effects: `validate_config` always returns `[]`
  and `execute` writes a structured log line only.
- `builtin_registry()` (`actions/registry.py`) returns a `PluginRegistry`
  containing exactly `launch_app` and `log_event`.

### 4.5 Config

- Bindings file: JSON object mapping event keys to
  `{"plugin": "<name>", "config": {...}}`, e.g.
  `{"button.1.press": {"plugin": "launch_app", "config": {"app": "alacritty"}}}`.
- `load_bindings(path) -> dict[str, ActionBinding]`
  (`actions/config.py`): a missing file yields an empty mapping; malformed
  JSON raises a defined `BindingsError` (a structured error, never a crash)
  that the caller — e.g. the CLI — renders as structured JSON.
- Shipped default sample `src/streamdock_n3/resources/actions.default.json`
  (same resource location convention as the key maps) binds the full standard
  key space — every button and knob event — to `log_event`, so an out-of-box
  install has zero side effects and satisfies the US-03 no-arbitrary-shell
  default.

### 4.6 Demo CLI

`src/streamdock_n3/actions/cli.py` with console script
`n3-ai-deck-run-action = "streamdock_n3.actions.cli:main"`, mirroring
`input_cli.py`'s structure:

- `--event button.1.press` (required) — parses the key into a synthetic
  `NormalizedInputEvent` (monotonic_ns from `time.monotonic_ns()`), so the
  CLI runs with no hardware, no SDK import, and no `/dev` access.
- `--bindings PATH` — defaults to the shipped `actions.default.json`.
- `--dry-run` — resolves the binding and reports `status: "skipped"` without
  invoking the plugin.
- Output is deterministic JSON with `schema_version` (1), plus `event_key`,
  `status`, `plugin`, `detail`, `duration_ms`; unbound events report
  `"status": "unbound"`. Malformed bindings render as structured error JSON,
  not a traceback.

## 5. Safety invariants

- No shell in the default configuration: the shipped sample binds every
  standard event to `log_event`, and `LaunchAppPlugin` executes argv lists
  only (`shell=False`); arbitrary shell strings, downloaded content, and
  untrusted scripts never run by default (US-03).
- The engine never raises across the plugin boundary: missing plugin, config
  validation failure, plugin exception, and timeout all return structured
  `ActionResult` values (US-03; ARCHITECTURE failure boundary).
- Plugin failure, timeout, or missing config never crashes the device service
  (US-03).
- Standard events carry no vendor protocol details: `ActionContext` and event
  keys are transport-neutral; raw codes, report bytes, and node names never
  enter the actions layer (US-03).
- The legacy `daemon.py` shell executor (`run_actions`/`run_command`,
  `shell=True`) is untouched (G8 concern) and not wired into the M3 engine.
- No hardware access anywhere in `actions/`: the package never imports the
  vendored SDK, never opens `/dev`, and never reads sysfs; it consumes only
  `NormalizedInputEvent`.
- Builtin launch resolves allowlisted names to absolute paths at execution
  time via `shutil.which`; non-allowlisted or unresolvable names fail as
  `error` results before any process is started.

## 6. Test plan (RED→GREEN, no real device)

- **Engine paths** with fake plugins, covering all six outcomes: success,
  unbound (returns `None`), missing plugin, config validation failure,
  plugin exception (engine does not raise), and timeout (a fake plugin that
  sleeps past `timeout_seconds`; engine returns within the bound).
- **Builtins** with mocked `subprocess.Popen` and `shutil.which`: argv-list
  construction, `shell=False`, `start_new_session=True`, allowlist rejection
  before any `Popen` call, unresolvable name → error result; `log_event`
  emits a structured log line only. No real process spawning, no `/dev`
  access.
- **Config**: `load_bindings` missing file → empty mapping; malformed JSON →
  `BindingsError`; the default sample parses and covers the full standard key
  space with `log_event`.
- **CLI**: `main(["--event", "button.1.press", "--dry-run"])` emits JSON with
  `schema_version` 1 and `status: "skipped"`; unknown event key and malformed
  bindings produce structured error JSON; no SDK import, no `/dev` access.
- **Public-project guards** (pattern of `test_public_project.py`): updated
  alongside the docs in P4 when ARCHITECTURE.md flips "Event and action
  engine"/"Plugin contract" from planned to implemented, ROADMAP.md M3 line
  is checked, and README.md/README.zh-CN.md drop the "planned plugin
  contract" phrasing (`test_public_docs_label_unavailable_architecture_as_planned`).

## 7. Implementation order

1. **P1** this design doc approved.
2. **P2** contracts + engine: `actions/contracts.py`, `actions/engine.py`,
   `event_key_for`, and the six-path engine test suite.
3. **P3** builtins + default config: `actions/registry.py`,
   `actions/builtins.py`, `actions/config.py`,
   `resources/actions.default.json`, with mocked-subprocess tests.
4. **P4** CLI + docs flip: `actions/cli.py`, console script in
   `pyproject.toml`, ARCHITECTURE.md/ROADMAP.md/README updates, and the
   `test_public_project.py` guard updates.
5. **P5** optional owner-gated on-hardware smoke: run the engine from a real
   key press through the formal input path; requires the owner present and is
   not blocking.

Each phase lands as its own small commit series with the quality gate
(`uv run pytest`, `uv run ruff check .`, `uv build`) green before the next.
