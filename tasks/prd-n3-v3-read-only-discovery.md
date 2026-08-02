# M1 产品需求文档：N3 V3.0 安全只读发现

## 文档信息

| 字段 | 内容 |
|---|---|
| 产品 | N3 AI Deck |
| 里程碑 | M1 — Safe N3 V3.0 Discovery |
| 版本 | 0.9 |
| 状态 | 正式评审稿；安全范围变更待产品负责人批准后执行 |
| 产品负责人 | `jincai822` |
| 编写 | 产品负责人与 Codex |
| 日期 | 2026-08-03 |
| 上位文档 | `tasks/prd-n3-ai-deck.md` |

### 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| 0.9 | 2026-08-03 | 定义 `6602:1000` 的被动目录、sysfs 扫描、CLI、测试和真机只读验收 |

## 1. 执行摘要

M1 为 N3 AI Deck 增加一条独立、被动、默认安全的 Linux 设备发现路径，使用户和自动化系统可以确认是否出现了与目标 USB ID `6602:1000` 匹配的候选设备、看到非敏感 USB/HID 接口拓扑，并得到“机主报告的型号候选；协议未验证”的诚实状态。M1 只读取 sysfs 元数据，不打开任何 `/dev` 节点、不导入或调用 vendored SDK、不安装权限规则，也不执行初始化、亮度或 LCD 写入。完成后，M2 才能基于确切接口证据设计受控的身份与协议验证。

## 2. 问题陈述

### 2.1 用户问题

设备所有者需要回答三个基础问题：“目标设备是否连接？软件识别到的究竟是哪一台？下一步是否安全？”当前项目没有一个产品级只读命令来回答这些问题；现有 daemon、probe 和 debug 路径依赖活跃设备库或 `/dev` 节点，其中部分流程会打开、初始化或写入设备，因此不能作为 M1 的默认入口。

### 2.2 技术事实与证据

2026-08-03 对当前已连接硬件进行了不含序列号的只读 sysfs 观测：

| 字段 | 观测值 |
|---|---|
| USB VID:PID | `6602:1000` |
| `bcdDevice` | `0300` |
| 设备级 class/subclass/protocol | `00/00/00` |
| 接口 `00` | HID `03/00/00` |
| 接口 `01` | HID Boot Keyboard `03/01/01` |
| Linux 绑定 | 两个接口均由 `usbhid` 绑定；键盘接口产生一个 input event |

该证据只证明枚举和拓扑，不证明物理型号身份、协议兼容、事件映射、亮度或 LCD 能力。总线位置、hidraw 编号和 input event 编号会随机器与插拔变化，因此不作为稳定身份。🔶 **假设：** VID/PID 加接口拓扑可以把 M2 的候选范围收窄到可人工验证的程度，但不能自动认证型号。

代码审查还确认：

- vendored `ProductIDs.g_products` 没有 `6602:1000` 这一精确组合。
- `DeviceManager` 枚举依赖 native HID transport；其监听路径可能在匹配后直接打开设备。
- 现有 `probe` 默认包含初始化、亮度和图像写入。
- 现有 daemon/debug/GUI 多处硬编码上游参考组合 `6603:1003`。

因此，M1 不把 `6602:1000` 加入活跃 `g_products`，而是建立与 SDK 完全隔离的被动目录与发现模块。

## 3. 目标用户与 Jobs-to-be-Done

### 首要角色

已确认的首要用户是拥有一台自报型号为 N3 V3.0、希望继续兼容开发但不愿冒硬件风险的产品负责人。🔶 **假设：** 其他 Linux 设备所有者也需要同样的安全发现能力；M1 不以外部用户价值验证为完成门。

### Jobs-to-be-Done

- 当我接入 N3 V3.0 时，我希望运行一个明确的只读命令确认目标 USB ID 和接口数量，从而决定是否进入后续验证。
- 当发现失败时，我希望获得可操作且不要求提权的说明，从而区分“未连接”“sysfs 数据不完整”和“命令错误”。
- 当我把结果用于自动化时，我希望有稳定 JSON 和退出码，从而无需解析易变的人类文本。

