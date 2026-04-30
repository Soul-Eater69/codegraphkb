import type {
  ContextRequest,
  ContextResponse,
  FileTreeNode,
  GraphPayload,
  GraphView,
  NodeDetails,
  NodeRelations,
  ProcessDetails,
  ProcessSummary,
  SearchResponse,
  SummaryResponse,
} from "../types/graph";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return (await res.json()) as T;
}

export async function getSummary(): Promise<SummaryResponse> {
  return request<SummaryResponse>("/api/summary");
}

export async function getGraph(
  view: GraphView,
  opts?: { maxNodes?: number; maxEdges?: number; nodeKinds?: string[]; edgeTypes?: string[] },
): Promise<GraphPayload> {
  const params = new URLSearchParams({ view });
  if (opts?.maxNodes) {
    params.set("max_nodes", String(opts.maxNodes));
  }
  if (opts?.maxEdges) {
    params.set("max_edges", String(opts.maxEdges));
  }
  if (opts?.nodeKinds && opts.nodeKinds.length > 0) {
    params.set("node_kinds", opts.nodeKinds.join(","));
  }
  if (opts?.edgeTypes && opts.edgeTypes.length > 0) {
    params.set("edge_types", opts.edgeTypes.join(","));
  }
  return request<GraphPayload>(`/api/graph?${params.toString()}`);
}

export async function searchNodes(query: string): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query });
  return request<SearchResponse>(`/api/search?${params.toString()}`);
}

export async function getNode(nodeId: string): Promise<NodeDetails> {
  return request<NodeDetails>(`/api/node/${encodeURIComponent(nodeId)}`);
}

export async function getNodeRelations(nodeId: string): Promise<NodeRelations> {
  return request<NodeRelations>(`/api/node/${encodeURIComponent(nodeId)}/relations`);
}

export async function getNeighborhood(nodeId: string, depth = 2): Promise<GraphPayload> {
  const params = new URLSearchParams({
    node_id: nodeId,
    depth: String(depth),
  });
  return request<GraphPayload>(`/api/neighborhood?${params.toString()}`);
}

export async function getProcesses(): Promise<ProcessSummary[]> {
  const payload = await request<{ processes: ProcessSummary[] }>("/api/processes");
  return payload.processes;
}

export async function getProcess(processId: string): Promise<ProcessDetails> {
  return request<ProcessDetails>(`/api/processes/${encodeURIComponent(processId)}`);
}

export async function getImpact(target: string): Promise<GraphPayload> {
  const params = new URLSearchParams({ target });
  return request<GraphPayload>(`/api/impact?${params.toString()}`);
}

export async function getFilesTree(): Promise<FileTreeNode> {
  return request<FileTreeNode>("/api/files/tree");
}

export async function createContext(requestBody: ContextRequest): Promise<ContextResponse> {
  return request<ContextResponse>("/api/context", {
    method: "POST",
    body: JSON.stringify(requestBody),
  });
}
