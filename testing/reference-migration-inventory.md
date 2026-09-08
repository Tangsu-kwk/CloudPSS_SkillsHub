# 辅助建模参考代码迁移清单

> 2026-09-08 更新：本文保留第一步迁移前清单。第二步已迁入核心方法，第三步正在统一交互契约；当前方法签名及尚未迁移的边界以 `skills/cloudpss-aux-modeling/references/api-contracts.md` 为准。

本文档是第一步的盘点结果。它以 `FuZhuJM2/CaseEditToolbox.py`、`FuZhuJM2/PSAToolbox.py` 和 `FuZhuJM2/demo_N-1.py` 为主要依据，暂不修改运行时代码。

## 1. 参考代码的实际使用链

同事的 N-1 示例使用方式是：

```text
PSAToolbox()
→ setConfig(token, apiURL, username, model)
→ setInitialConditions()
→ 按 RID/label 查询线路
→ setN_1_GroundFault(...)
→ createOrUpdateJob(...)
→ createOrUpdateConfig(...)
→ addVoltageMeasures(...)
→ runProject(...)
→ 读取 runner.result
```

其中 `PSAToolbox` 继承 `CaseEditToolbox`。因此迁移不能只复制几个孤立的 `create/update` 函数，必须保留工作区、组件库、画布、拓扑和对象解析之间的关系。

## 2. 方法分类与目标归属

| 类别 | 参考方法 | 迁移到辅助建模 Skill | 说明 |
|---|---|---:|---|
| 工作区初始化 | `setConfig`、`setInitialConditions`、`getRevision`、`loadRevision` | 是 | 建立 CloudPSS 项目、revision、组件库和画布状态；必须保留原方法语义 |
| 标识与查询 | `getComponentByKey`、`getComponentsByRid`、`getAllComponents`、`_resolve_comp_key`、`_resolve_comp_keys`、`convertLabelToKey`、`screenCompByArg` | 是 | 支撑用户按 label、key、RID、参数查询；需要结构化 JSON 适配入口 |
| 组件基础增删改 | `addComp`、`addCompInCanvas`、`updateCompArgs` | 是 | 核心元件新增与参数修改；删除需单独确认通用接口 |
| 画布与布局 | `createCanvas`、`initCanvasPos`、`addxPos`、`newLinePos` | 是，分阶段 | 先保证结构写入，再迁移自动排布；不能把模板默认坐标误称为布局完成 |
| 拓扑与连接 | `refreshTopology`、`getEdgeTopoPinNum`、`deleteEdges` | 是 | 接线、边转换和拓扑检查属于辅助建模核心；当前运行时的 configs 类型问题需修复 |
| 网络分析辅助 | `generateNetwork`、`getNetworkNeighbor`、`plotNetwork` | 后续 | 属于建模后的网络检查/可视化，不是首版 CRUD 闭环必需 |
| 故障元件建模 | `setGroundFault`、`setBreaker_3p`、`setCutFault` | 是，作为建模操作 | 这些方法创建或修改故障相关元件；不负责执行短路分析 |
| N-1 建模 | `setN_1`、`batchSetCutFault`、`setN_1_GroundFault`、`setN_2_GroundFault`、`setN_k_GroundFault` | 后续阶段 | 属于辅助建模中的场景构造能力；N-1仿真执行仍由其他流程负责 |
| 输出通道与量测配置 | `addChannel`、`addVoltageMeasures`、`addBusFrequencyMonitors`、`addComponentOutputMeasures`、`addComponentPinOutputMeasures` | 是，按建模范围纳入 | 这些方法修改模型中的通道/量测元件或配置；结果读取留给报告/分析Skill |
| 控制/派生组件 | `addComponentOutputMeasures_relative` 及内部 `_addPLLComponent`、`_addDeMergeComponent` 等 | 后续 | 依赖具体输出量测需求，先保留原方法名和调用关系，不在首版强行展开 |
| 任务配置 | `initJobConfig`、`createOrUpdateJob`、`createOrUpdateConfig`、`addOutputs` | 暂不并入核心 | 它们服务于仿真任务配置；是否单独形成仿真配置Skill需另行设计 |
| 仿真执行 | `runProject`、`getRunnerLogs`、`checkSimulationStatus` | 不并入辅助建模核心 | 用户可以在后续把保存后的 RID交给短路/仿真Skill；本Skill只保留必要的模型配置能力 |
| 结果读取与展示 | `saveResult`、`plotResult`、`displayPFResult`、`show_table_plotly` | 不并入辅助建模核心 | 属于仿真结果或报告职责 |
| 云端持久化 | `saveProject` | 是，但必须确认 | 用户明确确认后执行；默认保存为新 RID，不覆盖原 RID；成功后回读新 RID |
| 网络/平台工具 | `setCompLabelDict`、`setChannelPinDict`、`getCurrentConfig`、`getCurrentJob`、`powerFlowModifyByID` | 分别处理 | 前三项是工作区支持方法；后者属于计算配置/仿真流程，暂不作为首版核心入口 |

## 3. Skill 内部保留的命名原则

迁移后的 Skill 内部应优先保留参考方法名和语义：

```text
setConfig
setInitialConditions
getComponentByKey
getComponentsByRid
addComp
addCompInCanvas
updateCompArgs
refreshTopology
deleteEdges
createCanvas
saveProject
```

面向 Agent 的入口可以另外增加结构化包装，但包装层不能替代这些方法成为唯一领域概念。例如：

```text
Agent 入口：preview_edit / execute_edit
内部调用：addCompInCanvas / updateCompArgs / refreshTopology
```

`memory_model` 只能作为宿主会话缓存字段，不应替代 `sa.project` 或 `sa.project.revision` 成为迁移文档中的领域名称。

## 4. 与当前 Skill 原型的差异

当前 `cloudpss-aux-modeling/mylib/runtime.py` 只提供：

```text
query / create / update / refresh_topology
```

它尚未等价迁移：

- `setConfig` 与 `setInitialConditions` 的完整组件库/画布/拓扑初始化流程；
- `getComponentsByRid`、`screenCompByArg` 等专用查询；
- `addCompInCanvas` 的位置递进和自动排布；
- `deleteEdges` 的图形边到 pins 转换；
- `saveProject` 的确认、新 RID 保存和云端回读；
- `setGroundFault`、`setN_1_GroundFault` 等高层场景构造方法。

因此当前原型的真实定位是“可运行的结构编辑试验入口”，不是完整迁移后的 SDK Skill。

## 5. 第一阶段迁移顺序

```text
CaseEditToolbox 基础状态和初始化
→ 查询与标识解析
→ addComp / addCompInCanvas / updateCompArgs
→ createCanvas / 画布位置
→ refreshTopology / deleteEdges
→ saveProject（新 RID、确认、回读）
→ PSAToolbox 的故障与量测建模方法
```

仿真任务执行、波形读取、短路分析和报告继续由其他 Skill负责。辅助建模Skill完成保存后，只需返回可追踪的新模型 RID。

## 6. 证据来源

- `D:/VScodeProjects/FuZhuJM2/CaseEditToolbox.py`
- `D:/VScodeProjects/FuZhuJM2/PSAToolbox.py`
- `D:/VScodeProjects/FuZhuJM2/demo_N-1.py`
- `D:/VScodeProjects/FuZhuJM2/validate_component_templates_batch2.py`
- `D:/VScodeProjects/FuZhuJM2/validate_component_templates_batch4.py`
- `D:/VScodeProjects/SCAgent2/skills/cloudpss-aux-modeling/mylib/runtime.py`
