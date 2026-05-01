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
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  onToggleLeft: () => void;
  onToggleRight: () => void;
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
  leftCollapsed,
  rightCollapsed,
  onToggleLeft,
  onToggleRight,
}: TopBarProps) {
  return (
    <header className="topbar">
      <div className="topbar-brand">
        <strong>CodeGraphKB</strong>
        <span title={summary?.repo_path || ""}>{summary?.repo || "repo"}</span>
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
          <span>View</span>
          <select value={view} onChange={(e) => onViewChange(e.target.value as GraphView)}>
            {views.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <div className="topbar-metrics">
          <span>{summary?.files ?? 0} files</span>
          <span>{summary?.symbols ?? 0} symbols</span>
          <span>{summary?.edges ?? 0} edges</span>
          <span>{summary?.processes ?? 0} processes</span>
        </div>
        <span className={`health-pill ${summary?.index_health === "stale" ? "stale" : "ok"}`}>
          {summary?.index_health === "stale" ? "stale index" : "index healthy"}
        </span>
        <button type="button" title="Toggle explorer panel" onClick={onToggleLeft}>
          {leftCollapsed ? "◧" : "◨"}
        </button>
        <button type="button" title="Toggle inspector panel" onClick={onToggleRight}>
          {rightCollapsed ? "◨" : "◧"}
        </button>
        <button type="button" onClick={onAskClick}>
          Ask
        </button>
      </div>
    </header>
  );
}
