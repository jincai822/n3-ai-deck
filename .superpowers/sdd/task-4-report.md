# Task 4 Report: Public Documentation and Package Gate

## Scope

- Updated the two public READMEs with M1 safe read-only discovery guidance.
- Documented the passive M1 and active M2 architecture boundary.
- Added public-document contract coverage and a fresh-wheel metadata smoke test.
- No hardware, `/dev`, SDK, native transport, udev, systemd, or install behavior was changed.

## RED

After adding the new contract tests, this command produced the expected documentation failures:

```bash
uv run pytest tests/test_public_project.py tests/test_discovery_safety.py -v
```

Result: 29 passed, 2 failed. The failures were for missing `n3-ai-deck-detect` safe-use documentation and missing `device_catalog.py`/`discovery.py` passive-versus-active architecture documentation. The fresh-wheel metadata test passed and built its wheel in pytest's temporary directory.

## GREEN and verification

```bash
uv run pytest tests/test_public_project.py tests/test_discovery_safety.py -v
```

Result: 31 passed.

```bash
wheel_smoke_dir=$(mktemp -d /tmp/n3-ai-deck-wheel-smoke.XXXXXX)
trap 'rm -rf "$wheel_smoke_dir"' EXIT
uv build --wheel --out-dir "$wheel_smoke_dir/dist"
uv venv "$wheel_smoke_dir/venv"
uv pip install --no-deps --python "$wheel_smoke_dir/venv/bin/python" "$wheel_smoke_dir"/dist/*.whl
"$wheel_smoke_dir/venv/bin/n3-ai-deck-detect" --help
```

Result: build, virtual environment creation, no-dependency wheel installation, and installed entry-point help all exited 0. Only `--help` was invoked; no default scan was run.

```bash
uv run pytest
uv run ruff check .
uv run mypy --strict src/streamdock_n3/device_catalog.py src/streamdock_n3/discovery.py
uv build
git diff --check
```

Result: 123 passed; Ruff reported `All checks passed!`; strict mypy reported `Success: no issues found in 2 source files`; source and wheel builds succeeded; `git diff --check` exited 0 with no output.

## Self-review

- Both READMEs provide human and JSON `n3-ai-deck-detect` examples.
- Both state that `6602:1000` is a USB ID candidate, identity is unconfirmed, protocol is unvalidated, multiple HID candidates can occur, and only allowlisted sysfs attributes are read.
- Both explicitly exclude inherited daemon, probe, debug, GUI, and install commands from M1's read-only guarantee and prohibit their use for `6602:1000` in M1.
- Neither README declares `6602:1000` supported.
- Architecture names implemented M1 `device_catalog.py` and `discovery.py`, leaves active SDK/device-adapter work for M2, and states the passive catalog is not and does not modify `ProductIDs.g_products`.
- The package test always builds to pytest `tmp_path`, requires exactly one wheel, and reads the wheel zip to check the console entry point plus both M1 modules. It does not inspect repository `dist/`.

## Concerns

- No real sysfs scan or physical-device interaction was performed here; the dedicated Task 5 acceptance record owns that hardware evidence.
- The fresh-wheel test adds one small build to the focused safety suite, intentionally enforcing the package-publication gate.
