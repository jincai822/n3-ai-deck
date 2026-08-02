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


def test_bilingual_readmes_are_honest_early_preview_pages() -> None:
    english = read_text("README.md")
    chinese = read_text("README.zh-CN.md")
    for text in (english, chinese):
        assert "Early Preview" in text
        assert "6602:1000" in text
        assert "https://github.com/asad-albadi/streamdock-n3" in text
        assert "curl -fsSL" not in text
    assert "README.zh-CN.md" in english
    assert "README.md" in chinese
    assert "not yet validated" in english
    assert "尚未完成真机验证" in chinese


def test_readme_has_no_inherited_release_claims() -> None:
    english = read_text("README.md")
    assert "asad-albadi/streamdock-n3/releases/latest" not in english
    assert "streamdock-n3-install" not in english


def test_required_public_documents_cover_launch_contract() -> None:
    requirements = {
        "ROADMAP.md": ("M0", "M5", "v0.1.0"),
        "docs/ARCHITECTURE.md": ("Device adapter", "Open Core", "structured result"),
        "ACKNOWLEDGEMENTS.md": ("asad-albadi/streamdock-n3", "StreamDock Device SDK", "MIT"),
        "SECURITY.md": ("private vulnerability reporting", "API keys", "device serial"),
        "CONTRIBUTING.md": ("uv run pytest", "hardware write", "pull request"),
    }
    for path, expected_phrases in requirements.items():
        text = read_text(path)
        for phrase in expected_phrases:
            assert phrase.lower() in text.lower()


def test_public_documents_do_not_expose_connected_device_serial() -> None:
    documents = "\n".join(
        read_text(path)
        for path in (
            "README.md",
            "README.zh-CN.md",
            "ROADMAP.md",
            "docs/ARCHITECTURE.md",
            "ACKNOWLEDGEMENTS.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
        )
    )
    for raw_serial_marker in ("ID_SERIAL_SHORT=", "iSerial=", "serial_number="):
        assert raw_serial_marker not in documents
