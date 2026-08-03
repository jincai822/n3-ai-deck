# M2 硬件控制安全架构设计

**日期：** 2026-08-03
**状态：** 对话设计已批准；正式书面规格待产品负责人复核
**产品：** N3 AI Deck
**里程碑：** M2 — Hardware Controls
**目标候选设备：** 妙联宝 N3 V3.0，USB `6602:1000`，`bcdDevice=0300`

> **授权边界：** 本文只记录方案设计。批准本文不等于激活 SDK、打开
> `/dev` 节点、修改 ACL/udev、安装系统文件、启动服务或向硬件发送数据。
> 每项主动动作必须通过本文定义的独立人工门。

## 1. 决策摘要

M2 采用“窄接口 Adapter + 隔离辅助进程”的方案 C。主进程维护设备档案、
能力状态机、审批校验和脱敏证据，不直接导入 vendored SDK 或 native transport。
默认后端是完全硬件无关的 `FakeBackend`；未来的只读输入和主动协议操作分别
进入能力受限、短生命周期的辅助进程。

M2 不把 `6602:1000` 直接加入 vendored `ProductIDs.g_products`，不复用旧
daemon/probe/debug/GUI 作为验证入口，也不复用现有 vendor-wide `0666` udev
规则。目标设备在完成相应证据门之前继续保持：

- `identity_status=user_reported_candidate`
- `protocol_status=unvalidated`

能力按证据逐项升级，不使用单一的“支持/不支持”布尔值。允许的升级顺序是：

```text
CANDIDATE
  -> PROFILE_APPROVED
  -> INPUT_VALIDATED
  -> INITIALIZATION_VALIDATED
  -> BRIGHTNESS_VALIDATED
  -> ONE_LCD_VALIDATED
  -> SIX_LCD_VALIDATED
```

任何失败进入 `BLOCKED`；任何断连进入 `DISCONNECTED`，重插后从 M1 被动发现
重新开始，不自动重连或恢复写入。

## 2. 已知证据和设计约束

### 2.1 M1 实机证据

M1 只读验证记录确认：

| 字段 | 当前证据 |
|---|---|
| USB VID:PID | `6602:1000` |
| `bcdDevice` | `0300` |
| 接口 `00` | HID `03/00/00` |
| 接口 `01` | HID Boot Keyboard `03/01/01` |
| 接口选择 | `ambiguous` |
| 身份状态 | 机主报告的候选设备 |
| 协议状态 | 未验证 |

该证据来自 [M1 验证记录](../../validation/2026-08-03-n3-v3-read-only-discovery.md)，
只证明枚举和拓扑，不证明具体物理型号、接口职责、事件码、亮度协议或 LCD 协议。

### 2.2 旧 SDK 不能作为安全边界

代码审查确认：

- vendored 活跃产品表没有精确的 `6602:1000`。
- `DeviceManager.enumerate()` 依赖全局产品表和 native 枚举，legacy 调用者常选择
  `devices[0]`，不能保证目标设备和接口。
- 高层 `open()` 会启动 reader 和 heartbeat；heartbeat 是周期性硬件写入。
- 高层 `close()` 会发送 disconnect，并存在 native 线程清理竞争；旧 daemon 已用
  `os._exit()` 规避观察到的 glibc tcache abort。
- 高层 `init()` 把 wake、亮度 100、清屏、固件读取和 refresh 捆绑在一起。
- 多数 native 返回码被包装层丢弃，无法仅凭调用返回判断设备结果。
- 上游 N3 的事件偏移、事件码、`64x64/-90°` 图像处理和按键索引只是参考实现，
  没有 `6602:1000` 的真机证据。

因此 M2 禁止把 `StreamDock.open()`、`StreamDock.init()` 或 `StreamDock.close()`
包装成“安全模式”。如果底层操作无法拆分、限时和审计，对应能力保持阻塞。

### 2.3 旧权限与服务不能复用

现有 udev 规则只匹配 vendor `6603`，同时给 USB、hidraw 和 input 节点
`MODE="0666"`，既不支持目标 `6602:1000`，又超出最小权限。旧安装器还会写
`/etc`、`/usr`、reload/trigger udev；旧用户服务会自动启动能够初始化、写亮度、
写图并执行 shell action 的 daemon。

