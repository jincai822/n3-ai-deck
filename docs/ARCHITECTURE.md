# Architecture

N3 AI Deck evolves the existing `streamdock_n3` package incrementally. The passive, read-only `device_catalog.py` and `discovery.py` path for sysfs USB/HID metadata is implemented in M1. This passive catalog is not ProductIDs.g_products and does not modify the vendored SDK's active product table. The active SDK/device adapter work is planned M2 work. Everything below describes the planned target architecture beyond that implemented M1 discovery boundary.

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
