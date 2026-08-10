# CloudPSS Model Structure

## Purpose

本参考文件定义 `fault-component-editor` 读取和编辑 CloudPSS 模型时使用的结构边界。

优先级：

1. 当前 CloudPSS SDK 的正式对象和字段；
2. 当前模型 `toJSON()` 与 `getAllComponents()` 返回的实际结构；
3. 已验证的项目参考代码；
4. 未确认的字段不得猜测或写入模型。

`CaseEditToolbox.py` 和 `PSAToolbox.py` 仅作为行为参考，不得整体复制。

## Model sources

Skill 可以从两个来源获得模型：

### CloudPSS RID

使用用户提供的原始 RID：

```text
model/<owner>/<model-key>
```

通过当前会话已经配置好的 CloudPSS SDK 加载：

```python
Model.fetch(rid)
```

不得自行搜索模型、替换 RID 或尝试其他模型。

### Current in-memory model

如果当前会话已经存在内存模型版本，优先使用该对象：

```text
session_state.memory_model
```

查询、编辑和验证必须针对同一个内存对象执行，不能因为模型尚未保存就重新 fetch 原始 RID。

## Model JSON

读取模型快照时，优先调用：

```python
model.toJSON()
```

模型级信息通常位于：

```text
model
revision
context
jobs
```

故障组件、信号组件和拓扑图元通常位于：

```text
revision.implements.diagram.cells
```

实际字段必须以当前 SDK 返回结果为准。

## Components

使用：

```python
model.getAllComponents()
```

获得组件对象集合。组件集合可能表现为：

```python
{"<component-id>": <component-object>}
```

每个组件应保存以下可验证信息：

```text
id
definition
shape
label
args
props
pins
```

不同组件不一定拥有全部字段；缺失字段不得自动补造。

### Component identity

组件定位顺序：

1. 精确组件 ID；
2. 精确 `args.Name`；
3. 精确展示 `label`。

如果一个标识匹配多个组件，必须停止并要求用户指定唯一组件。

查询结果中的展示名称优先使用 `args.Name`；当其不存在或为空时退回组件 ID。

如果 `args.Name` 含中文或特殊字符：

- 展示名称保留原始 `args.Name`；
- 内部通道名称使用组件 ID；
- 不修改用户可见的组件名称，除非用户明确要求。

## Component arguments

组件参数通常位于 `component.args`。参数值可能是普通值，也可能是：

```json
{"source": "1.0"}
```

读取参数时应解析 wrapper 的 `source` 值；写入参数时必须保留当前模型要求的值类型和 wrapper 结构。

故障相关字段包括：

```text
fs
fe
ft
Init
chg
I
V
```

本参考文件只规定字段位置，不规定中文含义和故障类型映射；这些内容由 `fault-parameter-mapping.md` 定义。

## Fault component discovery

第一版新增故障只支持 `faultresistor_3p`。活动故障查询应根据正式组件定义识别故障元件。当前 runtime 使用的保守识别方式是 `component.definition` 包含 `faultresistor`，并排除 `component.props.enabled == false`。最终实现必须再次核对 CloudPSS SDK 中实际的故障组件定义和启用字段。

活动故障快照至少记录：

```json
{
  "id": "<component-id>",
  "name": "<args.Name or component-id>",
  "definition": "<component-definition>",
  "args": {"fs": "...", "fe": "...", "ft": "...", "Init": "...", "chg": "...", "I": "...", "V": "..."},
  "props": {},
  "pins": {}
}
```

## Diagram and topology

拓扑图元通常位于 `revision.implements.diagram.cells`。拓扑连接对象通常使用 `shape == "diagram-edge"`。连接端点通常通过：

```json
{"source": {"cell": "<component-id>"}, "target": {"cell": "<component-id>"}}
```

实际端点、端口和引脚字段必须以当前 SDK JSON 为准。

解析拓扑时必须：

- 只把正式 `diagram-edge` 对象视为拓扑连接；
- 保留 edge ID、source 和 target 原始对象；
- 不根据组件名称或通道名称猜测连接关系；
- 无法确认连接归属时停止级联修改或删除。

新增故障时，目标引脚只有在以下条件同时满足时才视为空闲：