🔶 **假设：** 人类文本 + JSON 足以覆盖首批人工诊断和 AI Coding 自动化需求；尚无外部 CLI 可用性测试。

## 4. 战略背景

M1 是从公开愿景走向真实硬件证据的最小安全切片。它降低 M2 选择错误接口和误触发写入的风险，同时提供第一个 N3 AI Deck 原生、可演示、可自动测试的功能。该能力没有云服务、AI 供应商或商业私有代码依赖。

已批准的 2026-08-02 公开项目设计把“精确 USB 注册、Linux 权限和只读发现”合并在 M1。本文提出更窄的安全修订，必须由产品负责人明确批准后才取代原 M1 条款：

- **M1 注册**指被动产品目录，不是 SDK 活跃注册。
- **M1 权限工作**只收集接口拓扑并形成后续最小权限依据；不修改打包的 udev 规则，不安装系统文件。
- SDK 激活和 udev 权限变更进入 M2 的人工硬件门。

这是一个显式范围变更，不是对历史文档的静默改写。批准后，本 PRD 将正式取代公开项目设计第 7 节第 1 步和第 10 节 M1 中关于“选择意图接口、安装精确权限”的要求；历史文档保留并增加指向本决策的修订说明。“先发现、后控制”的里程碑顺序不变。

## 5. 方案概述

### 5.1 被动设备目录

新增与 vendored SDK 无依赖的公开设备目录，至少包含：

- 规范化 VID/PID。
- 对外候选名称。
- 身份状态和协议状态两个独立枚举。
- 可公开的注释，不包含序列号或机器路径。

目录必须登记两项：

- `6602:1000`：名称为 `N3 V3.0 candidate (owner-reported)`，`identity_status=user_reported_candidate`，`protocol_status=unvalidated`。
- `6603:1003`：名称为 `N3 upstream reference variant`，`identity_status=upstream_reference`，`protocol_status=upstream_reference`。

USB ID 命中只产生 `target_match`/`catalog_match`，不能把任何一项升级为“型号已确认”或“N3 AI Deck 已支持”。

### 5.2 纯 sysfs 发现模块

发现模块使用 Python 标准库遍历可注入的 sysfs USB 根目录，读取设备级 `idVendor`、`idProduct`、`bcdDevice` 以及其接口目录的 class/subclass/protocol。它只保留 class 为 `03` 的 HID 候选接口，并对多个候选明确标记 `ambiguous`，不猜测哪一个接口可安全用于协议访问。它只对目录中的文本属性执行只读访问：

```text
sysfs USB 根目录
  -> 读取 USB 设备属性
  -> 匹配被动设备目录
  -> 读取同级接口项元数据
  -> 产生结构化 DeviceObservation
```

扫描分两阶段进行：

1. 在根目录只把同时具有 `idVendor` 和 `idProduct` 的项视为 USB 设备候选；两项都没有的接口和普通项静默忽略，仅缺一项才产生结构化 warning；VID/PID 完整但未命中目录的设备也静默忽略。
2. 只有 VID/PID 命中被动目录后，才读取可选 `bcdDevice`，并从同级 `<device>:<config>.<interface>` 项读取接口 `bInterfaceNumber`、`bInterfaceClass`、`bInterfaceSubClass`、`bInterfaceProtocol`。接口项不是设备项的子目录。

真实 Linux 的 `/sys/bus/usb/devices` 设备项通常是指向 `/sys/devices/...` 的符号链接，因此安全策略分为两种明确模式：

- **可信 sysfs 模式：** 无论使用默认值还是显式传参，只有根目录解析后恰为 `/sys/bus/usb/devices` 才进入该模式。设备/接口目录链接只允许解析到 `/sys/devices` 下，并使用路径对象的 `is_relative_to()` 语义判断，禁止字符串前缀判断；属性本身必须是非符号链接的普通 sysfs 文件，且解析后位于对应设备或接口目录内。
- **严格 fixture 模式：** 所有其他 `--sysfs-root` 或测试注入根都视为不可信；设备目录、接口目录和属性中的任何符号链接都被拒绝并产生稳定 warning，不跟随到根目录外。

