import Graph from "graphology";
import type { GraphPayload } from "../types/graph";
import { baseNodeSize, edgeColor, nodeColor } from "./styles";

export interface SigmaNodeAttributes {
  x: number;
  y: number;
  size: number;
  color: string;
  label: string;
  nodeKind: string;
  filePath?: string;
  startLine?: number;
  endLine?: number;
  hidden?: boolean;
  zIndex?: number;
  highlighted?: boolean;
  metadata?: Record<string, unknown>;
}

export interface SigmaEdgeAttributes {
  size: number;
  color: string;
  edgeType: string;
  confidence?: number;
  precisionLevel?: number;
  extractionSource?: string;
  reason?: string;
  hidden?: boolean;
  zIndex?: number;
  metadata?: Record<string, unknown>;
}

export type SigmaGraph = Graph<SigmaNodeAttributes, SigmaEdgeAttributes>;

export function graphPayloadToGraphology(payload: GraphPayload): SigmaGraph {
  const graph = new Graph<SigmaNodeAttributes, SigmaEdgeAttributes>({
    multi: true,
    type: "directed",
    allowSelfLoops: true,
  });

  const goldenAngle = Math.PI * (3 - Math.sqrt(5));
  for (let index = 0; index < payload.nodes.length; index += 1) {
    const node = payload.nodes[index];
    if (!node.id || graph.hasNode(node.id)) {
      continue;
    }
    const radius = Math.sqrt(index + 1) * 20;
    const angle = index * goldenAngle;
    graph.addNode(node.id, {
      x: radius * Math.cos(angle),
      y: radius * Math.sin(angle),
      size: baseNodeSize(node.kind),
      color: nodeColor(node.kind),
      label: node.label || node.id,
      nodeKind: node.kind || "unknown",
      filePath: node.file_path,
      startLine: node.start_line,
      endLine: node.end_line,
      metadata: node.metadata || {},
    });
  }

  const edgeKeys = new Set<string>();
  for (const edge of payload.edges) {
    if (!edge.source || !edge.target) {
      continue;
    }
    if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) {
      continue;
    }
    let keyBase = edge.id || `${edge.source}->${edge.target}:${edge.type}`;
    let key = keyBase;
    let seq = 1;
    while (edgeKeys.has(key) || graph.hasEdge(key)) {
      seq += 1;
      key = `${keyBase}#${seq}`;
    }
    edgeKeys.add(key);
    graph.addEdgeWithKey(key, edge.source, edge.target, {
      size: edge.type === "STEP_IN_PROCESS" ? 1.8 : 1.1,
      color: edgeColor(edge.type),
      edgeType: edge.type || "UNKNOWN",
      confidence: edge.confidence,
      precisionLevel: edge.precision_level,
      extractionSource: edge.extraction_source,
      reason: edge.reason,
      metadata: edge.metadata || {},
    });
  }

  graph.forEachNode((node) => {
    const attrs = graph.getNodeAttributes(node);
    const degree = graph.degree(node);
    graph.mergeNodeAttributes(node, {
      size: attrs.size + Math.log(degree + 1),
    });
  });

  return graph;
}
