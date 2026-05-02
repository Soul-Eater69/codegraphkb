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
      layoutCalls(graph);
      return;
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
// Repo: packed-circle cluster layout. Each folder owns a sub-circle;
// its files sit inside that circle, and sub-folders are packed inside
// alongside them. Pure deterministic placement (no FA2), then noverlap.
// =================================================================
function layoutRepoTree(graph: SigmaGraph): void {
  layoutRepoTreeBands(graph);
  return;

  const childrenOf = new Map<string, string[]>();
  const parents = new Map<string, string>();
  graph.forEachEdge((_e, attrs, source, target) => {
    if (attrs.edgeType !== "CONTAINS") return;
    if (!childrenOf.has(source)) childrenOf.set(source, []);
    childrenOf.get(source)!.push(target);
    parents.set(target, source);
  });

  // The API only emits CONTAINS for folder->file. Reconstruct folder->folder
  // hierarchy by parsing path strings: `folder:src/codegraphkb/core` is a
  // child of `folder:src/codegraphkb`, which is a child of `folder:src`.
  const allFolderIds = new Set<string>();
  graph.forEachNode((node, attrs) => {
    if (attrs.kind === "folder") allFolderIds.add(node);
  });
  for (const folderId of allFolderIds) {
    if (parents.has(folderId)) continue;
    // folderId is "folder:<path>" - strip the prefix, get parent path
    const path = folderId.startsWith("folder:") ? folderId.slice("folder:".length) : folderId;
    const lastSlash = path.lastIndexOf("/");
    if (lastSlash <= 0) continue; // top-level folder
    const parentPath = path.slice(0, lastSlash);
    const parentId = `folder:${parentPath}`;
    if (allFolderIds.has(parentId) && parentId !== folderId) {
      if (!childrenOf.has(parentId)) childrenOf.set(parentId, []);
      childrenOf.get(parentId)!.push(folderId);
      parents.set(folderId, parentId);
    }
  }

  let roots: string[] = [];
  graph.forEachNode((node) => {
    if (!parents.has(node)) roots.push(node);
  });
  // If there's a single synthetic root, "explode" it: use ITS direct children
  // as the layout roots so the canvas shows them as separate constellations
  // instead of one big ring around the root.
  let syntheticRoot: string | null = null;
  if (roots.length === 1) {
    const onlyRoot = roots[0];
    const directChildren = childrenOf.get(onlyRoot) ?? [];
    if (directChildren.length >= 2) {
      syntheticRoot = onlyRoot;
      roots = [...directChildren];
      // Detach so radius/recursion don't include the root anymore
      childrenOf.delete(onlyRoot);
    }
  }
  if (roots.length === 0) {
    layoutClusteredForce(graph);
    return;
  }

  // Recursive radius computation: leaf radius = 18, parent radius = packs
  // children + folder hub.
  const radiusOf = new Map<string, number>();
  const FILE_R = 18;
  const FOLDER_HUB = 36;
  const computeRadius = (n: string): number => {
    const cached = radiusOf.get(n);
    if (cached !== undefined) return cached;
    const kids = childrenOf.get(n) ?? [];
    if (kids.length === 0) {
      radiusOf.set(n, FILE_R);
      return FILE_R;
    }
    // Sum of child areas -> square-root for a packed-circle radius estimate
    let areaSum = 0;
    for (const k of kids) {
      const r = computeRadius(k);
      areaSum += r * r;
    }
    // Padding multiplier so children don't overlap the folder hub
    const r = Math.max(FOLDER_HUB, Math.sqrt(areaSum) * 1.9 + 14);
    radiusOf.set(n, r);
    return r;
  };
  for (const r of roots) computeRadius(r);

  // Place children of `node` packed inside a circle of radius `r` around (cx, cy).
  // Folder hub sits at center; children placed on an inner ring sized by their own radii.
  const placeCluster = (node: string, cx: number, cy: number): void => {
    graph.mergeNodeAttributes(node, { x: cx, y: cy });
    const kids = childrenOf.get(node) ?? [];
    if (kids.length === 0) return;

    // Sort: big subtrees first -> they claim outer slots
    kids.sort((a, b) => (radiusOf.get(b) ?? FILE_R) - (radiusOf.get(a) ?? FILE_R));

    // Sum of child circumference proportions -> angle slots
    const totalChildR = kids.reduce((s, k) => s + (radiusOf.get(k) ?? FILE_R), 0);
    // Ring radius: place each child far enough that its circle clears the hub
    const myR = radiusOf.get(node) ?? FOLDER_HUB;
    const innerRing = Math.max(myR * 0.55, FOLDER_HUB + 18);

    let cursor = -Math.PI / 2;
    for (const k of kids) {
      const childR = radiusOf.get(k) ?? FILE_R;
      const share = childR / Math.max(totalChildR, 1);
      const angle = cursor + share * Math.PI;
      // Place child center at (innerRing + childR) so its circle is inside parent's
      const distance = innerRing + childR * 0.4;
      const x = cx + Math.cos(angle) * distance;
      const y = cy + Math.sin(angle) * distance;
      placeCluster(k, x, y);
      cursor += share * Math.PI * 2;
    }
  };

  // Place roots so total layout fits a roughly-square area, not a long arc.
  // Use a simple grid-pack: rows Ã— cols of root circles.
  roots.sort((a, b) => (radiusOf.get(b) ?? FILE_R) - (radiusOf.get(a) ?? FILE_R));
  const rootCount = roots.length;
  if (rootCount === 1) {
    placeCluster(roots[0], 0, 0);
  } else {
    // Grid the roots
    const cols = Math.max(1, Math.ceil(Math.sqrt(rootCount)));
    const rows = Math.ceil(rootCount / cols);
    const maxR = Math.max(...roots.map((r) => radiusOf.get(r) ?? FILE_R));
    const cellSize = maxR * 2.2 + 80;
    const totalW = cols * cellSize;
    const totalH = rows * cellSize;
    roots.forEach((r, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const x = col * cellSize - totalW / 2 + cellSize / 2;
      const y = row * cellSize - totalH / 2 + cellSize / 2;
      placeCluster(r, x, y);
    });
  }

  // Place the synthetic root at the canvas center so its label is visible
  if (syntheticRoot) {
    graph.mergeNodeAttributes(syntheticRoot, { x: 0, y: 0, size: 14 });
  }

  // Boost folder visual size so hubs read clearly
  graph.forEachNode((node, attrs) => {
    if (attrs.kind === "folder" || attrs.kind === "repo") {
      graph.mergeNodeAttributes(node, { size: Math.max(attrs.size, 9) });
    }
  });

  resolveOverlap(graph, 12);
}

