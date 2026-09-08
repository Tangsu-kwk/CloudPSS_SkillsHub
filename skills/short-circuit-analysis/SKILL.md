---
name: short-circuit-analysis
description: 使用 CloudPSS SDK 对 EMT-ready 模型执行真实 EMT 仿真，读取电流通道或功率/电压等效通道，计算峰值电流、故障窗口 RMS、故障前/后 RMS、直流偏置估计、短路容量近似值，并可由短路容量推导 PCC 戴维南等值阻抗、SCR/ESCR 和弱网等级，最终返回真实 CloudPSS 仿真任务 ID。当用户需要短路电流、故障电流、短路容量、断路器开断电流水平、保护整定初筛、戴维南等值、短路比、SCR/ESCR、弱电网判定或已有短路场景的 EMT 波形分析时使用。该 skill 只依赖公开 cloudpss 包和本 skill 的 bundled runtime，不依赖其他 skill 或共享包。
license: Internal Use Only
compatibility:
  python: ">=3.11"
  requires_env: true
  required_env_vars:
    - SIMSTUDIO_TOKEN
  notes: SimBot provides CloudPSS credentials; CLOUDPSS_TOKEN and CLOUDPSS_LOGIN_TOKEN are supported aliases.
metadata:
  owner: cloudpss-team
  category: analysis
  visibility: internal
  maturity: validated
  entrypoint: scripts/verify_runtime_contract.py
  dependency_strategy: bundled-mylib
  shared_packages: []
  verification_method: offline_runtime_contract_and_real_cloudpss_emt_case
---

# Short Circuit Analysis

## Deterministic entrypoint

For a live CloudPSS request, first use the bundled
`mylib.inspect_fault_candidates_from_source` preflight entrypoint. It loads the model and lists
active fault candidates without starting EMT. After fault selection is resolved, use
`mylib.analyze_model_from_source` once. The analysis entrypoint performs the complete sequence:

1. Fetch the exact user-supplied model RID with a bounded GraphQL timeout.
2. Read `model.toJSON()` and `model.getAllComponents()` to resolve model parameters.
3. Query the exact component definition RID for current-unit evidence and normalize direct current to `kA`.
4. Infer safe defaults from the retrieved model data.
5. Run EMT and analyze real current channels, or clearly marked power/voltage estimates.
6. Save JSON, Markdown, summary CSV, waveform, raw waveform, and complete analysis-code artifacts, then return only the real CloudPSS EMT `task_id`.

The entrypoint is part of this Skill, not a project business Tool. Import it from `mylib`.
Do not reimplement any step in an ad hoc command.

## When to use

- 需要从 CloudPSS EMT 波形中评估短路电流或故障电流。
- 需要计算峰值电流、故障窗口 RMS、故障前/后 RMS、短路容量近似值。
- 需要基于短路容量推导 PCC 戴维南等值阻抗、短路比 SCR、等效短路比 ESCR 或弱网等级。
- 需要基于已有短路/故障场景输出保护整定或设备开断电流水平的初筛报告。
- 需要轻量、独立的 EMT 波形分析 skill，而不是依赖共享 PSA 包或其他 skill。

## Input contract

正式入口为 `analyze_model_from_source(source, config=None)`：

- `source` 必须是从用户消息中取得的原始 CloudPSS 模型 RID，格式为 `model/<owner>/<model-key>`。
- 用户未明确提供分析选项时省略 `config`，不要传空配置或自行补造参数。
- `cloudpss` SDK 可能未安装；调用分析入口前，先检查是否可导入；若不可导入，则使用本 Skill 的 `requirements.txt` 安装后再分析。
- Token 和服务地址由宿主环境配置。
- Agent 不查找 SDK 文件，不读取或打印 Token，不执行认证初始化，不读取 `mylib` 源码或探测函数签名。

分析前预检查入口为 `inspect_fault_candidates_from_source(source)`：

- 只加载用户指定的模型并返回活动故障的 `id`、`name`、类型和故障时间，不启动 EMT。
- 没有活动故障时，要求用户先在模型中配置故障并停止。
- 只有一个活动故障时，直接使用返回的 `target_fault_id` 继续正式分析。
- 有多个活动故障时，列出每个故障的名称和 ID，询问用户要分析哪一个；在用户选择前不得调用正式分析入口。
- 用户可用唯一名称或组件 ID 选择。名称不唯一或选择不存在时继续询问，不得猜测、不得按创建时间或列表顺序默认选择。
- 用户选择后，将其作为 `config.analysis.target_fault_id` 传入正式入口。其他活动故障不会被自动禁用，必须告知用户它们仍参与同一次 EMT 场景并可能影响结果。

