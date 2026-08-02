# M0 Public GitHub Foundation Implementation Plan

> **Historical scope note (2026-08-03):** M0 is complete. The
> [formal M1 PRD](../../../tasks/prd-n3-v3-read-only-discovery.md) now defines the
> approved passive-discovery scope for M1. It does not retroactively change this
> historical M0 plan; it supersedes only the earlier M1 clauses it names explicitly.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the retained upstream codebase into an honest, customer-facing Early Preview repository for `jincai822/n3-ai-deck`, verify it locally, and publish only the `main` branch without a release.

**Architecture:** Keep the existing `streamdock_n3` Python package and upstream history intact during M0. Change repository identity, documentation, governance, and CI only; defer USB `6602:1000` implementation to M1. A local-only AI Coding 2.1 runner may execute the tasks, while committed `AGENTS.md` supplies shared constraints and GitHub CI is the final public gate.

**Tech Stack:** Python 3.11+, pytest, Ruff, mypy, Hatchling/uv, GitHub Actions, GitHub CLI.

## Global Constraints

- Product name is `N3 AI Deck`; public repository is `jincai822/n3-ai-deck`.
- Repository visibility is public, default branch is `main`, and launch status is `Early Preview`.
- Primary audience is potential customers and partners; developer details remain available.
- Public core includes device integration, local actions, plugin contracts, UI, docs, and tests; commercial extensions remain private.
- Do not claim `6602:1000` is supported until physical M1/M2 validation passes.
- Do not run `sudo`, change udev rules, initialize hardware, change brightness, or write LCD images in M0.
- Do not commit API keys, device serial numbers, customer data, local absolute paths, AI Coding 2.1 source files, `prd.json`, or `progress.txt`.
- Preserve the existing MIT license, upstream history, upstream author credit, and Mirabox SDK attribution.
- Do not create a tag or GitHub Release in M0.
- Every code or configuration change must pass its focused test before commit.

## File map

- `AGENTS.md`: durable context and safety rules for Codex, Claude, and other coding agents.
- `pyproject.toml`: public package description, maintainer, repository URLs, and source-distribution document list.
- `.github/workflows/ci.yml`: CI for `main` and pull requests.
- `.github/workflows/release.yml`: removed in M0 so inherited tags cannot publish a misleading release.
- `README.md`: English customer-facing landing page.
- `README.zh-CN.md`: complete Simplified Chinese landing page.
- `ROADMAP.md`: public milestones M0 through M5 and their release gates.
- `docs/ARCHITECTURE.md`: public/private boundaries and event data flow.
- `ACKNOWLEDGEMENTS.md`: upstream and SDK attribution.
- `SECURITY.md`: private vulnerability reporting and secret-handling policy.
- `CONTRIBUTING.md`: contribution, test, and hardware-safety workflow.
- `.github/ISSUE_TEMPLATE/*.yml`: structured bug and feature intake.
- `.github/pull_request_template.md`: PR evidence and safety checklist.
- `tests/test_public_project.py`: executable contract for public metadata and documentation.
- `docs/superpowers/specs/*`, `docs/superpowers/plans/*`: approved product context and execution record.

Local-only AI Coding 2.1 files live under `scripts/ralph/` and are excluded through
`.git/info/exclude`; they are execution tooling, not part of the public M0 deliverable.

---

### Task 1: Establish repository identity, agent guardrails, and CI safety

**Files:**
- Create: `AGENTS.md`
- Create: `tests/test_public_project.py`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Delete: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: approved design at `docs/superpowers/specs/2026-08-02-github-public-project-design.md`.
- Produces: shared agent rules, canonical GitHub URLs, `main` CI trigger, and a reusable `read_text(relative_path: str) -> str` test helper.

- [ ] **Step 1: Write failing repository-contract tests**

Add `tests/test_public_project.py`:

```python
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
```

