#!/usr/bin/env node

const { PLOTLY_PATH, PLOTLY_VERSION, assertEnvironment } = require('./report-runtime');

// 这是 Agent 的构建环境检查，不是最终报告用户需要执行的程序。
try {
  const plotly = assertEnvironment();
  console.log(`Node.js: ${process.versions.node}`);
  console.log(`Plotly: ${PLOTLY_VERSION}`);
  console.log(`Plotly path: ${PLOTLY_PATH}`);
  console.log(`Plotly bytes: ${Buffer.byteLength(plotly, 'utf8')}`);
  console.log('Environment check passed.');
} catch (error) {
  console.error(`ERROR: ${error.message}`);
  process.exitCode = 1;
}
