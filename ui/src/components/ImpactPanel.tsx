import type { GraphPayload } from "../types/graph";

interface ImpactPanelProps {
  impactTarget: string;
  onImpactTargetChange: (value: string) => void;
  onRunImpact: () => void;
  loading: boolean;
  error: string | null;
  impactGraph: GraphPayload | null;
}

export function ImpactPanel({
  impactTarget,
  onImpactTargetChange,
  onRunImpact,
  loading,
  error,
  impactGraph,
}: ImpactPanelProps) {
  return (
    <div className="impact-panel">
      <h3>Impact</h3>
      <div className="impact-form">
        <input
          type="text"
          placeholder="symbol, file path, route..."
          value={impactTarget}
          onChange={(e) => onImpactTargetChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              onRunImpact();
            }
          }}
        />
        <button type="button" onClick={onRunImpact} disabled={loading || impactTarget.trim().length === 0}>
          {loading ? "Running..." : "Run"}
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      {impactGraph ? (
        <div className="impact-result">
          <p>
            Nodes <strong>{impactGraph.nodes.length}</strong> · Edges <strong>{impactGraph.edges.length}</strong>
          </p>
          <p className="muted">Target: {String(impactGraph.metadata?.target ?? impactTarget)}</p>
        </div>
      ) : (
        <p className="muted">Run an impact query to inspect a local impact graph slice.</p>
      )}
    </div>
  );
}