`config` 接受以下等价 JSON 配置。真实电流通道只能来自模型中活动故障元件或故障母线声明的 args.I。
runtime 不扫描全部 EMT 通道，也不根据通道名称猜测目标通道。若模型没有电流通道，可以用 `equivalent_pairs` 指定功率/电压通道，按三相公式估算等效电流。

- `analysis`
  - `base_voltage_kv`: 基准线电压，优先由活动故障母线的模型 `VBase` 自动解析；如果自动解析失败，必须由调用方显式提供，禁止静默使用默认值。
  - `target_fault_id`: 多个活动故障时必须指定的目标故障元件 ID（也接受唯一的故障名称）；只有一个活动故障时可省略。
  - `calibration_scale`: 用户明确提供的额外校准系数，默认 `1.0`。电流单位换算由 runtime 根据 CloudPSS 元件参数元数据自动确定；不得使用本字段绕过未知单位。
  - `power_scale_mw`: 功率通道缩放系数，默认 `1.0`，用于等效电流估算。
  - `voltage_scale_pu`: 电压通道缩放系数，默认 `1.0`。
  - `nominal_voltage_pu`: 等效估算时电压过低的回退标幺值，默认 `1.0`。
  - `analysis_window`: 总分析时间窗 `[start, end]`；默认使用全仿真时间。
  - `prefault_window`: 故障前窗口 `[start, end]`；默认取分析窗前段。
  - `fault_window`: 故障窗口 `[start, end]`；默认取分析窗中段。
  - `postfault_window`: 故障后窗口 `[start, end]`；默认取分析窗末段。
  - `steady_fault_window`: 稳态故障窗口 `[start, end]`；未指定时从故障窗口两端各裁剪 20%。
  - `steady_fault_trim_fraction`: 默认稳态窗口裁剪比例 `0.2`；必须小于 `0.5`。
  - `min_samples`: 单通道最小样本数，默认 `128`。
- `thevenin`
  - `enabled`: 是否由短路容量推导戴维南等值和 SCR，默认 `true`。
  - `system_base_mva`: 标幺阻抗基准容量，默认 `100.0` MVA。
  - `plant_rating_mva`: 并网设备或电源额定容量；提供后计算 `SCR = Ssc / Srated`。
  - `reactive_compensation_mvar`: 并联补偿容量；提供后计算 `ESCR = (Ssc - Qcomp) / Srated`，默认 `0.0`。
  - `xr_ratio`: 可选 X/R 比。提供后把 `|Zth|` 分解为 R/X；不提供时只输出阻抗幅值。
  - `weak_scr_threshold`: 弱网阈值，默认 `2.0`。
  - `strong_scr_threshold`: 强网阈值，默认 `3.0`。
- `channels`
  - `current`: 不作为临时补充入口。真实电流通道必须从模型中活动故障元件或故障母线的 `args.I` 读取；如果用户通过 `channels.current` 提供通道，必须拒绝。
  - `voltage`: 电压通道列表，只能与 `equivalent_pairs` 配合使用，不能单独作为电流输入。
  - `generic`: 不用于短路电流计算；不要将普通波形通道当作电流通道。
  - `equivalent_pairs`: 功率/电压通道对列表，例如 `{"power": "#P1:0", "voltage": "vac:0"}`。
  - `auto_max_channels`:  仅限制模型已声明的故障元件或故障母线电流通道数量，默认 `3`；不扫描或自动选择其他 EMT 电流通道。
## Workflow
1. 先检查 cloudpss 依赖；缺失时安装 requirements.txt。依赖准备失败则停止，不加载模型。
2. 调用 `inspect_fault_candidates_from_source` 读取活动故障候选项；该步骤不得启动 EMT。
3. 无故障时停止；单故障时继续；多故障时暂停并询问用户，取得唯一名称或组件 ID 后再继续。
4. 使用调用方已配置好的 CloudPSS SDK 加载 EMT-ready 模型，并且只调用一次正式分析入口。
5. 在 `model_parameters` 阶段完成分析前置检查：
   - 定位活动故障元件；
   - 若只有一个活动故障则自动将其作为目标；若有多个活动故障，必须由调用方明确指定一个目标故障元件，不得默认取第一个；其他活动故障仍保留在同一次 EMT 场景中；
   - 通过 `diagram-edge` 解析故障母线；
   - 读取故障母线的 `Name` 和 `VBase`；
   - 读取故障元件的 `fs`、`fe` 和 `fault_type`；
   - 读取故障元件或故障母线声明的电流通道；
   - 对每个候选电流通道记录所属组件 ID、`definition RID` 和参数键 `I`；
   - 通过 GraphQL 按完整 `definition RID` 查询元件参数定义；
   - 单位解析顺序为 `parameter.unit`、`parameter.name` 中受支持的 `[单位]`、`parameter.description` 中受支持的 `[单位]`；
   - 仅支持大小写敏感的 `A`、`kA`、`MA`、`mA`，并在分析前换算为 `kA`；
   - 单位缺失、不受支持、冲突、元件定义无权限或 GraphQL 失败时，真实电流路径必须在 `model_parameters` 阶段停止。
