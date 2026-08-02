# N3 V3.0 Read-Only Discovery Validation

| Field | Result |
|---|---|
| Date | 2026-08-03 |
| Tested commit | `1e3938ebf610d1ff3b586a3645d13ea5afa5616d` |
| Command | `n3-ai-deck-detect --json` |
| Expected | Target `6602:1000`; target match `true`; identity `user_reported_candidate`; protocol `unvalidated`; `bcdDevice` `0300`; HID tuples `00/03/00/00` and `01/03/01/01`; interface selection `ambiguous` |
| Actual USB ID | `6602:1000` |
| Actual `bcdDevice` | `0300` |
| Actual HID interfaces | `00/03/00/00`; `01/03/01/01` |
| Actual interface selection | `ambiguous` |
| Exit code | `0` |

The approved command performed passive, read-only USB metadata discovery only. No
active interface, serial identifier, SDK operation, permission change, device
initialization, or hardware write was used.

M2 remains limited by unvalidated physical identity and protocol behavior. SDK
activation and udev permission design each require separate manual approval before
any active-device work.
