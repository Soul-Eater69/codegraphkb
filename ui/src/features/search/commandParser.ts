import type { GraphView, QueryExecution } from "../../types/graph";

const VIEW_SET = new Set<GraphView>(["repo", "symbols", "calls", "framework", "processes", "full"]);

export function parseQueryCommand(input: string): QueryExecution {
  const trimmed = input.trim();
  if (!trimmed) {
    return { perspective: "none" };
  }

  const [headRaw, ...rest] = trimmed.split(/\s+/);
  const head = headRaw.toLowerCase();
  const tail = rest.join(" ").trim();

  if (VIEW_SET.has(head as GraphView)) {
    return { perspective: head as GraphView, view: head as GraphView };
  }
  if (head === "impact" && tail) {
    return { perspective: "impact", target: tail };
  }
  if (head === "neighborhood" && tail) {
    return { perspective: "neighborhood", nodeId: tail };
  }
  if (head === "routes") {
    return { perspective: "framework", view: "framework" };
  }
  if (head === "tests") {
    return { perspective: "framework", view: "framework" };
  }

  return { perspective: "none" };
}
