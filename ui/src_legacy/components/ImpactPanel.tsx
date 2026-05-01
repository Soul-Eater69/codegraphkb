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
  const nodeCount = impactGraph?.nodes.length ?? 0;
  const edgeCount = impactGraph?.edges.length ?? 0;
  const severity = nodeCount > 200 ? "High" : nodeCount > 80 ? "Medium" : "Low";

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
            Nodes <strong>{nodeCount}</strong> · Edges <strong>{edgeCount}</strong>
          </p>
          <p className="muted">Target: {String(impactGraph.metadata?.target ?? impactTarget)}</p>
          <p className={`risk-badge risk-${severity.toLowerCase()}`}>Risk {severity}</p>
        </div>
      ) : (
        <p className="muted">Run an impact query to inspect blast radius and related symbols.</p>
      )}
    </div>
  );
}
