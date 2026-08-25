---
name: fault-component-editor
description: 当用户明确要求对 CloudPSS 模型中的故障元件进行查询、新增、修改或删除，查询或修改故障发生时间（fs）、故障结束时间（fe）、故障类型（ft）、初始电阻（Init）、故障期间电阻（chg）、故障电流通道（I）或故障电压通道（V），配置故障电流/电压信号组件、EMT 输出通道、接地支路或故障连接关系，创建故障场景，验证修改后的当前内存模型能否完成真实 EMT 仿真，或保存修改后的模型副本时使用。该 Skill 默认操作当前会话中 Model.fetch/load 得到的内存模型，不自动保存或覆盖原始云端模型；只有用户明确要求时才保存为新的 CloudPSS 模型 RID。用户仅要求短路电流分析、短路容量计算、Thevenin、SCR/ESCR 分析或生成 HTML 仿真报告时不要使用。
license: Internal Use Only
compatibility:
  python: ">=3.11"
  requires_env: true
  required_env_vars:
    - SIMSTUDIO_TOKEN
  notes: SimBot provides CloudPSS credentials; CLOUDPSS_TOKEN and CLOUDPSS_LOGIN_TOKEN are supported aliases.
metadata:
  owner: cloudpss-team
  category: workflow
  visibility: internal
  maturity: validated
  entrypoint: scripts/verify_runtime.py
  dependency_strategy: bundled-mylib
  shared_packages: []
  verification_method: offline_runtime_contract_with_optional_real_cloudpss_emt
---

# Fault Component Editor

## Deterministic entrypoints

查询和单进程内存编辑保留兼容入口：

```python
mylib.edit_model_from_context(request, session_state)
```

凡是编辑后需要跨轮提供新 RID 或保存云端副本，使用可序列化计划入口：

```python
plan = mylib.preview_edit_plan_from_source(source, operations)
mylib.execute_edit_plan_from_source(plan, target_rid)
```

`plan` 是普通 JSON，不包含 SDK `Model` 对象。预览和正式执行可以位于两个独立 Python 进程；不得把 `current_version`、`status="changed"` 或对话中记住的组件信息当作仍有可保存内存模型的证明。

该入口负责：

1. 读取当前会话中的原始 RID、内存模型版本和已保存副本 RID；
2. 在需要时加载原始模型；
3. 精简查询故障元件、信号组件引用、接地支路、拓扑连接和关联 EMT 输出项；
4. 将用户请求转换为结构化编辑请求；
5. 生成增删改预览；
6. 等待用户确认后，在一个工作模型中执行整批修改；
7. 创建或安全清理专属通道、连接和接地支路；
8. 写出版本化模型快照；
9. 在用户明确要求时验证 EMT；
10. EMT 失败时回滚到最近一次成功版本；
11. 在用户明确要求时保存为新的 CloudPSS 模型 RID，并回读该 RID 验收用户要求的事实。

Agent 不得把一组连续编辑和保存拆成多个自行维护 `memory_model` 的 `python -c` 进程，也不得直接调用 CloudPSS SDK 替代正式入口。

## When to use

仅在以下场景使用：

- 查询活动故障元件；
- 查询故障参数；
- 新增当前 Skill 支持的故障元件；
- 修改故障参数：
  - `fs`：故障发生时间；
  - `fe`：故障结束时间；
  - `ft`：故障类型；
  - `Init`：初始电阻；
  - `chg`：故障期间电阻；
  - `I`：故障电流通道；
  - `V`：故障电压通道；
- 删除故障元件；
- 配置故障电流信号通道；
- 用户明确要求时配置故障电压信号通道；
- 配置或检查 EMT 输出通道；
- 创建目标引脚、接地支路和信号组件；
- 验证当前内存模型能否完成 EMT 仿真；
- 将修改后的模型保存为新的云端副本。

以下情况不要使用：

