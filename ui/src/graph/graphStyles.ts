export const NODE_COLORS: Record<string, string> = {
  repo: "#8b5cf6",
  folder: "#6d7bff",
  file: "#4d8dff",
  function: "#39f58b",
  method: "#45f0e5",
  class: "#ff8a3d",
  interface: "#ffd166",
  type_alias: "#ffcf70",
  enum: "#ffcf70",
  route: "#ff3eb5",
  test: "#ffd166",
  test_block: "#ffd166",
  model: "#b45cff",
  database_table: "#b45cff",
  api_consumer: "#45f0e5",
  external: "#ff3eb5",
  process: "#ff476f",
  symbol: "#a8b4ff",
  unknown: "#74819e",
};

export const NODE_HALO: Record<string, string> = {
  process: "rgba(255, 93, 108, 0.28)",
  route: "rgba(255, 94, 188, 0.28)",
  class: "rgba(255, 138, 61, 0.28)",
  interface: "rgba(255, 138, 61, 0.28)",
};

export const COMMUNITY_COLORS = [
  "#5b7cff",
  "#7c5cff",
  "#ff7a2f",
  "#20c7d7",
  "#39f58b",
  "#ff3eb5",
  "#ffd166",
  "#a855f7",
  "#fb7185",
  "#34d399",
  "#38bdf8",
  "#f97316",
  "#e879f9",
  "#84cc16",
  "#facc15",
  "#818cf8",
];

export const EDGE_COLORS: Record<string, string> = {
  CONTAINS: "#1b2233",
  DEFINES: "#184d59",
  CALLS: "#3b2479",
  ACCESSES: "#2b3d75",
  IMPLEMENTS: "#6b381f",
  EXTENDS: "#6b381f",
  HANDLES_ROUTE: "#7a245f",
  ROUTES_TO: "#7a245f",
  USES_MIDDLEWARE: "#5c2748",
  TESTS: "#6d5520",
  TESTS_SYMBOL: "#6d5520",
  QUERIES: "#51308a",
  FETCHES: "#155866",
  CALLS_EXTERNAL: "#6b381f",
  STEP_IN_PROCESS: "#84273d",
  PROCESS_STEP: "#84273d",
  IMPORTS: "#252d40",
  UNKNOWN: "#252d40",
};

export function nodeColor(kind: string): string {
  return NODE_COLORS[kind] ?? NODE_COLORS.unknown;
}

export function overviewNodeColor(kind: string, scope: string): string {
  if (kind === "route" || kind === "process" || kind === "external" || kind === "api_consumer") {
    return nodeColor(kind);
  }
  return COMMUNITY_COLORS[hashString(moduleScope(scope)) % COMMUNITY_COLORS.length];
}

export function edgeColor(type: string): string {
  return EDGE_COLORS[type] ?? EDGE_COLORS.UNKNOWN;
}

export function baseNodeSize(kind: string): number {
  switch (kind) {
    case "process":
      return 9;
    case "route":
      return 7.5;
    case "class":
    case "interface":
      return 7;
    case "folder":
      return 5.5;
    case "file":
      return 4.6;
    case "function":
    case "method":
      return 4.4;
    default:
      return 4;
  }
}

export function baseEdgeSize(type: string): number {
  switch (type) {
    case "STEP_IN_PROCESS":
    case "PROCESS_STEP":
      return 1.4;
    case "HANDLES_ROUTE":
      return 0.8;
    case "CALLS":
    case "CALLS_EXTERNAL":
    case "FETCHES":
    case "QUERIES":
    case "TESTS":
      return 0.45;
    case "CONTAINS":
    case "IMPORTS":
      return 0.25;
    default:
      return 0.35;
  }
}

function moduleScope(scope: string): string {
  const clean = scope.replace(/^file:/, "").replace(/^symbol:/, "");
  const parts = clean.split(/[/.\\:]+/).filter(Boolean);
  if (parts.length === 0) {
    return clean;
  }
  const srcIndex = parts.findIndex((part) => part === "src" || part === "app" || part === "ui");
  if (srcIndex >= 0 && parts[srcIndex + 1]) {
    const first = parts[srcIndex + 1];
    const second = parts[srcIndex + 2];
    const third = parts[srcIndex + 3];
    if ((first === "codegraphkb" || first === "src") && second) {
      return `${second}:${third ?? ""}`;
    }
    return `${first}:${second ?? ""}`;
  }
  return parts.slice(0, 2).join(":");
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
