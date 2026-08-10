# 开发环境与交付模式

## 环境边界

Agent 构建环境使用 Node.js 18+ 和 skill 附带的 `assets/vendor/plotly-2.35.2.min.js`。先运行：

```bash
node scripts/check-environment.js
```

用户浏览最终 HTML 时不需要 Node.js、skill 文件夹或本地数据文件。

## 默认 CDN 模式

默认构建轻量在线报告：

```bash
node scripts/build-report.js --mode cdn .report-build/report.source.html report.html
node scripts/check-report.js --mode cdn report.html
```

- 最终 HTML 引用固定版本 `https://cdn.plot.ly/plotly-2.35.2.min.js`。
- 页面正文、绘图数据和样式均在 HTML 内；固定渲染器在构建时注入，读取 JSON 图表清单后执行绘制。
- 用户需要网络以获得交互图表；加载失败时页面在图表区显示联网提示。

## 可选离线模式

仅当用户明确要求断网可用时构建：

```bash
node scripts/build-report.js --mode offline .report-build/report.source.html report.html
node scripts/check-report.js --mode offline report.html
```

- 最终 HTML 内嵌固定版本 Plotly，不引用外部脚本。
- 文件体积增加是离线交互能力的必要代价。

## 源文件契约

`.report-build/report.source.html` 是内部中间源文件，不是交付入口。它必须：

- 恰好包含一次 `<!-- REPORT_PLOTLY -->`；
- 不包含 Plotly 库源码、Plotly `<script src>`、`report-plotly-library` 或 `report-plotly-fallback`；
- 包含所有报告内容、图表容器和唯一的 `<script id="report-chart-specs" type="application/json">` 数据清单；不得包含 `Plotly.newPlot`、`Plotly.react` 或其他可执行业务脚本。

构建器只在该标记位置装配 Plotly 与固定渲染器，不替换任何其他脚本标签。每个 `[data-plotly-chart]` 容器必须具有唯一 `id`，并与 JSON 清单项的 `id` 精确一一对应。构建或质检失败时不得交付最终报告。

## 用户可见产物

- `report.html` 是唯一最终交付入口。
- `simulation-results/` 是证据数据目录，用于报告来源追溯。
- `.report-build/` 是内部中间构建目录，可保留用于调试和重构建，不需要用户打开。
