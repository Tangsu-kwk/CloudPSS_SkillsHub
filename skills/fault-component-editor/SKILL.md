---
name: fault-component-editor
description: 当用户明确要求对 CloudPSS 模型中的故障元件进行查询、新增、修改或删除，查询或修改故障发生时间（fs）、故障结束时间（fe）、故障类型（ft）、初始电阻（Init）、故障期间电阻（chg）、故障电流通道（I）或故障电压通道（V），配置故障电流/电压信号组件、EMT 输出通道、接地支路或故障连接关系，创建 faultresistor_3p 故障场景，验证修改后的当前内存模型能否完成真实 EMT 仿真，或保存修改后的模型副本时使用。该 Skill 默认操作当前会话中 Model.fetch/load 得到的内存模型，不自动保存或覆盖原始云端模型；只有用户明确要求时才保存为新的 CloudPSS 模型 RID。用户仅要求短路电流分析、短路容量计算、SCR/ESCR 分析或生成 HTML 仿真报告时不要使用。
---

# Fault Component Editor

## Deterministic entrypoint

对当前会话中的 CloudPSS 模型执行故障元件编辑操作时，使用本 Skill 提供的唯一正式入口：

```python
mylib.edit_model_from_context(request, session_state)
```

该入口负责：

1. 读取当前会话中的原始 RID、内存模型版本和已保存副本 RID；
2. 在需要时加载原始模型；
3. 查询故障元件、信号组件、接地支路、拓扑连接和 EMT 输出通道；
4. 将用户请求转换为结构化编辑请求；
5. 生成增删改预览；
6. 等待用户确认后修改内存模型；
7. 创建或清理关联通道、连接和接地支路；
8. 写出版本化模型快照；
9. 在用户明确要求时验证 EMT；
10. EMT 失败时回滚到最近一次成功版本；
11. 在用户明确要求时保存为新的 CloudPSS 模型 RID。

Agent 不得自行拆分上述步骤，也不得直接调用 CloudPSS SDK 替代正式入口。

## When to use

仅在以下场景使用：

- 查询活动故障元件；
- 查询故障参数；
- 新增 `faultresistor_3p` 故障元件；
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
2. 查询操作直接读取当前内存模型；没有内存模型时加载原始 RID。
3. 对新增、修改、删除和通道配置请求，先解析用户意图。
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
6. 等待用户明确确认，例如“确认执行”。
7. 用户确认后，在当前内存模型中执行批量修改。
8. 修改故障参数时，不强制检查通道完整性。
9. 配置通道时，不强制检查 `fs、fe、ft`。
10. 修改或新增故障电流通道时，确保每个故障拥有独立信号组件，并按当前模型 JSON 的正式字段保持一致：若模型使用 `Input` / `Channel Name`，二者必须一致；若模型使用其他字段，则只同步该模型实际存在且已确认的字段，并与故障元件 `args.I` / `args.V` 对应。
11. 新增故障时，仅支持 `faultresistor_3p`，并要求目标引脚无明确拓扑连接。
12. 删除故障时，预览并清理其专属连接、接地支路、信号组件和无用输出配置。
13. 如果关联对象归属无法确认，停止级联删除，并允许用户授权“仅删除故障元件”。
14. 写出版本化模型快照。
15. 只有用户明确要求“验证仿真”时，才使用当前内存模型执行 EMT。
16. EMT 成功后，将当前版本标记为最近一次成功版本。
17. EMT 失败后，保留失败快照和错误信息，并回滚到最近一次成功版本；如果没有成功版本，则回滚到原始版本。
18. 失败记录:只读取当前会话最近三次的失败记录，并可读取对应模型快照及原始版本快照。
19. 只有用户明确要求保存时，才保存新的云端副本。
20. 保存时禁止覆盖原始 RID，只要求用户提供新的模型名。
21. 保存后维护原始 RID、内存版本和新副本 RID。
22. 后续分析前询问用户选择当前内存版本还是新保存的副本。

