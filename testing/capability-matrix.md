# CloudPSS 辅助建模能力对照表

> **历史快照说明（2026-09-08）**：下方是第一步迁移前的盘点，不能当作当前能力说明。第二步已经迁入核心类、模板查询、删除、多预览和只创建新 RID 保存。当前接口见 `skills/cloudpss-aux-modeling/references/api-contracts.md`；第三步验收证据见 `testing/runs/20260908-agent-integration/`。历史真实模型测试不自动证明迁移后版本已通过云端验证。

> 用途：在修改 Skill 或运行时之前，区分参考代码能力、当前 `cloudpss-aux-modeling` 实现、已有证据和首版纳入范围。
> 本文件只记录现状与待确认项，不改变运行时行为。

## 1. 能力总表

| 能力 | 参考代码中的原始命名 | 当前 Skill 适配实现 | 语义关系与迁移差异 | 已有证据 | 当前结论/首版建议 |
|---|---|---|---|---|---|
| 初始化模型工作区 | `CaseEditToolbox.setConfig()`、`setInitialConditions()` | `runtime._load_model()`；宿主会话字段 `session_state["memory_model"]` | `_load_model()` 只完成按 RID 获取并缓存 Model；`memory_model` 是会话缓存字段，不等同于参考代码的 `sa.project.revision` | 真实模型多轮查询和编辑成功 | 已实现基础加载；完整初始化流程待迁移，纳入首版 |
| 查询单个元件 | `getComponentByKey()`、`_resolve_comp_key()` | `inspect_model_from_context(identifier)`，支持 key、label、Name | 当前入口将参考代码的 key 解析逻辑封装为上下文查询；返回的是同类字段摘要 | 不存在对象、同名对象和指定 key 查询已测 | 已实现，纳入 |
| 按类型查询 | `getComponentsByRid()` | 无专用公开入口；只能通过全量查询后由 Agent 筛选 | 参考代码可按 definition RID筛选；当前没有等价的公开入口 | 全量查询曾产生约13万字符并截断 | 能力缺口，首版纳入专用入口 |
| 全量模型摘要 | `getAllComponents()` | `inspect_model_from_context()` 无 identifier 时返回所有非边元件 | 语义相近，但当前输出直接进入 Agent上下文，缺少分页/字段选择 | 已实际调用，但结果过大 | 保留为受限/分页能力 |
| 元件库模板读取 | `sa.compLib`、`saSource.json` | `_load_template()` 读取 `saSource.json` | 当前沿用参考组件库文件；返回模板 JSON，不是 `sa.compLib` 对象 | 21种模板均成功新增 | 已实现，纳入 |
| 模板清单和检索 | 参考代码的 `compLib` 字典键 | 无专用公开入口 | 数据文件存在，但 Agent不能稳定检索；曾猜测20多个不存在模板名 | 智能体曾猜测错误模板；debug后找到 `_newExpLoad_3p` | 关键缺口，首版必须纳入 |
| 模板参数 schema | 模板默认 `args`/`pins`；完整定义依赖 SDK 元数据 | 只返回模板默认 args/pins，无单位和枚举 schema | 当前字段结构与参考模板相近，但缺少定义说明；故障 `Init/chg/fct/ft` 语义无法确认 | 故障参数语义查询未完成 | 部分实现；首版纳入基础 schema，单位/枚举按证据返回 |
| 新增元件 | `addComp()`、`addCompInCanvas()` | `edit_model_from_context(operation="create")` | 当前入口把模板复制、key分配和内存写入封装为一次预览/确认操作；不是直接调用参考方法 | 21种模板均完成新增和回读 | 结构级已实现，纳入 |
| 新增时参数覆盖 | `addCompInCanvas(args=..., pins=..., label=...)` | `changes.args`、`changes.pins`、`changes.label` | 字段语义对应，但请求外形不同；Agent曾把参数放错位置 | 多个模板参数覆盖已成功 | 运行时可用，契约需加强，纳入 |
| 自动排布和位置管理 | `initCanvasPos()`、`addxPos()`、`newLinePos()` | 当前创建直接使用模板位置，无排布策略 | 当前结构写入不等于参考代码的画布布局行为 | 新增可回读，未验证布局 | 首版先保证结构；布局后续纳入 |
| 参数修改 | `updateCompArgs()` | `edit_model_from_context(operation="update")` | 当前入口通过 `changes.args`更新内存 Component.args；语义对应但调用层不同 | 常量、加法器、线路等修改已回读 | 已实现，纳入 |
| 引脚/接线修改 | 参考代码主要直接修改 `component.pins`，随后刷新拓扑 | `changes.pins` | 当前把低层 pins 修改封装为预览/确认；不是高层网络连接算法 | 电压表接 Bus12、信号链、负荷支路均回读成功 | 结构级已实现，纳入 |
| 断线/改接 | 参考代码支持低层 pins 修改；未形成专门断线接口 | 可将 pins 写为空或新节点，但无专用操作 | 语义对应但缺少断线校验 | 尚未系统验证 | 纳入改接；断线语义单独定义 |
| 删除元件 | 参考代码明确只有 `deleteEdges()`，未确认通用删元件接口 | 不支持 delete operation | `deleteEdges()` 只处理 diagram-edge，不是元件删除 | 未测试通用删除 | 首版不纳入，明确报告缺口 |
| 删除图形边并重建 pins | `deleteEdges()` | 未迁移 | 参考代码有完整边遍历和 pin重建；当前 Skill未暴露 | 未实现 | 拓扑迁移阶段再纳入 |
| 拓扑刷新 | `refreshTopology()` | `_refresh_topology()` 调用 `ModelRevision.create()`/`ModelTopology.fetch()` | 目标相同，但当前实现错误假设 `configs` 是 dict；真实模型是 list、`currentConfig` 是 int | 真实模型刷新失败 | 实现存在但需修复，首版必须修复 |
| 拓扑结果检查 | 参考代码可读取 `topo`、网络邻居 | 当前只返回拓扑结果摘要，无专用目标组件检查 | 当前能验证调用结果，不能确认目标组件已进入拓扑 | 接线主要依赖 pins回读 | 部分实现，纳入目标组件/连接检查 |
| 网络邻居/图分析 | `generateNetwork()`、`getNetworkNeighbor()`、`plotNetwork()` | 无对应公开入口 | 参考代码能力尚未迁移 | 未测试 | 暂不纳入首版 |
| 预览与确认 | 参考代码没有统一预览协议 | `pending_preview` 单槽、确认词执行 | 当前有统一预览，但会话管理方式不是参考代码能力 | 未确认不修改；大量操作已验证 | 纳入，改为带 preview ID |
| 串行批量新增/修改 | 参考代码可循环调用新增/修改 | Agent 串行调用单项 create/update | 当前批量是编排层行为，不是参考代码原子接口 | 3个常量批量新增和修改已通过 | 纳入并明确为串行批量 |
| 原子批量、失败回滚 | 参考代码无统一事务接口 | 不支持；单槽预览会覆盖 | 两者都没有现成等价能力 | 未验证回滚，已发现预览覆盖风险 | 首版明确不承诺；后续设计 |
| 云端保存新副本 | `saveProject(newID)` | 当前 Skill无公开 save入口 | 参考代码有保存方法；当前公开入口没有等价能力 | 未在当前 Skill中验证 | 是否纳入需确认；若纳入必须独立授权和回读 |
| 当前内存模型直接仿真 | 参考 `runProject()` 对当前 `project` 运行 | `cloudpss-aux-modeling` 无仿真入口；短路 Skill按RID重新加载 | 参考路径可能支持当前 Model运行；当前两个Skill之间尚未建立内存模型传递 | 已有云端模型EMT成功；辅助编辑后模型未衔接验证 | 后续单独设计和实测 |
| 仿真分析 | 参考 `runProject()`、`getRunnerLogs()`、结果读取 | 独立 `short-circuit-analysis` Skill | 两者都负责运行/结果，但入口、配置和分析口径不同 | IEEE39真实EMT任务完成并生成波形/指标 | 由独立Skill实现，不并入辅助建模核心 |
| 结果报告 | 参考 `saveResult()`、绘图方法 | 独立 `generate-simulation-report` Skill | 职责相邻但实现不同 | 尚未以本轮任务生成报告 | 不并入辅助建模核心 |

