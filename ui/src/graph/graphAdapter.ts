import Graph from "graphology";
import type { GraphPayload, Perspective } from "../types/graph";
import { baseNodeSize, edgeColor, nodeColor } from "./graphStyles";
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
    graph.addEdgeWithKey(key, edge.source, edge.target, {
      size: edge.type === "STEP_IN_PROCESS" ? 2.1 : 1.0,
      color: edgeColor(edge.type),
      edgeType: edge.type || "UNKNOWN",
      confidence: edge.confidence,
      precisionLevel: edge.precision_level,
      extractionSource: edge.extraction_source,
      reason: edge.reason,
      step,
    });
    edgeIndex += 1;
  }

  graph.forEachNode((node, attrs) => {
    const degree = graph.degree(node);
    graph.mergeNodeAttributes(node, { size: attrs.size + Math.log(degree + 1) * 0.8 });
  });

  markImpactRoles(graph, payload);
  applyDeterministicLayout(graph, perspective);
  return graph;
}

function markImpactRoles(graph: SigmaGraph, payload: GraphPayload): void {
  const target = typeof payload.metadata.target === "string" ? payload.metadata.target : null;
  if (!target) {
    return;
  }
  for (const node of graph.nodes()) {
    if (node.includes(target)) {
      graph.mergeNodeAttributes(node, { color: "#ff5d6c", size: 12 });
      graph.setNodeAttribute(node, "impactRole", "target");
      return;
    }
  }
}