## Agent execution contract

- 用户只提供 RID 时，可以自动执行查询。
- 用户明确要求增删改或通道配置时，必须先生成预览。
- 任何增删改操作必须等待用户再次确认。
- 允许用户一次确认并执行一批相关修改。
- 未经确认不得修改内存模型。
- 默认只修改内存中的 CloudPSS 模型对象。
- 不得自动保存、覆盖或替换原始云端模型。
- 保存必须使用新的模型名生成新的 RID。
- 新增故障只允许使用 `faultresistor_3p`。
- 新增目标引脚必须明确为空闲；无法判断时停止并请求确认。
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

- `query`：返回当前模型版本、活动故障元件、故障参数、目标引脚、接地关系、关联信号组件和 EMT 输出通道。
- `update`、`create`、`delete`、`configure_channel`：返回变更预览、用户确认状态、实际变更字段、版本化快照标识和当前内存版本。
- `verify_emt`：返回 EMT 验证成功或失败、对应版本、真实仿真任务信息（如 SDK 提供）以及失败时的错误信息和回滚版本；不返回短路分析指标。
- `save_copy`：返回新保存的 CloudPSS 模型 RID，并保留原始 RID、当前内存版本和新副本 RID 的对应关系。

不得把本地快照路径、时间戳或普通字符串伪造成 CloudPSS 模型 RID 或 EMT `task_id`。失败时返回安全错误信息，不伪造成功结果。

## Standards and references basis

- CloudPSS SDK 的 `Model.fetch/load`、模型 `toJSON()`、`getAllComponents()` 和模型保存接口是模型读取、内存编辑和副本保存的依据。
- CloudPSS 模型 JSON 中的正式组件字段、`args`、`props`、`diagram-edge`、组件连接关系、信号组件字段和 EMT `output_channels` 结构优先于参考代码中的推测。
- `faultresistor_3p` 是第一版唯一支持新增的故障元件类型。
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
- 增删改和通道配置必须先展示预览，并等待用户再次明确确认；允许一次确认执行一批相关修改。
- 默认只修改当前会话中的内存模型，不自动保存、覆盖或替换原始云端 RID。
- 保存只能创建新的 CloudPSS 模型副本，禁止覆盖原始 RID；保存后的新 RID 必须由 SDK 返回并原样保留。
- 用户只修改 `fs`、`fe`、`ft`、`Init`、`chg`、`I`、`V` 时，不强制检查其他通道或故障时序；配置通道时，也不强制检查故障时序和故障类型。
- 默认只自动创建故障电流信号组件；故障电压信号组件必须由用户明确要求创建或配置。
- 每个故障元件独占自己的电流/电压信号组件；内部名称须包含故障标识。`args.Name` 含中文或特殊字符时，内部名称使用组件 ID，展示名称保留 `args.Name`。
- 新增故障只支持 `faultresistor_3p`，目标引脚必须明确为空闲；没有明确拓扑连接时才视为空闲，无法判断时停止并请求确认。
- 删除时必须预览级联删除对象。无法确认关联对象是否专属于目标故障时，不得猜测删除；用户可以明确授权仅删除故障元件。
- 删除后若没有活动故障，必须提示后续短路分析无法执行。
- EMT 验证失败时必须保留失败快照和错误信息，并回滚到最近一次 EMT 成功版本；如果没有成功版本，则回滚到原始版本。
- 失败分析只读取当前会话最近三次 EMT 失败记录及其快照，不读取其他会话历史；允许读取原始版本快照和相关模型信息用于迭代。
- 不执行短路电流指标计算、Thevenin、SCR/ESCR 分析或 HTML 报告生成；这些职责属于其他 Skill。
- 不搜索本地目录寻找模型或 Skill，不更换用户提供的原始 RID，不读取、打印、保存或询问 Token、API Key、Cookie 或环境变量值。
