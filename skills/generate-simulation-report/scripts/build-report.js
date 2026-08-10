#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const {
  PLOTLY_CDN_URL,
  PLOTLY_MARKER,
  assertEnvironment,
  countOccurrences,
  parseModeArguments
} = require('./report-runtime');
const { CHART_SPECS_ID, buildRendererPayload, collectScriptBlocks, validateChartContract } = require('./report-chart-contract');

function buildCdnPayload() {
  // CDN 加载失败时，仅在图表容器中展示明确提示，不伪造静态图或数据结论。
  return `<script id="report-plotly-library" src="${PLOTLY_CDN_URL}" onerror="window.__reportPlotlyLoadFailed=true"></script>
<script id="report-plotly-fallback">window.addEventListener('DOMContentLoaded',function(){if(window.Plotly&&!window.__reportPlotlyLoadFailed)return;document.querySelectorAll('[data-plotly-chart]').forEach(function(chart){var notice=document.createElement('p');notice.className='report-plotly-notice';notice.setAttribute('role','alert');notice.textContent='交互图表库未加载，请联网后刷新。';chart.replaceChildren(notice);});});</script>
${buildRendererPayload()}`;
}

function buildOfflinePayload(plotly) {
  // 直接按标记位置拼接，避免 String.replace 将 Plotly 源码中的 $& 等字符当作替换语法。
  return `<script id="report-plotly-library">\n${plotly}\n</script>\n${buildRendererPayload()}`;
}

function validateSource(source) {
  const issues = [];
  if (countOccurrences(source, PLOTLY_MARKER) !== 1) {
    issues.push('Source must contain exactly one REPORT_PLOTLY marker.');
  }
  if (/<script\b[^>]*\bsrc\s*=\s*["'][^"']*plotly[^"']*["']/i.test(source)) {
    issues.push('Source must not contain a Plotly script src tag.');
  }
  if (/plotly\.js v2\.35\.2/i.test(source)) {
    issues.push('Source must not contain embedded Plotly library code.');
  }
  if (/id\s*=\s*["']report-plotly-(?:library|fallback)["']/i.test(source)) {
    issues.push('Source must not contain delivery-mode Plotly blocks.');
  }
  if (/Plotly\.(?:newPlot|react)\s*\(/i.test(source)) {
    issues.push('Source must not contain Plotly render calls; use report-chart-specs JSON.');
  }
  const htmlEndMatch = /<\/html\s*>/i.exec(source);
  if (htmlEndMatch && source.slice(htmlEndMatch.index + htmlEndMatch[0].length).trim() !== '') {
    issues.push('Source must not contain content after the HTML root closes.');
  }
  const contract = validateChartContract(source, new Set([CHART_SPECS_ID]));
  issues.push(...contract.issues);
  const sourceScripts = collectScriptBlocks(source);
  if (sourceScripts.some((block) => block.attributes && !/\bid\s*=\s*["']report-chart-specs["']/i.test(block.attributes))) {
    issues.push('Source must not contain executable script blocks.');
  }
  if (issues.length > 0) throw new Error(issues.join(' '));
}

try {
  const { mode, inputPath, outputPath } = parseModeArguments(
    process.argv.slice(2),
    'Usage: node build-report.js --mode <cdn|offline> <report.source.html> <report.html>'
  );
  const plotly = assertEnvironment();
  const resolvedInput = path.resolve(inputPath);
  const resolvedOutput = path.resolve(outputPath);
  if (!fs.existsSync(resolvedInput)) throw new Error(`Source HTML file was not found: ${resolvedInput}`);

  const source = fs.readFileSync(resolvedInput, 'utf8');
  validateSource(source);
  const markerIndex = source.indexOf(PLOTLY_MARKER);
  const payload = mode === 'cdn' ? buildCdnPayload() : buildOfflinePayload(plotly);
  const report = source.slice(0, markerIndex) + payload + source.slice(markerIndex + PLOTLY_MARKER.length);

  // 原子写入保证构建失败时不会覆盖已有的可交付报告。
  fs.mkdirSync(path.dirname(resolvedOutput), { recursive: true });
  const temporaryOutput = `${resolvedOutput}.tmp-${process.pid}`;
  fs.writeFileSync(temporaryOutput, report, 'utf8');
  fs.renameSync(temporaryOutput, resolvedOutput);
  console.log(`Built ${mode} report: ${resolvedOutput}`);
} catch (error) {
  console.error(`ERROR: ${error.message}`);
  process.exitCode = 1;
}
