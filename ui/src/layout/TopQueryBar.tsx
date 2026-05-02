import type { GraphView, QueryExecution, SearchResult, SummaryResponse } from "../types/graph";

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
  searchResults?: SearchResult[];
  onSelectSearchResult?: (result: SearchResult) => void;
}

const views: GraphView[] = ["full", "repo", "symbols", "calls", "framework", "processes"];
const viewLabels: Record<GraphView, string> = {
  full: "overview",
  repo: "repo",
  symbols: "symbols",
  calls: "calls",
  framework: "framework",
  processes: "processes",
};

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
  searchResults = [],
  onSelectSearchResult,
}: TopQueryBarProps) {
  return (
    <header className="top-query-bar">
      <div className="brand">
        <span className="brand-mark">CG</span>
        <div>
          <strong>CodeGraphKB</strong>
          <span>{summary?.repo ?? "repo"}</span>
        </div>
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
          placeholder="Search nodes... or run: repo, search <symbol>, impact <target>"
        />
        {query.trim().length >= 2 && searchResults.length > 0 ? (
          <div className="search-popover">
            {groupSearchResults(searchResults).map(([kind, results]) => (
              <section key={kind}>
                <h4>{kind}</h4>
                {results.slice(0, 6).map((result) => (
                  <button
                    key={result.id}
                    type="button"
                    onClick={() => onSelectSearchResult?.(result)}
                  >
                    <span>{result.label}</span>
                    <small>{result.file_path ?? result.id}</small>
                  </button>
                ))}
              </section>
            ))}
          </div>
        ) : null}
        <button type="button" onClick={onRunQuery}>
          Run
        </button>
      </div>
      <div className="top-controls">
        <button type="button" className="star-button">
          Star if cool
        </button>
        <span className="top-stat">{summary?.symbols ?? 0} nodes</span>
        <span className="top-stat">{summary?.edges ?? 0} edges</span>
        <span className="embedding-pill">Indexed {summary?.files ?? 0}/{summary?.symbols ?? 0}</span>
        <label>
          View
          <select value={selectedView} onChange={(e) => onViewChange(e.target.value as GraphView)}>
            {views.map((view) => (
              <option value={view} key={view}>
                {viewLabels[view]}
              </option>
            ))}
          </select>
        </label>
        <span className={`status-pill ${layoutStatus}`}>{layoutStatus}</span>
        <span className="execution-pill">{execution.perspective === "full" ? "overview" : execution.perspective}</span>
        <button type="button" className="icon-button" title="Settings">
          S
        </button>
        <button type="button" onClick={onAskClick}>
          Nexus AI
        </button>
      </div>
    </header>
  );
}

function groupSearchResults(results: SearchResult[]): Array<[string, SearchResult[]]> {
  const groups = new Map<string, SearchResult[]>();
  for (const result of results.slice(0, 24)) {
    const key = result.kind || "unknown";
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(result);
  }
  return Array.from(groups.entries());
}
