# Channel and Topology Rules

## Purpose

定义 `fault-component-editor` 创建、修改和删除故障元件时使用的通道、拓扑、接地和级联清理规则。

本文件处理：

- 故障元件 `I`、`V` 与信号组件的关系；
- 信号组件实际输入/名称字段和 EMT 输出名称；
- `diagram-edge`、目标引脚与接地支路；
- 新增故障的关联对象；
- 删除故障的级联对象和不确定归属处理；
- 变更预览。

参数中文含义和参数级校验见 `fault-parameter-mapping.md`；模型 JSON 字段位置和未确认 SDK 字段见 `cloudpss-model-structure.md`。

## Channel ownership

每个故障元件必须独占自己的故障信号组件。第一版不共享电流或电压信号组件。

故障标识优先使用组件 ID。即使 `args.Name` 是英文，也不要仅凭显示名称生成可执行内部通道名；组件 ID 才是稳定的唯一标识。

内部名称规则：

```text
<fault-component-id>_fault_current_channel
<fault-component-id>_fault_voltage_channel
```

例如故障组件 ID 为 `fault-1`：

```text
fault-1_fault_current_channel
fault-1_fault_voltage_channel
```

如果当前 CloudPSS 组件或表达式不接受连字符，必须在不改变唯一性的前提下将组件 ID 规范化为 SDK 允许字符；规范化规则和最终名称必须写入变更预览和快照。

## Fault current channel

默认只自动创建故障电流信号组件。

故障元件 `args.I`、电流信号组件的正式输入字段和正式名称字段必须表示同一个内部信号：

```text
fault.args.I              = #<fault-id>_fault_current_channel
signal.<actual-input-field> = #<fault-id>_fault_current_channel
signal.<actual-name-field>  = #<fault-id>_fault_current_channel
```

写入时必须以当前 SDK/模型中 `I`、`Input`、`Channel Name` 的正式字段格式为准。若模型字段不使用 `#` 前缀，必须保留模型原有格式，不得强行添加或移除前缀。

默认 EMT 业务展示名称为：

```text
故障电流通道
```

业务展示名称可以是中文，且不要求与内部名称相同。

### Existing current channel

当用户修改 `I` 或要求配置故障电流通道时：

1. 从故障元件 `args.I` 读取当前内部引用；
2. 通过当前模型正式的信号组件字段和连接关系定位对应信号组件；
3. 按模型正式字段验证信号组件关系：若存在输入字段和名称字段，二者必须一致；字段位置和 source-wrapper 必须从当前模型 JSON 读取；
4. 若两者不一致，将修复动作加入变更预览；
5. 用户确认后，同步更新故障元件引用和专属信号组件；
6. 若找不到专属信号组件，在预览中列出自动创建动作；用户确认后创建默认电流信号组件。

不得基于字符串包含 `I`、`IT`、`current` 或其他模糊名称去选择发电机、线路或支路电流通道。

## Fault voltage channel

默认不创建故障电压信号组件。

只有用户明确请求配置或创建故障电压通道时，才创建或更新：

```text
fault.args.V              = #<fault-id>_fault_voltage_channel
signal.args.Input         = #<fault-id>_fault_voltage_channel
signal.args.Channel Name  = #<fault-id>_fault_voltage_channel
EMT business output name  = 故障电压通道
```

与电流通道相同，实际前缀和正式字段格式必须沿用当前 CloudPSS 模型。

## EMT output channels

EMT 输出通道通常位于：

```text
jobs[*].args.output_channels
```

该配置与信号组件内部通道名相关，但不要求字符串完全一致：

```text
内部输入/名称字段：fault-1_fault_current_channel（字段名以当前模型 JSON 为准）
EMT 输出展示名称：故障电流通道
```

操作规则：

- 保留当前 `output_channels` 的原始列表结构和未知字段；
- 只修改已经通过当前 SDK 或真实模型确认的条目和字段；
- 不把中文业务展示名称强制改成英文内部名称；
- 不因配置输出通道而检查 `fs`、`fe` 或 `ft`；
- 不因修改故障参数而强制检查输出通道；
- 不扫描并借用其他发电机、线路或支路通道作为故障通道。

在确认 `output_channels` 的条目结构、关联组件方式和采样配置前，不得新增、删除、重排或推测其字段。

## Topology connections

正式拓扑连接必须通过 `diagram-edge` 及其正式端点字段解析。

解析时至少记录：

```text
edge id
source component id
source port or pin, if present
target component id
target port or pin, if present
```

