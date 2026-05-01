import type { SummaryResponse } from "../types/graph";

interface GraphInfoPanelProps {
  summary: SummaryResponse | null;
}

export function GraphInfoPanel({ summary }: GraphInfoPanelProps) {
  return (
    <section className="panel">
      <h3>Graph Info</h3>
      <ul>
        <li>
          <span>Repo</span>
          <strong>{summary?.repo ?? "—"}</strong>
        </li>
        <li>
          <span>Files</span>
          <strong>{summary?.files ?? 0}</strong>
        </li>
        <li>
          <span>Symbols</span>
          <strong>{summary?.symbols ?? 0}</strong>
        </li>
        <li>
          <span>Edges</span>
          <strong>{summary?.edges ?? 0}</strong>
        </li>
        <li>
          <span>Processes</span>
          <strong>{summary?.processes ?? 0}</strong>
        </li>
      </ul>
      <p className="muted">Index: {summary?.index_health ?? "unknown"}</p>
    </section>
  );
}
