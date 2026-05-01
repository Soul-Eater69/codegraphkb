import { useEffect, useMemo, useRef, useState } from "react";
import EdgeCurveProgram from "@sigma/edge-curve";
import Sigma from "sigma";
import type { SigmaEdgeAttrs, SigmaGraph, SigmaNodeAttrs } from "./graphAdapter";
import { edgeTouchesNode, nodeNeighborhood } from "./interactions";
import { runForceLayout } from "./layouts";

interface SigmaCanvasProps {
  graph: SigmaGraph | null;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  labelsEnabled: boolean;
  onToggleLabels: () => void;
  onNodeClick: (nodeId: string) => void;
  onEdgeClick: (edgeId: string, payload: Record<string, unknown>) => void;
  onStageClick: () => void;
  onLayoutStatusChange?: (status: "frozen" | "running") => void;
}

export function SigmaCanvas({
  graph,
  selectedNodeId,
  selectedEdgeId,
  labelsEnabled,
  onToggleLabels,
  onNodeClick,
  onEdgeClick,
  onStageClick,
  onLayoutStatusChange,
}: SigmaCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma<SigmaNodeAttrs, SigmaEdgeAttrs> | null>(null);
  const layoutTimerRef = useRef<number | null>(null);
  const [layoutRunning, setLayoutRunning] = useState(false);
  const [hovered, setHovered] = useState<{ label: string; kind: string; path?: string } | null>(null);

  useEffect(() => {
    if (!containerRef.current || !graph) {
      return;
    }
    if (sigmaRef.current) {
      sigmaRef.current.kill();
      sigmaRef.current = null;
    }

    const sigma = new Sigma<SigmaNodeAttrs, SigmaEdgeAttrs>(graph, containerRef.current, {
      defaultNodeType: "circle",
      defaultEdgeType: "curved",
      edgeProgramClasses: { curved: EdgeCurveProgram as any },
      hideLabelsOnMove: true,
      renderEdgeLabels: false,
      labelDensity: 0.6,
      labelGridCellSize: 80,
      labelRenderedSizeThreshold: graph.order > 200 ? 12 : 7,
      labelFont: "Inter, system-ui, sans-serif",
      labelSize: 11,
      labelWeight: "500",
      labelColor: { color: "#e9edf7" },
      zIndex: true,
      enableEdgeEvents: true,
      defaultNodeColor: "#7d8aa1",
      defaultEdgeColor: "rgba(120,130,150,0.18)",
      minCameraRatio: 0.05,
      maxCameraRatio: 14,
    });
    sigmaRef.current = sigma;

    sigma.on("clickNode", ({ node }) => onNodeClick(node));
    sigma.on("clickEdge", ({ edge }) => {
      const attrs = graph.getEdgeAttributes(edge);
      onEdgeClick(edge, {
        id: edge,
        source: graph.source(edge),
        target: graph.target(edge),
        type: attrs.edgeType,
        confidence: attrs.confidence,
        precision_level: attrs.precisionLevel,
        extraction_source: attrs.extractionSource,
        reason: attrs.reason,
        step: attrs.step,
      });
    });
    sigma.on("clickStage", () => onStageClick());
    sigma.on("enterNode", ({ node }) => {
      const attrs = graph.getNodeAttributes(node);
      setHovered({ label: attrs.label, kind: attrs.kind, path: attrs.filePath });
      sigma.getContainer().style.cursor = "pointer";
    });
    sigma.on("leaveNode", () => {
      setHovered(null);
      sigma.getContainer().style.cursor = "default";
    });

    // Auto-fit once on mount so the user lands centered
    requestAnimationFrame(() => {
      sigma.getCamera().animatedReset({ duration: 0 });
    });

    return () => {
      stopLayout();
      sigma.kill();
      sigmaRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  const neighborSet = useMemo(
    () => (graph ? nodeNeighborhood(graph, selectedNodeId) : new Set<string>()),
    [graph, selectedNodeId],
  );

  useEffect(() => {
    if (!graph || !sigmaRef.current) {
      return;
    }
    const sigma = sigmaRef.current;
    sigma.setSetting("nodeReducer", (node, data) => {
      const out = { ...data };
      if (!labelsEnabled) {
        out.label = "";
      }
      if (selectedNodeId) {
        const related = neighborSet.has(node);
        if (!related) {
          out.color = "rgba(120, 130, 150, 0.16)";
          out.label = "";
        } else {
          out.size = node === selectedNodeId ? data.size * 1.7 : data.size * 1.25;
          out.zIndex = 2;
        }
      }
      if (selectedEdgeId && graph.hasEdge(selectedEdgeId)) {
        const touches =
          graph.source(selectedEdgeId) === node || graph.target(selectedEdgeId) === node;
        if (!touches) {
          out.color = "rgba(120, 130, 150, 0.18)";
          out.label = "";
        }
      }
      return out;
    });
    sigma.setSetting("edgeReducer", (edge, data) => {
      const out = { ...data };
      if (selectedNodeId && !edgeTouchesNode(graph, edge, selectedNodeId)) {
        out.color = "rgba(120, 130, 150, 0.08)";
        out.size = Math.max(0.3, data.size * 0.4);
      } else if (selectedNodeId) {
        out.size = data.size * 1.6;
        out.zIndex = 2;
      }
      if (selectedEdgeId && edge === selectedEdgeId) {
        out.color = "#ffffff";
        out.size = data.size * 2.6;
        out.zIndex = 3;
      }
      return out;
    });
    sigma.refresh();
  }, [graph, labelsEnabled, neighborSet, selectedEdgeId, selectedNodeId]);

  useEffect(() => {
    if (!graph || !sigmaRef.current || !selectedNodeId || !graph.hasNode(selectedNodeId)) {
      return;
    }
    const attrs = graph.getNodeAttributes(selectedNodeId);
    sigmaRef.current.getCamera().animate({ x: attrs.x, y: attrs.y, ratio: 0.3 }, { duration: 320 });
  }, [graph, selectedNodeId]);

  useEffect(() => {
    onLayoutStatusChange?.(layoutRunning ? "running" : "frozen");
  }, [layoutRunning, onLayoutStatusChange]);

  function startLayout() {
    if (!graph || layoutRunning) {
      return;
    }
    setLayoutRunning(true);
    let ticks = 0;
    layoutTimerRef.current = window.setInterval(() => {
      runForceLayout(graph, 8);
      sigmaRef.current?.refresh();
      ticks += 1;
      if (ticks >= 24) {
        stopLayout();
      }
    }, 60);
  }

  function stopLayout() {
    if (layoutTimerRef.current != null) {
      window.clearInterval(layoutTimerRef.current);
      layoutTimerRef.current = null;
    }
    setLayoutRunning(false);
  }

  function zoomIn() {
    const camera = sigmaRef.current?.getCamera();
    if (!camera) return;
    camera.animate({ ratio: camera.getState().ratio * 0.75 }, { duration: 160 });
  }

  function zoomOut() {
    const camera = sigmaRef.current?.getCamera();
    if (!camera) return;
    camera.animate({ ratio: camera.getState().ratio * 1.33 }, { duration: 160 });
  }

  function fitGraph() {
    if (!sigmaRef.current) return;
    sigmaRef.current.getCamera().animatedReset({ duration: 280 });
  }

  return (
    <div className="sigma-wrap">
      <div ref={containerRef} className="sigma-container" />
      <div className={`layout-pill ${layoutRunning ? "running" : "frozen"}`}>
        <span className="layout-dot" />
        {layoutRunning ? "Layout running" : "Layout frozen"}
      </div>
      {hovered ? (
        <div className="hover-card">
          <strong>{hovered.label}</strong>
          <span className="hover-kind">{hovered.kind}</span>
          {hovered.path ? <small>{hovered.path}</small> : null}
        </div>
      ) : null}
      <div className="graph-controls">
        <button type="button" onClick={fitGraph} title="Fit to view">
          ⤢
        </button>
        <button type="button" onClick={zoomIn} title="Zoom in">
          +
        </button>
        <button type="button" onClick={zoomOut} title="Zoom out">
          −
        </button>
        {!layoutRunning ? (
          <button type="button" onClick={startLayout} title="Run force layout">
            ▶
          </button>
        ) : (
          <button type="button" onClick={stopLayout} title="Freeze layout" className="active">
            ■
          </button>
        )}
        <button
          type="button"
          onClick={onToggleLabels}
          title="Toggle labels"
          className={labelsEnabled ? "active" : ""}
        >
          Aa
        </button>
      </div>
    </div>
  );
}
