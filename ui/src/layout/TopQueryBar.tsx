import type { GraphView, QueryExecution, SummaryResponse } from "../types/graph";

interface TopQueryBarProps {
  summary: SummaryResponse | null;
  query: string;
  onQueryChange: (value: string) => void;
  onRunQuery: () => void;
  onAskClick: () => void;
  selectedView: GraphView;
  onViewChange: (view: GraphView) => void;
  execution: QueryExecution;
  layoutStatus: "frozen" | "running";
}

const views: GraphView[] = ["repo", "symbols", "calls", "framework", "processes", "full"];

export function TopQueryBar({
  summary,
  query,
  onQueryChange,
  onRunQuery,
  onAskClick,
  selectedView,
  onViewChange,
  execution,
  layoutStatus,
}: TopQueryBarProps) {
  return (
    <header className="top-query-bar">
      <div className="brand">
        <strong>CodeGraphKB</strong>
        <span>{summary?.repo ?? "repo"}</span>
      </div>
      <div className="query-input-wrap">
        <input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              onRunQuery();
            }
          }}
          placeholder="repo | calls | impact <target> | neighborhood <node_id>"
        />
        <button type="button" onClick={onRunQuery}>
          Run
        </button>
      </div>
      <div className="top-controls">
        <label>
          View
          <select value={selectedView} onChange={(e) => onViewChange(e.target.value as GraphView)}>
            {views.map((view) => (
              <option value={view} key={view}>
                {view}
              </option>
            ))}
          </select>
        </label>
        <span className={`status-pill ${layoutStatus}`}>{layoutStatus}</span>
        <span className="execution-pill">{execution.perspective}</span>
        <button type="button" onClick={onAskClick}>
          Ask
        </button>
      </div>
    </header>
  );
}
