const CHART_SPECS_ID = 'report-chart-specs';
const RENDERER_ID = 'report-plotly-renderer';

function collectScriptBlocks(content) {
  const blocks = [];
  const pattern = /<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi;
  let match;
  while ((match = pattern.exec(content)) !== null) {
    blocks.push({ attributes: match[1], content: match[2], start: match.index, end: pattern.lastIndex });
  }
  return blocks;
}

function attributeValue(attributes, name) {
  const match = attributes.match(new RegExp(`\\b${name}\\s*=\\s*["']([^"']+)["']`, 'i'));
  return match ? match[1] : null;
}

function removeBlocks(content, blocks) {
  let result = content;
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    result = result.slice(0, blocks[index].start) + result.slice(blocks[index].end);
  }
  return result;
}

function collectChartContainerIds(markup) {
  const ids = [];
  const pattern = /<[a-z][^>]*\bdata-plotly-chart(?:\s|=|>)[^>]*>/gi;
  let match;
  while ((match = pattern.exec(markup)) !== null) {
    ids.push(attributeValue(match[0], 'id'));
  }
  return ids;
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function validateChartContract(content, allowedScriptIds) {
  const issues = [];
  const blocks = collectScriptBlocks(content);
  const markup = removeBlocks(content, blocks);
  const specsBlocks = blocks.filter((block) => attributeValue(block.attributes, 'id') === CHART_SPECS_ID);
  const scriptIds = blocks.map((block) => attributeValue(block.attributes, 'id'));

  for (const id of scriptIds) {
    if (!allowedScriptIds.has(id)) issues.push('Report contains an unapproved script block.');
  }
  if (specsBlocks.length !== 1) {
    issues.push('Report requires exactly one report-chart-specs JSON script.');
    return { issues, chartCount: 0, blocks };
  }

  const specsBlock = specsBlocks[0];
  if ((attributeValue(specsBlock.attributes, 'type') || '').toLowerCase() !== 'application/json') {
    issues.push('report-chart-specs must use type="application/json".');
  }

  let specs;
  try {
    specs = JSON.parse(specsBlock.content);
  } catch {
    issues.push('report-chart-specs contains invalid JSON.');
    return { issues, chartCount: 0, blocks };
  }
  if (!Array.isArray(specs)) {
    issues.push('report-chart-specs must contain a JSON array.');
    return { issues, chartCount: 0, blocks };
  }

  const containerIds = collectChartContainerIds(markup);
  if (containerIds.some((id) => !id)) issues.push('Every data-plotly-chart container requires an id.');
  if (new Set(containerIds).size !== containerIds.length) issues.push('Plotly chart container ids must be unique.');

  const specIds = [];
  for (const spec of specs) {
    if (!isObject(spec) || typeof spec.id !== 'string' || spec.id.length === 0) {
      issues.push('Each chart specification requires a non-empty string id.');
      continue;
    }
    specIds.push(spec.id);
    if (!Array.isArray(spec.data) || spec.data.length === 0) {
      issues.push(`Chart ${spec.id} requires a non-empty data array.`);
    }
    if (spec.layout !== undefined && !isObject(spec.layout)) {
      issues.push(`Chart ${spec.id} layout must be an object when provided.`);
    }
    if (spec.config !== undefined && !isObject(spec.config)) {
      issues.push(`Chart ${spec.id} config must be an object when provided.`);
    }
  }
  if (new Set(specIds).size !== specIds.length) issues.push('Chart specification ids must be unique.');

  const containerIdSet = new Set(containerIds);
  const specIdSet = new Set(specIds);
  for (const id of containerIds) {
    if (id && !specIdSet.has(id)) issues.push(`Chart container ${id} has no chart specification.`);
  }
  for (const id of specIds) {
    if (!containerIdSet.has(id)) issues.push(`Chart specification ${id} has no chart container.`);
  }

  return { issues, chartCount: specs.length, blocks };
}

function buildRendererPayload() {
  // Keep executable Plotly calls in one tested script; report sources supply data-only JSON.
  return `<script id="${RENDERER_ID}">window.addEventListener('DOMContentLoaded',function(){var specsNode=document.getElementById('${CHART_SPECS_ID}');if(!specsNode||!window.Plotly)return;var specs;try{specs=JSON.parse(specsNode.textContent);}catch(error){document.querySelectorAll('[data-plotly-chart]').forEach(function(chart){chart.textContent='图表配置无效，无法渲染。';});return;}specs.forEach(function(spec){var chart=document.getElementById(spec.id);if(!chart)return;try{window.Plotly.newPlot(chart,spec.data,spec.layout||{},Object.assign({responsive:true},spec.config||{}));}catch(error){chart.textContent='图表渲染失败。';}});});</script>`;
}

module.exports = {
  CHART_SPECS_ID,
  RENDERER_ID,
  attributeValue,
  buildRendererPayload,
  collectScriptBlocks,
  removeBlocks,
  validateChartContract
};
