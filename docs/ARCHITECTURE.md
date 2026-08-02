# Architecture

N3 AI Deck evolves the existing `streamdock_n3` package incrementally. M0 changes repository presentation only; device behavior changes begin in M1. Everything below describes the planned target architecture, not capabilities available in M0.

## Public components

### Device adapter

The planned responsibility is to own supported USB identifiers, SDK/HID access, lifecycle, input, brightness, and LCD operations. The target behavior is to fail closed for unknown identifiers.

### Event and action engine

The planned responsibility is to normalize physical events, resolve configured actions, apply timeouts, and return a structured result without provider-specific logic.

### Plugin contract

The planned responsibility is to define metadata, configuration validation, execution, and result types for local automation and AI integrations.

### Local UI and diagnostics

The planned responsibility is to show device/action state and separate read-only discovery from hardware writes.

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