M2 只允许离线设计和验证精确权限产物。真实 ACL、udev、systemd 或系统安装都
必须独立批准。

## 3. 目标与非目标

### 3.1 目标

- 建立 `6602:1000` 的独立 active profile 和能力状态机，但不由 USB ID 自动激活。
- 让硬件无关的代码、模拟测试和 CI 可以最大程度自动完成。
- 把所有真实设备访问隔离到能力受限的辅助进程。
- 分阶段验证 6 个 LCD 键、3 个圆键、3 个旋钮、亮度和 6 块 LCD。
- 为每个主动阶段定义审批、超时、停止、证据和可逆恢复合同。
- 形成 M3 可以依赖的逐能力兼容矩阵，不夸大硬件支持范围。

### 3.2 非目标

- 在 M2 中接入动作引擎、插件、AI 凭据或任意 shell 命令。
- 直接改造 legacy daemon、GUI、probe、debug 或 systemd 服务。
- 自动安装 udev、修改 ACL、提权、reload/trigger udev。
- 自动重连后恢复亮度或 LCD 内容。
- 支持 Windows、macOS、其他 Stream Dock 型号或所有同 USB ID 设备。
- 完成云同步、账户、商业扩展或产品化 GUI。

## 4. 已评估方案

| 方案 | 描述 | 结论 |
|---|---|---|
| A | 新增 vendored subclass 并加入 `g_products` | 代码少，但会让所有 legacy 入口立即看见候选设备并继承 heartbeat/init/close 风险；拒绝 |
| B | 主进程内的窄 Adapter + 可注入 backend | 容易测试，但 native 崩溃、线程泄漏和阻塞仍会拖垮主进程；不单独采用 |
| C | 窄 Adapter + FakeBackend + 隔离辅助进程 | 测试性和故障隔离最好，能逐能力审批；已批准 |

方案 C 的额外进程与 IPC 有实现成本，但这是控制闭源 native transport 风险所需的
最小隔离。M2 不建设通用微服务或复杂 RPC；IPC 只承载固定 schema 和允许列表命令。

## 5. 组件与职责

```text
M1 passive observation
        |
        v
DeviceProfile + CapabilityGate
        |
        v
      N3Adapter -----------------> RedactedEvidenceRecorder
        |
        +--> FakeBackend
        |
        +--> ReadOnlyInputHelper ------> approved read-only interface
        |
        +--> VendorSdkHelper ----------> approved active operation
```

### 5.1 `DeviceProfile`

设备档案是不可变、可哈希的数据对象，至少包含：

- 精确 VID、PID 和允许的 `bcdDevice` 证据。
- 已人工确认的接口编号及 class/subclass/protocol。
- 身份与协议状态。
- 每项能力的 `disabled`、`approved`、`validated` 或 `blocked` 状态。
- 档案 schema 版本和生成它的软件 commit。

档案不包含序列号、总线位置、易变 `/dev` 编号、用户名或绝对路径。M1 observation
不会自动转换成 active profile；G1 必须显式批准。

### 5.2 `CapabilityGate`

能力门校验当前状态、阶段清单和前置证据。它必须失败关闭：

- 设备身份、`bcdDevice` 或接口与清单不一致时拒绝。
- 前置能力未验证时拒绝后续能力。
- 命令、次数、参数或时限不在允许列表时拒绝。
- 清单过期、commit 不一致或辅助进程报告未知结果时拒绝。
- 不提供“强制继续”“忽略错误”或自动降级到其他接口的生产选项。

### 5.3 `N3Adapter`

Adapter 是应用层唯一硬件能力接口。公开能力保持窄且类型化：

- `observe_inputs(plan)`
- `initialize(plan)`
- `set_brightness(plan, value)`
- `set_key_image(plan, key, image)`
- `close_session(plan)`

Adapter 不公开 `send_raw`、任意 method name、任意 native symbol、shell command 或
“自动初始化”方法。未来若必须增加协议诊断命令，它需要新 schema、新测试和单独审批门。

### 5.4 Backend