1. 目标组件和目标引脚能够被 SDK 明确解析；
2. 没有任何正式拓扑连接对象连接到该引脚；
3. 不是已经存在故障、接地支路或其他设备占用的引脚。

如果无法明确判断引脚是否空闲，必须停止新增并请求用户确认。

## Ground branch

故障接地关系必须通过正式组件和拓扑连接解析，不得只根据组件名称猜测。

直接接地结构通常表现为：

```text
faultresistor_3p pin -> target pin
faultresistor_3p other pin -> GND
```

带中间节点或接地电感的结构可能表现为：

```text
faultresistor_3p -> intermediate node
intermediate node -> inductor
inductor -> GND
```

删除故障时，只有能确认专属于目标故障的接地支路才允许自动删除；无法确认归属时必须停止；用户可以明确授权只删除故障元件而保留不确定关联对象。

## Signal components

故障电流和故障电压信号组件必须通过正式组件字段和拓扑关系识别。

内部信号名称规则：

```text
<fault-id>_fault_current_channel
<fault-id>_fault_voltage_channel
```

如果故障元件的 `args.Name` 含中文或特殊字符，使用故障组件 ID 生成内部名称。

信号组件必须依据当前模型 JSON 的正式字段解析，不能预设所有模型都有 `Input` / `Channel Name`。如果某个模型的 `_newChannel` 或等价信号组件使用名称字段和引脚字段，则读取该模型实际存在的字段，例如：

```text
channel.args.Name
channel.pins["0"]
```

二者必须表示同一个内部信号，并与故障元件 `args.I` 或 `args.V` 对应。只有在目标模型 JSON 明确存在 `Input` / `Channel Name` 字段时，才检查并同步这两个字段。

默认只创建故障电流信号组件：

```text
内部输入/名称字段：<fault-id>_fault_current_channel（字段名以当前模型 JSON 为准）
EMT output name: 故障电流通道
```

故障电压信号组件只有用户明确要求时才创建：

```text
内部输入/名称字段：<fault-id>_fault_voltage_channel（字段名以当前模型 JSON 为准）
EMT output name: 故障电压通道
```

如果故障元件声明了通道但找不到匹配信号组件：

1. 在变更预览中报告缺失；
2. 用户确认后自动创建专属信号组件；
3. 使用默认内部名称和默认 EMT 业务名称；
4. 不共享其他故障的信号组件。

## EMT output channels

EMT 输出通道通常位于 `jobs[*].args.output_channels`。参考代码显示其值为列表结构，但每个列表项的正式字段含义必须通过当前 CloudPSS SDK 和实际模型确认。

实现时必须保留 `output_channels` 原始结构，只修改已确认的字段；不凭通道名猜测组件或引脚；不把 EMT 输出名称强制改成内部 `Input`；允许 EMT 输出名称使用中文业务名称；配置通道时不自动检查 `fs、fe、ft`。

在正式确认 `output_channels` 字段结构前，不得新增、删除或重排未知字段。

## Snapshot evidence

每个模型快照应保留 `model.toJSON()` 和 `model.getAllComponents()`，并记录：

```text
source RID or memory version
component IDs
component definitions
component args
component props
component pins
diagram cells
diagram-edge relations
jobs.args.output_channels
```

快照必须区分原始模型、当前内存修改、EMT 成功版本、EMT 失败版本和回滚后的当前版本。

快照内容是内部验证证据，不得被伪造成 CloudPSS RID、EMT task_id、短路分析结果或 HTML 报告数据。

## Unconfirmed SDK fields

以下内容在实现前必须通过当前 CloudPSS SDK 或真实模型确认：

- 保存副本的正式 API 和返回 RID 字段；
- `diagram-edge` 的完整 source/target/port/pin 结构；
- 组件引脚的正式字段结构；
- 信号组件 `Input` 和 `Channel Name` 的正式字段位置；
- `output_channels` 每个条目的字段顺序和含义；
- `faultresistor_3p` 的正式 definition；
- 故障启用/禁用字段；
- 接地组件和接地电感的正式 definition；
- 内存模型执行 EMT 的正式 API。

未确认前，Skill 必须停止相关操作并报告缺少 SDK 结构依据。
