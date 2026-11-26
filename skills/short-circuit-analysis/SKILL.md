---
name: short-circuit-analysis
version: 1.0.0
description: 当用户询问单相、两相或三相短路计算与指标，解读或继续读取已有 CloudPSS EMT 任务，或要求分析已配置故障的 CloudPSS 模型时使用。
license: Internal Use Only
metadata:
  owner: cloudpss-team
  category: analysis
  visibility: internal
  entrypoint: scripts/analyze.py
---

# 短路电流分析

根据用户这次要取得的结果选择流程。已有身份、工况和资料可直接沿用。仅在缺失信息影响回答、选错故障或提交错工况时，询问具体缺项。

## 解释原理或计算方法

读取 [指标与标准](references/metrics-and-standards.md) 中相关条目。说明所问量的物理意义、所需输入和适用条件。用户给足参数时，可写出假设并做手算估算。知识问答只使用问题及相关资料，无需 CloudPSS 模型、认证或仿真。

## 解读已有结果

使用用户给出的报告、结果文件或指定任务。从实际记录核对故障工况、测点或通道、单位、时间窗和所用方法，再解释对应数值。相序需要模型或量测绑定证据。需要读字段时参照 [指标与标准](references/metrics-and-standards.md)。已有任务按 [任务续读入口](references/cloudpss-analysis.md#查询和继续已有任务) 查询状态或导出波形。当前会话有该任务的提交回执和分析上下文时，可接着生成短路指标。用户要求 HTML 报告时，将有效任务 ID 或可用结果交给报告流程。

## 运行指定故障的 EMT

按 [CloudPSS 分析入口](references/cloudpss-analysis.md) 调用 `scripts/analyze.py`。用户指向当前改好的工作副本时，使用该版本导出的交接文件并核对故障、EMT 方案、参数方案和电流绑定。用户指定已保存模型时，使用该 RID 查询活动故障并确认目标。多个候选且目标未明确时，列出名称、ID 和故障时段供选择。选择分析目标只决定读哪个故障的量测，其他活动故障仍按模型参与计算。

提交前核对实际工况和可用电流来源。已保存模型可分别指定参数方案和 EMT 计算方案。工作副本沿用交接绑定。缺少量测时，说明需补的故障电流输出及所在 EMT 方案。用户同时要求准备模型时，交给辅助建模处理。新提交后保留真实任务 ID。超时或交付失败时，沿用任务 ID 和结果目录，按续读入口处理。

单相、两相故障按所选相别、故障端点接法和实际电流通道解读。用户说“两相短路”且工况尚未确定时，确认是哪两相、是否接地。遇到单支路电阻切换，先根据接线和用户目标确认它代表的事件。相关输出和适用口径见 [指标与标准](references/metrics-and-standards.md)。

计算入口以 `{"task_id":"<实际 CloudPSS Job ID>"}` 交出成功结果。按宿主接口要求传递该对象。用户还要求解释指标时，以同次计算的结果为依据继续解读。用户已要求出报告时，将本次任务 ID 和可用的分析报告、分析 JSON 交给报告流程。按[指标对照表](references/metrics-and-standards.md#emt-报告字段与-gbt-155441-2023-指标对照)说明测点、通道、单位、取窗和指标来源。现有 EMT 采样值只按运行结果交付，国标计算量按适用条件另行求取。
