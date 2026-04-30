export const NODE_COLORS: Record<string, string> = {
  folder: "#64748b",
  file: "#3b82f6",
  module: "#60a5fa",
  function: "#22c55e",
  method: "#14b8a6",
  class: "#f97316",
  interface: "#f59e0b",
  type_alias: "#fbbf24",
  enum: "#facc15",
  route: "#ec4899",
  test: "#fde047",
  test_block: "#fde047",
  model: "#a855f7",
  orm_model: "#a855f7",
  database_table: "#9333ea",
  api_consumer: "#06b6d4",
  external: "#d946ef",
  process: "#ef4444",
  unknown: "#94a3b8",
};

export const NODE_SIZES: Record<string, number> = {
  folder: 7,
  file: 6,
  function: 5,
  method: 5,
  class: 8,
  interface: 7,
  route: 9,
  test: 7,
  test_block: 7,
  model: 8,
  api_consumer: 7,
  process: 10,
  external: 8,
  unknown: 5,
};

export const EDGE_COLORS: Record<string, string> = {
  CONTAINS: "#475569",
  DEFINES: "#0891b2",
  IMPORTS: "#2563eb",
  CALLS: "#7c3aed",
  ACCESSES: "#38bdf8",
  HANDLES_ROUTE: "#ec4899",
  ROUTE_HANDLED_BY: "#ec4899",
  USES_MIDDLEWARE: "#f97316",
  TESTS: "#facc15",
  TESTS_SYMBOL: "#facc15",
  QUERIES: "#a855f7",
  MODEL_USED_BY: "#a855f7",
  FETCHES: "#06b6d4",
  CALLS_EXTERNAL: "#d946ef",
  STEP_IN_PROCESS: "#ef4444",
  EXTENDS: "#fb923c",
  IMPLEMENTS: "#f59e0b",
  UNKNOWN: "#64748b",
};

export function nodeColor(kind: string): string {
  return NODE_COLORS[kind] ?? NODE_COLORS.unknown;
}

export function edgeColor(type: string): string {
  return EDGE_COLORS[type] ?? EDGE_COLORS.UNKNOWN;
}

export function baseNodeSize(kind: string): number {
  return NODE_SIZES[kind] ?? NODE_SIZES.unknown;
}

export function dimColor(hex: string, alpha = 0.18): string {
  if (!hex.startsWith("#") || (hex.length !== 7 && hex.length !== 4)) {
    return hex;
  }
  const full = hex.length === 4
    ? `#${hex[1]}${hex[1]}${hex[2]}${hex[2]}${hex[3]}${hex[3]}`
    : hex;
  const a = Math.max(0, Math.min(1, alpha));
  const suffix = Math.round(a * 255).toString(16).padStart(2, "0");
  return `${full}${suffix}`;
}
