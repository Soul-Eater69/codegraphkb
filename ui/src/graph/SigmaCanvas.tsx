import { useEffect, useMemo, useRef, useState } from "react";
import EdgeCurveProgram from "@sigma/edge-curve";
import FA2Layout from "graphology-layout-forceatlas2/worker";
import forceAtlas2 from "graphology-layout-forceatlas2";
import noverlap from "graphology-layout-noverlap";
import Sigma from "sigma";
import type { SigmaEdgeAttrs, SigmaGraph, SigmaNodeAttrs } from "./graphAdapter";
import { edgeTouchesNode, nodeNeighborhood } from "./interactions";

interface SigmaCanvasProps {
  graph: SigmaGraph | null;
  autoLayout?: boolean;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  highlightedNodeIds?: Set<string>;
  labelsEnabled: boolean;
  onToggleLabels: () => void;
  onNodeClick: (nodeId: string) => void;
  onEdgeClick: (edgeId: string, payload: Record<string, unknown>) => void;
  onStageClick: () => void;
  onLayoutStatusChange?: (status: "frozen" | "running") => void;
}

export function SigmaCanvas({
  graph,
  autoLayout = false,
  selectedNodeId,
  selectedEdgeId,
  highlightedNodeIds = new Set(),
  labelsEnabled,
  onToggleLabels,
  onNodeClick,
  onEdgeClick,
  onStageClick,
  onLayoutStatusChange,
}: SigmaCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma<SigmaNodeAttrs, SigmaEdgeAttrs> | null>(null);
  const layoutRef = useRef<FA2Layout<SigmaNodeAttrs, SigmaEdgeAttrs> | null>(null);
  const layoutTimerRef = useRef<number | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const layoutRunningRef = useRef(false);
  const selectedNodeIdRef = useRef<string | null>(selectedNodeId);
  const highlightedNodeIdsRef = useRef<Set<string>>(highlightedNodeIds);
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
      hideEdgesOnMove: false,
      renderEdgeLabels: false,
      labelDensity: 0.35,
      labelGridCellSize: 90,
      labelRenderedSizeThreshold: graph.order > 200 ? 13 : 7,
      labelFont: "Inter, system-ui, sans-serif",
      labelSize: 11,
      labelWeight: "600",
      labelColor: { color: "#e9edf7" },
      zIndex: true,
      enableEdgeEvents: true,
      defaultNodeColor: "#7d8aa1",
      defaultEdgeColor: "#252d40",
      defaultDrawNodeHover: (context: CanvasRenderingContext2D, data: { label?: string | null; size?: number; x: number; y: number; color?: string }, settings: { labelSize?: number; labelFont?: string; labelWeight?: string }) => {
        const label = data.label;
        if (!label) return;
        const size = settings.labelSize || 11;
        const font = settings.labelFont || "Inter, system-ui, sans-serif";
        const weight = settings.labelWeight || "600";
        context.font = `${weight} ${size}px ${font}`;
        const textWidth = context.measureText(label).width;
        const nodeSize = data.size || 8;
        const width = textWidth + 18;
        const height = size + 12;
        const x = data.x - width / 2;
        const y = data.y - nodeSize - height - 9;
        drawRoundRect(context, x, y, width, height, 6);
        context.fillStyle = "#0b0d16";
        context.fill();
        context.strokeStyle = data.color || "#704bff";
        context.lineWidth = 1.5;
        context.stroke();
        context.fillStyle = "#f7f8ff";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText(label, data.x, y + height / 2);
        context.beginPath();
        context.arc(data.x, data.y, nodeSize + 4, 0, Math.PI * 2);
        context.strokeStyle = data.color || "#704bff";
        context.globalAlpha = 0.46;
        context.stroke();
        context.globalAlpha = 1;
      },
      minCameraRatio: 0.008,
      maxCameraRatio: 34,
      allowInvalidContainer: true,
    });
    sigmaRef.current = sigma;

    sigma.on("clickNode", ({ node }) => {
      setHovered(null);
      stopLayout();
      onNodeClick(node);
    });
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
      sigma.getContainer().style.cursor = "grab";
    });

    if (graph.order <= 5000) {
      let lastRefresh = 0;
      const animate = (now: number) => {
        const shouldRefresh =
          selectedNodeIdRef.current != null ||
          highlightedNodeIdsRef.current.size > 0;
        if (shouldRefresh && now - lastRefresh > 32) {
          sigma.refresh();
          lastRefresh = now;
        }
        animationFrameRef.current = window.requestAnimationFrame(animate);
      };
      animationFrameRef.current = window.requestAnimationFrame(animate);
    }

    requestAnimationFrame(() => {
      sigma.getCamera().animatedReset({ duration: 360 });
    });
    if (autoLayout && graph.order > 20) {
      window.setTimeout(() => startLayout(true), 180);
    }

    return () => {
      stopLayout();
      if (animationFrameRef.current != null) {
        window.cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      sigma.kill();
      sigmaRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLayout, graph]);

  const neighborSet = useMemo(
    () => (graph ? nodeNeighborhood(graph, selectedNodeId) : new Set<string>()),
    [graph, selectedNodeId],
  );

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
    highlightedNodeIdsRef.current = highlightedNodeIds;
  }, [highlightedNodeIds, selectedNodeId]);

  useEffect(() => {
    layoutRunningRef.current = layoutRunning;
  }, [layoutRunning]);

  const selectedInfo = useMemo(() => {
    if (!graph || !selectedNodeId || !graph.hasNode(selectedNodeId)) {
      return null;
    }
    const attrs = graph.getNodeAttributes(selectedNodeId);
    return { id: selectedNodeId, label: attrs.label, kind: attrs.kind };
  }, [graph, selectedNodeId]);

  useEffect(() => {
    if (!graph || !sigmaRef.current) {
      return;
    }
    const sigma = sigmaRef.current;
    sigma.setSetting("nodeReducer", (node, data) => {
      const out = { ...data };
      const now = performance.now();
      if (!labelsEnabled) {
        out.label = "";
      }
      if (selectedNodeId) {
        const related = neighborSet.has(node);
        if (!related) {
          out.color = dimColor(data.color, 0.42);
          out.size = data.size * 0.72;
          out.label = "";
        } else {
          const pulse = node === selectedNodeId ? 1 + Math.sin(now / 210) * 0.13 : 1;
          out.size = node === selectedNodeId ? data.size * 1.85 * pulse : data.size * 1.28;
          out.zIndex = 4;
        }
      }
      if (highlightedNodeIds.has(node) && !selectedNodeId) {
        const pulse = 1 + Math.sin(now / 180) * 0.18;
        out.color = "#45f0e5";
        out.size = data.size * 1.85 * pulse;
        out.zIndex = 5;
      } else if (highlightedNodeIds.size > 0 && !selectedNodeId) {
        out.color = dimColor(data.color, 0.22);
        out.size = data.size * 0.62;
      }
      if (selectedEdgeId && graph.hasEdge(selectedEdgeId)) {
        const touches = graph.source(selectedEdgeId) === node || graph.target(selectedEdgeId) === node;
        if (!touches) {
          out.color = dimColor(data.color, 0.2);
          out.label = "";
        }
      }
      return out;
    });
    sigma.setSetting("edgeReducer", (edge, data) => {
      const out = { ...data };
      if (selectedNodeId && !edgeTouchesNode(graph, edge, selectedNodeId)) {
        out.color = "#252d40";
        out.size = Math.max(0.16, data.size * 0.5);
      } else if (selectedNodeId) {
        out.color = brightenColor(data.color, 1.55);
        out.size = Math.max(1, data.size * 2.1);
        out.zIndex = 2;
      }
      if (selectedEdgeId && edge === selectedEdgeId) {
        out.color = "#ffffff";
        out.size = Math.max(1.8, data.size * 3);
        out.zIndex = 3;
      }
      return out;
    });
    sigma.refresh();
  }, [graph, highlightedNodeIds, labelsEnabled, neighborSet, selectedEdgeId, selectedNodeId]);

  useEffect(() => {
    if (!graph || !sigmaRef.current || !selectedNodeId || !graph.hasNode(selectedNodeId)) {
      return;
    }
    if (!highlightedNodeIds.has(selectedNodeId)) {
      sigmaRef.current.refresh();
      return;
    }
    const attrs = graph.getNodeAttributes(selectedNodeId);
    const focusRatio = graph.order > 400 ? 1.08 : graph.order > 120 ? 0.78 : 0.52;
    sigmaRef.current.getCamera().animate({ x: attrs.x, y: attrs.y, ratio: focusRatio }, { duration: 360 });
    window.setTimeout(() => sigmaRef.current?.refresh(), 380);
  }, [graph, highlightedNodeIds, selectedNodeId]);

  useEffect(() => {
    onLayoutStatusChange?.(layoutRunning ? "running" : "frozen");
  }, [layoutRunning, onLayoutStatusChange]);

  function startLayout(isAutomatic = false) {
    if (!graph || layoutRunning || graph.order === 0) {
      return;
    }
    stopLayout();
    const settings = forceAtlas2.inferSettings(graph);
    layoutRef.current = new FA2Layout<SigmaNodeAttrs, SigmaEdgeAttrs>(graph, {
      settings: {
        ...settings,
        gravity: graph.order > 2000 ? 0.12 : graph.order > 700 ? 0.24 : 0.34,
        scalingRatio: graph.order > 2000 ? 92 : graph.order > 700 ? 54 : 28,
        slowDown: graph.order > 2000 ? 8 : graph.order > 700 ? 5.5 : 4.2,
        barnesHutOptimize: graph.order > 200,
        barnesHutTheta: graph.order > 2000 ? 0.8 : 0.65,
        outboundAttractionDistribution: true,
        adjustSizes: true,
        edgeWeightInfluence: 0.72,
      },
    });
    layoutRef.current.start();
    layoutRunningRef.current = true;
    setLayoutRunning(true);
    layoutTimerRef.current = window.setTimeout(
      () => stopLayout(),
      isAutomatic ? layoutDuration(graph.order) : Math.min(layoutDuration(graph.order), 16000),
    );
  }

  function stopLayout() {
    if (layoutTimerRef.current != null) {
      window.clearTimeout(layoutTimerRef.current);
      layoutTimerRef.current = null;
    }
    if (layoutRef.current) {
      layoutRef.current.stop();
      layoutRef.current.kill();
      layoutRef.current = null;
    }
    if (graph && graph.order > 0) {
      try {
        noverlap.assign(graph, {
          maxIterations: 18,
          settings: { margin: 8, ratio: 1.08, expansion: 1.03, speed: 3 },
        });
      } catch {
        // best-effort cleanup
      }
      sigmaRef.current?.refresh();
    }
    layoutRunningRef.current = false;
    setLayoutRunning(false);
  }

  function zoomIn() {
    sigmaRef.current?.getCamera().animatedZoom({ duration: 180 });
  }

  function zoomOut() {
    sigmaRef.current?.getCamera().animatedUnzoom({ duration: 180 });
  }

  function fitGraph() {
    sigmaRef.current?.getCamera().animatedReset({ duration: 320 });
  }

  return (
    <div className="sigma-wrap">
      <div ref={containerRef} className="sigma-container" />
      <div className={`layout-pill ${layoutRunning ? "running" : "frozen"}`}>
        <span className="layout-dot" />
        {layoutRunning ? "Layout optimizing..." : "Layout frozen"}
      </div>
      {hovered ? (
        <div className="hover-card">
          <strong>{hovered.label}</strong>
          <span className="hover-kind">{hovered.kind}</span>
          {hovered.path ? <small>{hovered.path}</small> : null}
        </div>
      ) : null}
      {selectedInfo ? (
        <div className="selection-bar">
          <span className="selection-pulse" />
          <strong>{selectedInfo.label}</strong>
          <small>{selectedInfo.kind}</small>
          <button type="button" onClick={onStageClick}>
            Clear
          </button>
        </div>
      ) : null}
      <button type="button" className="ai-highlight-toggle" title="AI highlights">
        AI
      </button>
      <button type="button" className="query-fab" title="Query graph" onClick={onToggleLabels}>
        Query
      </button>
      <div className="graph-controls">
        <button type="button" onClick={fitGraph} title="Fit to view">
          []
        </button>
        <button type="button" onClick={zoomIn} title="Zoom in">
          +
        </button>
        <button type="button" onClick={zoomOut} title="Zoom out">
          -
        </button>
        {!layoutRunning ? (
          <button type="button" onClick={() => startLayout(false)} title="Run worker layout">
            &gt;
          </button>
        ) : (
          <button type="button" onClick={stopLayout} title="Freeze layout" className="active">
            ||
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

function layoutDuration(nodeCount: number): number {
  if (nodeCount > 5000) return 35000;
  if (nodeCount > 2000) return 30000;
  if (nodeCount > 1000) return 25000;
  if (nodeCount > 500) return 22000;
  return 16000;
}

function drawRoundRect(context: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  context.beginPath();
  context.moveTo(x + radius, y);
  context.lineTo(x + width - radius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + radius);
  context.lineTo(x + width, y + height - radius);
  context.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  context.lineTo(x + radius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - radius);
  context.lineTo(x, y + radius);
  context.quadraticCurveTo(x, y, x + radius, y);
  context.closePath();
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const clean = hex.replace("#", "");
  if (clean.length !== 6) {
    return { r: 116, g: 129, b: 158 };
  }
  return {
    r: parseInt(clean.slice(0, 2), 16),
    g: parseInt(clean.slice(2, 4), 16),
    b: parseInt(clean.slice(4, 6), 16),
  };
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${[r, g, b]
    .map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0"))
    .join("")}`;
}

function dimColor(hex: string, amount: number): string {
  const rgb = hexToRgb(hex);
  const bg = { r: 4, g: 6, b: 12 };
  return rgbToHex(
    bg.r + (rgb.r - bg.r) * amount,
    bg.g + (rgb.g - bg.g) * amount,
    bg.b + (rgb.b - bg.b) * amount,
  );
}

function brightenColor(hex: string, factor: number): string {
  const rgb = hexToRgb(hex);
  return rgbToHex(
    rgb.r + ((255 - rgb.r) * (factor - 1)) / factor,
    rgb.g + ((255 - rgb.g) * (factor - 1)) / factor,
    rgb.b + ((255 - rgb.b) * (factor - 1)) / factor,
  );
}
