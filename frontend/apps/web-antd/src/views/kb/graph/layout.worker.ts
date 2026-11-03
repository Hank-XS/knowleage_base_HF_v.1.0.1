/// <reference lib="webworker" />
// Linear graph traversal off the UI thread; no continuously running physics simulation.
self.onmessage = ({ data }) => {
  const { request, nodes, edges } = data;
  const adjacency = new Map<string, Set<string>>(nodes.map((n: any) => [n.id, new Set<string>()]));
  for (const edge of edges) {
    adjacency.get(edge.src)?.add(edge.dst); adjacency.get(edge.dst)?.add(edge.src);
  }
  const ordered = [...adjacency.keys()].sort((a, b) => adjacency.get(b)!.size - adjacency.get(a)!.size || a.localeCompare(b));
  const visited = new Set<string>(); const positions: Record<string, { x: number; y: number }> = {};
  let groupX = 0; let groupY = 0; let rowHeight = 0;
  for (const root of ordered) {
    if (visited.has(root)) continue;
    const queue = [root]; visited.add(root);
    const depths = new Map<string, number>([[root, 0]]); const levels = new Map<number, string[]>();
    let width = 0; let height = 0;
    for (let cursor = 0; cursor < queue.length; cursor++) {
      const id = queue[cursor]!; const depth = depths.get(id)!;
      const level = levels.get(depth) || []; level.push(id); levels.set(depth, level);
      for (const next of adjacency.get(id) || []) {
        if (!visited.has(next) && adjacency.has(next)) { visited.add(next); depths.set(next, depth + 1); queue.push(next); }
      }
    }
    for (const level of levels.values()) {
      const rows = Math.min(64, Math.max(1, Math.ceil(Math.sqrt(level.length * .75))));
      height = Math.max(height, (rows - 1) * 90 + 120);
    }
    let levelX = 0;
    for (const level of levels.values()) {
      const rows = Math.min(64, Math.max(1, Math.ceil(Math.sqrt(level.length * .75))));
      const top = (height - ((rows - 1) * 90 + 120)) / 2;
      level.forEach((id, row) => {
        const x = levelX + Math.floor(row / rows) * 180; const y = top + (row % rows) * 90;
        positions[id] = { x: groupX + x, y: groupY + y };
        width = Math.max(width, x + 240); height = Math.max(height, y + 120);
      });
      levelX += Math.ceil(level.length / rows) * 180 + 120;
    }
    groupX += width + 120; rowHeight = Math.max(rowHeight, height);
    if (groupX > 2400) { groupX = 0; groupY += rowHeight + 160; rowHeight = 0; }
  }
  self.postMessage({ request, positions });
};
