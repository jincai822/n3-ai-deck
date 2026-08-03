# M2 G0 事务型 Adapter 安全修订设计

**日期：** 2026-08-03

**状态：** 对话设计已逐节批准；书面规格待最终复核

**产品：** N3 AI Deck

**里程碑：** M2 — Hardware Controls / G0

**修订对象：** `docs/superpowers/plans/2026-08-03-m2-g0-safe-adapter-foundation.md`

## 1. 决策摘要

G0 改为“事务型 `N3Adapter` 协调器”。`N3Adapter` 是唯一能力状态所有者，私有持有
profile、软件 commit、backend、evidence recorder 和 capability gate。调用者不再取得
可调用的 live gate，也不能以任意初始状态创建生产 Adapter。

每次命令必须完成以下事务，才计为成功：

```text
验证并预留命令
  -> backend 恰好执行一次
  -> 获得合法 OperationResult
  -> 写入 operation evidence
  -> 结算预留并增加成功次数
```

每次阶段晋级必须完成以下事务：

```text
校验 profile、阶段、命令顺序、恢复、机器结果和人工确认
  -> 生成带 session epoch 的 TransitionPreview
  -> 写入 stage evidence
  -> 原子提交能力状态
```

任何缺失结果、证据失败、身份漂移、顺序错误、恢复失败或 token 失配都失败关闭。backend
断连单独进入 `DISCONNECTED`。本修订只实现硬件无关 G0，不激活 SDK、设备节点、权限或
硬件写入。

## 2. 来源优先级与修订原因

事实来源按以下顺序治理：

1. `tasks/prd-m2-n3-v3-hardware-controls.md` version 1.0。
2. `docs/superpowers/specs/2026-08-03-m2-hardware-controls-design.md`。
3. 本安全修订。
4. 原 G0 实施计划中未被本修订替代的内容。

整分支最终审查确认原计划存在六个阻塞问题：

1. live gate 可在没有 backend/result/evidence 时推进状态。
2. 已获得的能力状态可转移到另一个 profile 或接口。
3. forward/recovery 顺序和恢复成功没有成为晋级条件。
4. backend 断连被错误归类为 `BLOCKED`。
5. helper 的普通 `python -m` 解析和可变模块常量不能证明固定来源。
6. evidence sink 异常可能发生在不可逆状态变更之后。

原计划中与上述事实来源冲突的“授权时计成功次数”“所有非成功都进入 BLOCKED”“无序
规则集合”“普通三元素 helper argv”和“状态先变更再写 evidence”全部被本修订替代。

## 3. 范围与非目标

### 3.1 范围

- 重构 G0 contracts、gate、adapter、fake helper IPC 和 evidence 事务。
- 用 `FakeBackend` 验证完整 forward、recovery、disconnect 和失败关闭合同。
- 更新静态、运行时、wheel 安装和公开事实测试。
- 更新原 G0 计划的修订声明，并生成独立安全加固实施计划。

### 3.2 非目标

- 不建立真实 `6602:1000` active profile。
- 不选择生产接口，不打开或枚举任何 `/dev` 节点。
- 不导入或加载 vendored SDK、native transport、evdev、pyudev 或 GTK。
- 不修改 ACL、udev、systemd、用户组或系统文件。
- 不发送 initialization、heartbeat、disconnect、brightness、LCD、raw HID 或其他硬件数据。
- 不声明妙联宝 N3 V3.0 已兼容。
- 不修复本修订之外的 legacy 全仓 mypy 债务。

## 4. 信任边界

G0 防御以下边界内的误用和绕过：

- 通过公开 Python API 跳过 backend、result、evidence、profile 或 recovery。
- 通过返回对象修改内部 gate、session、计数或队列。
- 通过当前工作目录、`PYTHONPATH` 或用户 site 影子包替换 fake helper。
- 通过重复、过期、错误命令或错误阶段 token 结算操作。
- 通过 sink 异常或 backend 异常制造“状态已晋级、证据未完成”。

任意同进程代码强行修改下划线私有字段、替换函数 `__code__`、修改 Python 解释器内存或
控制已安装 site-packages 属于进程完整性边界之外。未来真实 helper 仍必须作为独立受限
进程，不把 Python 对象封装当作操作系统安全沙箱。

## 5. 组件与所有权

### 5.1 `N3Adapter`

`N3Adapter` 私有持有：

- `_profile: DeviceProfile`
- `_current_commit: str`
- `_backend: Backend`
- `_gate: _CapabilityGate`
- `_evidence: EvidenceRecorder`
- 可选的 `_external_evidence: EvidenceSink`

这些引用在构造后不可替换。对外只提供不可变值或快照：

