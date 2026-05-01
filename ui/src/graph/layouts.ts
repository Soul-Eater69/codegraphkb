import forceAtlas2 from "graphology-layout-forceatlas2";
import noverlap from "graphology-layout-noverlap";
import type Graph from "graphology";
import type { SigmaEdgeAttrs, SigmaNodeAttrs } from "./graphAdapter";
import type { Perspective } from "../types/graph";

type SigmaGraph = Graph<SigmaNodeAttrs, SigmaEdgeAttrs>;

export function applyDeterministicLayout(graph: SigmaGraph, perspective: Perspective): void {
  if (graph.order === 0) {
    return;
  }
  switch (perspective) {
    case "repo":
      layoutRepoTree(graph);
      return;
    case "symbols":
      layoutSymbolsClustered(graph);
      return;
    case "processes":
      layoutProcessFlow(graph);
      return;
    case "impact":
      layoutImpact(graph);
      return;
    case "neighborhood":
      layoutConcentric(graph);
      return;
    case "calls":
    case "framework":
      layoutClusteredForce(graph);
      return;
    default:
      layoutClusteredForce(graph);
  }
  resolveOverlap(graph);
}

export function runForceLayout(graph: SigmaGraph, iterations = 120): void {
  if (graph.order === 0) {
    return;
  }
  const safeIterations = Math.max(20, Math.min(iterations, 240));
  forceAtlas2.assign(graph, {
    iterations: safeIterations,
    settings: {
      gravity: 0.6,
      scalingRatio: 8,
      slowDown: 6,
      barnesHutOptimize: graph.order > 200,
      strongGravityMode: false,
      adjustSizes: true,
    },
  });
}

// =================================================================
// Repo: hierarchical radial tree (root → folders → files)
// =================================================================
function layoutRepoTree(graph: SigmaGraph): void {
  // Build parent → children map from CONTAINS edges (source contains target).
  const childrenOf = new Map<string, string[]>();
  const parents = new Map<string, string>();
  graph.forEachEdge((_e, attrs, source, target) => {
    if (attrs.edgeType !== "CONTAINS") {
      return;
    }
    if (!childrenOf.has(source)) {
      childrenOf.set(source, []);
    }
    childrenOf.get(source)!.push(target);
    parents.set(target, source);
  });

  // Roots = nodes that have no parent in CONTAINS, prioritizing repo/folder kinds.
  const roots: string[] = [];
  graph.forEachNode((node) => {
    if (!parents.has(node)) {
      roots.push(node);
    }
  });
  if (roots.length === 0) {
    layoutClusteredForce(graph);
    return;
  }

  // If multiple roots, group them as siblings under a virtual center.
  const subtreeSize = new Map<string, number>();
  function computeSize(n: string): number {
    if (subtreeSize.has(n)) {
      return subtreeSize.get(n)!;
    }
    const kids = childrenOf.get(n) ?? [];
    let total = 1;
    for (const k of kids) {
      total += computeSize(k);
    }
    subtreeSize.set(n, total);
    return total;
  }
  for (const r of roots) {
    computeSize(r);
  }

  // Assign each root a wedge of the full circle proportional to subtree size.
  const totalSize = roots.reduce((s, r) => s + (subtreeSize.get(r) ?? 1), 0);
  let cursor = -Math.PI / 2;
  const placeSubtree = (
    node: string,
    angleStart: number,
    angleEnd: number,
    depth: number,
  ): void => {
    const angle = (angleStart + angleEnd) / 2;
    const radius = depth === 0 ? 0 : 140 + depth * 200;
    graph.mergeNodeAttributes(node, {
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    });
    const kids = childrenOf.get(node) ?? [];
    if (kids.length === 0) {
      return;
    }
    const kidTotal = kids.reduce((s, k) => s + (subtreeSize.get(k) ?? 1), 0);
    let local = angleStart;
    // Sort children deterministically so layout is stable across runs
    kids.sort((a, b) => (subtreeSize.get(b) ?? 1) - (subtreeSize.get(a) ?? 1));
    for (const k of kids) {
      const span = ((subtreeSize.get(k) ?? 1) / kidTotal) * (angleEnd - angleStart);
      placeSubtree(k, local, local + span, depth + 1);
      local += span;
    }
  };

  if (roots.length === 1) {
    placeSubtree(roots[0], 0, Math.PI * 2, 0);
  } else {
    for (const r of roots) {
      const span = ((subtreeSize.get(r) ?? 1) / Math.max(totalSize, 1)) * Math.PI * 2;
      placeSubtree(r, cursor, cursor + span, 1);
      cursor += span;
    }
  }
  resolveOverlap(graph, 4);
}

