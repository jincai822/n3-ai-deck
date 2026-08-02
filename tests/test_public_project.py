from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_project_metadata_targets_n3_ai_deck() -> None:
    metadata = tomllib.loads(read_text("pyproject.toml"))["project"]
    assert metadata["description"] == (
        "Local-first AI productivity console for the Mirabox Stream Dock N3 on Linux."
    )
    assert metadata["maintainers"] == [{"name": "jincai822"}]
    assert metadata["urls"]["Homepage"] == "https://github.com/jincai822/n3-ai-deck"
    assert metadata["urls"]["Issues"] == "https://github.com/jincai822/n3-ai-deck/issues"
    assert metadata["urls"]["Upstream"] == "https://github.com/asad-albadi/streamdock-n3"


def test_agents_file_contains_non_negotiable_safety_rules() -> None:
    instructions = read_text("AGENTS.md")
    for required in (
        "Early Preview",
        "6602:1000",
        "Never run sudo",
        "Never write to attached hardware",
        "Never push or publish",
        "uv run pytest",
    ):
        assert required in instructions


def test_ci_targets_main_and_automatic_release_is_disabled() -> None:
    ci = read_text(".github/workflows/ci.yml")
    assert "branches: [main]" in ci
    assert "branches: [master]" not in ci
    assert not (ROOT / ".github/workflows/release.yml").exists()
