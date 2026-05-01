import forceAtlas2 from "graphology-layout-forceatlas2";
import type Graph from "graphology";
import type { SigmaEdgeAttrs, SigmaNodeAttrs } from "./graphAdapter";
import type { Perspective } from "../types/graph";

type SigmaGraph = Graph<SigmaNodeAttrs, SigmaEdgeAttrs>;

export function applyDeterministicLayout(graph: SigmaGraph, perspective: Perspective): void {
  switch (perspective) {
    case "repo":
      layoutRepo(graph);
      return;
    case "symbols":
      layoutSymbols(graph);
      return;
    case "processes":
      layoutProcess(graph);
      return;
    case "impact":
      layoutImpact(graph);
      return;
    case "neighborhood":
      layoutNeighborhood(graph);
      return;
    default:
      layoutRadial(graph);
  }
}

export function runForceLayout(graph: SigmaGraph, iterations = 120): void {
  const safeIterations = Math.max(20, Math.min(iterations, 240));
  forceAtlas2.assign(graph, { iterations: safeIterations });
}

function layoutRepo(graph: SigmaGraph): void {
  const centerX = 0;
  const centerY = 0;
  const folders = graph.nodes().filter((n) => graph.getNodeAttribute(n, "kind") === "folder");
  const files = graph.nodes().filter((n) => graph.getNodeAttribute(n, "kind") === "file");
  const others = graph.nodes().filter((n) => {
    const kind = graph.getNodeAttribute(n, "kind");
    return kind !== "folder" && kind !== "file";
  });

  placeRing(graph, folders, centerX, centerY, 140);
  placeRing(graph, files, centerX, centerY, 280);
  placeRing(graph, others, centerX, centerY, 420);
}

function layoutSymbols(graph: SigmaGraph): void {
  const files = graph.nodes().filter((n) => graph.getNodeAttribute(n, "kind") === "file");
  const symbolNodes = graph.nodes().filter((n) => graph.getNodeAttribute(n, "kind") !== "file");
  files.sort();
  symbolNodes.sort();

  const columnWidth = 180;
  const rowHeight = 90;
  for (let i = 0; i < files.length; i += 1) {
    const x = (i % 6) * columnWidth - 450;
    const y = Math.floor(i / 6) * rowHeight - 220;
    graph.mergeNodeAttributes(files[i], { x, y });
  }

  for (let i = 0; i < symbolNodes.length; i += 1) {
    const host = files[i % Math.max(files.length, 1)];
    const baseX = host ? (graph.getNodeAttribute(host, "x") as number) : 0;
    const baseY = host ? (graph.getNodeAttribute(host, "y") as number) : 0;
    const angle = (i % 8) * (Math.PI / 4);
    const radius = 40 + 8 * Math.floor(i / Math.max(files.length, 1));
    graph.mergeNodeAttributes(symbolNodes[i], {
      x: baseX + Math.cos(angle) * radius,
      y: baseY + Math.sin(angle) * radius,
    });
  }
}

function layoutProcess(graph: SigmaGraph): void {
  const processEdges = graph
    .edges()
    .filter((e) => graph.getEdgeAttribute(e, "edgeType") === "STEP_IN_PROCESS");
  if (processEdges.length === 0) {
    layoutRadial(graph);
    return;
  }

  const ordered = processEdges
    .map((e) => {
      const step = Number((graph.getEdgeAttribute(e, "step") as number | undefined) ?? 0);
      return { e, step };
    })
    .sort((a, b) => a.step - b.step);

  const placed = new Set<string>();
  let x = -360;
  const y = 0;
  for (const item of ordered) {
    const source = graph.source(item.e);
    const target = graph.target(item.e);
    if (!placed.has(source)) {
      graph.mergeNodeAttributes(source, { x, y });
      placed.add(source);
      x += 140;
    }
    if (!placed.has(target)) {
      graph.mergeNodeAttributes(target, { x, y });
      placed.add(target);
      x += 140;
    }
  }

  const leftovers = graph.nodes().filter((n) => !placed.has(n));
  placeRing(graph, leftovers, 0, 220, 180);
}

function layoutImpact(graph: SigmaGraph): void {
  const target = graph.nodes().find((n) => {
    const role = graph.getNodeAttribute(n, "impactRole");
    return role === "target";
  });
  if (!target) {
    layoutNeighborhood(graph);
    return;
  }
  graph.mergeNodeAttributes(target, { x: 0, y: 0, size: 12 });

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

  placeLine(graph, callers, -320, -120, -320, 120);
  placeLine(graph, callees, 320, -120, 320, 120);
  placeLine(graph, routes, -120, -280, 120, -280);
  placeLine(graph, tests, -120, 280, 120, 280);
  placeRing(graph, others, 0, 0, 240);
}

function layoutNeighborhood(graph: SigmaGraph): void {
  const seed = graph.nodes()[0];
  if (!seed) {
    return;
  }
  graph.mergeNodeAttributes(seed, { x: 0, y: 0, size: 11 });
  const neighbors = graph.neighbors(seed);
  placeRing(graph, neighbors, 0, 0, 180);
  const remainder = graph.nodes().filter((n) => n !== seed && !neighbors.includes(n));
  placeRing(graph, remainder, 0, 0, 320);
}

function layoutRadial(graph: SigmaGraph): void {
  const nodes = graph.nodes();
  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < nodes.length; i += 1) {
    const radius = Math.sqrt(i + 1) * 26;
    const angle = i * goldenAngle;
    graph.mergeNodeAttributes(nodes[i], {
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
    });
  }
}

function placeRing(graph: SigmaGraph, nodes: string[], cx: number, cy: number, radius: number): void {
  if (nodes.length === 0) {
    return;
  }
  const step = (2 * Math.PI) / nodes.length;
  for (let i = 0; i < nodes.length; i += 1) {
    graph.mergeNodeAttributes(nodes[i], {
      x: cx + Math.cos(i * step) * radius,
      y: cy + Math.sin(i * step) * radius,
    });
  }
}

function placeLine(
  graph: SigmaGraph,
  nodes: string[],
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): void {
  if (nodes.length === 0) {
    return;
  }
  if (nodes.length === 1) {
    graph.mergeNodeAttributes(nodes[0], { x: (x1 + x2) / 2, y: (y1 + y2) / 2 });
    return;
  }
  for (let i = 0; i < nodes.length; i += 1) {
    const t = i / (nodes.length - 1);
    graph.mergeNodeAttributes(nodes[i], {
      x: x1 + (x2 - x1) * t,
      y: y1 + (y2 - y1) * t,
    });
  }
}
