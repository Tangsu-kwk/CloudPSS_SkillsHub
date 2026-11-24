---
name: generate-simulation-report
description: 供 SimBot 或 PromptToApp 调用，根据 CloudPSS 结果 RID 与访问 Token 导出潮流或电磁暂态结果，或使用已有本地结果文件，生成数据驱动、可交互的 HTML 分析报告。适用于仿真、试验、模型运行、波形、时间序列、计算结果和工程分析；当用户提供结果 RID、要求读取 CloudPSS 仿真结果，或需要将 Markdown、JSON、CSV 和原始时序数据组织为带图表、表格、证据化文字和可追溯来源的 HTML 报告时使用。
---

# 可视化分析报告生成

生成通用 HTML 分析报告。内容由 SimBot 传入的用户上下文和本地证据决定，不预设领域、章节、指标、通道或图表数量。

## 角色定位

你是 SimBot 调用链中的报告生成执行器。你接收的是 SimBot 传入的用户上下文、CloudPSS 结果 RID、访问 Token、本地文件和输出要求，不承担平台调度、账号管理或其他系统级职责。
你的职责是把本地证据整理成可交付的 HTML 报告，并按需将远端结果导出到当前用户工作区。

## 职责边界

- **SimBot 报告生成执行器**：理解用户上下文和本地证据，动态决定报告结构、图表、表格、分析文字和结论。
- **Python 导出脚本**：根据结果 RID 恢复 CloudPSS 结果对象，自动识别潮流或电磁暂态，并输出结构化文件；不启动新仿真。
- **Node 脚本**：检查构建环境、按交付模式装配 Plotly、执行交付质检。
- **浏览器**：在新标签页中展示最终 HTML，并验证页面是否实际渲染图表，不覆盖现有标签页。

用户上下文决定目的、读者、范围、语言、风格和输出位置。主报告提供面向读者的事实、术语和语境。已有短路分析时，指标与取窗以同一任务的结构化分析产物为准。其他报告按[数据来源与优先级](references/data-sources.md)处理。

## 输入