// =================================================================
// Symbols: file as cluster center, symbols radiate outward
// =================================================================
function layoutSymbolsClustered(graph: SigmaGraph): void {
  const files: string[] = [];
  const symbolsByFile = new Map<string, string[]>();
  const orphans: string[] = [];

  graph.forEachNode((node, attrs) => {
    if (attrs.kind === "file") {
      files.push(node);
      symbolsByFile.set(node, []);
    }
  });

  // Attach symbols to their containing file via CONTAINS or DEFINES edges.
  graph.forEachEdge((_e, attrs, source, target) => {
    if (attrs.edgeType !== "CONTAINS" && attrs.edgeType !== "DEFINES") {
      return;
    }
    if (symbolsByFile.has(source) && graph.getNodeAttribute(target, "kind") !== "file") {
      symbolsByFile.get(source)!.push(target);
    }
  });

  graph.forEachNode((node, attrs) => {
    if (attrs.kind === "file") {
      return;
    }
    const owners = files.filter((f) => symbolsByFile.get(f)?.includes(node));
    if (owners.length === 0) {
      orphans.push(node);
    }
  });

  files.sort();
  // Place files on a soft grid
  const cols = Math.max(1, Math.ceil(Math.sqrt(files.length)));
  const cellW = 360;
  const cellH = 320;
  const totalW = cols * cellW;

  files.forEach((file, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const x = col * cellW - totalW / 2 + cellW / 2;
    const y = row * cellH - (Math.ceil(files.length / cols) * cellH) / 2 + cellH / 2;
    graph.mergeNodeAttributes(file, { x, y, size: 8 });

    const kids = symbolsByFile.get(file) ?? [];
    kids.forEach((sym, j) => {
      const angle = (j / Math.max(kids.length, 1)) * Math.PI * 2;
      const radius = 70 + (j % 3) * 22;
      graph.mergeNodeAttributes(sym, {
        x: x + Math.cos(angle) * radius,
        y: y + Math.sin(angle) * radius,
      });
    });
  });

  // Place orphans on outer ring
  placeRing(graph, orphans, 0, 0, Math.max(totalW * 0.6, 400));
  resolveOverlap(graph, 4);
}

// =================================================================
// Process: ordered horizontal flow (Route → Handler → Service → ...)
// =================================================================
function layoutProcessFlow(graph: SigmaGraph): void {
  // Order nodes by step number. Backend stores step in edge metadata.
  const stepEdges: Array<{ source: string; target: string; step: number }> = [];
  graph.forEachEdge((_e, attrs, source, target) => {
    const step = typeof attrs.step === "number" ? attrs.step : null;
    if (step !== null) {
      stepEdges.push({ source, target, step });
    }
  });
  stepEdges.sort((a, b) => a.step - b.step);

  if (stepEdges.length === 0) {
    layoutClusteredForce(graph);
    return;
  }

  // Build the ordered sequence of nodes from steps
  const ordered: string[] = [];
  const seen = new Set<string>();
  for (const e of stepEdges) {
    if (!seen.has(e.source)) {
      ordered.push(e.source);
      seen.add(e.source);
    }
    if (!seen.has(e.target)) {
      ordered.push(e.target);
      seen.add(e.target);
    }
  }

  // Process node first, off to the left, then the steps
  const processNodes: string[] = [];
  graph.forEachNode((node, attrs) => {
    if (attrs.kind === "process") {
      processNodes.push(node);
    }
  });

  const stepX = 180;
  const baseX = -((ordered.length - 1) * stepX) / 2;
  ordered.forEach((node, i) => {
    graph.mergeNodeAttributes(node, {
      x: baseX + i * stepX,
      y: 0,
      size: i === 0 ? 9 : 7,
    });
  });

  // Process node above the entrypoint
  processNodes.forEach((p, i) => {
    graph.mergeNodeAttributes(p, {
      x: baseX - 180,
      y: -120 + i * 90,
      size: 12,
    });
  });

  // Anything else gets stacked on a parallel row below
  const leftovers: string[] = [];
  graph.forEachNode((node, attrs) => {
    if (seen.has(node) || attrs.kind === "process") {
      return;
    }
    leftovers.push(node);
  });
  leftovers.forEach((node, i) => {
    graph.mergeNodeAttributes(node, {
      x: baseX + (i % Math.max(ordered.length, 1)) * stepX,
      y: 180 + Math.floor(i / Math.max(ordered.length, 1)) * 100,
    });
  });
}

// =================================================================
// Impact: target-centered blast radius
// =================================================================
function layoutImpact(graph: SigmaGraph): void {
  const target = graph.nodes().find((n) => graph.getNodeAttribute(n, "impactRole") === "target");
  if (!target) {
    layoutConcentric(graph);
    return;
  }
  graph.mergeNodeAttributes(target, { x: 0, y: 0, size: 14 });

  const callers: string[] = [];
  const callees: string[] = [];
  const tests: string[] = [];
  const routes: string[] = [];
  const others: string[] = [];

  for (const node of graph.nodes()) {
    if (node === target) {
      continue;
    }
    const kind = graph.getNodeAttribute(node, "kind");
    if (kind === "test" || kind === "test_block") {
      tests.push(node);
    } else if (kind === "route") {
      routes.push(node);
    } else if (graph.hasEdge(target, node)) {
      callees.push(node);
    } else if (graph.hasEdge(node, target)) {
      callers.push(node);
    } else {
      others.push(node);
    }
  }

  placeColumn(graph, callers, -380, 380);
  placeColumn(graph, callees, 380, 380);
  placeRow(graph, routes, -360, 360, -320);
  placeRow(graph, tests, -360, 360, 320);
  placeRing(graph, others, 0, 0, 540);
  resolveOverlap(graph, 4);
}

