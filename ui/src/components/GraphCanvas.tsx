import { useMemo } from "react";
import type { GraphPayload, GraphView } from "../types/graph";
import { graphPayloadToGraphology } from "../graph/adapter";
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
  onNodeSelect: (nodeId: string) => void;
  onStageClick: () => void;
  onEdgeSelect: (edgeId: string, edgeData: unknown) => void;
  onClearSelection: () => void;
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
  onNodeSelect,
  onStageClick,
  onEdgeSelect,
  onClearSelection,
}: GraphCanvasProps) {
  const graphology = useMemo(() => {
    if (!graph) {
      return null;
    }
    if ((graph.metadata.node_count ?? graph.nodes.length) > 10000 || (graph.metadata.edge_count ?? graph.edges.length) > 30000) {
      return null;
    }
    return graphPayloadToGraphology(graph);
  }, [graph]);

  const {
    containerRef,
    controls,
    hoveredNodeId,
    layoutRunning,
    labelsEnabled,
    isLargeGraph,
  } = useSigma(graphology, {
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

  return (
    <section className="graph-canvas-panel">
      <div className="panel-header">
        <h2>
          Graph View: {graph?.metadata.view ?? view}
          {layoutRunning ? <span className="layout-pill running">layout running</span> : <span className="layout-pill">layout idle</span>}
        </h2>
      </div>

      <div className="graph-canvas-wrap">
        {loading ? <div className="overlay">Loading graph slice...</div> : null}
        {error ? <div className="overlay error-box">{error}</div> : null}
        {tooLarge ? (
          <div className="overlay warning-box">
            Graph is very large. Use filters, search, or neighborhood view before rendering.
          </div>
        ) : null}
        {graphology == null && !loading && !error && !tooLarge ? (
          <div className="overlay">No graph data available.</div>
        ) : null}
        <div ref={containerRef} className={`sigma-container ${tooLarge ? "hidden" : ""}`} />

        <div className="graph-controls">
          <button type="button" onClick={controls.zoomIn}>
            +
          </button>
          <button type="button" onClick={controls.zoomOut}>
            -
          </button>
          <button type="button" onClick={controls.fit}>
            Fit
          </button>
          <button type="button" onClick={controls.resetLayout}>
            Reset
          </button>
          <button type="button" onClick={controls.toggleLayout}>
            {layoutRunning ? "Stop Layout" : "Start Layout"}
          </button>
          <button type="button" onClick={controls.toggleLabels}>
            {labelsEnabled ? "Hide Labels" : "Show Labels"}
          </button>
          <button type="button" onClick={onClearSelection}>
            Clear
          </button>
        </div>

        {hoveredNodeAttrs ? (
          <div className="hover-tooltip">
            <strong>{hoveredNodeAttrs.label}</strong>
            <span>{hoveredNodeAttrs.nodeKind}</span>
          </div>
        ) : null}

        {isLargeGraph && !tooLarge ? (
          <div className="graph-hint">
            Large graph detected. Layout runs shorter by default. Use search + neighborhood for precision.
          </div>
        ) : null}
      </div>
    </section>
  );
}