- `state -> AdapterState`
- `profile -> DeviceProfile`
- `capability_snapshot -> CapabilitySnapshot`
- `session_snapshot -> StageSessionSnapshot | None`
- `evidence_records -> tuple[EvidenceRecord, ...]`

不再公开 `adapter.gate`、backend 引用或可变 evidence 容器。

生产构造函数只创建 `CANDIDATE` 状态，不接受 `initial_state`。聚焦测试通过执行真实的前置
FakeBackend 阶段获得后续状态，不在生产代码中增加 test-only 状态恢复入口。

### 5.2 `_CapabilityGate`

gate 改为模块私有实现，仅执行：

- stage/profile/session 校验。
- 有序 command reservation。
- backend result 结算。
- forward/recovery 阶段切换。
- transition preview 和 commit。
- `BLOCKED` / `DISCONNECTED` 终态管理。

gate 不调用 backend，不持有外部 sink，不公开可变数据。

### 5.3 `CommandPolicy`

fake helper 使用无状态 `CommandPolicy` 校验单次 IPC 请求。它验证 schema、commit、profile
digest、interface、stage、当前 step 和精确命令，但不能创建、恢复或推进主进程能力状态。
helper 只能返回一次 backend result。

## 6. 不可变合同

### 6.1 精确有序命令

原 `CommandRule(min_calls, max_calls, ...)` 的无序计数模型由以下合同替代：

```text
CommandSpec(
  operation,
  brightness | None,
  key | None,
  image_sha256 | None
)

CommandStep(
  forward: CommandSpec,
  recovery: CommandSpec | None
)
```

一个 `CommandStep` 代表恰好一次 forward 调用及最多一次对应 recovery。重复命令必须在
manifest 中出现为多个独立 step，从而使最大调用次数等于明确列出的 step 数。

`StageManifest.steps` 是非空有序 tuple。每个 stage 的允许 operation、参数范围、deadline、
expected result、recovery plan 和 approval reference 继续按现有合同严格校验。

### 6.2 快照

`CapabilitySnapshot` 至少包含：

- 当前 `AdapterState`。
- 已绑定 profile digest、`bcdDevice` 和 interface；G1 前为空。
- 单调递增 state/session epoch。
- 当前 stage 和阶段 phase；无 session 时为空。

`StageSessionSnapshot` 只包含 stage、`FORWARD` / `RECOVERY` phase、forward index、剩余
recovery 数量和是否存在 pending reservation。它不返回内部 manifest、token、list 或 queue。

所有合同和快照使用 frozen/slotted dataclass、tuple、enum 和经过验证的标量。

### 6.3 IPC 请求合同

`IpcRequest` 携带一次调用所需的不可变事实：capability state、已绑定 profile digest /
`bcdDevice` / interface、session epoch、stage、phase、step index、profile、manifest 和精确命令。
helper 用这些字段做无状态的一致性校验并只返回 `OperationResult`。

IPC 不接受主进程 reservation token，也不返回可被主进程当作状态恢复凭证的 gate、session
或 next-state。主进程只信任自己私有 reservation 与返回结果的关联；helper 结果不能自行结算
reservation 或推进状态。

## 7. Profile 与状态来源

1. Adapter 只从 `CANDIDATE` 创建。
2. G1 begin 校验 candidate profile 和 manifest 的 digest、`bcdDevice`、interface、commit。
3. G1 成功提交时，gate 永久绑定该身份和接口。
4. G2–G7 begin 必须匹配同一绑定；任何漂移以 `PROFILE_MISMATCH` 失败关闭。
5. 重插不恢复旧 Adapter。调用者必须创建新 Adapter，并从 M1/G1 重新开始。
6. IPC 请求中的 snapshot 仅供单次 helper policy 校验，不能成为主进程恢复凭证。

## 8. Reservation 与结果结算

### 8.1 预留

`execute(command)` 先要求：

- 当前 phase 为 `FORWARD`。
- 不存在 pending reservation。
- command 精确匹配当前 forward step。
- session/profile/state epoch 未变化。

成功后创建私有一次性 `Reservation`，绑定 session epoch、step index 和命令摘要。预留本身
不增加成功次数，也不推进 forward index。

### 8.2 backend 执行

Adapter 对每个 reservation 调用 backend 恰好一次。无论 backend 返回、抛错或返回非合同
对象，reservation 都必须被结算为成功或终态失败，不得悬挂。

### 8.3 成功结算

合法成功 result 的顺序是：

1. 构造并验证 operation evidence。
2. 写入内部 recorder。
3. 若配置外部 sink，调用外部 sink。
4. 所有 evidence 写入成功后，gate 结算 reservation。
5. 增加成功 step、推进 forward index，并把该 step 的 recovery 压入私有 LIFO 栈。

缺少 `record_result()` 的独立路径被删除；调用者不能只 authorize 后 complete。

### 8.4 失败结算