不得用组件标签、显示位置或通道名称推断导线连接。

## Target pin rule

第一版新增 `faultresistor_3p` 时，只允许连接到一个明确空闲的目标引脚。

目标引脚必须同时满足：

1. 目标组件、引脚名称和引脚方向可以从正式模型对象确认；
2. 没有任何正式 `diagram-edge` 连接到该引脚；
3. 没有现有故障、接地支路或其他设备占用该引脚；
4. 连接该引脚不会要求 Skill 自动拆分线路、重连已有设备或创建未知中间拓扑。

若任一条件无法确认，停止新增并说明缺少的拓扑信息。不得认为“可能仍可并联”就是空闲，也不得擅自在已有连接上增加分支。

## Ground branch

第一版新增故障时，默认创建直接接地支路：

```text
target pin -> faultresistor_3p pin +
faultresistor_3p pin - -> GND
```

必须通过当前 CloudPSS 模型的正式组件 definition、pins 和 `diagram-edge` 格式创建接地关系。

接地电感、中间节点、自动线路拆分、线路中点故障或 N-1/N-k 逻辑不属于第一版；用户提出这些需求时，停止并说明当前 Skill 不支持该建模方式。

## Create operation

新增故障前必须收集：

- 故障元件显示名称；
- 目标组件和目标引脚；
- `fs`、`fe`、`ft`、`Init`、`chg`；
- 是否明确要求创建故障电压通道；
- 用户明确提供的电流或电压通道业务名称（如有）。

若用户未指定电流通道名称，则采用默认内部名称和 `故障电流通道` 业务名称。

若模型中已经存在活动故障，预览必须列出已有故障，避免用户误以为新增操作会替换它们。

创建预览必须列出：

```text
新故障元件
目标引脚
直接接地支路
故障电流信号组件
故障电流 EMT 输出配置
故障电压信号组件和输出配置（仅在用户明确要求时）
将保留的现有活动故障
```

用户明确确认后，才允许在内存模型中一次性创建这些关联对象。

## Delete operation

删除预览必须识别并列出：

```text
目标故障元件
与故障直接相连的 diagram-edge
专属直接接地支路
专属故障电流信号组件
专属故障电压信号组件（如存在）
只被该故障使用的 EMT 输出配置
删除后的活动故障数量
```

只有满足以下条件时，才可自动级联删除关联对象：

- 能通过正式连接关系确认它直接属于目标故障；
- 它不被其他组件引用；
- 删除不会留下孤立但必需的拓扑对象。

归属不明确时，必须停止级联删除，列出不确定对象并等待用户选择：

```text
取消删除
仅删除故障元件
提供进一步的关联确认
```

用户选择“仅删除故障元件”时，只删除目标故障组件及能够确定为直接专属的连线；保留归属不明确的接地、信号或输出对象，并在结果中说明残留对象可能影响后续模型检查。

删除后若没有活动故障，必须提示：

```text
当前模型已没有活动故障，后续短路分析将无法执行。
```

## Change preview and snapshot evidence

所有新增、通道配置和删除操作都必须先生成预览。预览至少包含：

- 当前内存版本和来源 RID；
- 目标故障元件 ID 与展示名称；
- 原始和目标 `I`、`V`；
- 原始和目标信号组件 `Input`、`Channel Name`；
- 新增、修改或删除的 `diagram-edge`；
- 新增、修改或删除的接地支路；
- 新增、修改或删除的 EMT 输出配置；
- 自动修复、自动创建或保留的不确定对象；
- 删除后活动故障数量变化。

用户确认后，快照必须保留变更前后对应的组件、边、通道和 `output_channels` 原始结构，以支持 EMT 失败回滚和后续审计。

## Unconfirmed fields

以下内容必须通过当前 CloudPSS SDK 或真实模型确认后才能实现：

- 电流/电压信号组件的正式 definition；
- `Input`、`Channel Name` 的正式 JSON 字段名和 source-wrapper 格式；
- 信号组件与故障元件之间使用的正式连接关系；
- `output_channels` 每项的字段顺序、采样配置和关联组件方式；
- GND 组件的正式 definition 和引脚；
- `faultresistor_3p` 的引脚编号、正负端语义和正式 definition；
- `diagram-edge` 中端口和引脚的完整结构；
- `Model.addComponent`、`updateComponent`、`removeComponent` 对当前模型 revision 的实际变更行为。

未确认时，Skill 必须停止相关新增、删除或通道配置操作，不得生成推测性模型结构。
