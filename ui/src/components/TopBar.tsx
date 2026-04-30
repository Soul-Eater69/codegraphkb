import type { GraphView, SummaryResponse } from "../types/graph";

interface TopBarProps {
  summary: SummaryResponse | null;
  view: GraphView;
  onViewChange: (view: GraphView) => void;
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  onSearchSubmit: () => void;
  loading: boolean;
  onAskClick: () => void;
}

const views: GraphView[] = ["repo", "symbols", "calls", "framework", "processes", "full"];

export function TopBar({
  summary,
  view,
  onViewChange,
  searchQuery,
  onSearchQueryChange,
  onSearchSubmit,
  loading,
  onAskClick,
}: TopBarProps) {
  return (
    <header className="topbar">
      <div className="brand">
        <h1>CodeGraphKB</h1>
        <p title={summary?.repo_path || ""}>{summary?.repo || "repo"}</p>
        <p className="brand-metrics">
          f {summary?.files ?? 0} · s {summary?.symbols ?? 0} · e {summary?.edges ?? 0} · p {summary?.processes ?? 0}
        </p>
      </div>

      <div className="topbar-search">
        <input
          type="text"
          placeholder="Search files, symbols, routes, processes..."
          value={searchQuery}
          onChange={(e) => onSearchQueryChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              onSearchSubmit();
            }
          }}
        />
        <button type="button" onClick={onSearchSubmit} disabled={loading}>
          {loading ? "Searching..." : "Search"}
        </button>
      </div>

      <div className="topbar-controls">
        <label>
          View
          <select value={view} onChange={(e) => onViewChange(e.target.value as GraphView)}>
            {views.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={onAskClick}>
          Ask CodeGraphKB
        </button>
      </div>
    </header>
  );
}