- timeout、backend error、invalid result 或 evidence failure：状态进入 `BLOCKED`。
- `ResultStatus.DISCONNECTED`：状态进入 `DISCONNECTED`。
- 所有失败都清除 pending reservation。
- 非断连 forward 失败取消剩余 forward；已成功 step 的 recovery 栈可保留为 recovery-only
  session。
- 断连清除全部队列且不执行自动恢复写入，输出状态记为 `unknown`。

## 9. Forward 与 Recovery 状态机

### 9.1 正常路径

forward step 必须按 manifest 顺序逐个执行。全部 forward 成功后，phase 改为 `RECOVERY`，
调用者只能通过 `recover(command)` 按 LIFO 顺序消费 recovery 栈。

典型顺序：

- G5：`B-10 -> B`
- G6：测试图 -> 批准基线
- G7：测试图 `1 -> 6`，恢复 `6 -> 1`

没有 recovery 的阶段在最后一个 forward result/evidence 成功后进入可完成状态。

### 9.2 forward 失败后的恢复

非断连 forward 失败时：

- capability state 立即变为 `BLOCKED`。
- 剩余 forward 永久取消。
- 只保留已成功影响输出的 recovery 栈。
- `recover()` 只能按栈顶精确命令执行。
- recovery 结果和人工确认继续记录，但不能恢复或晋级 capability state。

任一 recovery 机器结果失败后停止剩余自动 recovery；状态保持 `BLOCKED`，剩余输出记为
`unknown`，等待机主人工处理。

### 9.3 阶段完成

`complete_stage(manual_confirmation, recovery_confirmation)` 要求严格 bool/None：

- `manual_confirmation` 必须为 `True`。
- 没有 recovery 的阶段要求 `recovery_confirmation is None`。
- 有 recovery 的阶段只有所有 recovery 机器结果成功且 `recovery_confirmation is True` 时，
  Adapter 才计算 `RecoveryStatus.SUCCEEDED`。
- `False` 计算为 `FAILED`；`None` 计算为 `UNKNOWN`。二者都不得晋级。
- 不存在 pending reservation，所有 forward 和 recovery step 已按序完成。

已 `BLOCKED` 的 recovery-only session 可调用 `complete_stage()` 完成失败证据和清理 session，
但返回值仍为 `BLOCKED`。

## 10. Evidence 事务

每个 Adapter 强制创建内部 `EvidenceRecorder`。外部 sink 是额外目的地，不替代内部记录。

operation 成功只有在内部 recorder 和已配置外部 sink 都返回成功后才结算。若 sink 抛错：

- 捕获并丢弃异常文本。
- 内部记录稳定 `EVIDENCE_FAILURE` 分类。
- reservation 失败结算。
- 状态进入 `BLOCKED`，不得增加成功 step。

阶段完成使用 gate 私有 precommit 回调：

1. gate 验证所有条件并生成绑定当前 epoch 的 `TransitionPreview`。
2. Adapter 调用 `_gate.commit(preview, evidence_callback)`。
3. gate 重新校验 preview；校验成功后，在同一个私有方法中调用 callback。
4. callback 构造并验证 stage evidence，写入内部 recorder 和已配置外部 sink。
5. callback 正常返回后，gate 立即提交 next state；callback 抛错则失败关闭且不提交 next state。

回调期间不允许重入同一 Adapter；重入或 stale preview 以 `STALE_RESERVATION` 失败关闭。
外部 sink 可能已经记录一次尝试但随后报告失败，因此本合同保证的是“全部已配置证据目的地
接受前绝不晋级”，而不是跨任意第三方 sink 的回滚事务。失败记录必须标为 attempt/failure，
不能表现成成功 transition。

Evidence 继续禁止 serial、总线位置、`/dev` 名称、用户名、绝对路径、原始 payload、图片
bytes 和图片 digest。

## 11. Helper 来源隔离

fake helper 的唯一启动 argv 改为：

```text
[sys.executable, "-I", "-m", "streamdock_n3.hardware.helper_main"]
```

模块名在调用点使用字面量，不保留可重写的 `HELPER_MODULE` 全局变量。`-I` 隔离模式忽略
当前目录、`PYTHONPATH`、用户 site 和 `PYTHON*` 环境注入产生的模块搜索变化。

运行时测试必须：

- 从包含伪造 `streamdock_n3.hardware.helper_main` 的临时 cwd 启动。
- 设置指向影子包的 `PYTHONPATH`。
- 证明响应来自已安装、受审的 fake helper。
- 继续证明 import/construct 阶段不启动子进程。

已安装 site-packages 和 Python 解释器本身属于受信进程环境；控制这些位置不在 G0 的
Python API 威胁模型内。

## 12. 稳定错误分类

新增 `ErrorCode`：

