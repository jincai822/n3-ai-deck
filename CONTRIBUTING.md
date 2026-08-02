# Contributing

## Workflow

1. Open or select an issue with testable acceptance criteria.
2. Create a focused branch from `main`.
3. Add a failing test before changing behavior.
4. Implement the smallest change and run `uv run pytest` plus `uv run ruff check .`.
5. Open a pull request with evidence and any remaining limitations.

## Hardware safety

- Label every hardware step as read-only or hardware write.
- Never run `sudo`, install udev rules, initialize the device, change brightness, or send LCD data without the device owner's explicit approval.
- Test `6602:1000` in the staged order documented in the design; a failed stage blocks later hardware write stages.
- Remove device serials, usernames, secrets, and local paths from logs before attaching them.

## Pull request expectations

Every pull request explains the customer-visible change, tests run, hardware access performed, screenshots or logs used as evidence, and upstream/license impact.