禁止整个 M1 生产依赖闭包（CLI、catalog、discovery）导入 `DeviceManager`、vendored SDK、native transport、GTK、`evdev` 或 `pyudev`。禁止枚举、打开或读取 `/dev/hidraw*` 和 `/dev/input/event*`。接口节点名称和 driver 链接不是 M1 输出字段。

### 5.3 自动化友好的 CLI

新增命令 `n3-ai-deck-detect`：

- 默认输出简短人类可读报告。
- `--json` 输出带 `schema_version: 1` 的确定性 JSON。
- `--sysfs-root PATH` 允许测试或诊断使用替代只读 sysfs 树；默认是 `/sys/bus/usb/devices`。
- 输出只包含目录中的已声明字段和被动目录提供的候选名称；绝不读取或输出 USB `serial`、`manufacturer`、`product` 或 driver 描述符。
- 多设备按稳定顺序输出。
- 安全保证只适用于 `n3-ai-deck-detect` 及其 M1 新模块；同一发行包中的旧 daemon、probe、debug 和 install 命令仍可能访问或写入硬件，M1 文档必须明确警告不要运行它们。
- `sysfs_name` 只接受 ASCII 字母、数字、点、下划线、冒号和连字符；非法名称不回显，并产生 `invalid_sysfs_name` warning，以避免人类输出中的终端控制字符。

退出码：

| 退出码 | 含义 |
|---:|---|
| `0` | 精确发现 `6602:1000`，并发现至少一个 HID 候选接口；多接口仍返回 `0`，但必须标记 `ambiguous` |
| `1` | 扫描成功，但没有发现目标 `6602:1000` |
| `2` | 参数错误或 sysfs 根目录无法扫描 |
| `3` | 发现目标 `6602:1000`，但没有 HID 候选接口 |

进程级退出码按固定优先级聚合：根目录/参数致命错误始终为 `2`；否则任意一台目标有至少一个完整 HID 候选则为 `0`；否则只要目标 USB ID 存在则为 `3`；否则为 `1`。局部属性错误只产生结构化 warning，不覆盖上述聚合结果。上游参考设备可以出现在报告中，但不能替代目标设备决定成功退出码。

使用 `--json` 且根目录在运行时不可扫描时，仍输出符合封闭合同的 JSON：`devices` 为空，`warnings` 含 `root_unavailable`，然后退出 `2`；`argparse` 自身的参数语法错误保留标准 stderr 和退出 `2`，不承诺 JSON。

### 5.4 输出数据最小集

JSON 顶层和每个 observation 的字段是封闭合同；可选标量必须以 `null` 出现，不得省略。最小完整示例：

```json
{
  "schema_version": 1,
  "target": {"vid": "6602", "pid": "1000"},
  "devices": [
    {
      "sysfs_name": "1-2",
      "vid": "6602",
      "pid": "1000",
      "catalog_name": "N3 V3.0 candidate (owner-reported)",
      "catalog_match": true,
      "target_match": true,
      "identity_status": "user_reported_candidate",
      "protocol_status": "unvalidated",
      "bcd_device": "0300",
      "interface_selection": "ambiguous",
      "hid_interfaces": [
        {"number": "00", "class": "03", "subclass": "00", "protocol": "00"},
        {"number": "01", "class": "03", "subclass": "01", "protocol": "01"}
      ]
    }
  ],
  "warnings": []
}
```

合同规则：

- `vid`、`pid` 为四位小写十六进制字符串。
- `catalog_name`、`catalog_match`、`target_match`、`identity_status` 和 `protocol_status` 均为必填字段。
- `bcd_device` 为四位小写十六进制字符串或 `null`。
- `sysfs_name` 是易变的根目录项名称，仅用于本次诊断，不作为设备身份。
- `hid_interfaces` 的所有四个字段均为两位小写十六进制字符串。
- `interface_selection` 为 `none`、`unique` 或 `ambiguous`；M1 永远不据此打开接口。
- `warnings` 每项只允许 `code`、`sysfs_name` 和 `attribute`；后两者可为 `null`。`code` 必须来自版本化枚举，不得包含原始异常文本或绝对路径。
- M1 warning code 仅允许 `root_unavailable`、`invalid_sysfs_name`、`incomplete_usb_identity`、`invalid_usb_identity`、`missing_bcd_device`、`invalid_bcd_device`、`incomplete_hid_interface`、`invalid_hid_interface`、`unsafe_symlink`、`unreadable_attribute`。
- 设备按 `(vid, pid, sysfs_name)`、接口按数值化接口号稳定排序；JSON 键顺序固定以便快照审阅，但消费者不得依赖键顺序。

