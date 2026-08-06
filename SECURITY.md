# Security Policy

## Reporting

Use GitHub private vulnerability reporting for security issues. If private vulnerability reporting is unavailable, do not open a public issue containing exploit details or secrets; contact the repository owner through their GitHub profile first.

## Secrets and private data

- Never commit API keys, access tokens, customer data, device serial numbers, or private workflow payloads.
- Redact credentials and machine-specific paths from logs and issue attachments.
- AI integrations must load secrets from user-controlled local storage or environment-backed configuration.

## Hardware safety

Reports involving udev, HID initialization, brightness, or LCD writes must state the exact model and USB ID but omit the device serial. Reproduction instructions must separate read-only diagnostics from write operations.

## Supported versions

The current `main` branch and the `v0.1.0` release receive security fixes; the project remains an Early Preview.
