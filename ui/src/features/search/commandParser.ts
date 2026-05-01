import type { GraphView, QueryExecution } from "../../types/graph";

const VIEW_SET = new Set<GraphView>(["repo", "processes"]);

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
    return { perspective: "framework", target: "routes" };
  }
  if (head === "tests") {
    return { perspective: "framework", target: "tests" };
  }
  if (head === "calls") {
    return { perspective: "calls", target: tail || undefined };
  }
  if (head === "symbols") {
    return { perspective: "symbols", target: tail || undefined };
  }
  if (head === "framework") {
    return { perspective: "framework", target: tail || undefined };
  }
  if (head === "full") {
    return { perspective: "none" };
  }

  return { perspective: "none" };
}