// =================================================================
// Concentric ring (neighborhood)
// =================================================================
function layoutConcentric(graph: SigmaGraph): void {
  // Pick highest-degree node as the seed
  let seed: string | null = null;
  let maxDeg = -1;
  graph.forEachNode((n) => {
    const d = graph.degree(n);
    if (d > maxDeg) {
      maxDeg = d;
      seed = n;
    }
  });
  if (!seed) {
    return;
  }
  graph.mergeNodeAttributes(seed, { x: 0, y: 0, size: 12 });

  const oneHop: string[] = graph.neighbors(seed);
  const oneHopSet = new Set(oneHop);
  const twoHop: string[] = [];
  for (const n1 of oneHop) {
    for (const n2 of graph.neighbors(n1)) {
      if (n2 === seed || oneHopSet.has(n2)) {
        continue;
      }
      if (!twoHop.includes(n2)) {
        twoHop.push(n2);
      }
    }
  }
  const remainder: string[] = [];
  graph.forEachNode((n) => {
    if (n !== seed && !oneHopSet.has(n) && !twoHop.includes(n)) {
      remainder.push(n);
    }
  });

  placeRing(graph, oneHop, 0, 0, 200);
  placeRing(graph, twoHop, 0, 0, 380);
  placeRing(graph, remainder, 0, 0, 540);
  resolveOverlap(graph, 4);
}

// =================================================================
// Generic clustered force layout (call graph, framework)
// Seeds nodes by kind cluster, then runs deterministic FA2 to settle.
// =================================================================
function layoutClusteredForce(graph: SigmaGraph): void {
  const kindBuckets = new Map<string, string[]>();
  graph.forEachNode((node, attrs) => {
    const kind = attrs.kind || "unknown";
    if (!kindBuckets.has(kind)) {
      kindBuckets.set(kind, []);
    }
    kindBuckets.get(kind)!.push(node);
  });

  const kinds = Array.from(kindBuckets.keys());
  const orbitRadius = Math.max(220, 60 + kinds.length * 40);
  kinds.forEach((kind, i) => {
    const baseAngle = (i / kinds.length) * Math.PI * 2;
    const cx = Math.cos(baseAngle) * orbitRadius;
    const cy = Math.sin(baseAngle) * orbitRadius;
    const bucket = kindBuckets.get(kind)!;
    bucket.forEach((node, j) => {
      const a = (j / Math.max(bucket.length, 1)) * Math.PI * 2;
      const r = 60 + Math.sqrt(j) * 18;
      graph.mergeNodeAttributes(node, {
        x: cx + Math.cos(a) * r,
        y: cy + Math.sin(a) * r,
      });
    });
  });

  // One-shot FA2 to relax the seeded layout — deterministic because seeds are fixed
  const iterations = graph.order > 300 ? 80 : graph.order > 100 ? 140 : 200;
  forceAtlas2.assign(graph, {
    iterations,
    settings: {
      gravity: 0.5,
      scalingRatio: 10,
      slowDown: 8,
      barnesHutOptimize: graph.order > 200,
      strongGravityMode: false,
      adjustSizes: true,
      linLogMode: false,
    },
  });
  resolveOverlap(graph, 6);
}

// =================================================================
// Helpers
// =================================================================
function placeRing(graph: SigmaGraph, nodes: string[], cx: number, cy: number, radius: number): void {
  if (nodes.length === 0) return;
  const step = (2 * Math.PI) / nodes.length;
  nodes.forEach((n, i) => {
    graph.mergeNodeAttributes(n, {
      x: cx + Math.cos(i * step - Math.PI / 2) * radius,
      y: cy + Math.sin(i * step - Math.PI / 2) * radius,
    });
  });
}

function placeColumn(graph: SigmaGraph, nodes: string[], x: number, height: number): void {
  if (nodes.length === 0) return;
  if (nodes.length === 1) {
    graph.mergeNodeAttributes(nodes[0], { x, y: 0 });
    return;
  }
  const step = height / (nodes.length - 1);
  nodes.forEach((n, i) => {
    graph.mergeNodeAttributes(n, { x, y: -height / 2 + i * step });
  });
}

function placeRow(graph: SigmaGraph, nodes: string[], x1: number, x2: number, y: number): void {
  if (nodes.length === 0) return;
  if (nodes.length === 1) {
    graph.mergeNodeAttributes(nodes[0], { x: (x1 + x2) / 2, y });
    return;
  }
  const step = (x2 - x1) / (nodes.length - 1);
  nodes.forEach((n, i) => {
    graph.mergeNodeAttributes(n, { x: x1 + i * step, y });
  });
}

function resolveOverlap(graph: SigmaGraph, iterations = 8): void {
  if (graph.order === 0) return;
  try {
    noverlap.assign(graph, {
      maxIterations: iterations,
      settings: { margin: 6, ratio: 1.05, speed: 4 },
    });
  } catch {
    // ignore — overlap pass is best-effort
  }
}