- [ ] **Step 2: Run the focused tests and confirm the contract fails**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: failures because `AGENTS.md` and the new metadata do not exist yet, CI still targets `master`, and the inherited release workflow exists.

- [ ] **Step 3: Create the agent context and safety contract**

Create `AGENTS.md`:

```markdown
# N3 AI Deck Agent Instructions

## Mission

Build N3 AI Deck as a local-first AI productivity console for Mirabox/妙联宝 N3 hardware on Linux. The repository is an Early Preview and must describe only behavior supported by evidence.

## Current hardware status

- The connected N3 V3.0 identifies as USB `6602:1000`.
- Detection evidence exists, but initialization, controls, brightness, and LCD writes are not yet validated for this variant.
- Treat all hardware writes as manual-gate operations.

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
```

- [ ] **Step 4: Update package and repository metadata**

In `pyproject.toml`:

```toml
description = "Local-first AI productivity console for the Mirabox Stream Dock N3 on Linux."
maintainers = [
    { name = "jincai822" },
]
keywords = ["ai", "automation", "streamdock", "n3", "mirabox", "linux", "hid", "gtk4", "productivity"]
```

Replace the development-status classifier with:

```toml
"Development Status :: 3 - Alpha",
```

Replace `[project.urls]` with:

```toml
[project.urls]
Homepage = "https://github.com/jincai822/n3-ai-deck"
Repository = "https://github.com/jincai822/n3-ai-deck"
Issues = "https://github.com/jincai822/n3-ai-deck/issues"
Changelog = "https://github.com/jincai822/n3-ai-deck/blob/main/CHANGELOG.md"
Upstream = "https://github.com/asad-albadi/streamdock-n3"
```

Extend the sdist include list with the exact public documents:

```toml
    "README.zh-CN.md",
    "ROADMAP.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "ACKNOWLEDGEMENTS.md",
    "docs/ARCHITECTURE.md",
```

- [ ] **Step 5: Move CI to `main` and remove automatic releases**

Change `.github/workflows/ci.yml` to `branches: [main]`. Delete `.github/workflows/release.yml`; release automation returns only when the M5 gate is designed and tested.

- [ ] **Step 6: Run focused tests and the inherited regression suite**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: all three tests pass.

Run: `uv run pytest`

Expected: all tests pass.

- [ ] **Step 7: Commit the repository identity**

```bash
git add AGENTS.md tests/test_public_project.py pyproject.toml .github/workflows/ci.yml .github/workflows/release.yml
git commit -m "chore: establish N3 AI Deck repository identity"
```

---

### Task 2: Replace the inherited landing page with honest bilingual product pages

**Files:**
- Modify: `tests/test_public_project.py`
- Modify: `README.md`
- Create: `README.zh-CN.md`

**Interfaces:**
- Consumes: canonical status, device ID, URLs, and safety language from Task 1.
- Produces: bilingual landing pages used by customers, partners, contributors, and GitHub repository metadata.

- [ ] **Step 1: Add failing landing-page tests**

Append to `tests/test_public_project.py`:

```python
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
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: the bilingual README tests fail against the inherited upstream README.

- [ ] **Step 3: Replace `README.md` with the English product page**

Use this complete structure and copy:

```markdown
# N3 AI Deck

