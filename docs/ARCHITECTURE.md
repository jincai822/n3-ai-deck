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

`FakeBackend` is the only implemented backend. G0 does not activate `6602:1000`: that identifier remains a candidate, unvalidated, and has no selected production interface or active profile. G0 does not import the vendored SDK, open `/dev`, install permissions, or write hardware.

G1 chooses and approves an exact active profile and interface responsibility; G2 covers separately approved permissions; G3–G7 cover input, initialization, brightness, one LCD, and six LCDs. The legacy daemon, action, plugin, and UI flow remains planned and disconnected from the G0 Adapter.

## Public components

### Device adapter

The planned responsibility is to own active supported USB identifiers, SDK/HID access, lifecycle, input, brightness, and LCD operations. The target behavior is to fail closed for unknown identifiers. It is deliberately separate from M1's passive catalog, which neither opens devices nor establishes protocol compatibility.

### Event and action engine

The planned responsibility is to normalize physical events, resolve configured actions, apply timeouts, and return a structured result without provider-specific logic.

### Plugin contract

The planned responsibility is to define metadata, configuration validation, execution, and result types for local automation and AI integrations.

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
