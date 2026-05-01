export const NODE_COLORS: Record<string, string> = {
  repo: "#9a82ff",
  folder: "#5f7595",
  file: "#4d8dff",
  function: "#2bd576",
  method: "#2bd576",
  class: "#ff8a3d",
  interface: "#ff8a3d",
  type_alias: "#ffb380",
  enum: "#ffb380",
  route: "#ff5ebc",
  test: "#f5c84b",
  test_block: "#f5c84b",
  model: "#a56bff",
  database_table: "#a56bff",
  api_consumer: "#20c7d7",
  external: "#20c7d7",
  process: "#ff5d6c",
  symbol: "#9aa6bd",
  unknown: "#7d8aa1",
};

export const NODE_HALO: Record<string, string> = {
  process: "rgba(255, 93, 108, 0.28)",
  route: "rgba(255, 94, 188, 0.28)",
  class: "rgba(255, 138, 61, 0.28)",
  interface: "rgba(255, 138, 61, 0.28)",
};

export const EDGE_COLORS: Record<string, string> = {
  CONTAINS: "rgba(120, 130, 150, 0.14)",
  DEFINES: "rgba(32, 199, 215, 0.32)",
  CALLS: "rgba(124, 92, 255, 0.42)",
  ACCESSES: "rgba(124, 92, 255, 0.32)",
  IMPLEMENTS: "rgba(255, 138, 61, 0.42)",
  EXTENDS: "rgba(255, 138, 61, 0.42)",
  HANDLES_ROUTE: "rgba(255, 94, 188, 0.55)",
  USES_MIDDLEWARE: "rgba(255, 94, 188, 0.32)",
  TESTS: "rgba(245, 200, 75, 0.45)",
  TESTS_SYMBOL: "rgba(245, 200, 75, 0.45)",
  QUERIES: "rgba(165, 107, 255, 0.5)",
  FETCHES: "rgba(32, 199, 215, 0.5)",
  CALLS_EXTERNAL: "rgba(255, 138, 61, 0.5)",
  STEP_IN_PROCESS: "rgba(255, 93, 108, 0.7)",
  PROCESS_STEP: "rgba(255, 93, 108, 0.7)",
  IMPORTS: "rgba(120, 130, 150, 0.22)",
  UNKNOWN: "rgba(120, 130, 150, 0.18)",
};

export function nodeColor(kind: string): string {
  return NODE_COLORS[kind] ?? NODE_COLORS.unknown;
}

export function edgeColor(type: string): string {
  return EDGE_COLORS[type] ?? EDGE_COLORS.UNKNOWN;
}

export function baseNodeSize(kind: string): number {
  switch (kind) {
    case "process":
      return 11;
    case "route":
      return 9;
    case "class":
    case "interface":
      return 8;
    case "folder":
      return 7;
    case "file":
      return 6;
    case "function":
    case "method":
      return 5.5;
    default:
      return 5;
  }
}

export function baseEdgeSize(type: string): number {
  switch (type) {
    case "STEP_IN_PROCESS":
    case "PROCESS_STEP":
      return 2.4;
    case "HANDLES_ROUTE":
      return 1.4;
    case "CALLS":
    case "CALLS_EXTERNAL":
    case "FETCHES":
    case "QUERIES":
    case "TESTS":
      return 1.0;
    case "CONTAINS":
    case "IMPORTS":
      return 0.55;
    default:
      return 0.8;
  }
}
