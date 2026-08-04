from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

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


def test_project_metadata_requires_patched_pillow_release() -> None:
    project = tomllib.loads(read_text("pyproject.toml"))["project"]

    assert "pillow>=12.3.0" in (dependency.lower() for dependency in project["dependencies"])


def test_lockfile_uses_patched_pillow_release() -> None:
    packages = tomllib.loads(read_text("uv.lock"))["package"]
    pillow = next(package for package in packages if package["name"].lower() == "pillow")

    assert tuple(int(part) for part in pillow["version"].split(".")) >= (12, 3, 0)


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


def test_readmes_publish_m1_read_only_discovery_boundary() -> None:
    english = read_text("README.md")
    chinese = read_text("README.zh-CN.md")

    for command in (
        "uv run n3-ai-deck-detect",
        "uv run n3-ai-deck-detect --json",
    ):
        assert command in english
        assert command in chinese

    for required in (
        "candidate",
        "identity not confirmed",
        "sysfs",
        "daemon, probe, debug, GUI, and install",
        "outside M1's read-only guarantee",
    ):
        assert required in english

    for required in (
        "候选",
        "身份未确认",
        "sysfs",
        "daemon、probe、debug、GUI 和 install",
        "不在 M1 的只读保证范围内",
    ):
        assert required in chinese

    for text in (english, chinese):
        for line in text.splitlines():
            assert not (
                "6602:1000" in line and ("supported" in line.lower() or "已支持" in line)
            ), f"unsupported compatibility claim: {line}"


def test_architecture_documents_m1_passive_and_m2_g0_boundaries() -> None:
    architecture = read_text("docs/ARCHITECTURE.md")
    roadmap = read_text("ROADMAP.md")

    for required in (
        "device_catalog.py",
        "discovery.py",
        "ProductIDs.g_products",
        "passive",
        "active",
        "implemented in M1",
        "planned M2 work",
        "not ProductIDs.g_products",
    ):
        assert required in architecture

    for required in (
        "G0",
        "FakeBackend",
        "N3Adapter",
        "helper process",
        "does not activate `6602:1000`",
        "candidate",
        "unvalidated",
        "does not import the vendored SDK",
        "G1",
        "G7",
        "hardware-free G0 simulation foundation is implemented",
        "active hardware stages G1–G7 remain planned M2 work",
    ):
        assert required in architecture

    assert (
        "N3Adapter transaction coordinator\n"
        "  -> private capability reservation\n"
        "  -> FakeBackend exactly once\n"
        "  -> redacted evidence acceptance\n"
        "  -> private settlement / stage commit"
    ) in architecture
    assert (
        "fake-only isolated helper process\n"
        "  -> stateless CommandPolicy\n"
        "  -> FakeBackend exactly once\n"
        "  -> OperationResult only"
        in architecture
    )
    assert "Helper snapshots are validation context, not state authority." in architecture
    assert "FakeBackend or fake-only helper process" not in architecture

    for required in (
        "tasks/prd-m2-n3-v3-hardware-controls.md",
        "docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md",
        "docs/superpowers/specs/2026-08-03-m2-g0-transactional-adapter-safety-design.md",
        "docs/superpowers/plans/2026-08-03-m2-g0-transactional-adapter-safety-hardening.md",
        "**Status:** In progress — G0 foundation only",
        "hardware-free transactional simulation foundation",
        "- [x] Define and test the hardware-free Adapter contracts",
        "- [ ] G1:",
        "- [ ] G2:",
        "- [ ] G3–G7:",
    ):
        assert required in roadmap

    for document in (architecture, roadmap):
        for line in document.splitlines():
            assert not (
                "6602:1000" in line
                and ("supported" in line.lower() or "已支持" in line)
            ), f"unsupported compatibility claim: {line}"


def test_public_docs_describe_g1_candidate_profile_approval() -> None:
    english = read_text("README.md")
    chinese = read_text("README.zh-CN.md")
    architecture = read_text("docs/ARCHITECTURE.md")
    roadmap = read_text("ROADMAP.md")

    for required in (
        "interface responsibility",
        "candidate profile",
        "passive",
        "G3 physical validation",
    ):
        assert required in "\n".join((english, architecture))

    assert "approved candidate roles" in architecture
    assert "pending G3 physical validation" in architecture
    assert "role classifier" in architecture
    assert "docs/superpowers/plans/2026-08-04-m2-g1-profile-approval.md" in roadmap

    for text in (english, chinese, architecture, roadmap):
        for line in text.splitlines():
            assert not (
                "6602:1000" in line and ("supported" in line.lower() or "已支持" in line)
            ), f"unsupported compatibility claim: {line}"


def test_readme_has_no_inherited_release_claims() -> None:
    english = read_text("README.md")
    assert "asad-albadi/streamdock-n3/releases/latest" not in english
    assert "streamdock-n3-install" not in english


def test_publication_tree_omits_inherited_installer_and_screenshots() -> None:
    assert not (ROOT / "install.sh").exists()
    assert not list((ROOT / "docs").glob("screenshot-*.png"))

    sdist_includes = tomllib.loads(read_text("pyproject.toml"))["tool"]["hatch"]["build"][
        "targets"
    ]["sdist"]["include"]
    assert "install.sh" not in sdist_includes


