import { useEffect, useMemo, useRef, useState } from "react";
import Sigma from "sigma";
import type { CameraState } from "sigma/types";
import type { SigmaEdgeAttributes, SigmaGraph, SigmaNodeAttributes } from "../graph/adapter";
import { dimColor } from "../graph/styles";
import { createLayoutController, layoutStateFor, type LayoutController } from "../graph/layout";
import { isEdgeVisible, neighborSet, visibleNodeIds } from "../graph/filters";

export interface UseSigmaOptions {
  onNodeClick?: (nodeId: string) => void;
  onEdgeClick?: (edgeId: string, edgeData: Record<string, unknown>) => void;
  onNodeHover?: (nodeId: string | null) => void;
  onStageClick?: () => void;
  selectedNodeId?: string | null;
  selectedEdgeId?: string | null;
  visibleNodeKinds?: Set<string>;
  visibleEdgeTypes?: Set<string>;
  highlightedNodeIds?: Set<string>;
}

export function useSigma(graph: SigmaGraph | null, options: UseSigmaOptions) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma<SigmaNodeAttributes, SigmaEdgeAttributes> | null>(null);
  const layoutRef = useRef<LayoutController | null>(null);

  const [layoutRunning, setLayoutRunning] = useState(false);
  const [labelsEnabled, setLabelsEnabled] = useState(true);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  const nodeKinds = options.visibleNodeKinds ?? new Set<string>();
  const edgeTypes = options.visibleEdgeTypes ?? new Set<string>();
  const highlightedNodeIds = options.highlightedNodeIds ?? new Set<string>();
  const selectedNodeId = options.selectedNodeId ?? null;
  const selectedEdgeId = options.selectedEdgeId ?? null;

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !graph) {
      return;
    }

    if (sigmaRef.current) {
      sigmaRef.current.kill();
      sigmaRef.current = null;
    }
    if (layoutRef.current) {
      layoutRef.current.cleanup();
      layoutRef.current = null;
    }

    const sigma = new Sigma(graph, container, {
      renderEdgeLabels: false,
      labelDensity: 0.06,
      labelRenderedSizeThreshold: 8,
      defaultNodeType: "circle",
      defaultEdgeType: "line",
      zIndex: true,
    });
    sigmaRef.current = sigma;

    sigma.on("clickNode", ({ node }) => {
      options.onNodeClick?.(node);
    });
    sigma.on("clickEdge", ({ edge }) => {
      const source = graph.source(edge);
      const target = graph.target(edge);
      const attrs = graph.getEdgeAttributes(edge);
      options.onEdgeClick?.(edge, {
        id: edge,
        source,
        target,
        type: attrs.edgeType,
        confidence: attrs.confidence,
        precision_level: attrs.precisionLevel,
        extraction_source: attrs.extractionSource,
        reason: attrs.reason,
        metadata: attrs.metadata ?? {},
      });
    });
    sigma.on("clickStage", () => {
      options.onStageClick?.();
    });
    sigma.on("enterNode", ({ node }) => {
      setHoveredNodeId(node);
      options.onNodeHover?.(node);
    });
    sigma.on("leaveNode", () => {
      setHoveredNodeId(null);
      options.onNodeHover?.(null);
    });

    const runner = createLayoutController(graph, setLayoutRunning);
    layoutRef.current = runner;
    if (graph.order > 1) {
      runner.start();
    }

    return () => {
      runner.cleanup();
      layoutRef.current = null;
      sigma.kill();
      sigmaRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  const neighbors = useMemo(
    () => (graph ? neighborSet(graph, selectedNodeId) : new Set<string>()),
    [graph, selectedNodeId],
  );

  useEffect(() => {
    if (!graph || !sigmaRef.current) {
      return;
    }

    const sigma = sigmaRef.current;
    const visibleNodes = visibleNodeIds(graph, nodeKinds);
    const anyNodeFilter = nodeKinds.size > 0;
    const anyEdgeFilter = edgeTypes.size > 0;

    sigma.setSetting("nodeReducer", (node, data) => {
      const reduced = { ...data };
      const nodeKind = graph.getNodeAttribute(node, "nodeKind") as string;
      const hiddenByNodeFilter = anyNodeFilter && !nodeKinds.has(nodeKind);
      if (hiddenByNodeFilter) {
        reduced.hidden = true;
        return reduced;
      }

      if (selectedNodeId) {
        const related = neighbors.has(node);
        if (!related) {
          reduced.color = dimColor(data.color, 0.12);
          reduced.label = labelsEnabled ? data.label : "";
        } else {
          reduced.zIndex = node === selectedNodeId ? 40 : 20;
          reduced.size = node === selectedNodeId ? data.size * 1.8 : data.size * 1.25;
        }
      }

      if (highlightedNodeIds.has(node)) {
        reduced.color = "#22d3ee";
        reduced.size = Math.max(reduced.size, data.size * 1.6);
        reduced.zIndex = 50;
      }

      if (!labelsEnabled) {
        reduced.label = "";
      }
      return reduced;
    });

    sigma.setSetting("edgeReducer", (edge, data) => {
      const reduced = { ...data };
      const hiddenByEdgeFilter = anyEdgeFilter && !edgeTypes.has(data.edgeType);
      const visibleByNodes = isEdgeVisible(graph, edge, edgeTypes, visibleNodes);
      if (hiddenByEdgeFilter || !visibleByNodes) {
        reduced.hidden = true;
        return reduced;
      }

      const source = graph.source(edge);
      const target = graph.target(edge);

      if (selectedNodeId) {
        const related = source === selectedNodeId || target === selectedNodeId;
        if (!related) {
          reduced.color = dimColor(data.color, 0.1);
          reduced.size = Math.max(0.3, data.size * 0.5);
        } else {
          reduced.size = data.size * 1.8;
          reduced.zIndex = 25;
        }
      }

      if (selectedEdgeId && edge === selectedEdgeId) {
        reduced.size = data.size * 2.4;
        reduced.color = "#f8fafc";
        reduced.zIndex = 60;
      }
      return reduced;
    });

    sigma.refresh();
  }, [
    graph,
    nodeKinds,
    edgeTypes,
    neighbors,
    selectedNodeId,
    selectedEdgeId,
    labelsEnabled,
    highlightedNodeIds,
  ]);

  useEffect(() => {
    if (!graph || !sigmaRef.current || !selectedNodeId || !graph.hasNode(selectedNodeId)) {
      return;
    }
    const attrs = graph.getNodeAttributes(selectedNodeId);
    sigmaRef.current.getCamera().animate(
      { x: attrs.x, y: attrs.y, ratio: 0.25 },
      { duration: 450 },
    );
  }, [graph, selectedNodeId]);

  const controls = useMemo(
    () => ({
      zoomIn() {
        const camera = sigmaRef.current?.getCamera();
        if (!camera) {
          return;
        }
        camera.animate({ ratio: camera.getState().ratio * 0.75 }, { duration: 220 });
      },
      zoomOut() {
        const camera = sigmaRef.current?.getCamera();
        if (!camera) {
          return;
        }
        camera.animate({ ratio: camera.getState().ratio * 1.25 }, { duration: 220 });
      },
      fit() {
        if (!graph || !sigmaRef.current) {
          return;
        }
        const camera = sigmaRef.current.getCamera();
        const nodes = graph.nodes();
        if (nodes.length === 0) {
          return;
        }
        let minX = Number.POSITIVE_INFINITY;
        let maxX = Number.NEGATIVE_INFINITY;
        let minY = Number.POSITIVE_INFINITY;
        let maxY = Number.NEGATIVE_INFINITY;
        for (const node of nodes) {
          const attrs = graph.getNodeAttributes(node);
          minX = Math.min(minX, attrs.x);
          maxX = Math.max(maxX, attrs.x);
          minY = Math.min(minY, attrs.y);
          maxY = Math.max(maxY, attrs.y);
        }
        const span = Math.max(maxX - minX, maxY - minY);
        const next: Partial<CameraState> = {
          x: minX + (maxX - minX) / 2,
          y: minY + (maxY - minY) / 2,
          ratio: Math.max(0.03, span / 900),
        };
        camera.animate(next, { duration: 350 });
      },
      resetLayout() {
        if (!graph) {
          return;
        }
        const goldenAngle = Math.PI * (3 - Math.sqrt(5));
        let index = 0;
        graph.forEachNode((node, attrs) => {
          const radius = Math.sqrt(index + 1) * 20;
          const angle = index * goldenAngle;
          graph.mergeNodeAttributes(node, {
            ...attrs,
            x: radius * Math.cos(angle),
            y: radius * Math.sin(angle),
          });
          index += 1;
        });
        layoutRef.current?.start();
      },
      toggleLayout() {
        layoutRef.current?.toggle();
      },
      toggleLabels() {
        setLabelsEnabled((prev) => !prev);
      },
    }),
    [graph],
  );

  return {
    containerRef,
    hoveredNodeId,
    layoutRunning,
    labelsEnabled,
    isLargeGraph: graph ? layoutStateFor(graph).isLarge : false,
    controls,
  };
}
