import { useMemo } from "react";
import type { GraphPayload, GraphView } from "../types/graph";
import { graphPayloadToGraphology } from "../graph/adapter";
import { EDGE_COLORS, formatKindLabel, NODE_COLORS } from "../graph/styles";
import { useSigma } from "../hooks/useSigma";

interface GraphCanvasProps {
  view: GraphView;
  graph: GraphPayload | null;
  loading: boolean;
  error: string | null;
  selectedNodeKinds: Set<string>;
  selectedEdgeTypes: Set<string>;
  selectedNodeId?: string | null;
  selectedEdgeId?: string | null;
  highlightedNodeIds?: Set<string>;
  nodeKindCounts?: Record<string, number>;
  edgeTypeCounts?: Record<string, number>;
  onNodeSelect: (nodeId: string) => void;
  onStageClick: () => void;
  onEdgeSelect: (edgeId: string, edgeData: unknown) => void;
  onClearSelection: () => void;
  onRequestView: (view: GraphView) => void;
}

export function GraphCanvas({
  view,
  graph,
  loading,
  error,
  selectedNodeKinds,
  selectedEdgeTypes,
  selectedNodeId,
  selectedEdgeId,
  highlightedNodeIds,
  nodeKindCounts = {},
  edgeTypeCounts = {},
  onNodeSelect,
  onStageClick,
  onEdgeSelect,
  onClearSelection,
  onRequestView,
}: GraphCanvasProps) {
  const graphology = useMemo(() => {
    if (!graph) {
      return null;
    }
    if (
      (graph.metadata.node_count ?? graph.nodes.length) > 10000 ||
      (graph.metadata.edge_count ?? graph.edges.length) > 30000
    ) {
      return null;
    }
    return graphPayloadToGraphology(graph);
  }, [graph]);

  const { containerRef, controls, hoveredNodeId, layoutRunning, labelsEnabled, isLargeGraph } = useSigma(graphology, {
    onNodeClick: onNodeSelect,
    onEdgeClick: onEdgeSelect,
    onStageClick,
    selectedNodeId,
    selectedEdgeId,
    visibleNodeKinds: selectedNodeKinds,
    visibleEdgeTypes: selectedEdgeTypes,
    highlightedNodeIds,
  });

  const hoveredNodeAttrs = useMemo(() => {
    if (!graphology || !hoveredNodeId || !graphology.hasNode(hoveredNodeId)) {
      return null;
    }
    return graphology.getNodeAttributes(hoveredNodeId);
  }, [graphology, hoveredNodeId]);

  const tooLarge =
    graph != null &&
    ((graph.metadata.node_count ?? graph.nodes.length) > 10000 ||
      (graph.metadata.edge_count ?? graph.edges.length) > 30000);

  const topNodeKinds = Object.entries(nodeKindCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);
  const topEdgeTypes = Object.entries(edgeTypeCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);

  return (
    <section className="graph-scene">
      <div className="graph-scene-header">
        <div className="graph-scene-title">
          <strong>{graph?.metadata.view ?? view}</strong>
          <span>
            {graph?.nodes.length ?? 0} nodes · {graph?.edges.length ?? 0} edges
          </span>
        </div>
        <div className={`layout-status ${layoutRunning ? "running" : ""}`}>
          {layoutRunning ? "layout running" : "layout idle"}
        </div>
      </div>

      <div className="graph-canvas-wrap">
        {loading ? <div className="overlay">Loading graph slice...</div> : null}
        {error ? <div className="overlay error-box">{error}</div> : null}
        {tooLarge ? (
          <div className="overlay warning-box action-overlay">
            <h3>Large graph slice</h3>
            <p>
              This slice is too large to render directly. Pivot to a focused perspective, then search or open a neighborhood.
            </p>
            <div className="action-grid">
              <button type="button" onClick={() => onRequestView("calls")}>
                Load Calls View
              </button>
              <button type="button" onClick={() => onRequestView("processes")}>
                Load Processes View
              </button>
              <button type="button" onClick={() => onRequestView("repo")}>
                Open Repo View
              </button>
              <button type="button" onClick={() => onRequestView("symbols")}>
                Open Symbols View
              </button>
            </div>
          </div>
        ) : null}
        {graphology == null && !loading && !error && !tooLarge ? (
          <div className="overlay">No graph data available.</div>
        ) : null}

        <div ref={containerRef} className={`sigma-container ${tooLarge ? "hidden" : ""}`} />

        <div className="floating-controls" role="toolbar" aria-label="Graph controls">
          <button type="button" title="Zoom in" onClick={controls.zoomIn}>
            +
          </button>
          <button type="button" title="Zoom out" onClick={controls.zoomOut}>
            −
          </button>
          <button type="button" title="Fit graph" onClick={controls.fit}>
            ⤢
          </button>
          <button type="button" title="Reset layout" onClick={controls.resetLayout}>
            ↺
          </button>
          <button type="button" title="Start or stop layout" onClick={controls.toggleLayout}>
            {layoutRunning ? "■" : "▶"}
          </button>
          <button type="button" title="Toggle labels" onClick={controls.toggleLabels}>
            {labelsEnabled ? "Aa" : "A"}
          </button>
          <button type="button" title="Clear selection" onClick={onClearSelection}>
            ✕
          </button>
        </div>

        {hoveredNodeAttrs ? (
          <div className="hover-card">
            <strong>{hoveredNodeAttrs.label}</strong>
            <span>{formatKindLabel(hoveredNodeAttrs.nodeKind)}</span>
            <small>{hoveredNodeAttrs.filePath ?? hoveredNodeId}</small>
          </div>
        ) : null}

        <div className="legend-card">
          <details open>
            <summary>Legend</summary>
            <div className="legend-grid">
              <div>
                <h4>Node Kinds</h4>
                <ul>
                  {topNodeKinds.map(([kind, count]) => (
                    <li key={kind}>
                      <span className="dot" style={{ background: NODE_COLORS[kind] ?? NODE_COLORS.unknown }} />
                      <span>{formatKindLabel(kind)}</span>
                      <strong>{count}</strong>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <h4>Edge Types</h4>
                <ul>
                  {topEdgeTypes.map(([type, count]) => (
                    <li key={type}>
                      <span className="line" style={{ background: EDGE_COLORS[type] ?? EDGE_COLORS.UNKNOWN }} />
                      <span>{type}</span>
                      <strong>{count}</strong>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </details>
        </div>

        {selectedNodeId ? <div className="selection-chip">Selected: {selectedNodeId}</div> : null}
        {isLargeGraph && !tooLarge ? (
          <div className="graph-hint">
            Large graph detected. Use filters, search, and neighborhood pivots for faster investigation.
          </div>
        ) : null}
      </div>
    </section>
  );
}
