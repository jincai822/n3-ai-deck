# N3 AI Deck

[![CI](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/jincai822/n3-ai-deck/actions/workflows/ci.yml)
[![状态：Early Preview](https://img.shields.io/badge/status-Early%20Preview-orange)](ROADMAP.md)
[![许可证：MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

[English](README.md)

**N3 AI Deck 是面向 Linux 和妙联宝/Mirabox N3 V3.0 的开源、本地优先 AI 生产力控制台。** 项目目标是把六个 LCD 按键、三个圆形按键和三个旋钮变成可视、可重复的 AI 与桌面自动化工作流入口。

> **Early Preview：** `6602:1000` 是机主报告为 N3 V3.0 的 USB ID 候选。其物理型号身份未确认，协议兼容性、初始化、输入控件、亮度和 LCD 写入尚未完成真机验证。现在不要把该分支作为设备驱动安装。

## 可以用来做什么

- 一次实体操作触发 AI 助手或固定工作流。
- 使用旋钮调节参数、切换模式或控制桌面软件。
- 在 LCD 按键上显示执行中、成功和失败状态。
- API 凭据和执行过程默认留在本机。
- 通过已文档化的插件契约和安全的本地插件增加新的集成。

## 当前状态

| 硬件 | USB ID | 状态 |
|---|---:|---|
| 机主报告的 N3 V3.0 候选 | `6602:1000` | USB ID 候选；身份未确认；协议与写入操作尚未验证 |
| FHOOU/Mirabox N3 参考型号 | `6603:1003` | 上游已支持，等待 N3 AI Deck 重新验证 |

当前代码保留了上游项目的 Linux 后台服务和 GTK4 界面。M1 已实现独立的只读发现路径；目标架构仍计划增加主动设备边界。M3 已实现动作引擎契约、安全内置插件、无硬件的演示 CLI 和机主运行的实时派发 CLI（`n3-ai-deck-live`）；daemon 后台接线仍处于规划中。发布门槛见 [ROADMAP.md](ROADMAP.md)。

> **Early Preview 命名说明：** Python 分发包和 CLI 标识符仍保留上游的 `streamdock-n3-linux` 与 `streamdock-n3` 名称。继承的 `0.2.5` 只表示上游版本脉络，并非 N3 AI Deck 的发布版本；命名和版本方案将在 `v0.1.0` 之前解决。

## 安全只读发现（M1）

使用专用的 M1 命令，只检查经允许的 sysfs USB 与 HID 属性，不打开设备节点：

```bash
uv run n3-ai-deck-detect
uv run n3-ai-deck-detect --json
```

`6602:1000` 仅是 USB ID 候选：身份未确认，且该命令不证明协议兼容性。报告可能显示多个 HID 候选，并且不会选择任何一个接口进行设备访问。M1 路径只读取 allowlisted sysfs 属性；不会初始化硬件，也不会访问 `/dev` 节点。

继承的 daemon、probe、debug、GUI 和 install 命令不在 M1 的只读保证范围内，M1 中不得用于 `6602:1000`。这包括 `streamdock-n3`、`streamdock-n3-probe`、`streamdock-n3-debug`、`streamdock-n3-gui` 和 `streamdock-n3-install`。

G1 在被动发现之上解决接口职责：同一 sysfs-only 命令现在为每个 HID 接口报告角色（`input` / `control` / `unknown`）及其脱敏证据依据，并给出 `interface_selection`（`resolved` / `ambiguous` / `none`）。已解析的候选 profile 及其角色通过 `N3Adapter` 的 G1 门显式批准；批准是候选 profile 决定，不是兼容性声明。角色在 G3 真机物理验证前仍是已批准的候选角色，`6602:1000` 仍是协议未验证的候选。

G2 完全离线设计权限且不授予任何权限：仅生成临时单节点 ACL 计划（仅占位符）和精确匹配 `6602:1000` 的 `TAG+="uaccess"` udev 规则模板，以及只针对显式非系统 root 的安装事务。未授予任何权限、未写任何系统文件、未执行任何权限命令；任何真实的 ACL 或 udev 安装仍是独立的人工操作。

G3 通过一次有界只读会话（`n3-ai-deck-observe-inputs`）观察实体输入：helper 仅以 `O_RDONLY` 打开唯一已批准输入节点，从不写入、从不 grab、从不加载 SDK，断连即停且零自动恢复写入。会话按控件计数按压/旋转、测量 p95 延迟并记录脱敏证据；门仅在机器结果满足要求时推进。自动化测试从不打开 `/dev`；真机会话是独立的人工门操作。

## 动作引擎（M3）

M3 已实现不接触硬件的动作引擎：进程内插件契约、带超时的执行引擎、安全内置插件（白名单启动器与结构化日志），以及基于文件的 JSON 绑定。无需设备即可试用：

```bash
uv run n3-ai-deck-run-action --event button.1.press --dry-run
```

随附的默认绑定把每个标准事件都绑定到无副作用的结构化日志；从实体事件触发动作已通过下面的实时派发 CLI 实现，daemon 后台接线仍处于规划中。

## 实时派发（`n3-ai-deck-live`）

插上设备后，把实体事件实时流入动作引擎：

```bash
uv run n3-ai-deck-live --duration-ms 60000
```

每个被派发的事件输出一行 JSON（`schema_version`、`event_key`、`status`、`plugin`、`duration_ms`），最后输出一行会话汇总。会话在前台运行、有时长上限，到达时限、按 Ctrl+C 或设备断连都会干净退出。没有绑定文件时只记录日志（零副作用）；要启动白名单应用，请创建 `~/.config/streamdock-n3/bindings.json`，例如把 `button.1.press` 绑定到白名单内置 `launch_app`。CLI 会自动读取该文件，或通过 `--bindings` 指定。先预览解析结果而不打开设备：

```bash
uv run n3-ai-deck-live --dry-run
```

## AI 工作流（M4）

M4 把真实 AI 工作流接入设备：按下 LCD 按键会读取当前剪贴板，通过 OpenAI 兼容端点把它总结成一句话，并在按键上显示结果状态——运行中为黄色、成功为绿色、失败为红色、超时为橙色。

```bash
uv run n3-ai-deck-live --feedback --timeout-seconds 15
```

凭据由你通过环境变量提供（`N3_AI_DECK_API_KEY`——名称可在绑定中配置，值绝不存入本仓库）；缺少凭据只会禁用 `ai_text` 插件，所有本地动作照常工作。AI 插件不增加任何新运行时依赖——只使用 Python 标准库。无需设备即可预览解析结果：

```bash
uv run n3-ai-deck-live --feedback --timeout-seconds 15 --dry-run
```

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

## 规划中的 Open Core 模式

规划中的公开核心拟包含设备通信、本地动作、插件协议、本地配置、诊断、界面、文档和测试。目标边界会把云同步、企业管理、付费集成和客户专属部署保留为私有商业扩展。

## 本地开发

M1 自动化开发不会访问已连接硬件：

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv build
```

硬件开发必须遵循 [CONTRIBUTING.md](CONTRIBUTING.md) 中的人工确认门。技术架构见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，安全问题请按 [SECURITY.md](SECURITY.md) 报告。

## 上游与许可证

N3 AI Deck 基于 [asad-albadi/streamdock-n3](https://github.com/asad-albadi/streamdock-n3)，并包含 Mirabox StreamDock Device SDK 的部分代码。详情见 [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) 和 [LICENSE](LICENSE)。本项目不代表 Mirabox 官方，也不暗示获得官方背书。