- 用户只要求短路电流分析；
- 用户只要求短路容量、SCR、ESCR 或 Thevenin 计算；
- 用户只要求生成 HTML 仿真报告；
- 用户没有明确要求增删改，只是在询问分析结果。

## Input contract

正式入口接收结构化编辑请求：

```python
edit_model_from_context(
    request={
        "operation": "query | update | create | delete | configure_channel | verify_emt | save_copy",
        "target": {...},
        "changes": {...},
        "confirmation": "execute",
        "options": {...},
    },
    session_state={...},
)
```

### `session_state`

由当前会话维护：

```json
{
  "original_rid": "model/<owner>/<model-key>",
  "memory_model": "<当前内存模型对象>",
  "current_version": "v001_F1_fs",
  "last_successful_emt_version": "v001_F1_fs",
  "saved_copy_rid": null,
  "recent_emt_failures": []
}
```

必须区分：

- 原始云端 RID；
- 当前内存修改版本；
- 最近一次 EMT 成功版本；
- 新保存的云端副本 RID。

`session_state` 仅用于兼容同一 Python 进程中的查询、内存编辑和 EMT 验证。若用户下一轮才确认或提供新 RID，不得依赖其中的活 `memory_model`；使用上述 JSON 编辑计划入口。

### `operation`

允许的操作：

```text
query
update
create
delete
configure_channel
verify_emt
save_copy
```

### 参数字段

支持的故障参数：

```text
fs
fe
ft
Init
chg
I
V
```

用户可以使用中文自然语言表达，例如：

```text
1 秒发生故障，2 秒结束，ABC 三相短路
```

入口必须转换为模型实际字段：

```json
{
  "fs": "1",
  "fe": "2",
  "ft": "7"
}
```

`ft` 映射（仅当当前 CloudPSS 组件定义确认采用该枚举时）：

```text
0：无故障
1：A 相
2：B 相
3：AB 两相
4：C 相
5：AC 两相
6：BC 两相
7：ABC 三相
```

仅当 CloudPSS SDK/模型定义确认采用该映射时才使用。

### 通道默认值

默认故障电流通道：

```text
内部 Input：<故障标识>_fault_current_channel
内部 Channel Name：<故障标识>_fault_current_channel
EMT 输出名称：故障电流通道
```

默认不创建故障电压通道。只有用户明确要求配置 `V` 时，才创建：

```text
内部 Input：<故障标识>_fault_voltage_channel
内部 Channel Name：<故障标识>_fault_voltage_channel
EMT 输出名称：故障电压通道
```

如果 `args.Name` 含中文或特殊字符，则内部名称使用组件 ID；展示名称仍使用 `args.Name`。

## Workflow

1. 读取当前会话上下文和原始 RID。
2. 查询操作直接读取当前内存模型；没有内存模型时加载原始 RID。默认只返回故障参数、关联组件 ID、通道引用和连接摘要，不返回完整 `cells`、原始边对象、全局输出配置，也不查询电流单位。电流单位与 `kA` 换算由 `short-circuit-analysis` 负责。
3. 对新增、修改、删除和通道配置请求，先解析用户意图。
   如果同一请求包含多个编辑操作，按照用户明确给出的先后顺序执行，不得将“先删除、再新增”改写为“移动”或“替换”。
4. 生成变更预览，不立即修改模型。
5. 预览至少列出：
   - 原值和新值；
   - 目标故障元件；
   - 关联信号组件；
   - `diagram-edge`；
   - 接地支路；
   - EMT 输出通道；
   - 将自动创建或删除的对象；
   - 当前活动故障数量变化。
