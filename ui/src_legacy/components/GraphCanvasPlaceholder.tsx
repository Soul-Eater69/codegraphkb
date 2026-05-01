import type { GraphPayload, GraphView } from "../types/graph";

interface GraphCanvasPlaceholderProps {
  view: GraphView;
  graph: GraphPayload | null;
  filteredNodeCount: number;
  filteredEdgeCount: number;
  loading: boolean;
  error: string | null;
}

export function GraphCanvasPlaceholder({
  view,
  graph,
  filteredNodeCount,
  filteredEdgeCount,
  loading,
  error,
}: GraphCanvasPlaceholderProps) {
  const nodeKinds = topCounts(graph?.nodes.map((n) => n.kind) ?? []);
  const edgeTypes = topCounts(graph?.edges.map((e) => e.type) ?? []);

  return (
    <section className="graph-placeholder">
      <div className="panel-header">
        <h2>Graph View: {view}</h2>
      </div>
      {loading ? <p className="muted">Loading graph slice...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      {!loading && !error ? (
        <div className="placeholder-stats">
          <div className="stat-grid">
            <div className="stat-card">
              <span>Nodes</span>
              <strong>{filteredNodeCount}</strong>
            </div>
            <div className="stat-card">
              <span>Edges</span>
              <strong>{filteredEdgeCount}</strong>
            </div>
            <div className="stat-card">
              <span>Total Nodes</span>
              <strong>{graph?.nodes.length ?? 0}</strong>
            </div>
            <div className="stat-card">
              <span>Total Edges</span>
              <strong>{graph?.edges.length ?? 0}</strong>
            </div>
          </div>

          <div className="placeholder-lists">
            <div>
              <h3>Top Node Kinds</h3>
              <ul>
                {nodeKinds.length === 0 ? <li className="muted">No node data.</li> : null}
                {nodeKinds.map(([kind, count]) => (
                  <li key={kind}>
                    <span>{kind}</span>
                    <strong>{count}</strong>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3>Top Edge Types</h3>
              <ul>
                {edgeTypes.length === 0 ? <li className="muted">No edge data.</li> : null}
                {edgeTypes.map(([type, count]) => (
                  <li key={type}>
                    <span>{type}</span>
                    <strong>{count}</strong>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <p className="muted notice">
            Sigma.js graph canvas arrives in Phase UI-3. This panel currently reports loaded graph slice stats.
          </p>
        </div>
      ) : null}
    </section>
  );
}

function topCounts(values: string[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const v of values) {
    counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
}