不包含序列号、任何本机绝对路径、用户名、权限位、环境变量或 `/dev` 节点内容。

🔶 **假设：** 该 JSON v1 合同足以被首批 AI Coding 任务和外部诊断脚本消费；在首个外部集成前仍可能通过提升 `schema_version` 调整。

## 6. 成功指标

### 6.1 首要指标

| 指标 | 当前 | M1 目标 |
|---|---:|---:|
| 已知设备分类正确率（版本化夹具矩阵） | 无产品级发现实现 | 100% |

夹具矩阵至少覆盖：目标 `6602:1000`、上游参考 `6603:1003`、未知设备、大小写/空白、属性缺失、格式错误、多个设备和多个接口。

### 6.2 次要指标

- 实机命令将当前目标报告为 `6602:1000`、`identity_status=user_reported_candidate`、`protocol_status=unvalidated`、两个 HID 候选接口和 `interface_selection=ambiguous`。
- 人类输出和 JSON 对同一 observation 保持语义一致。
- 新模块在无物理硬件、无 native SDK 和无 `/dev` 访问时可完整测试。
- M1 所有故事均有失败测试先行、独立代码复核和完整 CI 证据。

### 6.3 护栏指标

- `/dev` 节点 open/read/write：**0 次**。
- vendored SDK/native transport 导入或调用：**0 次**。
- `ProductIDs.g_products` 变更：**0 处**。
- udev/systemd 安装或系统文件修改：**0 次**。
- 硬件初始化、亮度、图像或其他写入：**0 次**。
- 序列号读取、输出或提交：**0 个**。

## 7. 用户故事与需求

### Epic 假设

我们相信，先提供完全隔离于活跃 SDK 的被动 sysfs 发现能力，可以让用户和自动化可靠确认目标设备及接口拓扑，同时把意外硬件访问风险维持为零。我们通过夹具矩阵 100% 正确、实机只读结果匹配和安全护栏测试来验证。

### M1-01：建立被动设备目录

作为维护者，我希望用纯数据登记已知 USB 组合、身份状态和协议状态，从而让发现能力不等同于“驱动已支持”。

**验收标准：**

- [ ] `6602:1000` 以 `user_reported_candidate` + `unvalidated` 登记。
- [ ] `6603:1003` 必须以 `upstream_reference` 身份和协议状态登记。
- [ ] VID/PID 接受整数或十六进制文本输入并输出规范四位小写文本；越界和非法值失败关闭。
- [ ] 重复 VID/PID 在测试或构建时被拒绝。
- [ ] 模块不导入 vendored SDK 或任何硬件访问库。

### M1-02：扫描 sysfs USB 元数据

作为设备所有者，我希望发现模块只读取 sysfs 元数据，从而在不打开设备节点时确认目标和接口。

**验收标准：**

- [ ] 给定替代 sysfs 根目录时，可发现单台、多台和无设备情形。
- [ ] 严格 fixture 模式拒绝所有符号链接逃逸；可信 sysfs 模式只接受解析到 `/sys/devices` 的设备/接口链接。
- [ ] 只读取候选目录中的明确允许属性，且从不读取名为 `serial` 的属性。
- [ ] 接口从与设备同级的 `<device>:<config>.<interface>` 目录关联，并按接口号稳定排序。
- [ ] 缺失、不可读或格式错误属性不会产生 traceback 或错误匹配。
- [ ] 目标夹具产生 `6602:1000`、`0300` 和两个预期 HID 接口。

### M1-03：提供人类与 JSON CLI

作为用户或自动化系统，我希望用一个安全命令获得稳定结果，从而快速决定下一步。

**验收标准：**

