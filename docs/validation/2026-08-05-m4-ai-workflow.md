# N3 V3.0 (6602:1000) M4 AI Workflow On-Hardware Validation

| Field | Result |
|---|---|
| Date | 2026-08-05 |
| Tested commit | `334fbf9` |
| Context | Owner-present validation session for M4, following the M4 AI workflow design (`docs/superpowers/specs/2026-08-05-m4-ai-workflow-design.md`, measurement contract in section 4.2) and the M3/live-dispatch sessions. Same device as those sessions |
| Scope | One interleaved read+write smoke with LCD state feedback, one single AI trial, and the golden workflow run against the section 4.2 measurement contract, driven through the owner-run foreground CLI (`n3-ai-deck-live`) and the action engine demo CLI. The only writes were the validated init trio and per-press LCD state images through the G7-validated key-image path; no daemon wiring |

## Interleaved read+write smoke (approval point 1)

1. `n3-ai-deck-live --bindings <demo> --feedback --duration-ms 60000` with
   `button.1.press` bound to `log_event`; the owner pressed LCD key 1 eight
   times.
2. The session reported 8 events, 8 dispatched, 0 unknown, `disconnected:
   false`, `init_ok: true`, and exited 0.
3. The owner visually confirmed the key-1 LCD flashed a green SUCCESS image
   on every press while the read loop kept running — interleaved reads and
   frame-level writes on the same node are validated on hardware. The
   conservative pause-then-write fallback was not needed.

## Single AI trial

1. `n3-ai-deck-run-action --event button.1.press --bindings <ai demo>` with
   the `ai_text` plugin configured for an OpenAI-compatible provider
   (`base_url` `https://api.deepseek.com`, model `deepseek-v4-flash`). The
   credential came from an environment variable sourced from user-controlled
   local configuration and was never printed, logged, or committed.
2. The run returned `status: ok` with a one-sentence Chinese summary (content
   not recorded per contract), 1632 ms, and exited 0.

## Golden run (approval point 2)

1. `n3-ai-deck-live --bindings <ai demo> --feedback --timeout-seconds 15
   --duration-ms 300000`; the owner pressed LCD key 1 eleven times (target
   was 10; the extra press also succeeded).
2. Every press returned `status: ok`, `plugin: ai_text`, with durations
   between 1457 ms and 1880 ms. The final summary reported
   `{"status": "succeeded", "events": 11, "dispatched": 11, "unknown": 0,
   "disconnected": false, "init_ok": true, "duration_ms": 300001}` and the
   session exited 0.
3. The owner visually confirmed every press showed yellow RUNNING then green
   SUCCESS on the key-1 LCD; zero red FAILURE and zero orange TIMEOUT
   occurred.

## Measurement-contract mapping (section 4.2)

1. **Scenario** = the clipboard-summarize golden workflow of the design;
   **start event** = `button.1.press`; **end** = the `ActionResult` recorded
   (plus the state image written).
2. **Per-run timeout** = 15 s engine bound (`--timeout-seconds 15`) with a
   10 s HTTP self-timeout inside the plugin; every run finished well within
   both bounds (1457–1880 ms).
3. **Evidence** = the state sequence and counters above only — this record
   contains no AI output text, no clipboard content, and no credentials.
4. **Golden metric** (`tasks/prd-n3-ai-deck.md:157`): required 10/10
   consecutive successes → achieved 11/11.

## Conclusions

- US-04 acceptance is met: at least one end-to-end scenario runs from device
  event to structured result; running / success / failure / timeout are
  distinguishable on-device (yellow / green / red / orange); credentials were
  provided locally and never exposed; the golden scenario completed 10/10
  (actual 11/11) with non-sensitive evidence retained.
- Interleaved read+write on the same node is now validated on hardware; the
  conservative pause-then-write fallback was not required.
- This is the owner-run foreground workflow. G8 daemon-managed background
  wiring remains planned and is not claimed by this record.

## Constraints honored / redaction

- The sessions were foreground and bounded; the only writes were the validated
  init trio and per-press LCD state images through the G7-validated key-image
  path; no daemon wiring and no automatic recovery writes.
- This record contains no serial, bus location, `/dev` node name, absolute
  path, username, key material, AI output text, or clipboard content. The
  bindings files are referred to only as explicit bindings files outside the
  repository; the credential source is referred to only as user-controlled
  local configuration.
