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
  highlightedNodeIds: Set<string>;
  onNodeClick: (nodeId: string) => void;
  onEdgeClick: (edgeId: string, edgePayload: Record<string, unknown>) => void;
  onStageClick: () => void;
  onQuickAction: (action: "full" | "repo" | "calls" | "processes" | "symbols" | "framework") => void;
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
  highlightedNodeIds,
  onNodeClick,
  onEdgeClick,
  onStageClick,
  onQuickAction,
  onLayoutStatusChange,
}: GraphSceneProps) {
  const [labelsEnabled, setLabelsEnabled] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);

  const nodeLimit = perspective === "full" ? 9000 : 2500;
  const edgeLimit = perspective === "full" ? 30000 : 8000;
  const tooLarge =
    graph != null &&
    ((graph.metadata.node_count ?? graph.nodes.length) > nodeLimit ||
      (graph.metadata.edge_count ?? graph.edges.length) > edgeLimit);
  const emptyGraph = graph != null && graph.nodes.length === 0 && !loading && !error;

  const sigmaGraph = useMemo(() => {
    if (!graph || tooLarge) {
      return null;
    }
    return toSigmaGraph(graph, perspective, selectedNodeKinds, selectedEdgeTypes);
  }, [graph, perspective, selectedNodeKinds, selectedEdgeTypes, tooLarge]);
  const emptyCopy = emptyStateForPerspective(perspective);

  return (
    <section className="graph-scene">
      {graph == null && !loading && !error ? (
        <div className="scene-empty">
          <h2>Query-first graph workspace</h2>
          <p>{notice || "Pick a perspective or run a command to load a controlled graph slice. The full graph stays bounded; pivot from a target, never dump it all."}</p>
          <div className="quick-actions">
            <button type="button" onClick={() => onQuickAction("repo")}>
              <strong>Repo Map</strong>
              <small>Hierarchical view of folders and files. Bounded to 500 nodes.</small>
            </button>
            <button type="button" onClick={() => onQuickAction("full")}>
              <strong>Overview</strong>
              <small>GitNexus-style mixed graph scene capped for browser performance.</small>
            </button>
            <button type="button" onClick={() => onQuickAction("calls")}>
              <strong>Call Graph</strong>
              <small>Search a symbol first, then explore callers and callees.</small>
            </button>
            <button type="button" onClick={() => onQuickAction("processes")}>
              <strong>Process Flows</strong>
              <small>Ordered route to handler to service to DB walkthroughs.</small>
            </button>
            <button type="button" onClick={() => onQuickAction("symbols")}>
              <strong>Symbols Scope</strong>
              <small>Pick a file or module to inspect classes and functions.</small>
            </button>
            <button type="button" onClick={() => onQuickAction("framework")}>
              <strong>Framework Entrypoints</strong>
              <small>Routes, middleware, models, external calls and tests.</small>
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
      {emptyGraph ? (
        <div className="scene-overlay">
          <div className="large-message">
            <h3>{emptyCopy.title}</h3>
            <p>{emptyCopy.body}</p>
            <div className="quick-actions">
              {emptyCopy.actions.map((action) => (
                <button key={action.action} type="button" onClick={() => onQuickAction(action.action)}>
                  {action.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {sigmaGraph && graph != null && graph.nodes.length > 0 ? (
        <SigmaCanvas
          graph={sigmaGraph}
          autoLayout={["full", "calls", "framework", "neighborhood"].includes(perspective)}
          selectedNodeId={selectedNodeId}
          selectedEdgeId={selectedEdgeId}
          highlightedNodeIds={highlightedNodeIds}
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
          {legendOpen ? "Legend v" : "Legend >"}
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

function emptyStateForPerspective(perspective: Perspective): {
  title: string;
  body: string;
  actions: Array<{ label: string; action: "full" | "repo" | "calls" | "processes" | "symbols" | "framework" }>;
} {
  if (perspective === "processes") {
    return {
      title: "No process flows in this index.",
      body: "This repo has no extracted process traces yet. Open Overview or Framework, or index an example with process maps.",
      actions: [
        { label: "Overview", action: "full" },
        { label: "Framework", action: "framework" },
        { label: "Repo Map", action: "repo" },
      ],
    };
  }
  if (perspective === "symbols") {
    return {
      title: "Select a file or search a symbol.",
      body: "Symbols are shown as a focused file or module scene, not as a full-repo hairball.",
      actions: [
        { label: "Repo Map", action: "repo" },
        { label: "Overview", action: "full" },
      ],
    };
  }
  if (perspective === "calls") {
    return {
      title: "Search a symbol to open its call graph.",
      body: "The UI no longer dumps the global call graph. Pick a function, class, route, or method first.",
      actions: [
        { label: "Overview", action: "full" },
        { label: "Symbols Scope", action: "symbols" },
      ],
    };
  }
  return {
    title: "No graph nodes in this perspective yet.",
    body: "Try Overview, Repo Map, or search for a symbol to open a focused neighborhood.",
    actions: [
      { label: "Overview", action: "full" },
      { label: "Repo Map", action: "repo" },
      { label: "Symbols Scope", action: "symbols" },
    ],
  };
}
