import type { SigmaGraph } from "./graphAdapter";

export function nodeNeighborhood(graph: SigmaGraph, nodeId: string | null): Set<string> {
  const set = new Set<string>();
  if (!nodeId || !graph.hasNode(nodeId)) {
    return set;
  }
  set.add(nodeId);
  for (const n of graph.neighbors(nodeId)) {
    set.add(n);
  }
  return set;
}

export function edgeTouchesNode(graph: SigmaGraph, edgeId: string, nodeId: string): boolean {
  return graph.source(edgeId) === nodeId || graph.target(edgeId) === nodeId;
}
