# Architecture

N3 AI Deck evolves the existing `streamdock_n3` package incrementally. M0 changes repository presentation only; device behavior changes begin in M1.

## Public components

### Device adapter

Owns supported USB identifiers, SDK/HID access, lifecycle, input, brightness, and LCD operations. Unknown identifiers fail closed.

### Event and action engine

Normalizes physical events, resolves configured actions, applies timeouts, and returns a structured result without provider-specific logic.

### Plugin contract

Defines metadata, configuration validation, execution, and result types for local automation and AI integrations.

### Local UI and diagnostics

Shows device/action state and separates read-only discovery from hardware writes.

## Data flow

```text
device event -> Device adapter -> normalized event -> action engine
             -> plugin -> structured result -> UI/log/optional LCD feedback
```

## Open Core boundary

The public repository owns device integration, local execution, plugin contracts, UI, diagnostics, documentation, and tests. Hosted synchronization, enterprise administration, paid connectors, and customer deployment live outside the public dependency graph.

## Failure boundaries

- Missing permissions produce remediation guidance without privilege escalation.
- Plugin failure or timeout does not crash the device daemon.
- Missing AI credentials disable only the affected plugin.
- Hardware writes require a deliberate manual validation stage.