- `RESULT_MISSING`
- `PROFILE_MISMATCH`
- `ORDER_VIOLATION`
- `RECOVERY_REQUIRED`
- `STALE_RESERVATION`
- `EVIDENCE_FAILURE`

规则：

- CANDIDATE/G1 尚未绑定身份时，manifest begin 前的纯输入验证错误不创建 session，也不改变
  capability state。
- G1 已绑定身份后，profile、commit、`bcdDevice` 或 interface 漂移属于 capability 完整性
  违规，即使发生在新 session 创建前也进入 `BLOCKED`。
- session 创建后的未授权命令、顺序错误、重复 token 或错误 phase 使当前阶段 `BLOCKED`。
- backend 和 evidence 异常不泄漏异常消息，只返回稳定分类。
- 不自动重试 backend、evidence、helper 或 recovery。

## 13. 公开 API 迁移

删除：

- `N3Adapter.gate`
- `N3Adapter(..., initial_state=...)`
- 调用者传入的 `RecoveryStatus`
- 可单独调用并计成功的公开 `CapabilityGate.authorize()/record_result()/complete()` 流程
- 可重写的 `HELPER_MODULE`

保留或新增：

```text
N3Adapter(profile, current_commit, backend, external_evidence=None)
N3Adapter.begin_stage(manifest) -> None
N3Adapter.execute(command) -> OperationResult
N3Adapter.recover(command) -> OperationResult
N3Adapter.complete_stage(
    manual_confirmation: bool,
    recovery_confirmation: bool | None = None,
) -> AdapterState
N3Adapter.disconnect() -> AdapterState
N3Adapter.state -> AdapterState
N3Adapter.profile -> DeviceProfile
N3Adapter.capability_snapshot -> CapabilitySnapshot
N3Adapter.session_snapshot -> StageSessionSnapshot | None
N3Adapter.evidence_records -> tuple[EvidenceRecord, ...]
```

这是 Early Preview 的明确破坏性安全修订，不提供旧 live-gate API 的兼容层。

## 14. 测试策略

每项生产行为使用 RED -> 验证预期失败 -> GREEN：

1. 没有 backend 调用或 result 时不能晋级。
2. live gate 不再存在，快照不能修改内部状态。
3. profile、`bcdDevice`、interface 或 commit 漂移失败关闭。
4. production Adapter 无任意 initial state。
5. reservation 重复、过期、错误 step、错误 phase 和缺失 result 被拒绝。
6. G5–G7 forward 顺序和 LIFO recovery 顺序精确。
7. forward 失败只允许 bounded recovery，最终不晋级。
8. recovery `FAILED` / `UNKNOWN` 不晋级。
9. backend 断连进入 `DISCONNECTED`，清队列且自动写入为零。
10. throwing evidence sink 不能产生无证据晋级。
11. helper cwd/PYTHONPATH 影子包无法执行。
12. 完整 G1–G7 FakeBackend 正常路径继续按顺序通过。
13. IPC schema、framing、limits、duplicate keys 和错误归一化继续通过。
14. G0 静态/import/runtime/wheel 安装隔离门继续通过。
15. 公开文档继续只声明 G0 foundation，拒绝兼容性外推。

## 15. 验证与完成标准

聚焦测试按受影响模块分别运行，最终必须重新运行：

```text
uv run pytest
uv run ruff check .
uv run mypy --strict src/streamdock_n3/hardware
uv build
git diff --check
git status --short
```

完成要求：

- 六个最终审查阻塞项都有先失败后通过的真实回归测试。
- 全部 G0 hardware-free 测试通过。
- strict G0 mypy、Ruff、wheel 和 sdist 构建通过。
- 禁止路径和硬件隔离测试没有放宽。
- 整分支独立复审为 `APPROVED`。
- 不把 unchanged legacy 全仓 mypy 债务伪装成本修订的通过项。

## 16. 文档和提交策略

1. 单独提交本安全修订规格。
2. 在原 G0 计划顶部增加修订声明，保留历史内容。
3. 新建独立安全加固实施计划，明确替代冲突的 Task 2/4/5/6/7 行为。
4. 由一个修复代理按计划完成全部最终审查 finding，避免并行代理同时修改状态机合同。
5. 每个可审查阶段运行聚焦测试并提交；最终统一复审。

## 17. 审批记录

- 2026-08-03：产品负责人批准 PRD 和正式设计优先于冲突的 G0 实施计划。
- 2026-08-03：产品负责人允许 Early Preview API 做破坏性安全修改，不保留兼容层。
- 2026-08-03：产品负责人选择事务型 Adapter 协调器。
- 2026-08-03：产品负责人逐节批准架构/事务、profile/恢复、helper/evidence 和 API/测试设计。
- 本文书面稿提交后仍需产品负责人最终复核，之后才生成实施计划和修改生产代码。
