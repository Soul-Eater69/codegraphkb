import type { SigmaGraph } from "./adapter";

export function visibleNodeIds(
  graph: SigmaGraph,
  selectedNodeKinds: Set<string>,
): Set<string> {
  const ids = new Set<string>();
  graph.forEachNode((node, attrs) => {
    if (selectedNodeKinds.size === 0 || selectedNodeKinds.has(attrs.nodeKind)) {
      ids.add(node);
    }
  });
  return ids;
}

export function isEdgeVisible(
  graph: SigmaGraph,
  edge: string,
  selectedEdgeTypes: Set<string>,
  visibleNodes: Set<string>,
): boolean {
  const attrs = graph.getEdgeAttributes(edge);
  const source = graph.source(edge);
  const target = graph.target(edge);
  const typeVisible =
    selectedEdgeTypes.size === 0 || selectedEdgeTypes.has(attrs.edgeType);
  return typeVisible && visibleNodes.has(source) && visibleNodes.has(target);
}

export function neighborSet(graph: SigmaGraph, nodeId: string | null): Set<string> {
  const neighbors = new Set<string>();
  if (!nodeId || !graph.hasNode(nodeId)) {
    return neighbors;
  }
  neighbors.add(nodeId);
  for (const n of graph.neighbors(nodeId)) {
    neighbors.add(n);
  }
  return neighbors;
}