6. 返回可序列化计划并等待用户明确确认，例如“确认执行”。用户在原请求中已经明确要求编辑并保存到新的 RID 时，可将该明确请求视为对整批操作的授权，不额外制造确认轮次。
7. 用户确认或已明确授权后，正式入口重新加载原 RID、校验预览时的源模型指纹，并在一个工作模型中按原顺序重放整批操作。源模型变化时返回 `preview_stale`，不保存。
8. 修改故障参数时，不强制检查通道完整性。
9. 配置通道时，不强制检查 `fs、fe、ft`。
10. 修改或新增故障电流通道时，确保每个故障拥有独立信号组件，并按当前模型 JSON 的正式字段保持一致：若模型使用 `Input` / `Channel Name`，二者必须一致；若模型使用其他字段，则只同步该模型实际存在且已确认的字段，并与故障元件 `args.I` / `args.V` 对应。
11. 新增故障时，使用当前 Skill 支持的组件类型；当前版本已验证的类型为 `faultresistor_3p`。故障显示名称可以由用户指定，未指定时由 Skill 生成。普通设备目标引脚必须空闲；`*_newBus_3p` 等明确的三相母线/汇流节点允许在已有端口追加并联故障支路。目标连接是否合法，应根据目标对象类型和当前模型拓扑判断。
12. 删除故障时，先基于 `diagram-edge`、组件定义、故障 `args.I/V`、信号引用和 EMT 输出引用生成删除计划；确认后事务式清理专属连接、接地支路、信号组件和无用输出引用。
13. `pins` 为空但正式 `diagram-edge` 足以确定关系时不得阻止删除。共享 GND、信号组件或混合输出项必须保留：混合输出项只移除目标组件 ID。关联对象归属仍无法确认时，停止级联删除，并允许用户授权“仅删除故障元件”。
14. 写出版本化模型快照。
15. 只有用户明确要求“验证仿真”时，才使用当前内存模型执行 EMT。
16. EMT 成功后，将当前版本标记为最近一次成功版本。
17. EMT 失败后，保留失败快照和错误信息，并回滚到最近一次成功版本；如果没有成功版本，则回滚到原始版本。
18. 失败记录:只读取当前会话最近三次的失败记录，并可读取对应模型快照及原始版本快照。
19. 只有用户明确要求保存时，才保存新的云端副本。
20. 保存时禁止覆盖原始 RID；目标可以是同 owner 的完整新 RID 或新模型名。
21. 保存后必须重新读取 SDK 返回的新 RID，核对计划所涉及的故障存在或删除、参数、目标连接、接地、信号组件和 EMT 输出引用。只有事实一致才返回 `verified_saved`；API 返回成功但回读不一致时返回 `save_verification_failed`。
22. 后续短路分析只使用已回读验证的新云端 RID，不使用会话内存模型。

## Agent execution contract

- 调用 CloudPSS 正式入口前，在命令中显式引用宿主提供的 `CLOUDPSS_LOGIN_TOKEN`、`CLOUDPSS_TOKEN` 或 `SIMSTUDIO_TOKEN`，优先使用第一个非空值，并仅在当前进程中将其作为 `CLOUDPSS_TOKEN` 提供给 CloudPSS SDK。不得读取、打印、保存或向用户索取 Token。
- 用户只提供 RID 时，可以自动执行查询。
- 用户明确要求增删改或通道配置时，必须先生成预览。
- 用户尚未在同一请求中明确给出完整操作及新 RID 时，增删改必须等待确认；完整请求本身可作为一次批量授权。
- 允许用户一次确认并执行一批相关修改；整批操作必须由 `execute_edit_plan_from_source` 在同一工作模型中完成。
- 未经用户明确授权不得修改或保存模型。
- 默认只修改内存中的 CloudPSS 模型对象。
- 不得自动保存、覆盖或替换原始云端模型。
- 保存必须使用新的模型名生成新的 RID。
- 新增故障必须使用当前 Skill 正式入口支持的组件类型；当前版本已验证的类型为 `faultresistor_3p`。
- 故障元件显示名称可以由用户指定，内部组件 ID 由 Skill 管理。
- 目标连接保留现有 `diagram-edge`；新增故障时显式创建目标端口到故障端口、故障接地端口到 GND 端口的两条 `diagram-edge`。Pin 字段仅作为组件兼容信息，不得删除或替换原有拓扑边；不得因母线已有输电线连接拒绝新增并联故障支路。
- 每个故障元件独占故障电流和故障电压信号组件；默认只创建电流信号组件。
- 信号组件的正式输入字段和通道名称字段（若存在）必须完全一致；不得假设所有模型都使用 `Input` / `Channel Name`。
- EMT `output_channels` 可以使用中文业务名称，不要求与内部通道名称相同。
- 修改故障参数时，不强制验证通道。
- 配置通道时，不强制验证故障时间和故障类型。
- 删除关联对象归属不明确时，不得猜测删除。
- 删除后没有活动故障时，必须提示后续短路分析无法执行。
- EMT 验证失败时必须保留失败信息和模型快照，并回滚内存模型。
- 不得伪造仿真成功、`task_id`、模型 RID 或快照内容。
- 不得自动调用 `short-circuit-analysis` 进行短路指标计算。
- 不得自动调用 `generate-simulation-report`。
- 只有用户明确要求验证 EMT 时，才执行仿真验证。
- 只有用户明确要求保存时，才执行云端保存。
- 如果正式入口失败，立即停止当前操作，不更换 RID、不搜索其他模型、不读取其他会话历史。