6.在上述检查完成后，调用真实 CloudPSS `runEMT()` 并轮询到完成。如果活动故障元件和故障母线均未声明电流通道，且用户未明确提供合法 `equivalent_pairs`，必须在 `model_parameters` 阶段失败，不得启动 EMT。
7. EMT 完成后，仅从所选目标故障元件及其故障母线声明的电流通道中读取目标通道；目标故障的母线、`VBase`、故障时间和指标均以该元件为准。
   不扫描、猜测或使用其他发电机、线路或支路通道替代。
   如果声明的通道在 EMT 结果中不存在，直接在 `emt_analysis` 阶段失败。
8. 截取分析、故障前、故障中、故障后窗口，校验时间轴单调和样本数。
9. 从故障窗口中排除初始和结束各 20% 的暂态段，计算稳态故障窗口 RMS、峰值和短路容量；普通故障窗口指标仍单独保留。
10. 以 `kA` 计算峰值电流、普通故障窗口 RMS、故障前/后 RMS、RMS 比值、直流偏置估计和短路容量近似值。
11. 如果启用 `thevenin`，按 `Zth = Vll^2 / Ssc`、`Zth(pu) = Sbase / Ssc`、`SCR = Ssc / Srated`、`ESCR = (Ssc - Qcomp) / Srated` 推导戴维南等值和短路比。
12. 通过 CloudPSS `EMTResult.getPlotChannelData()` 读取选定通道并完成确定性分析；不对不同时间轴静默插值。
13. 在任务结果目录保存模型参数快照、派生指标 JSON、Markdown 主报告、指标汇总 CSV、轻量波形摘要、选定分析通道的标准化合并波形 CSV、CloudPSS 全部原始通道的逐通道 CSV，以及本次实际使用函数组成的完整 Python 代码快照。
14. 对 Agent 仅返回 `{"task_id":"<CloudPSS job.id>"}`；PromptToApp/Report 根据该 ID 获取仿真结果并负责可视化与报告。

## Agent execution contract

- 在任何真实分析前，必须先调用此 Skill。
- 必须严格使用用户提供的原始 RID。
- 必须先调用 `inspect_fault_candidates_from_source`。多故障时必须等待用户选择，禁止默认选择最新故障、第一个故障或任何推测目标。
- 如果可用，应从活动故障母线的 `VBase` 解析 `analysis.base_voltage_kv`。
  在结果中包含解析出的数值及其来源路径。模型没有基准电压时，必须明确报错或要求调用方提供，
  不得静默使用 230 kV 作为回退值。
- 如果故障组件通过 `diagram-edge` 连接到母线，则根据模型拓扑解析活动故障母线；
  使用该母线的 `Name` 以及对应的 `Bus_<n>_Vbase` 变量。
  在正式入口启动后，不得要求 Agent 通过探索组件的方式查找这些信息。
- 保留原始 CloudPSS 通道名称。除非模型明确提供了对应关系，
  不得将通道后缀 `:0`、`:1` 和 `:2` 标记为 A/B/C。
- RID 和目标故障确定后，只调用一次 `analyze_model_from_source`。
  如果用户明确提供了分析选项，则将其作为 `config` 参数传入；
  否则省略 `config`，由入口函数根据获取到的模型自动生成默认配置。
- 除 `cloudpss` 依赖预检查外，不得查看 Skill 目录、`mylib`、函数签名、验证脚本、
  历史结果、SDK 源码或认证信息。
- 如果使用 Windows PowerShell，不要提交多行 `python -c` 命令。
  如果必须执行 Shell 命令，应使用单行命令，导入 `analyze_model_from_source`，
  并输出其 JSON 结果。优先使用准确的 Skill 路径和绝对 RID。
- 将 `SCA_STAGE=model_loading`、`SCA_STAGE=model_parameters`、
  `SCA_STAGE=emt_analysis` 和 `SCA_STAGE=complete` 视为执行检查点。
- 如果未到达某个检查点，必须将对应阶段报告为失败阶段。
  在相应输出出现之前，不得声称模型参数或短路分析结果已经存在。
- 如果任一阶段失败，立即停止当前分析，报告失败阶段和错误信息后结束。
  不得使用其他 RID 重试，也不得继续探索文件。
