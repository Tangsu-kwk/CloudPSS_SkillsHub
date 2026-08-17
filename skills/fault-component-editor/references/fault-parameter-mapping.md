# Fault Parameter Mapping

## Purpose

定义 CloudPSS 故障参数与用户自然语言之间的映射、规范化和校验规则。

本文件只处理：

- `fs、fe、ft、Init、chg、I、V`；
- 中文自然语言转换；
- 参数格式校验；
- 参数修改预览。

暂不处理 `fct`，因为其枚举值尚未通过 SDK 或真实模型确认。

## Supported fault type

第一版新增故障只支持：

```text
faultresistor_3p
```

## Parameter mapping

| 字段 | 中文含义 |
|---|---|
| `fs` | 故障发生时间 |
| `fe` | 故障结束时间 |
| `ft` | 故障类型 |
| `Init` | 初始电阻 |
| `chg` | 故障期间电阻 |
| `I` | 故障电流通道 |
| `V` | 故障电压通道 |

字段类型、单位、默认值和 source-wrapper 格式必须以当前模型为准。

## Fault time

示例：

```text
故障在 1 秒发生
故障开始时间改为 1
fs=1
```

转换为：

```json
{"fs": "1"}
```

```text
故障在 2 秒结束
2 秒切除故障
fe=2
```

转换为：

```json
{"fe": "2"}
```

```text
1 秒发生故障，2 秒结束
```

转换为：

```json
{"fs": "1", "fe": "2"}
```

如果只提供持续时间，不能擅自推断 `fs` 或 `fe`。

## Fault type

根据当前 CloudPSS 模型界面确认：

```text
0：No Fault
1：Phase A Fault
2：Phase B Fault
3：Phase AB Fault
4：Phase C Fault
5：Phase AC Fault
6：Phase BC Fault
7：Phase ABC Fault
```

常见中文表达：

```text
无故障       -> 0
A 相故障     -> 1
B 相故障     -> 2
AB 两相故障  -> 3
C 相故障     -> 4
AC 两相故障  -> 5
BC 两相故障  -> 6
ABC 三相故障 -> 7
三相短路     -> 7
```

以下表达有歧义，必须询问：

```text
两相故障
相间短路
故障类型改一下
```

`ft` 必须写入模型接受的整数值。

## Resistance parameters

`Init` 表示初始电阻：

```text
初始电阻改为 0.01
Init=0.01
```

`chg` 表示故障期间电阻：

```text
故障期间电阻改为 0.001
chg=0.001
```

用户只说“故障电阻”而未说明 `Init` 或 `chg` 时，必须询问。

只有用户明确提供单位时才进行单位换算。

## Current channel

`I` 表示故障元件声明的故障电流内部通道。

查询故障信息时，使用故障元件完整 `definition RID` 查询参数 `I` 的单位元数据。优先使用 `parameter.unit`；为空时只接受 `name` 或 `description` 中明确支持的 `[A]`、`[kA]`、`[MA]`、`[mA]`。该查询用于审计和后续分析准备，失败时标记为 `unavailable`，不得猜测单位，也不得阻止普通故障参数编辑。

默认名称：

```text
<fault-id>_fault_current_channel
```

默认 EMT 输出名称：

```text
故障电流通道
```

用户未指定通道名称时使用默认名称。

如果用户输入中文或特殊字符：

- 内部通道名使用规范化名称；
- 信号组件的正式输入字段与正式名称字段使用同一个内部名称；字段名必须从当前模型 JSON 读取；
- EMT 输出名称可以保留中文业务名称。

## Voltage channel

`V` 表示故障元件声明的故障电压内部通道。

默认不创建故障电压通道。

只有用户明确要求时才配置，例如：

```text
创建故障电压通道
配置故障点电压输出
```

默认名称：

```text
<fault-id>_fault_voltage_channel
```

默认 EMT 输出名称：

```text
故障电压通道
```

## Source-value wrapper

如果原模型使用：

```json
{"source": "1.0"}
```

修改后必须保持同样结构：

```json
{"source": "2.0"}
```

不得无理由改变普通值和 source-wrapper 的类型。

## Validation

参数修改时：

- 只允许修改白名单字段；
- 数值必须可解析且为有限值；
- 同时修改 `fs`、`fe` 时必须满足 `fs < fe`；
- `ft` 必须为合法整数；
- `I`、`V` 必须为非空文本；
- 修改参数时不强制检查通道；
- 配置通道时不强制检查 `fs、fe、ft`。

## Ambiguity handling

以下情况必须停止并询问：

- 未指定故障元件；
- 标识匹配多个故障元件；
- 未说明是 `Init` 还是 `chg`；
- 未说明具体故障相别；
- 时间或单位含义不明确；
- 参数无法转换为模型要求的类型；
- 当前模型的 `ft` 定义与上述映射不一致。

## Change preview

修改前预览至少包含：

```text
故障元件 ID
故障元件展示名称
字段名
字段中文含义
原始值
规范化后的新值
单位
是否涉及通道联动
```

只有用户明确确认后，才写入当前内存模型。
