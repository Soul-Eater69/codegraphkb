export const NODE_COLORS: Record<string, string> = {
  file: "#4d8dff",
  folder: "#6b7280",
  function: "#2bd576",
  method: "#2bd576",
  class: "#ff9f43",
  interface: "#ff9f43",
  route: "#ff5ebc",
  test: "#f5c84b",
  test_block: "#f5c84b",
  model: "#a56bff",
  database_table: "#a56bff",
  api_consumer: "#20c7d7",
  external: "#20c7d7",
  process: "#ff5d6c",
  unknown: "#8b98ad",
};

export const EDGE_COLORS: Record<string, string> = {
  CONTAINS: "rgba(148, 163, 184, 0.28)",
  DEFINES: "rgba(32, 199, 215, 0.35)",
  CALLS: "rgba(124, 92, 255, 0.42)",
  HANDLES_ROUTE: "rgba(255, 94, 188, 0.45)",
  TESTS: "rgba(245, 200, 75, 0.45)",
  TESTS_SYMBOL: "rgba(245, 200, 75, 0.45)",
  QUERIES: "rgba(165, 107, 255, 0.45)",
  FETCHES: "rgba(32, 199, 215, 0.45)",
  CALLS_EXTERNAL: "rgba(255, 138, 61, 0.45)",
  STEP_IN_PROCESS: "rgba(255, 93, 108, 0.62)",
  IMPORTS: "rgba(148, 163, 184, 0.3)",
  UNKNOWN: "rgba(148, 163, 184, 0.28)",
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
      return 10;
    case "route":
      return 8;
    case "class":
    case "interface":
      return 7;
    case "folder":
      return 7;
    case "file":
      return 6;
    default:
      return 5;
  }
}
