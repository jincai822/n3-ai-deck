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
- 在规划中的插件协议实现后，通过该协议增加新的集成。

## 当前状态

| 硬件 | USB ID | 状态 |
|---|---:|---|
| 妙联宝 N3 V3.0 | `6602:1000` | 已识别，写入操作尚未验证 |
| FHOOU/Mirabox N3 参考型号 | `6603:1003` | 上游已支持，等待 N3 AI Deck 重新验证 |

当前代码保留了上游项目可工作的 Linux 后台服务和 GTK4 界面。目标架构计划在此基础上增加更安全的设备边界，以及面向 AI 的动作与插件架构；这些 N3 AI Deck 层在 M0 尚未实现。发布门槛见 [ROADMAP.md](ROADMAP.md)。

> **Early Preview 命名说明：** Python 分发包和 CLI 标识符仍保留上游的 `streamdock-n3-linux` 与 `streamdock-n3` 名称。继承的 `0.2.5` 只表示上游版本脉络，并非 N3 AI Deck 的发布版本；命名和版本方案将在 `v0.1.0` 之前解决。

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
