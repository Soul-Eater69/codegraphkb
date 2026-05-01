import { useMemo, useState } from "react";
import type { GraphPayload, Perspective } from "../types/graph";
import { EDGE_COLORS, NODE_COLORS } from "./graphStyles";
import { toSigmaGraph } from "./graphAdapter";
import { SigmaCanvas } from "./SigmaCanvas";

interface GraphSceneProps {
  perspective: Perspective;
  graph: GraphPayload | null;
  notice?: string;
  loading: boolean;
  error: string | null;
  selectedNodeKinds: Set<string>;
  selectedEdgeTypes: Set<string>;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  onNodeClick: (nodeId: string) => void;
  onEdgeClick: (edgeId: string, edgePayload: Record<string, unknown>) => void;
  onStageClick: () => void;
  onQuickAction: (action: "repo" | "calls" | "processes" | "symbols" | "framework") => void;
  onLayoutStatusChange?: (status: "frozen" | "running") => void;
}

export function GraphScene({
  perspective,
  graph,
  notice,
  loading,
  error,
  selectedNodeKinds,
  selectedEdgeTypes,
  selectedNodeId,
  selectedEdgeId,
  onNodeClick,
  onEdgeClick,
  onStageClick,
  onQuickAction,
  onLayoutStatusChange,
}: GraphSceneProps) {
  const [labelsEnabled, setLabelsEnabled] = useState(true);
  const [legendOpen, setLegendOpen] = useState(false);

  const tooLarge =
    graph != null &&
    ((graph.metadata.node_count ?? graph.nodes.length) > 1000 ||
      (graph.metadata.edge_count ?? graph.edges.length) > 2000);

  const sigmaGraph = useMemo(() => {
    if (!graph || tooLarge) {
      return null;
    }
    return toSigmaGraph(graph, perspective, selectedNodeKinds, selectedEdgeTypes);
  }, [graph, perspective, selectedNodeKinds, selectedEdgeTypes, tooLarge]);

  return (
    <section className="graph-scene">
      {graph == null && !loading && !error ? (
        <div className="scene-empty">
          <h2>Query-first graph workspace</h2>
          <p>{notice || "Pick a perspective or run a command to load a controlled graph slice."}</p>
          <div className="quick-actions">
            <button type="button" onClick={() => onQuickAction("repo")}>
              Open Repo Map
            </button>
            <button type="button" onClick={() => onQuickAction("calls")}>
              Search Symbol First
            </button>
            <button type="button" onClick={() => onQuickAction("processes")}>
              Open Process Flows
            </button>
            <button type="button" onClick={() => onQuickAction("symbols")}>
              Open Symbols Scope
            </button>
            <button type="button" onClick={() => onQuickAction("framework")}>
              Open Framework Entrypoints
            </button>
          </div>
        </div>
      ) : null}

      {loading ? <div className="scene-overlay">Loading graph slice...</div> : null}
      {error ? <div className="scene-overlay error">{error}</div> : null}
      {tooLarge ? (
        <div className="scene-overlay">
          <div className="large-message">
            <h3>This graph slice is too large.</h3>
            <p>Start with a focused perspective, then pivot with search or neighborhood.</p>
            <div className="quick-actions">
              <button type="button" onClick={() => onQuickAction("repo")}>
                Repo Map
              </button>
              <button type="button" onClick={() => onQuickAction("calls")}>
                Search Symbol
              </button>
              <button type="button" onClick={() => onQuickAction("processes")}>
                Process Flows
              </button>
              <button type="button" onClick={() => onQuickAction("symbols")}>
                Symbols Scope
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {sigmaGraph ? (
        <SigmaCanvas
          graph={sigmaGraph}
          selectedNodeId={selectedNodeId}
          selectedEdgeId={selectedEdgeId}
          labelsEnabled={labelsEnabled}
          onToggleLabels={() => setLabelsEnabled((v) => !v)}
          onNodeClick={onNodeClick}
          onEdgeClick={onEdgeClick}
          onStageClick={onStageClick}
          onLayoutStatusChange={onLayoutStatusChange}
        />
      ) : null}

      <div className="legend-pill">
        <button type="button" onClick={() => setLegendOpen((v) => !v)}>
          {legendOpen ? "Legend ▾" : "Legend ▸"}
        </button>
        {legendOpen ? (
          <div className="legend-popover">
            <h4>Node Colors</h4>
            <ul>
              {Object.entries(NODE_COLORS).map(([kind, color]) => (
                <li key={kind}>
                  <span className="dot" style={{ background: color }} />
                  <span>{kind}</span>
                </li>
              ))}
            </ul>
            <h4>Edge Colors</h4>
            <ul>
              {Object.entries(EDGE_COLORS).map(([type, color]) => (
                <li key={type}>
                  <span className="line" style={{ background: color }} />
                  <span>{type}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}
