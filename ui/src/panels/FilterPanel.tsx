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

  return (
    <section className="panel">
      <h3>Filters</h3>
      <h4>Node Kinds</h4>
      <ul>
        {sortedKinds.map(([kind, count]) => (
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
      <h4>Edge Types</h4>
      <ul>
        {sortedTypes.map(([type, count]) => (
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
    </section>
  );
}
