---
name: generate-simulation-report
description: 供 SimBot 或 PromptToApp 调用，根据 CloudPSS 结果 RID 与访问 Token 导出潮流或电磁暂态结果，或使用已有本地结果文件，生成数据驱动、可交互的 HTML 分析报告。适用于仿真、试验、模型运行、波形、时间序列、计算结果和工程分析；当用户提供结果 RID、要求读取 CloudPSS 仿真结果，或需要将 Markdown、JSON、CSV 和原始时序数据组织为带图表、表格、证据化文字和可追溯来源的 HTML 报告时使用。
---

# 可视化分析报告生成

生成通用 HTML 分析报告。内容由 SimBot 传入的用户上下文和本地证据决定，不预设领域、章节、指标、通道或图表数量。

## 角色定位

你是 SimBot 调用链中的报告生成执行器。你接收的是 SimBot 传入的用户上下文、CloudPSS 结果 RID、访问 Token、本地文件和输出要求，不承担平台调度、账号管理或其他系统级职责。
你的职责是将远端结果导出到当前用户工作区，并把本地证据整理成可交付的 HTML 报告。

## 职责边界

- **SimBot 报告生成执行器**：理解用户上下文和本地证据，动态决定报告结构、图表、表格、分析文字和结论。
- **Python 导出脚本**：根据结果 RID 恢复 CloudPSS 结果对象，自动识别潮流或电磁暂态，并输出结构化文件；不启动新仿真。
- **Node 脚本**：检查构建环境、按交付模式装配 Plotly、执行交付质检。
- **浏览器**：在新标签页中展示最终 HTML，并验证页面是否实际渲染图表，不覆盖现有标签页。

用户上下文决定目的、读者、范围、语言、风格和输出位置。可读主报告（尤其是 Markdown）优先提供面向读者的事实、名称、结论与分析范围；JSON 补充配置和溯源，结果 CSV 补充详细表格，原始时序数据用于图表和数据观察。冲突影响展示含义时，以主报告为展示基准并记录来源说明。

## 必填输入

- `result_rid`：必填。仿真运行结果的 ID，从当前会话上下文中获取；缺失时向用户索取。
- `token`：必填。执行 CloudPSS 仿真结果导出脚本前，由 Agent 在命令中显式引用 `CLOUDPSS_LOGIN_TOKEN` 和 `CLOUDPSS_TOKEN`，让 SimBot 的 CUSTOM_SECRETS 机制自动注入可用凭据；优先使用 `CLOUDPSS_LOGIN_TOKEN`，为空时使用 `CLOUDPSS_TOKEN`，取得第一个非空值后作为 `--token` 参数传入脚本。脚本不读取环境变量，也不接受默认 Token。若两个候选变量均为空，停止导出并提示用户：“当前运行环境缺少 CloudPSS Token，无法导出仿真结果。”不得要求用户在普通对话中明文发送 Token，不得输出或保存 Token。

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
2. 从当前会话上下文取得 `result_rid`。任一必填输入缺失时停止执行并按“必填输入”要求向用户索取或提示配置；不得假设 Token 已存在。
3. 在导出命令中显式引用 `CLOUDPSS_LOGIN_TOKEN` 和 `CLOUDPSS_TOKEN`，优先取 `CLOUDPSS_LOGIN_TOKEN`，为空时取 `CLOUDPSS_TOKEN`，并作为 `--token` 参数传给脚本；若均为空，则停止导出并提示缺少 CloudPSS Token，无法导出仿真结果。
4. 在当前用户工作区运行 `python <skill目录>/scripts/export-simulation-result.py --result-rid <RID> --token <TOKEN>`，将已发现的 Token 作为启动参数传入。不得把 Token 写入脚本、结果文件、报告、日志或最终回复。保持命令工作目录为当前用户工作区，不得切换到 Skill 目录执行。
5. 读取 `<当前工作区>/simulation-results/<RID>/manifest.json`，按其中的相对路径读取结果文件。脚本会根据远端结果对象自动识别 `powerflow` 或 `emt`，不要求模型 RID 或仿真类型。导出失败、结果流不可用或结果类型不支持时停止报告生成并说明原因。
6. 盘点本地文件，分类为主报告、结构化结果、结果表、原始时序、模型/配置和无关文件；阅读 `references/data-sources.md` 建立来源映射。
7. 提取事实、指标、单位、时间范围、通道和溯源信息。发现时序 CSV 时先读取 `references/waveform-csv-contract.md`，只使用表头、少量样本和统计摘要完成识别。
8. 阅读 `references/report-assembly.md`、`references/visualization-and-writing.md`，依据实际证据动态组织阅读顺序、图表、表格和论文式分析文字。
9. 运行 `node scripts/check-environment.js`。环境未通过时停止构建。
10. 生成 `.report-build/report.source.html` 作为中间源文件：内嵌正文、样式、图表容器和唯一的 `report-chart-specs` JSON 数据清单；仅保留一个 `<!-- REPORT_PLOTLY -->` 标记。每个 `[data-plotly-chart]` 容器必须具有唯一 `id`，并与 JSON 中的图表 `id` 一一对应。不得写入 Plotly 库、Plotly `<script src>`、`Plotly.newPlot`、`Plotly.react` 或任何可执行业务脚本；构建器会注入固定图表渲染器。
11. 默认使用 CDN 轻量模式构建：`node scripts/build-report.js --mode cdn .report-build/report.source.html report.html`。仅当用户明确要求断网可用时，使用 `--mode offline`。
12. 运行 `node scripts/check-report.js --mode <cdn|offline> report.html`。质检失败时，报告状态为**未交付**；修复源文件后重新构建和质检。
13. 如果修改了构建、质检或资源装配脚本，运行 `node tests/run-regression.js`。`tests/fixtures` 是通用的正常与故障输入，用于防止构建规则退化；它们不参与用户报告生成，也不随报告交付。
14. 启动本地 HTTP 服务器提供 `report.html` 所在目录，并在浏览器中新开标签页打开最终 HTML 完成实渲染验收；不得直接覆盖已有标签页。确认正文、图表、交互和控制台无错误。没有完成这一步，不得宣称交付完成。

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
