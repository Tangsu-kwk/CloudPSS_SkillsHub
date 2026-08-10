# 质量门禁

任何构建或检查失败均表示报告**未交付**。修复 `.report-build/report.source.html` 后重新构建并重新检查。

## 静态检查

构建前运行：

```bash
node scripts/check-environment.js
```

构建后运行：

```bash
node scripts/check-report.js --mode cdn report.html
```

用户明确要求离线交付时，将 `cdn` 替换为 `offline`。

检查应确认：

- 报告事实、表格和图表可追溯到用户上下文和实际来源。
- 章节、表格、图表和结论均有有效证据，且不存在空内容、占位符、生成代码或正文乱码。
- 图表容器、`report-chart-specs` JSON 清单和固定渲染器精确对应；有效图表具备标题、已知单位和图例。
- `cdn` 模式只使用固定版本 Plotly CDN，并存在加载失败提示；不嵌入 Plotly。
- `offline` 模式没有外部脚本，且内嵌 Plotly 与 skill 的 vendor 文件完全一致。
- 脚本边界完整，源文件没有自由的 Plotly 调用，Plotly 源码和图表 JSON 没有泄漏为页面正文，且 `</html>` 后不存在内容；输出文件体积和图表密度预警。

## 浏览器实渲染检查

最终交付前必须先通过本地 HTTP server 访问最终 HTML，再在浏览器中新开标签页验收：

- 启动本地 HTTP 服务器服务 `report.html` 所在目录。
- 在浏览器中新开标签页打开 `http://localhost:<port>/report.html`。
- 确认 `window.Plotly` 已加载；CDN 模式应可访问网络。
- 确认每个 `[data-plotly-chart]` 容器生成 Plotly 的 SVG、Canvas 或图例节点，且未显示图表库、配置或渲染失败提示。
- 确认页面正文、图表和关键结果可见。
- 确认控制台不存在 Plotly 加载和绘图错误。
- 不得直接覆盖已有标签页或打断原有页面状态；再次验证时继续使用新标签页。

缺少浏览器能力时，交付说明中只陈述已完成静态质检，不得声称已完成最终实渲染验收。

最终回复只将 `report.html` 作为交付入口；`simulation-results/` 可说明为证据数据目录，`.report-build/` 不作为用户需要打开的文件。