function layoutRepoTreeBands(graph: SigmaGraph): void {
  const childrenOf = new Map<string, Set<string>>();
  const parents = new Map<string, string>();

  const addChild = (parent: string, child: string): void => {
    if (!graph.hasNode(parent) || !graph.hasNode(child) || parent === child) {
      return;
    }
    if (!childrenOf.has(parent)) {
      childrenOf.set(parent, new Set());
    }
    childrenOf.get(parent)!.add(child);
    if (!parents.has(child)) {
      parents.set(child, parent);
    }
  };

  graph.forEachEdge((_e, attrs, source, target) => {
    if (attrs.edgeType === "CONTAINS") {
      addChild(source, target);
    }
  });

  const folderIds = new Set<string>();
  graph.forEachNode((node, attrs) => {
    if (attrs.kind === "folder") {
      folderIds.add(node);
    }
  });

  for (const folderId of folderIds) {
    if (parents.has(folderId)) {
      continue;
    }
    const path = folderId.startsWith("folder:") ? folderId.slice("folder:".length) : folderId;
    const lastSlash = path.lastIndexOf("/");
    if (lastSlash <= 0) {
      continue;
    }
    const parentId = `folder:${path.slice(0, lastSlash)}`;
    if (folderIds.has(parentId)) {
      addChild(parentId, folderId);
    }
  }

  let roots: string[] = [];
  graph.forEachNode((node) => {
    if (!parents.has(node)) {
      roots.push(node);
    }
  });
  roots = roots.sort(compareRepoNodes(graph));
  if (roots.length === 0) {
    layoutConcentric(graph);
    return;
  }

  const leafCounts = new Map<string, number>();
  const countLeaves = (node: string, seen = new Set<string>()): number => {
    const cached = leafCounts.get(node);
    if (cached !== undefined) {
      return cached;
    }
    if (seen.has(node)) {
      return 1;
    }
    seen.add(node);
    const kids = sortedRepoChildren(graph, childrenOf, node);
    const count = kids.length === 0 ? 1 : kids.reduce((sum, child) => sum + countLeaves(child, new Set(seen)), 0);
    leafCounts.set(node, count);
    return count;
  };
  roots.forEach((root) => countLeaves(root));

  const colGap = 260;
  const rowGap = 54;
  let cursor = 0;

  const placeNode = (node: string, depth: number, seen = new Set<string>()): number => {
    if (seen.has(node)) {
      const y = cursor * rowGap;
      cursor += 1;
      graph.mergeNodeAttributes(node, { x: depth * colGap, y });
      return y;
    }
    seen.add(node);
    const kids = sortedRepoChildren(graph, childrenOf, node);
    let y: number;
    if (kids.length === 0) {
      y = cursor * rowGap;
      cursor += 1;
    } else {
      const childYs = kids.map((child) => placeNode(child, depth + 1, new Set(seen)));
      y = (Math.min(...childYs) + Math.max(...childYs)) / 2;
    }
    const kind = graph.getNodeAttribute(node, "kind");
    graph.mergeNodeAttributes(node, {
      x: depth * colGap,
      y,
      size: kind === "folder" || kind === "repo" ? 10 : 5.8,
    });
    return y;
  };

  roots.forEach((root, index) => {
    if (index > 0) {
      cursor += 1;
    }
    placeNode(root, 0);
  });

  let minX = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  graph.forEachNode((_node, attrs) => {
    minX = Math.min(minX, attrs.x);
    maxX = Math.max(maxX, attrs.x);
    minY = Math.min(minY, attrs.y);
    maxY = Math.max(maxY, attrs.y);
  });
  const offsetX = (minX + maxX) / 2;
  const offsetY = (minY + maxY) / 2;
  graph.forEachNode((node, attrs) => {
    graph.mergeNodeAttributes(node, { x: attrs.x - offsetX, y: attrs.y - offsetY });
  });
}

