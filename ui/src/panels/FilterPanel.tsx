import { NODE_COLORS, EDGE_COLORS } from "../graph/graphStyles";

interface FilterPanelProps {
  nodeKinds: Record<string, number>;
  edgeTypes: Record<string, number>;
  selectedNodeKinds: Set<string>;
  selectedEdgeTypes: Set<string>;
  onToggleNodeKind: (kind: string) => void;
  onToggleEdgeType: (type: string) => void;
}

export function FilterPanel({
  nodeKinds,
  edgeTypes,
  selectedNodeKinds,
  selectedEdgeTypes,
  onToggleNodeKind,
  onToggleEdgeType,
}: FilterPanelProps) {
  const sortedKinds = Object.entries(nodeKinds).sort((a, b) => b[1] - a[1]);
  const sortedTypes = Object.entries(edgeTypes).sort((a, b) => b[1] - a[1]);
  const hasNodes = sortedKinds.length > 0;
  const hasEdges = sortedTypes.length > 0;

  return (
    <section className="panel">
      <h3>Filters</h3>

      <h4>Node Kinds</h4>
      {hasNodes ? (
        <div className="kind-chips">
          {sortedKinds.map(([kind, count]) => {
            const active = selectedNodeKinds.size === 0 || selectedNodeKinds.has(kind);
            return (
              <button
                key={kind}
                type="button"
                className={`kind-chip ${active ? "active" : ""}`}
                onClick={() => onToggleNodeKind(kind)}
              >
                <span className="dot" style={{ background: NODE_COLORS[kind] ?? NODE_COLORS.unknown }} />
                <span>{kind}</span>
                <span className="count">{count}</span>
              </button>
            );
          })}
        </div>
      ) : (
        <p className="muted">Load a graph slice to filter by kind.</p>
      )}

      <h4>Edge Types</h4>
      {hasEdges ? (
        <div className="kind-chips">
          {sortedTypes.map(([type, count]) => {
            const active = selectedEdgeTypes.size === 0 || selectedEdgeTypes.has(type);
            const color = EDGE_COLORS[type] ?? EDGE_COLORS.UNKNOWN;
            return (
              <button
                key={type}
                type="button"
                className={`kind-chip ${active ? "active" : ""}`}
                onClick={() => onToggleEdgeType(type)}
              >
                <span className="dot" style={{ background: color }} />
                <span>{type}</span>
                <span className="count">{count}</span>
              </button>
            );
          })}
        </div>
      ) : (
        <p className="muted">No edges to filter yet.</p>
      )}
    </section>
  );
}