- [ ] 安装后提供 `n3-ai-deck-detect` 命令，帮助文字明确说明“只读 sysfs、不证明协议兼容”。
- [ ] 默认输出清楚区分“USB ID 候选命中”“身份未确认”“协议未验证”“未发现”和“属性警告”。
- [ ] `--json` 输出有效 JSON、`schema_version: 1` 和稳定排序。
- [ ] 退出码严格遵循 `0/1/2/3` 契约。
- [ ] `--json` 的运行时根目录错误仍输出封闭 JSON；参数语法错误保持 argparse 标准行为。
- [ ] 含控制字符或非允许字符的根目录项名称不会原样进入人类或 JSON 输出。
- [ ] 所有输出不包含序列号；JSON 不包含未声明字段。

### M1-04：建立零硬件 CI 安全门

作为维护者，我希望 CI 能证明 M1 不接触活跃硬件路径，从而允许 AI Coding 自动迭代。

**验收标准：**

- [ ] 测试只使用临时 sysfs 夹具，不要求物理硬件。
- [ ] 测试拦截从 CLI `main()` 调用到扫描结果期间、由 M1 scanner/attribute-reader 发起的数据文件访问：严格 fixture 模式只允许读取根内 allowlist 属性；可信 sysfs 模式解析路径只允许位于 `/sys/devices`；两种模式都不含 `serial`。Python/importlib 的模块与发行元数据加载不属于此数据读取断言。
- [ ] 静态依赖检查覆盖 entry point、catalog 和 discovery，禁止导入其他项目生产模块；运行时导入检查确认没有加载 `_vendor`、GTK、`evdev`、`pyudev` 或 native transport。
- [ ] AST/源码安全门覆盖全部 M1 生产模块，禁止 `DeviceManager`、`LibUSBHIDAPI`、`os.open`、`subprocess`、`/dev/hidraw` 和未受 allowlist 约束的文件读取。
- [ ] 原有测试、Ruff 和 build 继续通过；`uv run mypy --strict src/streamdock_n3/device_catalog.py src/streamdock_n3/discovery.py` 单独通过。
- [ ] 构建后的 wheel 包含并能调用 `n3-ai-deck-detect --help` entry point，且帮助命令也不加载禁止依赖。
- [ ] 发布隐私扫描继续覆盖新增文档和源码。

### M1-05：记录实机只读验收

作为合作方，我希望看到一份可复核但不泄露设备身份的实机记录，从而相信发现能力基于真实硬件。

**验收标准：**

- [ ] 在目标设备连接时运行默认发现命令，不使用 `sudo`。
- [ ] 记录 commit、日期、VID:PID、`bcdDevice`、接口元数据、期望与实际结果。
- [ ] 不记录序列号、易变 `/dev` 编号或本机绝对工作区路径。
- [ ] README/路线图只把 M1 能力描述为“只读发现”，不声称协议或写入兼容。

## 8. 不在 M1 范围内

- 把 `6602:1000` 加入 vendored `ProductIDs.g_products` 或 `DeviceManager`。
- 加载 native HID transport、打开 `/dev/hidraw*`、读取 `/dev/input/event*`。
- 监听按键、圆键、旋钮或热插拔事件。
- 设备初始化、亮度、刷新、图标或 LCD 图像写入。
- 修改或安装 udev 规则、systemd 单元、桌面文件或其他系统文件。
- 运行现有 daemon、probe、debug 的活跃硬件模式。
- 声称 `6602:1000` 已支持、与 N3 协议兼容或可安全写入。
- Windows、macOS 或非 sysfs 平台发现。

以上能力只能进入 M2 或后续里程碑，并遵守人工硬件门。

## 9. 依赖与风险

### 9.1 依赖

- Linux sysfs 的 USB 设备/接口目录和标准文本属性。
- Python 3.11+ 标准库。
- 现有项目测试、Ruff、build 和 GitHub CI。
- 一台已由系统枚举的目标设备，用于最终只读验收；自动测试不依赖它。

### 9.2 风险与缓解

