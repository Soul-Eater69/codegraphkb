export type GraphView =
  | "full"
  | "repo"
  | "symbols"
  | "calls"
  | "framework"
  | "processes";

export interface GraphMetadata {
  repo_path?: string;
  view?: string;
  schema_version?: number;
  schema_version_indexed?: string;
  node_count?: number;
  edge_count?: number;
  indexed_at?: string;
  [key: string]: unknown;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  file_path?: string;
  start_line?: number;
  end_line?: number;
  metadata?: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence?: number;
  precision_level?: number;
  extraction_source?: string;
  reason?: string;
  line?: number | null;
  metadata?: Record<string, unknown>;
}

export interface GraphPayload {
  metadata: GraphMetadata;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SummaryResponse {
  repo?: string;
  repo_path?: string;
  files?: number;
  symbols?: number;
  edges?: number;
  processes?: number;
  languages?: Record<string, number>;
  [key: string]: unknown;
}

export interface SearchResult {
  id: string;
  label: string;
  kind: string;
  file_path?: string;
  start_line?: number;
  end_line?: number;
  score?: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

export interface NodeDetails {
  node: Record<string, unknown>;
  relationships?: Record<string, unknown>;
  process?: Record<string, unknown>;
}

export interface ProcessSummary {
  id: string;
  label: string;
  process_type: string;
  entrypoint_id?: string;
  terminal_id?: string;
  step_count: number;
  confidence: number;
  metadata?: Record<string, unknown>;
}

export interface ProcessStep {
  step: number;
  src_qname: string;
  dst_qname: string;
  confidence: number;
  metadata?: Record<string, unknown>;
}

export interface ProcessDetails extends ProcessSummary {
  steps: ProcessStep[];
}

export interface ContextRequest {
  task: string;
  mode?: string;
  selected_node_ids?: string[];
  pinned_files?: string[];
  token_budget?: number;
  retrieval?: string;
}

export interface ContextResponse {
  context_pack: string;
  selected_node_ids: string[];
  pinned_files: string[];
  files_likely_to_edit: string[];
  related_tests: string[];
  process_traces: unknown[];
  audit: Record<string, unknown>;
  context: Record<string, unknown>;
}
