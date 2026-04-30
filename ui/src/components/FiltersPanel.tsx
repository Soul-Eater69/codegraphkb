interface FiltersPanelProps {
  nodeKindCounts: Record<string, number>;
  edgeTypeCounts: Record<string, number>;
  selectedNodeKinds: Set<string>;
  selectedEdgeTypes: Set<string>;
  onToggleNodeKind: (kind: string) => void;
  onToggleEdgeType: (type: string) => void;
}

export function FiltersPanel({
  nodeKindCounts,
  edgeTypeCounts,
  selectedNodeKinds,
  selectedEdgeTypes,
  onToggleNodeKind,
  onToggleEdgeType,
}: FiltersPanelProps) {
  const nodeKinds = Object.entries(nodeKindCounts).sort((a, b) => b[1] - a[1]);
  const edgeTypes = Object.entries(edgeTypeCounts).sort((a, b) => b[1] - a[1]);

  return (
    <div className="filters-panel">
      <h3>Node Kinds</h3>
      <ul>
        {nodeKinds.length === 0 ? <li className="muted">No node kinds in this view.</li> : null}
        {nodeKinds.map(([kind, count]) => (
          <li key={kind}>
            <label>
              <input
                type="checkbox"
                checked={selectedNodeKinds.size === 0 || selectedNodeKinds.has(kind)}
                onChange={() => onToggleNodeKind(kind)}
              />
              <span>{kind}</span>
            </label>
            <strong>{count}</strong>
          </li>
        ))}
      </ul>

      <h3>Edge Types</h3>
      <ul>
        {edgeTypes.length === 0 ? <li className="muted">No edge types in this view.</li> : null}
        {edgeTypes.map(([type, count]) => (
          <li key={type}>
            <label>
              <input
                type="checkbox"
                checked={selectedEdgeTypes.size === 0 || selectedEdgeTypes.has(type)}
                onChange={() => onToggleEdgeType(type)}
              />
              <span>{type}</span>
            </label>
            <strong>{count}</strong>
          </li>
        ))}
      </ul>
      <p className="muted notice">UI-2 filters update counts; canvas filtering lands in UI-3.</p>
    </div>
  );
}
