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
const { CHART_SPECS_ID, RENDERER_ID, attributeValue, collectScriptBlocks, removeBlocks, validateChartContract } = require('./report-chart-contract');

const MAX_FILE_BYTES = 3 * 1024 * 1024;

function removeLibraryBlock(content, blocks) {
  const library = blocks.find((block) => /\bid\s*=\s*["']report-plotly-library["']/i.test(block.attributes));
  if (!library) return { visibleContent: content, libraryContent: null };
  return {
    visibleContent: content.slice(0, library.start) + content.slice(library.end),
    libraryContent: library.content.trim()
  };
}

function collectIssues(mode, content, plotly) {
  const issues = [];
  const warnings = [];
  const blocks = collectScriptBlocks(content);
  const { visibleContent, libraryContent } = removeLibraryBlock(content, blocks);
  const markup = removeBlocks(content, blocks);
  const scriptOpenCount = (content.match(/<script\b/gi) || []).length;
  const scriptCloseCount = (content.match(/<\/script\s*>/gi) || []).length;

  if (!/<html\b/i.test(content)) issues.push('Missing HTML root element.');
  if (!/<title>[^<]+<\/title>/i.test(content)) issues.push('Missing or empty document title.');
  if (content.includes(PLOTLY_MARKER)) issues.push('Unreplaced REPORT_PLOTLY marker found.');
  if (/\{\{[A-Z0-9_]+\}\}/.test(content)) issues.push('Unreplaced template placeholder found.');
  if (/(?:-join\s+|ForEach-Object|ConvertTo-Json|powershell)/i.test(visibleContent)) issues.push('Generator syntax appears in the report.');
  if (visibleContent.includes('\uFFFD')) issues.push('Replacement-character encoding issue found outside the Plotly library.');
  if (/<section(?![^>]*class=["'][^"']*chart)[^>]*>\s*<\/section>/i.test(visibleContent)) issues.push('Empty section found.');
  if (scriptOpenCount !== scriptCloseCount) issues.push('Script opening and closing tag counts differ.');
  if (/Plotly\.(?:newPlot|react)\s*\(/i.test(markup)) issues.push('Plotly render code appears outside a script block.');
  const htmlEndMatch = /<\/html\s*>/i.exec(content);
  if (htmlEndMatch && content.slice(htmlEndMatch.index + htmlEndMatch[0].length).trim() !== '') {
    issues.push('Content appears after the HTML root closes.');
  }

  const allowedScriptIds = new Set([CHART_SPECS_ID, 'report-plotly-library', RENDERER_ID, 'report-plotly-fallback']);
  const contract = validateChartContract(content, allowedScriptIds);
  issues.push(...contract.issues);
  const chartCount = contract.chartCount;

  const externalScriptSources = blocks
    .map((block) => attributeValue(block.attributes, 'src'))
    .filter(Boolean);
  const libraryBlocks = blocks.filter((block) => /\bid\s*=\s*["']report-plotly-library["']/i.test(block.attributes));
  const rendererBlocks = blocks.filter((block) => attributeValue(block.attributes, 'id') === RENDERER_ID);
  if (rendererBlocks.length !== 1 || !/Plotly\.newPlot\s*\(/.test(rendererBlocks[0]?.content || '')) {
    issues.push('Report requires the fixed Plotly renderer.');
  }

  if (mode === 'cdn') {
    if (libraryBlocks.length !== 1) issues.push('CDN mode requires exactly one report-plotly-library script.');
    if (externalScriptSources.length !== 1 || externalScriptSources[0] !== PLOTLY_CDN_URL) {
      issues.push('CDN mode must use exactly the fixed Plotly CDN URL.');
    }
    if (libraryContent !== '') issues.push('CDN mode must not embed Plotly library code.');
    if (!blocks.some((block) => /\bid\s*=\s*["']report-plotly-fallback["']/i.test(block.attributes))) {
      issues.push('CDN mode is missing the Plotly load-failure notice.');
    }
  } else {
    if (externalScriptSources.length !== 0) issues.push('Offline mode must not contain external script sources.');
    if (libraryBlocks.length !== 1) issues.push('Offline mode requires exactly one embedded Plotly library block.');
    if (libraryContent !== plotly.trim()) issues.push('Embedded Plotly library does not exactly match the vendor file.');
    if (blocks.some((block) => /\bid\s*=\s*["']report-plotly-fallback["']/i.test(block.attributes))) {
      issues.push('Offline mode must not contain the CDN fallback block.');
    }
  }

  const byteLength = Buffer.byteLength(content, 'utf8');
  const arrayLiterals = (visibleContent.match(/\[[^\[\]]{80,}\]/g) || []).length;
  if (byteLength > MAX_FILE_BYTES) warnings.push(`Report size is ${(byteLength / 1024 / 1024).toFixed(2)} MB; review chart downsampling.`);
  if (arrayLiterals > 100) warnings.push(`Detected ${arrayLiterals} large inline arrays; review chart data density.`);
  return { issues, warnings, byteLength, chartCount };
}

try {
  const argumentsList = process.argv.slice(2);
  if (argumentsList.length !== 3 || argumentsList[0] !== '--mode' || !['cdn', 'offline'].includes(argumentsList[1])) {
    throw new Error('Usage: node check-report.js --mode <cdn|offline> <report.html>');
  }
  const mode = argumentsList[1];
  const reportPath = argumentsList[2];
  const plotly = assertEnvironment();
  const resolvedReport = path.resolve(reportPath);
  if (!fs.existsSync(resolvedReport)) throw new Error(`Report file was not found: ${resolvedReport}`);

  const content = fs.readFileSync(resolvedReport, 'utf8');
  const { issues, warnings, byteLength, chartCount } = collectIssues(mode, content, plotly);
  for (const warning of warnings) console.warn(`WARNING: ${warning}`);
  if (issues.length > 0) {
    for (const issue of issues) console.error(`ERROR: ${issue}`);
    process.exitCode = 1;
  } else {
    console.log(`Static report check passed: ${resolvedReport}`);
    console.log(`Mode: ${mode}; size: ${byteLength} bytes; charts: ${chartCount}; fixed renderer: present.`);
  }
} catch (error) {
  console.error(`ERROR: ${error.message}`);
  process.exitCode = 1;
}
