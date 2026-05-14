export type ProjectStatus = "created" | "importing" | "indexing" | "ready" | "failed" | "deleted";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export interface Project {
  id: string;
  name: string;
  source_type: "github_url" | "zip_upload" | "local_path";
  source_ref: string;
  status: ProjectStatus;
  error_message: string;
  created_at: string;
  updated_at: string;
  last_indexed_at: string | null;
}

export interface IndexJob {
  id: string;
  project_id: string;
  status: JobStatus;
  progress_message: string;
  error_message: string;
  files_scanned: number;
  files_indexed: number;
  symbols: number;
  edges: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ProjectFile {
  path: string;
  language: string;
  size_bytes: number;
  indexed_at: string;
  symbol_count: number;
}

export interface ProjectSymbol {
  kind: string;
  name: string;
  qualified_name: string;
  file_path: string;
  start_line: number;
  end_line: number;
  signature: string;
}

export interface ProjectStats {
  files: number;
  symbols: number;
  edges: number;
  parameters?: number;
  embeddings?: number;
  languages?: Record<string, number>;
  roles?: Record<string, number>;
  last_indexed_at?: string | null;
  schema_version?: string;
  repo_name?: string;
}

export interface ContextItem {
  kind: string;
  title: string;
  file_path: string;
  start_line: number | null;
  end_line: number | null;
  score: number;
  tokens: number;
  body?: string;
  retrieval_sources: string[];
  reason?: string;
}

export interface ContextPackResponse {
  intent: string;
  mode: string;
  retrieval_mode: string;
  estimated_tokens: number;
  graph_paths: string[];
  files_likely_to_edit: string[];
  related_tests: string[];
  repo_map: unknown;
  audit: Record<string, unknown>;
  items: ContextItem[];
}

export interface AskResponse {
  question?: string;
  answer?: string;
  model?: string;
  used_llm?: boolean;
  context?: ContextPackResponse;
}

export interface EditFileEntry {
  file: string;
  reason: string;
  confidence: number;
  symbols?: string[];
}

export interface EditTestEntry {
  file: string;
  reason: string;
  confidence: number;
  test_blocks?: string[];
}

export interface EditSymbolEntry {
  symbol: string;
  file: string;
  reason: string;
  confidence: number;
}

export interface EditRisk {
  title: string;
  level: string;
  reason: string;
  affected?: string[];
  task_keywords?: string[];
}

export interface ValidationCommand {
  command: string;
  type: string;
  reason: string;
  confidence: number;
}

export interface EditPlanResponse {
  task: string;
  mode: string;
  summary: string;
  files_likely_to_edit: EditFileEntry[];
  files_to_read_only: EditFileEntry[];
  related_tests: EditTestEntry[];
  symbols_to_modify: EditSymbolEntry[];
  callers: EditSymbolEntry[];
  callees: EditSymbolEntry[];
  risks: EditRisk[];
  validation_commands: ValidationCommand[];
  context_pack: ContextItem[];
  process_traces: Array<Record<string, unknown>>;
  audit: Record<string, unknown>;
  warnings: string[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      const error = body?.error;
      if (error?.message) {
        message = `${message}: ${error.message}`;
      }
    } catch {
      const text = await res.text().catch(() => "");
      if (text) {
        message = `${message}: ${text}`;
      }
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export async function listProjects(): Promise<Project[]> {
  const payload = await request<{ projects: Project[] }>("/projects");
  return payload.projects;
}

export async function createGithubProject(url: string, name?: string): Promise<{ project_id: string; status: string; job_id: string }> {
  return request("/projects/github", {
    method: "POST",
    body: JSON.stringify({ url, name }),
  });
}

export async function uploadZipProject(file: File, name?: string): Promise<{ project_id: string; status: string; job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  if (name?.trim()) {
    form.append("name", name.trim());
  }
  return request("/projects/upload", {
    method: "POST",
    body: form,
  });
}

export async function getProject(projectId: string): Promise<Project> {
  return request<Project>(`/projects/${encodeURIComponent(projectId)}`);
}

export async function getLatestJob(projectId: string): Promise<IndexJob | null> {
  try {
    return await request<IndexJob>(`/projects/${encodeURIComponent(projectId)}/jobs/latest`);
  } catch (err) {
    if (err instanceof Error && err.message.includes("404")) {
      return null;
    }
    throw err;
  }
}

export async function reindexProject(projectId: string, force = false): Promise<{ project_id: string; status: string; job_id: string }> {
  return request(`/projects/${encodeURIComponent(projectId)}/index`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export async function askProject(
  projectId: string,
  question: string,
  contextOnly = true,
): Promise<ContextPackResponse | AskResponse> {
  return request(`/projects/${encodeURIComponent(projectId)}/ask`, {
    method: "POST",
    body: JSON.stringify({ question, context_only: contextOnly }),
  });
}

export async function prepareEdit(projectId: string, task: string): Promise<EditPlanResponse> {
  return request(`/projects/${encodeURIComponent(projectId)}/prepare-edit`, {
    method: "POST",
    body: JSON.stringify({ task }),
  });
}

export async function getProjectStats(projectId: string): Promise<ProjectStats> {
  return request<ProjectStats>(`/projects/${encodeURIComponent(projectId)}/stats`);
}

export async function getProjectFiles(projectId: string): Promise<ProjectFile[]> {
  const payload = await request<{ files: ProjectFile[] }>(`/projects/${encodeURIComponent(projectId)}/files`);
  return payload.files;
}

export async function getProjectSymbols(projectId: string): Promise<ProjectSymbol[]> {
  const payload = await request<{ symbols: ProjectSymbol[] }>(`/projects/${encodeURIComponent(projectId)}/symbols`);
  return payload.symbols;
}