[![CI](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml)
[![Status: Early Preview](https://img.shields.io/badge/status-Early%20Preview-orange)](ROADMAP.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

[简体中文](README.zh-CN.md)

**N3 AI Deck is an open-source, local-first AI productivity console for the Mirabox/妙联宝 N3 V3.0 on Linux.** It aims to turn six LCD keys, three round buttons, and three knobs into visible, repeatable AI and desktop automation workflows.

> **Early Preview:** the connected N3 V3.0 (`6602:1000`) has been identified at the USB/HID level, but initialization, input controls, brightness, and LCD writes are not yet validated. Do not install this branch as a device driver yet.

## What it is for

- Trigger an AI assistant or repeatable workflow with one physical action.
- Use knobs to adjust parameters, change modes, or control desktop applications.
- Show running, success, and failure state on LCD keys.
- Keep credentials and execution local by default.
- Add integrations through a documented plugin contract.

## Current status

| Hardware | USB ID | Status |
|---|---:|---|
| 妙联宝 N3 V3.0 | `6602:1000` | Detected; write operations not yet validated |
| FHOOU/Mirabox N3 reference variant | `6603:1003` | Supported by upstream; N3 AI Deck revalidation pending |

The current source retains the working Linux daemon and GTK4 GUI from the upstream project while N3 AI Deck adds a safer device boundary and an AI-oriented action/plugin architecture. See [ROADMAP.md](ROADMAP.md) for release gates.

## Planned flow

```text
N3 key or knob
  -> device adapter
  -> normalized event
  -> action engine
  -> AI or automation plugin
  -> structured result
  -> UI and optional LCD feedback
```

## Open Core model

The public core contains device communication, local actions, plugin contracts, local configuration, diagnostics, UI, documentation, and tests. Hosted synchronization, enterprise administration, paid integrations, and customer-specific deployment remain private commercial extensions.

## Development

M0 development does not access attached hardware:

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
```

Hardware work follows the manual gates in [CONTRIBUTING.md](CONTRIBUTING.md). Architecture details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and security reports follow [SECURITY.md](SECURITY.md).

## Upstream and license

N3 AI Deck is derived from [asad-albadi/streamdock-n3](https://github.com/asad-albadi/streamdock-n3) and includes portions of the Mirabox StreamDock Device SDK. See [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) and [LICENSE](LICENSE). No affiliation with or endorsement by Mirabox is implied.
```

- [ ] **Step 4: Create the complete Chinese product page**

Create `README.zh-CN.md`:

```markdown
# N3 AI Deck

[![CI](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml)
[![状态：Early Preview](https://img.shields.io/badge/status-Early%20Preview-orange)](ROADMAP.md)
[![许可证：MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

[English](README.md)

**N3 AI Deck 是面向 Linux 和妙联宝/Mirabox N3 V3.0 的开源、本地优先 AI 生产力控制台。** 项目目标是把六个 LCD 按键、三个圆形按键和三个旋钮变成可视、可重复的 AI 与桌面自动化工作流入口。

> **Early Preview：** 当前 N3 V3.0（`6602:1000`）已经完成 USB/HID 层识别，但初始化、输入控件、亮度和 LCD 写入尚未完成真机验证。现在不要把该分支作为设备驱动安装。

## 可以用来做什么

- 一次实体操作触发 AI 助手或固定工作流。
- 使用旋钮调节参数、切换模式或控制桌面软件。
- 在 LCD 按键上显示执行中、成功和失败状态。
- API 凭据和执行过程默认留在本机。
- 通过公开插件协议增加新的集成。

## 当前状态

| 硬件 | USB ID | 状态 |
|---|---:|---|
| 妙联宝 N3 V3.0 | `6602:1000` | 已识别，写入操作尚未验证 |
| FHOOU/Mirabox N3 参考型号 | `6603:1003` | 上游已支持，等待 N3 AI Deck 重新验证 |

当前代码保留了上游项目可工作的 Linux 后台服务和 GTK4 界面；N3 AI Deck 将在此基础上增加更安全的设备边界，以及面向 AI 的动作与插件架构。发布门槛见 [ROADMAP.md](ROADMAP.md)。

## 规划中的执行链路

```text
N3 按键或旋钮
  -> 设备适配层
  -> 标准事件
  -> 动作引擎
  -> AI 或自动化插件
  -> 结构化结果
  -> 本地界面与可选 LCD 反馈
```

## Open Core 模式

公开核心包含设备通信、本地动作、插件协议、本地配置、诊断、界面、文档和测试。云同步、企业管理、付费集成和客户专属部署保留为私有商业扩展。

## 本地开发

M0 开发阶段不会访问已连接硬件：

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
```

硬件开发必须遵循 [CONTRIBUTING.md](CONTRIBUTING.md) 中的人工确认门。技术架构见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，安全问题请按 [SECURITY.md](SECURITY.md) 报告。

## 上游与许可证

N3 AI Deck 基于 [asad-albadi/streamdock-n3](https://github.com/asad-albadi/streamdock-n3)，并包含 Mirabox StreamDock Device SDK 的部分代码。详情见 [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) 和 [LICENSE](LICENSE)。本项目不代表 Mirabox 官方，也不暗示获得官方背书。
```

- [ ] **Step 5: Run the focused tests**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: all landing-page and metadata tests pass.

- [ ] **Step 6: Commit the bilingual landing page**

```bash
git add README.md README.zh-CN.md tests/test_public_project.py
git commit -m "docs: present N3 AI Deck as an early preview"
```

---

### Task 3: Add roadmap, architecture, attribution, security, and contribution documents

**Files:**
- Modify: `tests/test_public_project.py`
- Create: `ROADMAP.md`
- Create: `docs/ARCHITECTURE.md`
- Create: `ACKNOWLEDGEMENTS.md`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`

**Interfaces:**
- Consumes: public/private and safety decisions from the approved design.
- Produces: stable documents linked from both README files and later GitHub templates.

- [ ] **Step 1: Add failing document-contract tests**

Append:

```python
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
```

- [ ] **Step 2: Run the document tests and confirm missing-file failures**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: failures identify each missing document.

- [ ] **Step 3: Create the public roadmap**

Create `ROADMAP.md` with these exact release gates:

```markdown
# N3 AI Deck Roadmap

N3 AI Deck is an Early Preview. Milestone completion requires evidence; dates are intentionally secondary to safe hardware validation.

## M0 — Public foundation

**Status:** In progress

- [ ] Independent repository identity and bilingual landing pages.
- [ ] Attribution, governance, and passing public CI.
- [ ] No device writes, tags, or release artifacts.

## M1 — Safe N3 V3.0 discovery

- Add exact `6602:1000` registration and narrowly scoped Linux permissions.
- Prove read-only discovery of the intended HID interface.

## M2 — Hardware controls

- Validate keys, round buttons, knobs, brightness, and all six LCD keys in staged manual tests.

## M3 — Extensible action engine

- Publish the plugin contract and safe local example actions.

## M4 — AI workflow demonstration

- Record one useful end-to-end AI workflow with visible device feedback and local credentials.

## M5 — v0.1.0

- Publish reproducible artifacts only after CI and the physical validation checklist pass.
```

- [ ] **Step 4: Create the architecture document**

Create `docs/ARCHITECTURE.md`:

```markdown
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
```

- [ ] **Step 5: Create attribution and policy documents**

Create `ACKNOWLEDGEMENTS.md`:

```markdown
# Acknowledgements

N3 AI Deck retains code and history from [asad-albadi/streamdock-n3](https://github.com/asad-albadi/streamdock-n3), originally authored by Asad Al Badi and distributed under the MIT License.

The repository also vendors portions of the Mirabox StreamDock Device SDK under `src/streamdock_n3/_vendor/StreamDock/`. Original notices and upstream terms must remain with redistributed SDK code. Those terms will be checked again before commercial binary distribution.

N3 AI Deck is an independent community project and is not affiliated with or endorsed by Mirabox.
```

Create `SECURITY.md`:

```markdown
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

Until `v0.1.0`, only the current `main` branch receives security fixes and the project remains an Early Preview.
```

Create `CONTRIBUTING.md`:

```markdown
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
```

- [ ] **Step 6: Run tests and commit the public documentation set**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: all contract tests pass.

```bash
git add ROADMAP.md docs/ARCHITECTURE.md ACKNOWLEDGEMENTS.md SECURITY.md CONTRIBUTING.md tests/test_public_project.py
git commit -m "docs: add public roadmap and project policies"
```

---

### Task 4: Add structured GitHub contribution templates

**Files:**
- Create: `.github/ISSUE_TEMPLATE/bug_report.yml`
- Create: `.github/ISSUE_TEMPLATE/feature_request.yml`
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Create: `.github/pull_request_template.md`
- Modify: `tests/test_public_project.py`

**Interfaces:**
- Consumes: reporting and hardware rules in `SECURITY.md` and `CONTRIBUTING.md`.
- Produces: GitHub issue forms and a pull-request evidence checklist.

- [ ] **Step 1: Add failing template tests**

Append:

```python
def test_github_templates_collect_status_and_safety_evidence() -> None:
    bug = read_text(".github/ISSUE_TEMPLATE/bug_report.yml")
    feature = read_text(".github/ISSUE_TEMPLATE/feature_request.yml")
    pull_request = read_text(".github/pull_request_template.md")
    assert "USB ID" in bug
    assert "serial" in bug.lower()
    assert "customer outcome" in feature.lower()
    assert "Hardware access" in pull_request
    assert "Upstream / license impact" in pull_request
```

- [ ] **Step 2: Run the focused test and confirm missing-template failure**

Run: `uv run pytest tests/test_public_project.py::test_github_templates_collect_status_and_safety_evidence -v`

Expected: failure because the templates do not exist.

- [ ] **Step 3: Create the issue forms**

Create `.github/ISSUE_TEMPLATE/bug_report.yml`:

```yaml
name: Bug report
description: Report reproducible incorrect behavior
title: "[Bug]: "
labels: [bug, needs-triage]
body:
  - type: markdown
    attributes:
      value: "Do not include API keys or a device serial number."
  - type: input
    id: usb-id
    attributes:
      label: USB ID
      description: "VID:PID only, for example 6602:1000. Never include the serial."
    validations:
      required: true
  - type: textarea
    id: behavior
    attributes:
      label: Reproduction and observed behavior
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behavior
    validations:
      required: true
  - type: dropdown
    id: hardware-access
    attributes:
      label: Hardware access performed
      options: [None, Read-only diagnostics, Hardware write]
    validations:
      required: true
```

Create `.github/ISSUE_TEMPLATE/feature_request.yml`:

```yaml
name: Feature request
description: Propose a customer outcome for the public core
title: "[Feature]: "
labels: [enhancement, needs-triage]
body:
  - type: textarea
    id: customer-outcome
    attributes:
      label: Customer outcome
      description: What should become faster, easier, or possible?
    validations:
      required: true
  - type: textarea
    id: workflow
    attributes:
      label: Physical workflow
      description: Describe the key, knob, screen, AI, or automation interaction.
    validations:
      required: true
  - type: dropdown
    id: boundary
    attributes:
      label: Suggested product boundary
      options: [Public core, Commercial extension, Unsure]
    validations:
      required: true
```

Create `.github/ISSUE_TEMPLATE/config.yml`:

```yaml
blank_issues_enabled: false
contact_links:
  - name: Security report
    url: https://github.com/jincai822/n3-ai-deck/security/advisories/new
    about: Report vulnerabilities privately; never include secrets in a public issue.
```

- [ ] **Step 4: Create the pull-request template**

Create `.github/pull_request_template.md`:

```markdown
## Customer-visible outcome

## What changed

## Verification

- [ ] Focused tests pass
- [ ] Full `uv run pytest` passes
- [ ] `uv run ruff check .` passes

## Hardware access

- [ ] No hardware access
- [ ] Read-only diagnostics, with redacted evidence attached
- [ ] Hardware write explicitly approved by the device owner

## Safety and provenance

- [ ] No secrets, serial numbers, customer data, or local absolute paths
- [ ] Upstream / license impact documented
- [ ] Compatibility claims match recorded evidence
```

- [ ] **Step 5: Run tests and commit the templates**

Run: `uv run pytest tests/test_public_project.py -v`

Expected: all tests pass.

```bash
git add .github/ISSUE_TEMPLATE .github/pull_request_template.md tests/test_public_project.py
git commit -m "chore: add GitHub contribution templates"
```

---

### Task 5: Verify the complete M0 branch and publish it to GitHub

**Files:**
- Verify only; no new product files.
- External target: `https://github.com/jincai822/n3-ai-deck`.

**Interfaces:**
- Consumes: committed Tasks 1–4 on local `main` and authenticated GitHub CLI account `jincai822`.
- Produces: public repository with `origin`, retained `upstream`, passing CI, correct metadata, no tag, and no release.

- [ ] **Step 1: Run all local quality gates**

Run:

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv build
git diff --check
```

Expected: each command exits `0`.

Run the existing advisory type check separately:

```bash
uv run mypy src/streamdock_n3
```

Expected: record its output. Existing upstream warnings may remain advisory in M0, but this task must not introduce new warnings in files changed by M0.

- [ ] **Step 2: Scan tracked publication content for private data**

Run:

```bash
git grep -n -E 'sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|/(srv|home)/[^[:space:]]+' -- ':!docs/superpowers/plans/*'
```

Expected: no matches.

Run: `git status --short --branch`

Expected: clean `## main`.

- [ ] **Step 3: Create the empty public GitHub repository without pushing tags**

Run:

```bash
gh repo create jincai822/n3-ai-deck --public --source=. --remote=origin --description "Open-source AI productivity console for the Mirabox/妙联宝 N3 V3.0 on Linux."
git push -u origin main
```

Expected: the repository is created, only `main` is pushed, and `upstream` still points to `https://github.com/asad-albadi/streamdock-n3.git`.

- [ ] **Step 4: Configure customer-facing repository settings**

Run:

```bash
gh repo edit jincai822/n3-ai-deck --default-branch main --enable-issues --enable-wiki=false --add-topic ai --add-topic automation --add-topic hid --add-topic linux --add-topic mirabox --add-topic productivity --add-topic streamdock
gh api --method PUT repos/jincai822/n3-ai-deck/private-vulnerability-reporting
gh api --method PUT repos/jincai822/n3-ai-deck/vulnerability-alerts
gh api --method PUT repos/jincai822/n3-ai-deck/automated-security-fixes
```

Expected: `main` is default, Issues are enabled, Wiki is disabled, topics are visible, private vulnerability reporting is enabled, and dependency alerts/fixes are enabled.

- [ ] **Step 5: Verify the external state**

Run:

```bash
gh repo view jincai822/n3-ai-deck --json nameWithOwner,visibility,defaultBranchRef,description,url
gh run list --repo jincai822/n3-ai-deck --workflow ci.yml --limit 1
gh release list --repo jincai822/n3-ai-deck
git remote -v
```

Expected:

- Repository is `PUBLIC` at `https://github.com/jincai822/n3-ai-deck`.
- Default branch is `main`.
- The newest CI run succeeds; if it is still running, monitor it to completion.
- No GitHub Release exists.
- `origin` is the new repository and `upstream` is the source repository.

- [ ] **Step 6: Record M0 completion only after CI succeeds**

Only if the public CI and external-state checks pass, change the M0 block to:

```markdown
## M0 — Public foundation

**Status:** Complete

- [x] Independent repository identity and bilingual landing pages.
- [x] Attribution, governance, and passing public CI.
- [x] No device writes, tags, or release artifacts.
```

Then commit and push:

```bash
git add ROADMAP.md
git commit -m "docs: record M0 public foundation completion"
git push origin main
```

Expected: final CI succeeds and the public landing page accurately remains `Early Preview`.