function sortedRepoChildren(
  graph: SigmaGraph,
  childrenOf: Map<string, Set<string>>,
  node: string,
): string[] {
  return Array.from(childrenOf.get(node) ?? []).sort(compareRepoNodes(graph));
}

function compareRepoNodes(graph: SigmaGraph): (a: string, b: string) => number {
  return (a, b) => {
    const aKind = graph.getNodeAttribute(a, "kind");
    const bKind = graph.getNodeAttribute(b, "kind");
    const aRank = aKind === "repo" ? 0 : aKind === "folder" ? 1 : 2;
    const bRank = bKind === "repo" ? 0 : bKind === "folder" ? 1 : 2;
    if (aRank !== bRank) {
      return aRank - bRank;
    }
    return graph.getNodeAttribute(a, "label").localeCompare(graph.getNodeAttribute(b, "label"));
  };
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
// Process: ordered horizontal flow (Route -> Handler -> Service -> ...)
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

// Focused local call graph: seed center, callers left, callees right.
function layoutCalls(graph: SigmaGraph): void {
  const seed = graph.nodes().find((node) => graph.getNodeAttribute(node, "focusRole") === "seed") ?? highestDegreeNode(graph);
  if (!seed) {
    layoutConcentric(graph);
    return;
  }

  graph.mergeNodeAttributes(seed, { x: 0, y: 0, size: 13 });

  const callers: string[] = [];
  const callees: string[] = [];
  const tests: string[] = [];
  const routes: string[] = [];
  const others: string[] = [];
  const placed = new Set<string>([seed]);

  graph.forEachDirectedEdge((_edge, attrs, source, target) => {
    if (attrs.edgeType !== "CALLS" && attrs.edgeType !== "ACCESSES") {
      return;
    }
    if (target === seed && !placed.has(source)) {
      callers.push(source);
      placed.add(source);
    }
    if (source === seed && !placed.has(target)) {
      callees.push(target);
      placed.add(target);
    }
  });

  graph.forEachNode((node, attrs) => {
    if (placed.has(node)) {
      return;
    }
    if (attrs.kind === "test" || attrs.kind === "test_block") {
      tests.push(node);
    } else if (attrs.kind === "route") {
      routes.push(node);
    } else {
      others.push(node);
    }
    placed.add(node);
  });

  placeColumn(graph, callers, -360, 360);
  placeColumn(graph, callees, 360, 360);
  placeRow(graph, routes, -260, 260, -260);
  placeRow(graph, tests, -260, 260, 260);
  placeRing(graph, others, 0, 0, 430);
  resolveOverlap(graph, 4);
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
  const seed = graph.nodes().find((node) => graph.getNodeAttribute(node, "focusRole") === "seed") ?? highestDegreeNode(graph);
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

function highestDegreeNode(graph: SigmaGraph): string | null {
  let seed: string | null = null;
  let maxDeg = -1;
  graph.forEachNode((n) => {
    const d = graph.degree(n);
    if (d > maxDeg) {
      maxDeg = d;
      seed = n;
    }
  });
  return seed;
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

  // One-shot FA2 to relax the seeded layout - deterministic because seeds are fixed
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
    // ignore - overlap pass is best-effort
  }
}