## 2. 当前已验证等级

| 等级 | 当前状态 |
|---|---|
| 模板识别 | 21种模板在已知 key 条件下通过；自然语言自主检索不稳定 |
| 结构新增 | 21种模板均有真实对话新增和回读证据 |
| 参数修改/查询 | 多数模板的选定参数通过；不是全部参数穷举 |
| 接线结构 | 电压表、信号链、母线—线路—负荷支路已通过 pins 回读 |
| 拓扑验证 | 当前被 `configs/context` 类型兼容问题阻断 |
| 串行批量 | 已通过；不是原子事务 |
| 既有模型仿真 | 短路 EMT 已通过 |
| 辅助建模修改后的模型仿真 | 尚未通过，也尚未建立正式传递路径 |

## 3. 与参考代码的边界

参考项目中的 `PSAToolbox`/`CaseEditToolbox` 是迁移依据，不是当前 Agent 的直接调用接口。当前 Agent 自动挂载的辅助建模 Skill 实际公开入口来自：

```python
from mylib import EditRequest, edit_model_from_context, inspect_model_from_context
```

`newagentv2.py` 通过自动发现 Skill 的 `__all__`，注册以 `_from_context` 或 `_from_source` 结尾的函数。当前 `cloudpss-aux-modeling` 实际暴露：

- `edit_model_from_context`
- `inspect_model_from_context`

这里的 `session_state["memory_model"]` 只是宿主会话中的缓存字段。阅读或迁移参考代码时，优先沿用 `sa.project`、`sa.project.revision`、`Component` 等参考概念，再把当前字段作为适配层实现细节处理。

短路分析和报告属于独立 Skill，不应被写成辅助建模 Skill 的内部依赖。

## 4. 首版建议纳入的最小闭环

首版先承诺以下闭环：

```text
初始化/复用模型
→ 检索模板和 schema
→ 查询目标元件
→ 生成 create/update 预览
→ 用户确认
→ 执行内存修改
→ 定向回读
→ 拓扑刷新和目标连接检查
→ 明确报告是否保存/仿真
```

首版暂不承诺：通用删除、原子批量回滚、完整网络分析、保存新副本、辅助建模结果自动进入仿真。它们应作为后续独立设计项，而不是隐含在“辅助建模已完成”中。

## 5. 证据文件

- `testing/runs/20260907-user-dialogue/TEST_REPORT.md`
- `testing/runs/20260907-user-dialogue/verification-matrix.json`
- `testing/runs/20260907-user-dialogue/SUMMARY.json`
- `testing/runs/20260907-user-dialogue/0701-result.json`
- `testing/runs/20260907-user-dialogue/0721-result.json`
- `results/short_circuit_analysis_result/283f8e6d-83ff-4ca0-8313-f67cc93ba765/task.json`

这些证据分别覆盖结构编辑、串行批量和已有模型 EMT，不代表辅助建模修改后的模型已经通过仿真。