| 风险 | 缓解措施 | 触发/责任人 |
|---|---|---|
| 价值：用户可能不需要独立发现命令 | 用当前首位用户执行 M1-05；外部价值验证继承总 PRD、留到 M4 前 | 产品负责人，M1-05/M4 前 |
| 易用性：身份、协议和接口状态可能让用户困惑 | 人类输出使用明确候选措辞；用有/无设备场景做可理解性检查 | 产品负责人，M1-03 |
| 可行性：USB ID 可能被其他产品复用，单凭 ID 不能证明物理型号 | 分离身份/协议状态；输出接口拓扑；M2 前人工确认 | 技术负责人，任何身份歧义时 |
| sysfs 布局或属性不完整 | 容错解析、warnings、夹具覆盖，不猜测缺失值 | 技术负责人，解析失败时 |
| 误把被动目录当作 SDK 支持表 | 类型和文档明确区分；测试禁止 `g_products` 变更 | 每个 M1 PR |
| 安全：CLI 无意读取序列号、逃逸 symlink 或访问 `/dev` | 双根策略、属性 allowlist、文件访问和完整依赖闭包测试 | 每个 M1 PR |
| 人类输出适合演示但不适合自动化 | 提供版本化 JSON 与退出码 | M1-03 |
| 实机结果包含易变或敏感信息 | 固定记录字段；隐私扫描；不提交原始全量 udev 输出 | M1-05 |
| 现有打包名称仍沿用上游 | 新命令使用 N3 AI Deck 名称；整体包重命名留到 M5 前 | M1 发布说明 |
| 商业可行性：M1 本身不产生收入证据 | 限制为低成本开源基础层；商业验证继承总 PRD，不以 M1 结果外推收入 | 产品负责人，M4 后 |

## 10. 开放问题

| 问题 | 责任人 | 最晚决策点 | 状态 |
|---|---|---|---|
| M2 应选择接口 `00`、`01` 还是两者分别承担控制/键盘能力？ | 技术负责人 | 首次打开设备前 | 🔵 开放；M1 只记录拓扑 |
| 是否需要在 M2 为目标增加精确 udev 规则，规则应授予哪些节点？ | 技术负责人 | M2 权限设计评审 | 🔵 开放 |
| `bcdDevice=0300` 是否足以区分 N3 V3.0 与同 ID 设备？ | 产品/技术负责人 | M2 身份验证前 | 🔵 开放 |
| JSON schema 何时承诺向后兼容？ | 技术负责人 | 首个外部集成前 | 🔵 开放；M1 仅固定 `schema_version: 1` |

这些问题不阻塞 M1 的纯 sysfs 实现。

## M1 完成定义

M1 只有在以下条件全部满足时才完成：

- [ ] M1-01 至 M1-05 全部验收。
- [ ] 全量测试、Ruff、build 和公开隐私扫描通过。
- [ ] 独立代码审查确认没有活跃设备访问或支持性误导。
- [ ] GitHub CI 在支持的 Python 版本上通过。
- [ ] 路线图和 README 与实机记录一致。
- [ ] 没有执行任何硬件写入、系统安装、发布标签或 release。

## PRD 自评

### 最强部分

安全边界和技术范围：它们直接来自当前代码调用链与同日实机只读 sysfs 证据，并被可测试的禁止项保护。

### 最弱部分

设备身份：`6602:1000` 和接口拓扑能稳定发现硬件，但尚不能证明供应商协议或所有同 ID 设备均为 N3 V3.0。

### 优先验证的假设

| # | 假设 | 错误时的影响 | 验证方式 |
|---:|---|---|---|
| 1 | VID/PID + 接口拓扑足以把 M2 候选范围收窄到可人工验证 | 可能选错同 ID 设备 | M2 前比对报告描述符与协议响应，只在人工门后进行 |
| 2 | sysfs-only CLI 足以完成首次诊断 | 用户仍需要额外工具 | 用当前实机和无设备场景验证输出是否可行动 |
| 3 | JSON v1 字段满足自动任务消费 | 很快出现破坏性 schema 变更 | 用后续任务队列消费一次，再冻结公共契约 |

### 建议下一步

将 M1-01 至 M1-05 转为按依赖排序的 AI Coding 任务队列；使用测试驱动方式先实现设备目录和夹具扫描，再实现 CLI，最后运行一次实机只读验收。