def test_public_docs_label_unavailable_architecture_as_planned() -> None:
    english = read_text("README.md")
    chinese = read_text("README.zh-CN.md")
    architecture = read_text("docs/ARCHITECTURE.md")

    assert "target architecture" in english
    assert "planned plugin contract" in english
    assert "planned public core" in english
    assert "目标架构" in chinese
    assert "规划中的插件协议" in chinese
    assert "规划中的公开核心" in chinese
    assert "target architecture" in architecture
    assert "planned responsibility" in architecture

    for reviewed_claim in (
        "N3 AI Deck adds a safer device boundary",
        "Add integrations through a documented plugin contract.",
        "The public core contains device communication",
        "Owns supported USB identifiers",
        "Normalizes physical events",
        "Defines metadata, configuration validation",
        "The public repository owns device integration",
        "Plugin failure or timeout does not crash the device daemon.",
        "Missing AI credentials disable only the affected plugin.",
    ):
        assert reviewed_claim not in "\n".join((english, architecture))

    for reviewed_claim in (
        "通过公开插件协议增加新的集成。",
        "公开核心包含设备通信",
    ):
        assert reviewed_claim not in chinese


def test_readmes_explain_inherited_distribution_identifiers() -> None:
    english = read_text("README.md")
    chinese = read_text("README.zh-CN.md")
    for identifier in ("streamdock-n3-linux", "streamdock-n3"):
        assert identifier in english
        assert identifier in chinese
    assert "before `v0.1.0`" in english
    assert "not an N3 AI Deck release" in english
    assert "`v0.1.0` 之前" in chinese
    assert "并非 N3 AI Deck 的发布版本" in chinese


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


def test_public_documents_do_not_expose_connected_device_details() -> None:
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
            "docs/validation/2026-08-03-n3-v3-read-only-discovery.md",
        )
    )
    for raw_serial_marker in ("ID_SERIAL_SHORT=", "iSerial=", "serial_number="):
        assert raw_serial_marker not in documents
    for machine_root in ("/home", "/srv", "/Users"):
        assert machine_root not in documents
    for sensitive_pattern in (
        re.compile(r"/dev/hidraw\d+"),
        re.compile(r"/dev/input/event\d+"),
        re.compile(r"\bsysfs_name\b"),
        re.compile(r"(?<![-\d])\d+-\d+(?::\d+\.\d+)?(?![-\d])"),
    ):
        assert sensitive_pattern.search(documents) is None


def test_github_templates_collect_status_and_safety_evidence() -> None:
    bug = read_text(".github/ISSUE_TEMPLATE/bug_report.yml")
    feature = read_text(".github/ISSUE_TEMPLATE/feature_request.yml")
    pull_request = read_text(".github/pull_request_template.md")
    assert "USB ID" in bug
    assert "serial" in bug.lower()
    assert "1234:abcd" in bug
    assert "6602:1000" not in bug
    assert "customer outcome" in feature.lower()
    assert "Hardware access" in pull_request
    assert "Upstream / license impact" in pull_request


def test_issue_template_requires_private_security_reporting() -> None:
    config = read_text(".github/ISSUE_TEMPLATE/config.yml")
    assert "blank_issues_enabled: false" in config
    assert "https://github.com/jincai822/n3-ai-deck/security/advisories/new" in config
    assert "Report vulnerabilities privately" in config


def test_tracked_publication_text_has_no_local_paths_or_obvious_tokens() -> None:
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode().split("\0")
    binary_suffixes = {
        ".dll",
        ".dylib",
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".lib",
        ".pdf",
        ".png",
        ".so",
        ".woff",
        ".woff2",
    }
    machine_path_patterns = (
        re.compile("/" + r"(?:home|Users)/[^/\s]+(?:/[^/\s]+)+"),
        re.compile("/" + r"srv(?:/[^/\s]+)+"),
    )
    token_patterns = (
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(r"gh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}"),
        re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    )
    findings: list[str] = []

    for relative_path in tracked:
        if not relative_path:
            continue
        path = Path(relative_path)
        if path.suffix.lower() in binary_suffixes:
            continue
        data = (ROOT / path).read_bytes()
        if b"\0" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(text) for pattern in machine_path_patterns):
            findings.append(relative_path)
        if any(pattern.search(text) for pattern in token_patterns):
            findings.append(relative_path)

    assert not findings, f"publication-sensitive text found in: {sorted(set(findings))}"


@pytest.mark.parametrize(
    ("relative_path", "sensitive_text"),
    (
        ("src/package/_vendor/source.py", "/" + "home/" + "reviewer/private/file"),
        ("notes.txt", "/" + "home/" + "builder/project"),
        ("notes.txt", "/" + "srv/" + "builds/project"),
        ("notes.txt", "/" + "Users/" + "developer/project"),
        ("notes.txt", "github_" + "pat_" + "A" * 30),
    ),
)
def test_tracked_publication_scan_rejects_general_paths_and_vendor_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    sensitive_text: str,
) -> None:
    subprocess.run(
        ["git", "init", "--quiet"], cwd=tmp_path, check=True
    )
    fixture_path = tmp_path / relative_path
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(sensitive_text, encoding="utf-8")
    subprocess.run(
        ["git", "add", relative_path], cwd=tmp_path, check=True
    )
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)

    with pytest.raises(AssertionError, match="publication-sensitive text"):
        test_tracked_publication_text_has_no_local_paths_or_obvious_tokens()