#### `FakeBackend`

默认后端，只处理夹具事件和可控结果。所有状态机、边界、错误、恢复队列和隐私测试
先在该后端完成。CI 只能使用该后端或纯文件 fixture。

#### `ReadOnlyInputHelper`

未来 G3 获批后，以短生命周期进程对唯一已批准接口执行只读输入会话：

- 文件描述符必须以只读模式打开。
- 不导入 `_vendor` 或 native transport。
- 不发送 heartbeat、feature/output report、init、refresh 或 disconnect write。
- 未知事件只产生分类结果；原始 payload 默认不落盘。
- 如果目标平台无法证明输入会话无写入，该阶段进入 `BLOCKED`，不得回退到旧 SDK。

#### `VendorSdkHelper`

未来 G4 之后才允许存在真实执行路径。它在独立短生命周期进程中按清单加载 backend：

- 不使用全局 `DeviceManager.enumerate()` 或 `devices[0]`。
- 不调用高层组合 `open()/init()/close()`。
- 只有能绑定精确设备和接口、声明实际生命周期写集合的 backend 才可激活。
- 每次进程只执行一个已批准阶段；输入持续测试可以在有界会话内运行。
- native crash、卡死或非零退出只使当前阶段失败，不能污染主进程状态。

真实 backend 最终使用受控的底层 SDK seam 还是 direct HID，需要 G4 前的协议证据决定；
Adapter 和 IPC 合同不依赖该选择。

### 5.5 `RedactedEvidenceRecorder`

每个阶段记录：commit、阶段、设备档案摘要、预期、实际、稳定错误分类、耗时、人工观察、
恢复动作和结果。公开记录不得包含 serial、`/dev` 节点、总线位置、用户名、绝对路径、
密钥或图片内容。未知原始帧默认只记录长度、类别和会话内计数，不记录 payload。

## 6. IPC 与阶段清单

主进程和辅助进程只交换版本化结构化消息。请求至少包含：

| 字段 | 作用 |
|---|---|
| `schema_version` | 拒绝不兼容消息 |
| `stage` | 限定当前 G0–G7 能力 |
| `commit` | 绑定已审阅代码 |
| `profile_digest` | 绑定脱敏设备档案 |
| `interface` | 绑定已批准接口 |
| `allowed_operations` | 精确命令、次数和参数范围 |
| `deadline_ms` | 限制会话或调用时间 |
| `expected_result` | 形成机器可判定的合同 |
| `recovery_plan` | 记录已批准恢复方式 |
| `approval_reference` | 关联人工批准记录 |

辅助进程先验证整个清单，再进行任何设备访问。响应只允许稳定状态、结果码、持续时间、
归一化事件和脱敏错误；不得把任意 native 对象、异常文本或本机路径传回主进程。

## 7. 状态机与审批门

| 门 | 能力 | 前置条件 | 允许动作 | 阻塞条件 |
|---|---|---|---|---|
| G0 | 设计与模拟 | 书面规格、实施计划和 G0 开始授权分别批准 | 文档、FakeBackend、测试、离线 fixture | 任何 SDK、`/dev`、权限或硬件访问 |
| G1 | Active profile | M1 observation | 确认精确身份约束和接口职责；仍不打开设备 | 接口歧义、身份漂移、档案字段不完整 |
| G2 | 权限 | G1 | 独立评审临时 ACL 或精确 udev 方案 | vendor-only、`0666`、未证明的 subsystem/interface |
| G3 | 输入 | G1；必要时 G2 | 只读、有界输入观察 | 任何隐式写入、未知接口、崩溃或清理失败 |
| G4 | 初始化 | G3 | 仅执行清单声明的生命周期/握手操作 | 只能调用组合 `init()`、写集合未知、无法恢复 |
| G5 | 亮度 | G4 | 已知基线 `B -> B-10 -> B` | 基线未知、LCD 副作用、恢复失败 |
| G6 | 单 LCD | G5 | 仅 LCD 1 写唯一测试图并恢复 | 错屏、串扰、方向/裁切错误、恢复失败 |
| G7 | 六 LCD | G6 | 按 1→6 逐块写入、核验和恢复 | 任一失败；不得继续后续键 |
| G8 | Legacy 集成 | G7；不属于 M2 | 未来单独评审 daemon/GUI/systemd | close/tcache、自动重启和 action 隔离未解决 |