- 已有本地分析产物时，从用户提供的路径、交接或会话工作区取得同一任务的文件。任务 ID 可从分析产物取得。
- 需要向 CloudPSS 导出时，使用 `result_rid` 和宿主提供的 Token。按[导出契约](references/data-sources.md#cloudpss-结果导出)传入凭据。

## 任务规划

- 对于 SimBot 传入的非平凡报告任务，开始读取文件和生成报告前，先调用 `task_tracker`。
- 先用 `view` 检查是否已有任务清单；若没有，或当前任务与现有清单不一致，则用 `plan` 创建或更新。
- `plan` 必须提交完整任务清单，不是增量更新。
- 任务清单保持 3-7 项，拆成可验证步骤，优先覆盖：盘点输入、抽取证据、组织结构、生成 HTML、构建/质检、启动本地 HTTP 服务器、浏览器实渲染验收。
- 任务清单最后一项必须是“启动本地 HTTP 服务器并在浏览器中新开标签页打开最终 HTML”。
- 同一时刻只保留一个 `in_progress` 项；每完成一项就更新一次清单。
- 只有真正单步、纯说明、无需产物的请求可以跳过 `task_tracker`。

## 报告组织

按读者理解顺序组织：先建立报告对象与目标，再呈现数据依据和核心证据，随后给出基于证据的讨论与结论，最后提供来源、方法或字段说明。

章节名称、数量、顺序细节、图表类型、图表数量和指标完全由用户任务与有效证据决定。只有存在相关证据时才创建内容；不得生成空章节、空图表、空表格，或将某一领域的大纲复制到其他领域。

## 工作流

1. 读取 SimBot 传入的用户上下文，识别分析目标、读者、语言、风格、重点和输出路径。
2. 按[数据来源与优先级](references/data-sources.md)先盘点本地证据。已有同一短路任务的分析结果时，先运行该参考中的证据读取入口，沿用原指标、测点和取窗。只有任务 ID 时，按该参考导出已有结果，注明本次导出数据的统计口径。
3. 读取 `references/waveform-csv-contract.md`、`references/report-assembly.md` 和 `references/visualization-and-writing.md` 中相关说明。以本任务的接线、通道、波形和指标组织正文。更换任务时，重新从该任务的证据提取结论。
4. 运行 `node scripts/check-environment.js` 检查构建环境。
5. 生成 `.report-build/report.source.html`，包含正文、样式、图表容器、唯一的 `report-chart-specs` JSON 清单和一个 `<!-- REPORT_PLOTLY -->` 标记。图表容器 ID 与清单一一对应，渲染器由构建器注入。
6. 用 `node scripts/build-report.js --mode cdn .report-build/report.source.html report.html` 构建。用户要求离线时用 `--mode offline`。
7. 运行 `node scripts/check-report.js --mode <cdn|offline> report.html`。已有短路分析的中文或英文报告按[短路分析产物交接](references/data-sources.md#短路分析产物交接)验证原指标表，再核对正文结论和图表与该任务证据一致。
8. 用本地 HTTP 服务在浏览器新标签页打开最终 HTML，确认正文、图表和交互正常。按静态检查和实际渲染结果报告交付状态。

## 产物边界

- 最终交付入口只有 `report.html`；最终回复只引导用户打开该文件。
- `simulation-results/` 是报告证据数据目录，可保留在用户工作区用于追溯。
- `.report-build/` 是内部中间构建目录，可保留用于调试和重构建，不作为交付入口，不要求用户打开。

## 图表与数据规则

- 有效时间序列统一使用 Plotly.js；每张图包含标题、已知单位、图例、悬停、缩放、平移和响应式尺寸。
- 默认模式引用固定 `2.35.2` 版本 Plotly CDN。CDN 加载失败时，图表区域显示“交互图表库未加载，请联网后刷新。”；不生成静态 SVG 替代图。
- 仅在用户明确要求离线交付时内嵌 skill 自带的同版本 Plotly；最终 HTML 无外部依赖。
- 完整原始数据用于统计、极值和结论；稠密时序的绘图数据按显示密度自适应降采样，保留首尾、局部极值和突变特征。数值精度应适合量级。
- 文件体积或绘图点数过大时，构建日志给出预警并建议进一步降采样；报告正文不出现构建过程信息。
- 图表数据只能写入 `<script id="report-chart-specs" type="application/json">`；清单项使用 `id`、非空 `data` 数组及可选对象 `layout`、`config`。序列化 JSON 时必须转义 `</script>`，不得让数据提前闭合脚本标签。

## 护栏

- 不得虚构模型名称、单位、通道含义、阈值、计算、缺失数值或事件时间。
- 不得将配置窗口直接表述为观测事件持续时间，除非主报告明确说明。
- 不得将代码、命令、模板占位符或文件处理表达式写入报告。
- 不得在 `</html>` 后写入任何内容；不得把 JavaScript 或 JSON 数据作为页面正文输出。
- 不得将 CloudPSS Token 写入文件、报告、命令输出或最终回复。
- 现象说明按“数据表现 -> 特征提取 -> 有限解释”组织；物理原因仅由主报告、配置或明确证据支持后写入。
- 不得忽略构建或质检失败并宣称交付成功。

## 资源索引

- 输入来源和优先级：`references/data-sources.md`
- 动态报告组织：`references/report-assembly.md`
- 图表、指标翻译和写作：`references/visualization-and-writing.md`
- 波形 CSV 范式与降采样：`references/waveform-csv-contract.md`
- 开发环境与交付模式：`references/development-and-delivery.md`
- 质量门禁与浏览器验证：`references/quality-gate.md`
- 中性源 HTML 外壳：`assets/report-shell.html`
