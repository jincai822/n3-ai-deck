# M4 AI Workflow Design

**Date:** 2026-08-05
**Status:** Draft for owner review
**Supersedes:** None
**Evidence base:** `tasks/prd-n3-ai-deck.md` (US-04 at :218-227, golden
metric :157, measurement-contract assumption :159, credential question :279,
manual owner gate :142, no-credential fallback :115), `SECURITY.md` (:7-11),
`docs/ARCHITECTURE.md` (:101, "Event and action engine" and "Owner-run live
dispatch" sections), `ROADMAP.md` (M4 line :104-105),
`docs/superpowers/specs/2026-08-05-live-dispatch-design.md` (live loop, CLI,
default bindings), `docs/validation/2026-08-05-g7-six-lcd-and-production-regression.md`
(G7 write/input validation), `docs/validation/2026-08-05-live-dispatch.md`
(live foreground validation),
`src/streamdock_n3/icons.py`, `src/streamdock_n3/actions/engine.py`,
`src/streamdock_n3/actions/contracts.py`, `src/streamdock_n3/actions/live.py`,
`src/streamdock_n3/actions/builtins.py`, `src/streamdock_n3/actions/config.py`,
`src/streamdock_n3/hardware/vendor_backend.py`, `tests/test_public_project.py`

## 1. Why this design exists

M3 delivered the action engine and its safe builtins, and the live-dispatch
milestone delivered a foreground CLI that streams real physical events into
the engine. The device can now turn one key press into a structured
`ActionResult`, but every shipped path is local: `log_event` writes a log
line, `launch_app` starts an allowlisted program. Nothing yet runs a real
end-to-end **AI** workflow with visible device feedback — the M4 user story
(`tasks/prd-n3-ai-deck.md:218-227`).

M4's acceptance criteria are:

- [ ] at least one end-to-end scenario from device event to structured result;
- [ ] running / success / failure / timeout states are distinguishable;
- [ ] credentials are provided locally by the user and never enter the
      repository, diagnostics, or LCD images;
- [ ] the golden scenario runs successfully 10 times in a row with
      non-sensitive evidence retained.

The PRD also makes M4's success metric conditional on a contract that was
never formed: the golden-metric row (`tasks/prd-n3-ai-deck.md:157`) targets
10/10 consecutive runs, and the assumption at
`tasks/prd-n3-ai-deck.md:159` states the concrete workflow, start/end
events, per-run timeout, and evidence format **must** be fixed before M3 —
that deadline has passed and no contract exists. **This document produces
that measurement contract** (§4.2); M4 cannot be accepted without it.

The PRD left the credential mechanism open
(`tasks/prd-n3-ai-deck.md:279`: desktop keyring vs environment variable vs
external secret manager). **This design resolves it: an environment
variable** (§4.3), consistent with `SECURITY.md:11`, which requires AI
integrations to load secrets from user-controlled local storage or
environment-backed configuration.

## 2. Validated facts (ground truth for implementation)

Ground truth, verified against the code and prior hardware records:

- **The PRD pins the acceptance contract.** US-04 acceptance criteria are at
  `tasks/prd-n3-ai-deck.md:224-227`; the golden metric and its measurement
  contract are at `tasks/prd-n3-ai-deck.md:157,159`; the credential question
  is at `tasks/prd-n3-ai-deck.md:279`; the manual owner gate for hardware
  writes, secrets, and releases is at `tasks/prd-n3-ai-deck.md:142`; and the
  no-credential fallback ("without AI credentials, local automation still
  works") is at `tasks/prd-n3-ai-deck.md:115`.
- **Security posture is already written down.** `SECURITY.md:7-11` forbids
  committing keys/tokens and mandates that AI integrations load secrets from
  user-controlled local storage or environment-backed configuration;
  `docs/ARCHITECTURE.md:101` states missing AI credentials are limited to the
  affected plugin.
- **Engine statuses map directly to the required feedback states.**
  `ActionStatus` is `ok` / `error` / `timeout` / `skipped`
  (`src/streamdock_n3/actions/contracts.py:13-19`), and
  `ActionEngine.handle_event` (`src/streamdock_n3/actions/engine.py:60`)
  never raises across the plugin boundary. The LCD states (success / failure
  / timeout) are the engine's own outcomes; "running" is the engine call in
  flight.
- **The engine timeout is the per-run bound.** `DEFAULT_TIMEOUT_SECONDS = 5.0`
  (`src/streamdock_n3/actions/engine.py:19`) and plugin calls run on a
  `ThreadPoolExecutor(max_workers=1)` (`engine.py:118-121`). A slow plugin
  therefore serializes the loop; the AI plugin needs a longer bound (§4.2,
  §4.7) and its HTTP call needs an internal self-timeout below the engine
  bound.
- **The live loop dispatches after the engine returns.** In
  `run_live_loop`, `_dispatch` (guarded at
  `src/streamdock_n3/actions/live.py:109-119`) runs
  `engine.handle_event`, and only afterwards the optional `on_event`
  callback fires (`live.py:177-179`). The "running" state therefore needs a
  **pre-dispatch hook**, and the `on_event` call itself is currently
  **not** exception-guarded (`live.py:178-179`) — a callback that raises
  would abort the loop, unlike every other failure path.
- **Writes open/close per frame, and the transport is idle after init.** The
  live session writes the init trio once through `_write_init_frames`
  (`live.py:92-106`): `transport.open_read_write(node)`, then per frame
  `transport.write` + `transport.drain_acks`, then `transport.close` in a
  `finally`. The same shape is used by `VendorHidCommandBackend.execute`
  (`src/streamdock_n3/hardware/vendor_backend.py:173-217`), which opens the
  node only inside each execute; the `VendorHidTransport` protocol is
  `open_read_write` / `write` / `drain_acks` / `close`
  (`vendor_backend.py:65-82`) and frame encoding is `_frames_for_command`
  (`vendor_backend.py:131-152`). After init the transport sits idle, so a
  per-write open/write/drain/close call is the natural shape for writing key
  images during the read loop.
- **Interleaved read+write on one node is NOT hardware-validated.** The G7
  record and the live-dispatch record drove writes and reads through
  separate node opens/sessions (init write and input read happened on
  separate file descriptors at separate times). Writing an LCD image **while
  the read loop is actively polling another descriptor** has not been
  exercised on hardware — P5 must validate it first (§7), with a
  pause-listen-then-write ordering as the conservative fallback.
- **Rendering primitives exist.** `make_icon`
  (`src/streamdock_n3/icons.py:32-52`) shows the house centering pattern:
  `Image.new("RGB", ...)`, `draw.textbbox` per line, centered `x`/`y`, saved
  as JPEG (`icons.py:38-52`). LCD keys are 72×72; the feedback renderer
  reuses this pattern.
- **Plugin contract and registry are in place.** `builtin_registry()`
  (`src/streamdock_n3/actions/builtins.py:102-107`) returns `launch_app` and
  `log_event`; the contract is `metadata()` / `validate_config()` /
  `execute()` returning `ActionResult` (`builtins.py:25-99`). The AI plugin
  follows the same contract and registers alongside them.
- **Clipboard tooling is confirmed.** `xclip` is present on the owner's X11
  machine. Reading the clipboard as a fixed argv list
  (`xclip -selection clipboard -o`) with no shell satisfies the M3 rule
  against arbitrary shell execution.
- **Public secret scanning already covers new files.** The tracked-publication
  scan (`tests/test_public_project.py`,
  `test_tracked_publication_text_has_no_local_paths_or_obvious_tokens`)
  checks every git-tracked file for machine paths and credential tokens, and
  `test_public_documents_do_not_expose_connected_device_details` checks the
  published docs for serial markers, `/dev` names, and bus numbers. New code
  and docs must clear these as they land.

## 3. Scope

**In scope (M4 AI workflow):**
1. New `src/streamdock_n3/actions/ai.py`: `AiTextPlugin`, a stdlib-only
   OpenAI-compatible `/chat/completions` client with the `{clipboard}`
   prompt placeholder, registered in `builtin_registry`.
2. New `src/streamdock_n3/actions/feedback.py`: `render_state_image` and
   `write_key_image` for per-key LCD state feedback.
3. Live-loop hooks: an optional `on_dispatch_start(event)` pre-dispatch
   callback and an exception guard around `on_event` in
   `src/streamdock_n3/actions/live.py` (backward compatible).
4. CLI flags on `n3-ai-deck-live`: `--feedback` (LCD state images on key 1)
   and `--timeout-seconds` (engine timeout override, default 5).
5. The **measurement contract** for M4 acceptance (§4.2), resolving
   `tasks/prd-n3-ai-deck.md:159`.
6. Tests first (RED→GREEN) with mocked HTTP, subprocess, environment, and a
   fake transport; no real device, no network, no processes.
7. Owner-gated on-hardware validation (P5): interleaved read+write smoke,
   then the golden 10/10 run, then a validation record.

**Out of scope:** G8 (daemon wiring, auto-restart, auto-reconnect — remains
planned); `daemon.py`; keyring or file-based secret storage (resolved to
environment variable, §4.3); plugin marketplaces or arbitrary downloaded
plugins; LCD brightness or non-key-1 feedback; batch/multi-key workflows;
shell access from the AI plugin (clipboard and HTTP only); any change to the
M3 engine's plugin contract.

## 4. Design

### 4.1 Golden workflow

One physical action runs one real AI workflow with visible state:

```text
LCD key 1 press
  -> normalized `button.1.press`
  -> on_dispatch_start -> LCD key 1 = yellow "running"
  -> AiTextPlugin.execute
       xclip -selection clipboard -o        (fixed argv, no shell, 2 s timeout)
       POST {base_url}/chat/completions     (urllib.request, 10 s self-timeout,
                                             Authorization: Bearer <key>)
       prompt = configured prompt with {clipboard} substituted
       -> one-sentence summary
  -> ActionResult recorded
  -> on_event -> LCD key 1 = green (success, first line truncated)
                 | red (failure) | orange (timeout)
```

LCD key 1 states: **yellow** = running, **green** = success (first line of
the summary, truncated to fit 72×72), **red** = failure, **orange** =
timeout. The final state persists on the key until the next press.

### 4.2 Measurement contract (full text)

This section is the measurement contract required by
`tasks/prd-n3-ai-deck.md:159`. It fixes, before M4 implementation, the
scenario, start/end events, per-run timeout, and evidence format that the
golden metric (`tasks/prd-n3-ai-deck.md:157`) will be judged against.

1. **Scenario.** The golden workflow of §4.1: LCD key 1 press reads the
   current clipboard text via `xclip`, sends it to the configured
   OpenAI-compatible endpoint for a one-sentence summary, and shows the
   outcome state on LCD key 1.
2. **Start event.** The normalized `button.1.press` event on LCD key 1. A
   run is counted only when dispatch starts (`on_dispatch_start` fired).
3. **End event.** The `ActionResult` for that dispatch is recorded (success,
   failure, or timeout). The run is complete when the state image for the
   result has been written (or the write was attempted and failed) and the
   JSONL line for the event has been emitted.
4. **Per-run timeout.** 15 seconds total per run: the engine runs with
   `--timeout-seconds 15`, and the plugin's HTTP call carries a 10-second
   self-timeout (`urllib.request` `timeout=10`). A run that exceeds the
   engine bound is recorded as `timeout`, never as success.
5. **Evidence format.** The validation record lists the 10-run **state
   sequence** (e.g. `ok, ok, timeout, ...`) and the counters (runs, success,
   failure, timeout) **only**. It contains no AI output text, no clipboard
   content, and no credentials or credential identifiers beyond the
   environment-variable name.
6. **Acceptance.** The golden scenario counts as passed when 10 consecutive
   controlled runs each record a distinguishable end state, at least the
   required 10/10 complete with the `ok` state, and the retained evidence is
   non-sensitive per item 5. As `tasks/prd-n3-ai-deck.md:159` states, this
   is technical evidence for the Early Preview, not a claim of user value,
   stability, or production readiness.

### 4.3 Credentials

- The API key is read from an **environment variable only**. Default name
  `N3_AI_DECK_API_KEY`, overridable per binding via the plugin config key
  `api_key_env`. This resolves `tasks/prd-n3-ai-deck.md:279` (keyring vs
  environment variable vs external secret manager → environment variable)
  and satisfies `SECURITY.md:11` (environment-backed configuration).
- Default endpoint `https://api.moonshot.cn/v1` and default model
  `moonshot-v1-8k`; both overridable via plugin config (`base_url`, `model`).
- The key is read from `os.environ` at execute time, used only in the
  `Authorization` header of the one HTTP request, and is never logged,
  rendered on an LCD image, written to any file, or included in any
  `ActionResult` detail, JSONL output, or validation record.
- Supplying a real credential is an owner-gated manual action
  (`tasks/prd-n3-ai-deck.md:142`); the shipped defaults contain no key, and
  without the variable set the plugin returns a structured failure while
  every other plugin keeps working (`tasks/prd-n3-ai-deck.md:115`,
  `docs/ARCHITECTURE.md:101`).

### 4.4 AiTextPlugin (`src/streamdock_n3/actions/ai.py`)

Stdlib only (`urllib.request`, `subprocess`, `os`, `json`) — **zero new
runtime dependencies**. Config keys, all optional:

```python
{"base_url": str,      # default https://api.moonshot.cn/v1
 "model": str,         # default moonshot-v1-8k
 "api_key_env": str,   # default N3_AI_DECK_API_KEY
 "prompt": str}        # default "Summarize the following text into one sentence: {clipboard}"
```

`validate_config` checks types and the `api_key_env` name syntax; `execute`
never raises and returns a structured `ActionResult` for every path:

| path | status | detail (fixed, no payload) |
|---|---|---|
| credential missing/empty | `error` | "ai: no credential in environment" |
| clipboard empty / xclip missing or failed | `error` | "ai: clipboard unavailable" |
| network error / HTTP error | `error` | "ai: request failed" |
| HTTP self-timeout (10 s) | `error` | "ai: request timed out" |
| malformed response | `error` | "ai: malformed response" |
| engine timeout (15 s) | `timeout` | engine-supplied timeout detail |
| success | `ok` | first line of the summary, truncated to 80 chars |

The `{clipboard}` placeholder is substituted with the clipboard text into
the request body only. The response's summary text is truncated to its first
line (max 80 chars) for the LCD; the full AI payload never enters logs, LCD
images, or evidence. Success `detail` is the truncated line — a bounded
display artifact, not evidence (the validation record keeps only states and
counters, §4.2 item 5). Clipboard content and the API key appear in exactly
one place: the outgoing HTTP request (body and header respectively).
`builtin_registry()` (`src/streamdock_n3/actions/builtins.py:102-107`)
gains an `ai` entry.

### 4.5 Live-loop changes (`src/streamdock_n3/actions/live.py`)

Backward-compatible additions to `run_live_loop`:

```python
on_dispatch_start: Callable[[NormalizedInputEvent], None] | None = None,
```

1. **Pre-dispatch hook.** Immediately before `engine.handle_event(normalized)`
   for a normalized event, call `on_dispatch_start(normalized)` if provided
   (default `None`). This is the "running" signal the post-dispatch
   `on_event` (`live.py:177-179`) cannot provide.
2. **Exception guard around `on_event`.** Wrap the existing
   `on_event(normalized, result)` call in the same never-raise style as
   `_dispatch` (`live.py:109-119`): a callback exception is recorded (or
   ignored by the loop) and the session continues to its deadline. The
   engine/plugin boundary already never raises; this closes the last
   unguarded callback in the loop.
3. Neither change alters the `LiveSessionSpec`/`LiveSessionResult` contract;
   existing callers and the CLI keep working unchanged.

### 4.6 Feedback (`src/streamdock_n3/actions/feedback.py`)

New module, hardware-agnostic renderer plus a transport-bound writer:

```python
class FeedbackState(StrEnum):
    RUNNING  = "running"    # yellow
    SUCCESS  = "success"    # green
    FAILURE  = "failure"    # red
    TIMEOUT  = "timeout"    # orange

def render_state_image(state: FeedbackState, text: str | None = None) -> bytes:
    # 72x72 RGB JPEG via io.BytesIO, reusing the icons.py centering pattern
    # (icons.py:38-52): solid state color, optional single-line label centered.

def write_key_image(
    node: str, key: int, jpeg: bytes, transport: VendorHidTransport
) -> bool:
    # open/write/drain/close per the _write_init_frames shape (live.py:92-106):
    # open_read_write(node), write the validated image frames, drain ACKs,
    # close in a finally. Any OSError -> False. Never raises.
```

- `render_state_image` reuses the Pillow centering from `make_icon`
  (`src/streamdock_n3/icons.py:38-52`): solid state color background, the
  state label (or the truncated success line) centered, JPEG output into
  memory.
- `write_key_image` encodes the JPEG through the same frame pipeline as
  `_frames_for_command` (`vendor_backend.py:131-152`) and opens/closes per
  call like `_write_init_frames` (`live.py:92-106`), so each image write is
  an independent bounded transaction on an otherwise idle transport.
- Credentials and full AI payloads are never rendered: the only text that
  reaches the LCD is the state label or the bounded success line from §4.4.

### 4.7 CLI (`src/streamdock_n3/actions/live_cli.py`)

Two new flags on `n3-ai-deck-live`, both optional:

- `--feedback` — after each dispatch, write the state image to LCD key 1:
  `on_dispatch_start` renders and writes yellow "running" before the engine
  call, then `on_event` writes green/red/orange per the `ActionResult`
  status (`contracts.py:13-19`). Requires a device node and the
  `--feedback` path uses `write_key_image` with the injectable transport.
- `--timeout-seconds SECONDS` — engine timeout override, default `5`
  (matching `DEFAULT_TIMEOUT_SECONDS`, `engine.py:19`). The golden workflow
  runs with `--timeout-seconds 15` per §4.2 item 4.

Without `--feedback` the CLI behaves exactly as today (JSONL + summary,
zero side effects). `--dry-run` still opens nothing and now also resolves
the `--feedback`/`--timeout-seconds` configuration without touching the
device.

## 5. Safety invariants

- **Credentials never enter the repo, logs, LCD images, or evidence.** The
  key is read from the environment at execute time, used in one request
  header, and excluded from every output channel (§4.3). Public secret
  scanning (`tests/test_public_project.py`) stays green on every new file.
- **Missing credentials degrade only the AI plugin.** Without the variable,
  `AiTextPlugin` returns a structured failure and every other plugin and the
  no-credential flow (`tasks/prd-n3-ai-deck.md:115`) keep working
  (`docs/ARCHITECTURE.md:101`).
- **No new runtime dependencies.** `ai.py` and `feedback.py` use stdlib and
  already-shipped Pillow; the plugin contract, engine, and bindings formats
  are unchanged.
- **Tests never touch the network, processes, or the device.** HTTP,
  `xclip`, and the environment are mocked; the transport is fake; no `/dev`
  access and no SDK import (§6).
- **Hardware writes and real credentials are owner-gated.** LCD image writes
  go through the M2/G7-validated frame path; real-credential use and the
  on-hardware session are manual owner actions
  (`tasks/prd-n3-ai-deck.md:142`).
- **Zero unauthorized hardware writes.** The only new writes are the
  per-state key image on the single configured key during a `--feedback`
  session, each a bounded open/write/drain/close transaction that never
  raises and never retries; a failed write degrades to "no feedback", not a
  crash.
- **Never-raise everywhere.** The plugin, the feedback writer, and the live
  loop's callbacks all return structured outcomes instead of propagating
  exceptions; the session always reaches its clean bounded exit.

## 6. Test plan (RED→GREEN, no real device)

- **AiTextPlugin** (`actions/ai.py`), with `urllib.request`, `subprocess.run`,
  and `os.environ` mocked (pattern of the M2/M3 test suites):
  - config validation: bad types, bad `api_key_env` name;
  - every failure path in §4.4 returns the fixed structured detail and never
    raises: no credential, empty clipboard, xclip missing/failing, network
    error, HTTP error, 10 s self-timeout, malformed response;
  - success returns `ok` with the truncated first line (≤80 chars);
  - the request carries the key in the `Authorization` header and the
    clipboard only in the body; nothing sensitive is logged;
  - the plugin registers in `builtin_registry` alongside the M3 builtins.
- **Feedback** (`actions/feedback.py`):
  - `render_state_image` returns valid JPEG bytes (decode and check size,
    solid state color, centered label); all four states render;
  - `write_key_image` with a fake recording transport: opens once, writes the
    image frames, drains ACKs, closes in a `finally`; `OSError` → `False`,
    no exception; per-call open/write/close independence.
- **Live-loop hooks** (`actions/live.py`):
  - `on_dispatch_start` fires before `engine.handle_event` for every
    normalized event and not for unknown/unbound inputs;
  - an `on_event` callback that raises does not abort the loop (session
    reaches the deadline with correct counters);
  - defaults keep existing behavior (both hooks `None`).
- **CLI** (`actions/live_cli.py`), with node/key map/loop mocked:
  - `--feedback` wiring renders and writes state images via the fake
    transport; `--timeout-seconds` overrides the engine default (default 5);
  - `--dry-run` with `--feedback`/`--timeout-seconds` opens nothing;
  - no device node name, serial, or credential text appears in any output.
- **Public-doc guards** (pattern of `tests/test_public_project.py`) updated
  in P4 alongside the docs flip: ROADMAP M4 checked with an evidence link and
  approval reference `owner:2026-08-05:m4-ai-workflow`, README en/zh status
  lines, and a guard asserting the measurement contract text and the
  no-AI-output evidence rule. The tracked-publication and connected-device
  scans already cover every new file automatically.

## 7. Implementation order

1. **P1** this design doc approved (produces the measurement contract of
   §4.2 and the credential decision of §4.3).
2. **P2** `AiTextPlugin` (`actions/ai.py`): plugin, registry entry, and the
   mocked-HTTP/subprocess/env test suite.
3. **P3** feedback + hooks: `actions/feedback.py` (`render_state_image`,
   `write_key_image`), the `on_dispatch_start` hook and `on_event` guard in
   `actions/live.py`, and their test suites.
4. **P4** CLI + docs flip: `--feedback` and `--timeout-seconds` on
   `n3-ai-deck-live`, `uv build`, ROADMAP M4 checked with the evidence link
   and approval reference `owner:2026-08-05:m4-ai-workflow`, README en/zh
   status lines, and the public-doc guards of §6.
5. **P5** owner-gated on-hardware validation, in this order:
   1. interleaved read+write smoke first — write an LCD key image **while**
      the input loop is active, since this exact interleaving is not yet
      hardware-validated (§2); if it misbehaves, fall back to the
      conservative pause-listen-then-write ordering (stop reading, write,
      resume reading) and record which ordering was used;
   2. the golden 10/10 run against the §4.2 measurement contract, owner
      supplying the credential;
   3. a validation record under `docs/validation/` with only the state
      sequence and counters. Not blocking.

Each phase lands as its own small commit series with the quality gate
(`uv run pytest`, `uv run ruff check .`, `uv build`) green before the next.