## Agent output

根据操作类型返回结构化结果：

- `query`：返回当前模型版本、活动故障元件、故障参数、关联组件 ID、通道引用和连接摘要；默认不返回完整模型结构或电流单位。
- `update`、`create`、`delete`、`configure_channel`：返回变更预览、用户确认状态、实际变更字段、版本化快照标识和当前内存版本。
- `verify_emt`：返回 EMT 验证成功或失败、对应版本、真实仿真任务信息（如 SDK 提供）以及失败时的错误信息和回滚版本；不返回短路分析指标。
- `execute_edit_plan_from_source`：返回 `verified_saved`、`saved_with_warnings`、`preview_stale`、`operation_failed` 或 `save_verification_failed`。只有 `verified_saved` 表示云端副本已通过关键事实回读验收；`saved_with_warnings` 仅用于不影响用户要求的非关键差异。
- 兼容 `save_copy`：仅允许同一进程中确实存在 `memory_model` 时使用，并执行故障状态回读；跨进程保存必须使用编辑计划入口。

不得把本地快照路径、时间戳或普通字符串伪造成 CloudPSS 模型 RID 或 EMT `task_id`。失败时返回安全错误信息，不伪造成功结果。

## Standards and references basis

- CloudPSS SDK 的 `Model.fetch/load`、模型 `toJSON()`、`getAllComponents()` 和模型保存接口是模型读取、内存编辑和副本保存的依据。
- CloudPSS 模型 JSON 中的正式组件字段、`args`、`props`、`diagram-edge`、组件连接关系、信号组件字段和 EMT `output_channels` 结构优先于参考代码中的推测。
- 当前版本已验证的新增故障元件类型为 `faultresistor_3p`；新增类型是否支持，以正式入口实际能力为准。
- `fs`、`fe`、`ft`、`Init`、`chg`、`I`、`V` 的含义以 CloudPSS 当前模型定义和 SDK 结构为准；自然语言输入必须转换为模型实际字段。
- `ft` 的 0–7 映射只有在当前 SDK/模型定义确认一致时才可使用：0 无故障，1 A 相，2 B 相，3 AB 两相，4 C 相，5 AC 两相，6 BC 两相，7 ABC 三相。
- 信号组件的正式输入字段和通道名称字段（若存在）必须完全一致；EMT `output_channels` 可以使用中文业务名称，不要求与内部通道名称相同。
- `CaseEditToolbox.py` 和 `PSAToolbox.py` 仅作为行为参考，不得整体复制其中与本 Skill 无关的 MinIO、Plotly、潮流展示、网络绘图、N-1、频率测量或批量测量功能。


## Internal result

