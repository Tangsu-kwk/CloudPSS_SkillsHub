const fs = require('node:fs');
const path = require('node:path');

// 所有构建脚本共享同一份版本和资源定义，避免 CDN 与本地资源版本漂移。
const PLOTLY_VERSION = '2.35.2';
const PLOTLY_CDN_URL = `https://cdn.plot.ly/plotly-${PLOTLY_VERSION}.min.js`;
const PLOTLY_MARKER = '<!-- REPORT_PLOTLY -->';
const PLOTLY_PATH = path.resolve(__dirname, `../assets/vendor/plotly-${PLOTLY_VERSION}.min.js`);

function assertEnvironment() {
  const majorVersion = Number(process.versions.node.split('.')[0]);
  if (!Number.isInteger(majorVersion) || majorVersion < 18) {
    throw new Error(`Node.js 18+ is required; found ${process.versions.node}.`);
  }
  if (!fs.existsSync(PLOTLY_PATH)) {
    throw new Error(`Local Plotly file was not found: ${PLOTLY_PATH}`);
  }

  const plotly = fs.readFileSync(PLOTLY_PATH, 'utf8');
  if (!plotly.includes(`plotly.js v${PLOTLY_VERSION}`)) {
    throw new Error(`Local Plotly version marker does not match ${PLOTLY_VERSION}.`);
  }
  return plotly;
}

function parseModeArguments(argv, usage) {
  if (argv.length !== 4 || argv[0] !== '--mode' || !['cdn', 'offline'].includes(argv[1])) {
    throw new Error(usage);
  }
  return { mode: argv[1], inputPath: argv[2], outputPath: argv[3] };
}

function countOccurrences(text, value) {
  let count = 0;
  let index = 0;
  while ((index = text.indexOf(value, index)) !== -1) {
    count += 1;
    index += value.length;
  }
  return count;
}

module.exports = {
  PLOTLY_VERSION,
  PLOTLY_CDN_URL,
  PLOTLY_MARKER,
  PLOTLY_PATH,
  assertEnvironment,
  parseModeArguments,
  countOccurrences
};
