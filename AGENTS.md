# N3 AI Deck Agent Instructions

## Mission

Build N3 AI Deck as a local-first AI productivity console for Mirabox/妙联宝 N3 hardware on Linux. The repository is an Early Preview and must describe only behavior supported by evidence.

## Current hardware status

- The connected N3 V3.0 identifies as USB `6602:1000`.
- M2 hardware controls (G0–G7) are complete and validated on the owner's unit:
  adapter contracts, candidate profile approval, input observation, init trio,
  brightness, all six LCD keys, and the calibrated key map.
- M3 action engine, M4 AI workflow, and G8 background service are complete.
- `6602:1000` remains an owner-reported candidate whose identity is not
  independently confirmed; treat hardware writes as manual-gate operations.

## Required commands

- Tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Types: `uv run mypy src/streamdock_n3`
- Build: `uv build`

## Non-negotiable rules

- Never run sudo or install system files without explicit human authorization.
- Never write to attached hardware, initialize it, change brightness, or send LCD images without explicit human authorization.
- Never push or publish branches, tags, releases, issues, or comments unless the assigned story explicitly authorizes that external action.
- Never commit secrets, device serial numbers, customer data, machine-specific paths, `scripts/ralph/prd.json`, or `scripts/ralph/progress.txt`.
- Keep public-core code independent from private commercial extensions.
- Preserve MIT notices and credit `asad-albadi/streamdock-n3` and the Mirabox StreamDock Device SDK.
- Implement one story at a time, run its focused tests, then run the relevant regression suite.
- Do not claim `6602:1000` compatibility until recorded physical tests support the claim.