Skill 内部应维护当前会话的版本化模型状态和审计信息，但不把所有内部文件作为对外接口：

- `model_parameters_v000_original.json`：首次加载的原始模型快照；
- `model_parameters_v###_<component>_<field>.json`：参数或通道修改后的模型快照；
- `model_parameters_v###_<component>_created.json`：新增故障及其关联对象快照；
- `model_parameters_v###_<component>_deleted.json`：删除故障及级联清理后的模型快照；
- `emt_verification_v###.json`：EMT 验证状态、版本、任务信息和错误摘要；
- `emt_failure_v###.json`：失败版本快照索引、失败阶段和安全错误信息；
- `session_state.json`：原始 RID、当前内存版本、最近一次 EMT 成功版本、新保存副本 RID 和最近三次失败记录的索引。

内部快照必须记录：

- 模型 RID 或版本来源；
- 故障元件 ID、展示名称和定义；
- `fs`、`fe`、`ft`、`Init`、`chg`、`I`、`V`；
- 目标引脚、`diagram-edge` 和接地支路关系；
- 关联信号组件的内部名称、`Input`、`Channel Name`；
- EMT `output_channels` 的原始结构；
- 本次变更、前一版本、验证结果和回滚目标。

内部结果用于验证、回滚和后续迭代，不得被 Agent 当作短路分析结果、报告内容、模型 RID 或 EMT `task_id` 的替代品。


## Constraints

- 只有用户明确提出增删改、通道配置、EMT 验证或保存副本时，才执行对应操作。
- 增删改和通道配置必须先生成预览；用户已在同一请求中明确给出操作及新 RID 时无需重复确认，否则等待用户确认。允许一次确认执行一批相关修改。
- 默认只修改当前会话中的内存模型，不自动保存、覆盖或替换原始云端 RID。
- 保存只能写入不同于原始 RID 的 CloudPSS 模型副本；保存后的新 RID 必须由 SDK 返回并原样保留，并通过回读验收。
- 连续编辑是一个事务：任一操作失败时不得调用保存；不得跨进程依赖活 `memory_model`。重复执行同一计划不得重复叠加新增故障。
- 用户只修改 `fs`、`fe`、`ft`、`Init`、`chg`、`I`、`V` 时，不强制检查其他通道或故障时序；配置通道时，也不强制检查故障时序和故障类型。
- 本 Skill 不查询或换算故障电流单位；该职责属于 `short-circuit-analysis`，普通编辑不得因此触发 GraphQL。
- 默认只自动创建故障电流信号组件；故障电压信号组件必须由用户明确要求创建或配置。
- 每个故障元件独占自己的电流/电压信号组件；内部名称须包含故障标识。`args.Name` 含中文或特殊字符时，内部名称使用组件 ID，展示名称保留 `args.Name`。
- 新增故障使用当前 Skill 支持的组件类型；当前版本已验证的类型为 `faultresistor_3p`。目标连接合法性按目标对象类型和当前拓扑判断，不得仅因母线已有正常支路连接就拒绝新增。
- 删除时必须预览级联删除对象，在模型副本中执行并校验无悬空引用后才提交。共享对象必须保留并返回原因；无法确认关联对象是否专属于目标故障时，不得猜测删除，用户可以明确授权仅删除故障元件。
- 删除后若没有活动故障，必须提示后续短路分析无法执行。
- EMT 验证失败时必须保留失败快照和错误信息，并回滚到最近一次 EMT 成功版本；如果没有成功版本，则回滚到原始版本。
- 失败分析只读取当前会话最近三次 EMT 失败记录及其快照，不读取其他会话历史；允许读取原始版本快照和相关模型信息用于迭代。
- 不执行短路电流指标计算、Thevenin、SCR/ESCR 分析或 HTML 报告生成；这些职责属于其他 Skill。
- 不搜索本地目录寻找模型或 Skill，不更换用户提供的原始 RID，不读取、打印、保存或询问 Token、API Key、Cookie 或环境变量值。