审批具有最小授权语义：批准 G4 不自动批准 G5；批准写入测试不批准 udev 安装；批准
文档不批准 G0 实施。任何硬件门开始前，执行者必须再次展示精确命令类别、预期、时限和
恢复步骤。

## 8. 权限设计

M2 的默认第一次真机策略是不安装持久规则。若普通用户没有所需权限，G2 提供三个分离
选项，且每项都需要人工选择：

1. 对已重新核对 ancestry 的单一当前节点施加临时用户 ACL；拔插失效，风险最低。
2. 在仓库中生成精确 `6602:1000`、已验证 subsystem/interface、`TAG+="uaccess"`
   的惰性规则模板，并只做离线测试。
3. 在身份和协议全部验证后，另立长期安装里程碑，由包管理器管理规则和回滚。

所有方案都禁止 vendor-only 匹配、`MODE="0666"`、无证据地同时授权 USB/hidraw/input，
以及把用户加入可读取全部键盘事件的通用组。写 `/etc`、reload、trigger、重新插拔、
systemctl 和真实安装/卸载永远不由 G0 自动化执行。

## 9. 阶段行为与恢复

### 9.1 G3 输入

- 验证 6 个 LCD 键、3 个圆键和 3 个旋钮。
- 每种离散按键连续 10 次 press/release；每个旋钮每方向 20 格并按压 10 次。
- 连续运行 10 分钟；本地结构化事件可见延迟目标 p95 不超过 250ms。
- 输入会话只关闭只读文件描述符，没有硬件恢复写入。

### 9.2 G4 初始化

旧 `init()` 永久禁止用于该阶段。开始前必须列出 wake、握手、refresh、heartbeat、
disconnect 等实际写集合；无法区分或捕获的写入使阶段阻塞。初始化后重跑输入验证，
确认事件映射没有回归。

### 9.3 G5 亮度

无可靠读回 API 时，由机主在操作前确认已知基线 `B`。清单只允许 `B-10` 和恢复 `B`
两次受限写入。返回结果、人工可见变化、恢复成功三者缺一不可。若基线未知则不执行。

### 9.4 G6 单 LCD

只写 LCD 1 的唯一高对比图。原始屏幕内容无法读取时，必须在操作前由机主批准一个明确
的替代基线；这只能称为“恢复到批准基线”，不能声称恢复未知原图。验证位置、方向、裁切、
串扰和恢复。

### 9.5 G7 六 LCD

使用六张不同编号和颜色的图，按 1→6 顺序逐块写后人工核验。任一失败时取消剩余队列，
按相反顺序尝试恢复已影响的屏幕，并记录成功、失败和未知清单。恢复失败后不得自动重试。

## 10. 错误、断连与恢复语义

- 身份、接口或权限不匹配：`BLOCKED`，不猜测替代节点、不提权。
- read/write 超时：取消本阶段，辅助进程在有界宽限后终止；不无限重试。
- native crash：记录稳定分类和退出状态，主进程保持运行，能力不晋级。
- 未知事件或 payload：记录计数和分类，不连接动作引擎。
- 写入期间断连：取消队列，显示/亮度状态标记为 `unknown`。
- 重插：创建新 session，重新运行 M1 被动发现和 G1 核对；不自动恢复写入能力。
- 恢复基线未知：明确标记“需要机主人工处理”，不得用 clear/default 假装回滚成功。

## 11. 测试策略

### 11.1 硬件无关自动化

- 精确档案、接口歧义和身份漂移必须失败关闭。
- 状态机禁止越级、重复批准、过期清单和额外操作。
- Fake transport 注入全部按键与旋钮帧并验证归一化事件。
- 输入后端合同证明不导入 `_vendor`、不发送输出命令。
- 亮度合同只允许两次批准值写入，不调用组合初始化。
- 图片合同验证 key 1–6 边界、顺序、目标唯一性和恢复队列。
- IPC 覆盖 schema 错误、超时、helper crash、部分响应和断连。
- 日志合同拒绝 serial、路径、用户名、原始 payload 和图片内容。
- 构建和 CI 不要求硬件、root、sudo、udev/systemd 或 `/dev`。

