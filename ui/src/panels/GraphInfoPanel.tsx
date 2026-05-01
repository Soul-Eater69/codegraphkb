import type { SummaryResponse } from "../types/graph";

interface GraphInfoPanelProps {
  summary: SummaryResponse | null;
}

export function GraphInfoPanel({ summary }: GraphInfoPanelProps) {
  const rows: Array<[string, string | number]> = [
    ["Repo", summary?.repo ?? "—"],
    ["Files", summary?.files ?? 0],
    ["Symbols", summary?.symbols ?? 0],
    ["Edges", summary?.edges ?? 0],
    ["Processes", summary?.processes ?? 0],
  ];
  return (
    <section className="panel">
      <h3>Graph Info</h3>
      <div className="info-rows">
        {rows.map(([label, value]) => (
          <div className="info-row" key={label}>
            <span>{label}</span>
            <span>{String(value)}</span>
          </div>
        ))}
      </div>
      <p className="muted">Index: {summary?.index_health ?? "unknown"}</p>
    </section>
  );
}
