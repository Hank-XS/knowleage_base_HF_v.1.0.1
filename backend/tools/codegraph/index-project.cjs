'use strict';
// No agent installation, watcher, model, or execution of uploaded source code.
const { CodeGraph } = require('@colbymchenry/codegraph');
const path = require('node:path');

(async () => {
  const root = path.resolve(process.argv[2]);
  const graph = await CodeGraph.init(root, { index: false });
  try {
    const result = await graph.indexAll({
      onProgress: (progress) => process.stdout.write(`${JSON.stringify(progress)}\n`),
    });
    process.stdout.write(`${JSON.stringify({ result, stats: graph.getStats() })}\n`);
  } finally {
    graph.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