### 11.2 真机验收

| 能力 | 成功标准 |
|---|---|
| LCD 键 | 1–6 各 10/10 press/release，无串键 |
| 圆键 | 7–9 各 10/10 press/release，无误分类 |
| 旋钮 | 每个左右各 20/20、按压/释放各 10/10，方向正确 |
| 输入延迟 | p95 ≤ 250ms，或明确报告未达标分布 |
| 稳定性 | 输入运行 10 分钟；每个后续切片稳定 60 秒 |
| 亮度 | 可见变化、返回结果和恢复均成功；无 LCD 副作用 |
| 单 LCD | 仅目标屏变化；方向、裁切正确；恢复成功 |
| 六 LCD | 6/6 正确，0 错屏、0 邻屏串扰、0 未记录残留 |
| 断连 | 2 秒内进入断连；重插后 0 次自动写入 |

“返回码成功”不能替代人工观察；一次成功也不能外推到未测试设备或固件。

## 12. 自动化边界

书面规格、实施计划和 G0 开始授权全部获得批准后，AI Coding 可以在不反复等待人工的
情况下完成 G0 中的代码、测试、文档、FakeBackend、IPC harness、静态安全门和离线
产物验证。它必须在以下第一条边界前停止并给出单句审批请求：

- 首次把 `6602:1000` 加入任何 active profile。
- 首次导入/加载 vendor SDK 或 native `.so`。
- 首次打开 `/dev/hidraw*` 或 `/dev/input/event*`。
- 任何 ACL、udev、systemd、sudo 或系统安装动作。
- 初始化、heartbeat、disconnect、亮度、LCD 或其他硬件写入。

这样把大部分工程工作自动化，同时保留少量清晰、可逆的物理风险门。

## 13. M2 完成定义与 M3 边界

M2 完成需要：

- G0 自动测试全部通过。
- G1–G7 全部按顺序通过，并各有独立批准和脱敏证据。
- Adapter、helper、超时、断连和恢复合同得到验证。
- 兼容表逐能力反映实际结果，不把 USB 命中写成整机支持。
- legacy daemon/GUI/systemd 仍未自动接管目标设备。

如果任一门阻塞，项目可以发布部分验证证据并保持 Early Preview，但 M2 里程碑仍为
未完成；不得用“明确记录了失败”替代该能力的完成标准。

M3 才开始插件、动作执行、AI 工作流和业务 LCD 状态。G8 legacy 集成可以在 M2 之后
与 M3 前置安全工作一起规划，但必须先解决任意 shell action、自动重启、close/tcache
和自动写入问题。

## 14. 待验证证据

这些项目不是文档占位符，而是对应门的明确阻塞条件：

| 证据问题 | 当前状态 | 阻塞门 |
|---|---|---|
| 接口 `00`、`01` 的实际职责 | 未验证 | G1/G3 |
| 是否可在完全无输出情况下捕获全部输入 | 未验证 | G3 |
| 生命周期/握手能否拆成可声明写集合 | 未验证 | G4 |
| `6602:1000` 的事件码和偏移是否等同上游 | 未验证 | G3 |
| 图片尺寸、方向、编码和 key mapping | 未验证 | G6/G7 |
| 每次写入前的可恢复亮度/图片基线 | 会话时确认 | G5–G7 |

## 15. 审批记录

- 2026-08-03：产品负责人批准以“独立 Adapter + 分阶段真机验证”为 M2 交付边界。
- 2026-08-03：产品负责人选择方案 C。
- 2026-08-03：产品负责人批准组件与数据流设计。
- 2026-08-03：产品负责人批准状态机、审批门与回滚设计。
- 2026-08-03：产品负责人批准测试、验收与 M2/M3 边界，并授权生成正式文档。
- 当前待办：产品负责人复核本书面规格；该复核只授权后续编写实施计划，不授权 G0
  实施、SDK 激活、权限变更或硬件访问。