- 看到 `SCA_STAGE=complete` 后，立即结束响应。
  不得再搜索文件、重新运行分析，或询问可选的 SCR/ESCR 参数，除非用户明确要求。
- 返回入口函数生成的完整 `task_id` 对象。
  不得添加分析数值、文件路径、状态文字、Markdown 或解释文字，
  也不得生成或改写 ID。
- 不得打印或包含 Token、API Key、Cookie 或任何环境变量的值。

## Agent output

成功时只输出单字段 JSON：

```json
{"task_id":"34201796-fba6-4e0e-9e67-21f814fc796e"}
```

`task_id` 必须原样等于本次 CloudPSS EMT Job 的 `job.id`。本地结果目录、内部 JSON、模型参数、波形和派生指标都不是 Agent 对外响应的一部分。

## Internal result

runtime 按任务保存到 `results/short_circuit_analysis_result/<task_id>/`：

- `task.json`：最小任务元数据和内部分析结果文件名；
- `model_parameters.json`：本次分析读取的模型、仿真配置、故障对象、故障母线、基准电压以及候选电流通道的单位解析依据；
- `analysis_result.json`：确定性计算得到的通道指标、汇总指标、单位信息、来源信息和内部产物索引；
- `analysis_report.md`：可读主报告，包含分析对象、单位依据、通道指标、Thevenin、SCR/ESCR、结论和限制；
- `summary.csv`：每个分析通道一行的指标汇总，电流字段统一为 `kA`，短路容量为 `MVA`；
- `waveform.csv`：参与分析的电流或等效电流通道合并波形，统一为 `kA`；
- `waveform_summary.json`：供智能体或后续流程读取的轻量统计，不包含完整逐点波形；
- `raw_waveforms/`：CloudPSS EMT Job 返回的全部原始通道逐通道 CSV，保持原始数值不缩放；`index.json` 仅给能够可靠映射的分析电流通道记录原始单位；
- `analysis_code.py`：本次实际使用的单位查询、模型解析、EMT、通道选择、指标计算和产物生成函数的完整代码快照，并固化本次 RID 与配置；不嵌入 Token 或波形样本。

这些文件是 runtime 的本地持久化结果，但不属于 Agent 对外响应，也不要求 PromptToApp 依赖本地路径。PromptToApp 的统一契约仍只有 `task_id`。

## Standards and references basis

- IEC 60909 和 IEEE 551 用于短路容量、等效电压源法和设备校核口径参考；当前实现只做 EMT 波形驱动的短路容量和等值阻抗初筛。
- IEEE 2800 和 NERC Low Short Circuit Strength IBR 用于 SCR/ESCR 与弱网风险解释；当前阈值默认采用工程常见 `SCR < 2` 弱网、`2 <= SCR < 3` 中等、`SCR >= 3` 较强的初筛分级。
- pandapower short-circuit、GridCal 和 `CloudPSS_skillhub` 的 `thevenin_equivalent` / `short_circuit` 作为实现边界参考；本 skill 不 import 这些项目或兄弟 skill。

## Constraints

- 该 skill 默认不创建故障、不修改云端模型，只分析已有 EMT 输出通道。
- 模型必须包含启用的故障对象；如果没有故障对象，立即报告模型不满足分析前提并停止。
- 真实电流通道必须具有可追溯的单位证据；禁止在单位未知时默认按 `kA` 或 `current_scale=1.0` 继续计算。
- `A`、`kA`、`MA` 和 `mA` 大小写敏感，不得通过统一转小写解析单位。
- 功率/电压等效电流由公式直接得到 `kA`，不得再次套用故障元件 `I` 参数的单位换算。
- 完整波形只由确定性 Python 代码处理和导出，不得打印、粘贴或整体加载到智能体上下文。
- 如果活动故障元件和故障母线都没有声明真实电流通道，且用户未明确提供合法的 `equivalent_pairs`，runtime 必须在 `model_parameters` 阶段直接失败，不启动 EMT；只有明确提供合法 `equivalent_pairs` 时，才允许进行功率/电压等效估算。
- 戴维南等值由已计算短路容量推导；若短路容量本身来自功率/电压等效电流，`Zth` 和 SCR 也属于同一近似链路。
- SCR/ESCR 是弱网初筛，不替代 IEEE 2800/NERC 接入研究、控制相互作用研究或 IEC 60909 设备校核级短路计算。
- 如果目标通道不存在、分析时间窗无数据、样本数不足或 EMT 仿真失败，runtime 直接失败；不得使用发电机、线路或其他支路通道替代，也不执行 KCL 汇总。
