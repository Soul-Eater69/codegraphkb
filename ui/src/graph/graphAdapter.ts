import Graph from "graphology";
import type { GraphPayload, Perspective } from "../types/graph";
import { baseEdgeSize, baseNodeSize, edgeColor, nodeColor } from "./graphStyles";
import { applyDeterministicLayout } from "./layouts";

export interface SigmaNodeAttrs {
  x: number;
  y: number;
  size: number;
  color: string;
  label: string;
  kind: string;
  filePath?: string;
  lineRange?: string;
  impactRole?: "target";
  hidden?: boolean;
  zIndex?: number;
  type?: string;
}

export interface SigmaEdgeAttrs {
  size: number;
  color: string;
  edgeType: string;
  confidence?: number;
  precisionLevel?: number;
  extractionSource?: string;
  reason?: string;
  step?: number;
  hidden?: boolean;
  zIndex?: number;
  type?: string;
}

export type SigmaGraph = Graph<SigmaNodeAttrs, SigmaEdgeAttrs>;

export function toSigmaGraph(
  payload: GraphPayload,
  perspective: Perspective,
  selectedNodeKinds: Set<string>,
  selectedEdgeTypes: Set<string>,
): SigmaGraph {
  const graph = new Graph<SigmaNodeAttrs, SigmaEdgeAttrs>({
    multi: true,
    type: "directed",
    allowSelfLoops: true,
  });

  for (const node of payload.nodes) {
    if (selectedNodeKinds.size > 0 && !selectedNodeKinds.has(node.kind)) {
      continue;
    }
    graph.addNode(node.id, {
      x: 0,
      y: 0,
      size: baseNodeSize(node.kind),
      color: nodeColor(node.kind),
      label: node.label || node.id,
      kind: node.kind || "unknown",
      filePath: node.file_path,
      lineRange:
        typeof node.start_line === "number" && typeof node.end_line === "number"
          ? `${node.start_line}-${node.end_line}`
          : undefined,
      type: "circle",
    });
  }

  let edgeIndex = 0;
  for (const edge of payload.edges) {
    if (selectedEdgeTypes.size > 0 && !selectedEdgeTypes.has(edge.type)) {
      continue;
    }
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) {
      continue;
    }
    const key = edge.id || `${edge.source}:${edge.target}:${edge.type}:${edgeIndex}`;
    const step =
      (typeof edge.metadata?.step === "number" ? edge.metadata.step : undefined) ??
      (typeof edge.metadata?.index === "number" ? edge.metadata.index : undefined);
    if (graph.hasEdge(key)) {
      edgeIndex += 1;
      continue;
    }
    graph.addEdgeWithKey(key, edge.source, edge.target, {
      size: baseEdgeSize(edge.type),
      color: edgeColor(edge.type),
      edgeType: edge.type || "UNKNOWN",
      confidence: edge.confidence,
      precisionLevel: edge.precision_level,
      extractionSource: edge.extraction_source,
      reason: edge.reason,
      step,
      type: "curved",
    });
    edgeIndex += 1;
  }

  // For process flows, connect the process node to the first ordered step so
  // the ordered layout has an obvious entrypoint.
  if (perspective === "processes") {
    bridgeProcessEntrypoint(graph, payload);
  }

  // Size by degree (hub emphasis)
  graph.forEachNode((node, attrs) => {
    const degree = graph.degree(node);
    graph.mergeNodeAttributes(node, {
      size: attrs.size + Math.log(degree + 1) * 1.1,
    });
  });

  markImpactRoles(graph, payload);
  applyDeterministicLayout(graph, perspective);
  return graph;
}

function bridgeProcessEntrypoint(graph: SigmaGraph, payload: GraphPayload): void {
  // Find process node
  let processNode: string | null = null;
  graph.forEachNode((node, attrs) => {
    if (!processNode && attrs.kind === "process") {
      processNode = node;
    }
  });
  if (!processNode) {
    return;
  }
  // Find earliest step source
  let firstStepSrc: string | null = null;
  let minStep = Number.POSITIVE_INFINITY;
  for (const e of payload.edges) {
    const s =
      typeof e.metadata?.step === "number"
        ? e.metadata.step
        : typeof e.metadata?.index === "number"
          ? e.metadata.index
          : null;
    if (s == null) continue;
    if (s < minStep && graph.hasNode(e.source)) {
      minStep = s;
      firstStepSrc = e.source;
    }
  }
  if (!firstStepSrc || firstStepSrc === processNode) {
    return;
  }
  const key = `process-link:${processNode}:${firstStepSrc}`;
  if (!graph.hasEdge(key)) {
    graph.addEdgeWithKey(key, processNode, firstStepSrc, {
      size: 1.6,
      color: "rgba(255, 93, 108, 0.55)",
      edgeType: "PROCESS_STEP",
      step: -1,
      type: "curved",
    });
  }
}

function markImpactRoles(graph: SigmaGraph, payload: GraphPayload): void {
  const target = typeof payload.metadata.target === "string" ? payload.metadata.target : null;
  if (!target) {
    return;
  }
  for (const node of graph.nodes()) {
    if (node.includes(target)) {
      graph.mergeNodeAttributes(node, { color: "#ff5d6c" });
      graph.setNodeAttribute(node, "impactRole", "target");
      return;
    }
  }
}
