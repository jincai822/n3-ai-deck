# Architecture

N3 AI Deck evolves the existing `streamdock_n3` package incrementally. The passive, read-only `device_catalog.py` and `discovery.py` path for sysfs USB/HID metadata is implemented in M1, and the hardware-free G0 simulation foundation is implemented in M2. This passive catalog is not ProductIDs.g_products and does not modify the vendored SDK's active product table. The active hardware stages G1–G7 remain planned M2 work. Everything below distinguishes those implemented M1/G0 boundaries from the planned target architecture.

## G0 implemented safety boundary

Only the hardware-free G0 simulation foundation is implemented. Its Adapter and helper paths are independent:

```text
M1 passive observation
  -> immutable test/profile contract

N3Adapter transaction coordinator
  -> private capability reservation
  -> FakeBackend exactly once
  -> redacted evidence acceptance
  -> private settlement / stage commit

fake-only isolated helper process
  -> stateless CommandPolicy
  -> FakeBackend exactly once
  -> OperationResult only
```

`N3Adapter` is the sole stateful transaction coordinator. Its private gate owns ordered reservations, result settlement, recovery, and stage commits; the backend and evidence sinks receive no live gate authority. The helper path is independent: `N3Adapter` does not invoke it, and it returns only an `OperationResult` without connecting to the Adapter's evidence recorder. Helper snapshots are validation context, not state authority.

Evidence acceptance is mandatory before settlement: if an external evidence sink raises, the gate blocks and the stage cannot advance. When an evidence failure coincides with a backend `DISCONNECTED` result, the disconnect classification takes priority over `EVIDENCE_FAILURE`: evidence is still recorded as failed, but the Adapter returns the disconnect result and enters `DISCONNECTED`, clearing all queues with zero automatic recovery writes.

`FakeBackend` is the only implemented backend. G0 does not activate `6602:1000`: that identifier remains a candidate, unvalidated, and has no selected production interface or active profile. G0 does not import the vendored SDK, open `/dev`, install permissions, or write hardware.

G1 chooses and approves an exact active profile and interface responsibility; G2 covers separately approved permissions; G3–G7 cover input, initialization, brightness, one LCD, and six LCDs. The legacy daemon, action, plugin, and UI flow remains planned and disconnected from the G0 Adapter.

## G1 implemented safety boundary

G1 approves an exact candidate active profile and resolves interface responsibility from passive sysfs evidence only; it never opens `/dev` or loads the SDK. A pure role classifier maps boot-keyboard and input-subsystem interfaces to `INPUT`, and vendor-HID interfaces without an input association to `CONTROL`; any ambiguity, incomplete evidence, or later identity/interface/role drift fails closed at the gate. The approved profile and roles are pinned at G1 commit and every later stage must match exactly. Approved roles are approved candidate roles pending G3 physical validation: `6602:1000` remains a candidate with unvalidated protocol, and no compatibility claim is made.

## G2 implemented offline permission boundary

G2 designs permissions offline and grants nothing. Pure generators render a temporary single-node ACL plan (default first strategy, placeholders only, never executed) and precise persistent udev rule templates matching exactly `6602:1000` plus the validated subsystem/interface with `TAG+="uaccess"`; `MODE="0666"`, vendor-only matches, and unproven combined grants are rejected by tests. An offline install transaction applies artifacts only to an explicit target root that can never be `/etc` or `/usr`, verifying target state before commit and rolling back byte-for-byte. The G2 gate requires a permission plan covering exactly the input and hidraw subsystems justified by the pinned G1 roles and records redacted approval evidence. No permission was granted, no system file was written, and no permission command was executed; any real ACL or udev installation remains a separate owner-gated manual action before G3.

## G3 implemented read-only input boundary

G3 observes physical inputs through one bounded, read-only, short-lived helper session. A pure evdev codec parses raw `input_event` bytes and normalizes them through a configurable key map; the session opens exactly one approved input node `O_RDONLY`, runs a select-bounded loop with per-control counts and p95 read-to-normalize latency, counts unknown events without ever persisting raw payloads, and classifies read errors as `DISCONNECTED` within a bounded grace with zero automatic recovery writes and no reopen. The G3 gate requires a session spec and settles machine-backed: `INPUT_VALIDATED` only when every control meets its press/release/rotation counts, latency is within target, and the session did not disconnect. Session evidence records counts, latency, unknown count, and a disconnect flag with redacted digests. Automated tests never open `/dev`; the real session remains an owner-gated manual action (temporary ACL, exact command/expectation/deadline/recovery presented before execution).

## Public components

### Device adapter

The planned responsibility is to own active supported USB identifiers, SDK/HID access, lifecycle, input, brightness, and LCD operations. The target behavior is to fail closed for unknown identifiers. It is deliberately separate from M1's passive catalog, which neither opens devices nor establishes protocol compatibility.

### Event and action engine

M3 implements the action engine in `streamdock_n3.actions`: `ActionEngine`
resolves configured actions for transport-neutral normalized events, enforces
a hard timeout per execution, and returns a structured result without
provider-specific logic and without raising across the plugin boundary.
Entry-point discovery of plugins, GUI configuration, and wiring the engine to
physical events through the device daemon remain planned.

### Plugin contract

M3 implements the plugin contract in `streamdock_n3.actions`: an in-process
`ActionPlugin` protocol with metadata, configuration validation, execution,
and structured result types, plus safe builtin plugins (an allowlisted
launcher and a structured-log-only plugin) and file-based JSON bindings.
Entry-point discovery and GUI configuration remain planned.

### Local UI and diagnostics

The planned responsibility is to show device/action state and separate read-only discovery from hardware writes. The implemented M1 `discovery.py` command reads only allowlisted sysfs metadata and can report multiple HID candidates without choosing an interface.

## Target data flow

```text
device event -> Device adapter -> normalized event -> action engine
             -> plugin -> structured result -> UI/log/optional LCD feedback
```

## Open Core boundary

The planned public core is intended to own device integration, local execution, plugin contracts, UI, diagnostics, documentation, and tests. In the target boundary, hosted synchronization, enterprise administration, paid connectors, and customer deployment remain outside the public dependency graph.

## Failure boundaries

- The target design produces permission-remediation guidance without privilege escalation.
- The target design isolates plugin failures and timeouts from the device daemon.
- The target design limits missing AI credentials to the affected plugin.
- Hardware-write work remains subject to a deliberate manual validation stage.
