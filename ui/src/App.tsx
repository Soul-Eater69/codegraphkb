import { useEffect, useMemo, useState } from "react";
import {
  getFilesTree,
  getGraph,
  getImpact,
  getNeighborhood,
  getNode,
  getNodeRelations,
  getProcess,
  getProcesses,
  getSummary,
  searchNodes,
} from "./api/client";
import { parseQueryCommand } from "./features/search/commandParser";
import { GraphScene } from "./graph/GraphScene";
import { InspectorDrawer } from "./layout/InspectorDrawer";
import { LeftRail } from "./layout/LeftRail";
import { StatusBar } from "./layout/StatusBar";
import { TopQueryBar } from "./layout/TopQueryBar";
import { FileTreePanel } from "./panels/FileTreePanel";
import { FilterPanel } from "./panels/FilterPanel";
import { GraphInfoPanel } from "./panels/GraphInfoPanel";
import { PerspectivesPanel } from "./panels/PerspectivesPanel";
import { ProcessPanel } from "./panels/ProcessPanel";
import type {
  FileTreeNode,
  GraphPayload,
  GraphView,
  NodeRelations,
  Perspective,
  ProcessSummary,
  QueryExecution,
  SearchResult,
  SummaryResponse,
} from "./types/graph";

const EMPTY_EXECUTION: QueryExecution = { perspective: "none" };

export default function App() {
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [perspective, setPerspective] = useState<Perspective>("none");
  const [selectedView, setSelectedView] = useState<GraphView>("repo");
  const [execution, setExecution] = useState<QueryExecution>(EMPTY_EXECUTION);

  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [processes, setProcesses] = useState<ProcessSummary[]>([]);
  const [fileTree, setFileTree] = useState<FileTreeNode | null>(null);

  const [selectedNodeKinds, setSelectedNodeKinds] = useState<Set<string>>(new Set());
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState<Set<string>>(new Set());

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [detailsTitle, setDetailsTitle] = useState("Selection");
  const [details, setDetails] = useState<unknown>(null);
  const [relations, setRelations] = useState<NodeRelations | null>(null);

  const [loadingGraph, setLoadingGraph] = useState(false);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [loadingProcesses, setLoadingProcesses] = useState(false);
  const [loadingTree, setLoadingTree] = useState(false);
  const [layoutStatus, setLayoutStatus] = useState<"frozen" | "running">("frozen");

  const [errorGraph, setErrorGraph] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<string | null>(null);
  const [errorTree, setErrorTree] = useState<string | null>(null);
  const [errorProcesses, setErrorProcesses] = useState<string | null>(null);

  useEffect(() => {
    void loadSummary();
    void loadProcesses();
    void loadFileTree();
  }, []);

  const nodeKindCounts = useMemo(() => counts(graph?.nodes.map((n) => n.kind) ?? []), [graph]);
  const edgeTypeCounts = useMemo(() => counts(graph?.edges.map((e) => e.type) ?? []), [graph]);

  async function loadSummary() {
    try {
      setSummary(await getSummary());
    } catch {
      setSummary(null);
    }
  }

  async function loadProcesses() {
    setLoadingProcesses(true);
    setErrorProcesses(null);
    try {
      setProcesses(await getProcesses());
    } catch (err) {
      setErrorProcesses(asError(err));
    } finally {
      setLoadingProcesses(false);
    }
  }

  async function loadFileTree() {
    setLoadingTree(true);
    setErrorTree(null);
    try {
      setFileTree(await getFilesTree());
    } catch (err) {
      setErrorTree(asError(err));
    } finally {
      setLoadingTree(false);
    }
  }

  async function executeView(view: GraphView) {
    setLoadingGraph(true);
    setErrorGraph(null);
    setPerspective(view);
    setExecution({ perspective: view, view });
    try {
      const payload = await getGraph(view);
      setGraph(payload);
      clearSelection();
    } catch (err) {
      setErrorGraph(asError(err));
    } finally {
      setLoadingGraph(false);
    }
  }

  async function runQuery() {
    const parsed = parseQueryCommand(query);
    if (parsed.perspective === "none") {
      await runSearchQuery(query);
      return;
    }
    setExecution(parsed);
    if (parsed.view) {
      setSelectedView(parsed.view);
      await executeView(parsed.view);
      return;
    }
    if (parsed.perspective === "impact" && parsed.target) {
      await executeImpact(parsed.target);
      return;
    }
    if (parsed.perspective === "neighborhood" && parsed.nodeId) {
      await executeNeighborhood(parsed.nodeId);
    }
  }

  async function runSearchQuery(term: string) {
    const q = term.trim();
    if (!q) {
      return;
    }
    const result = await searchNodes(q);
    setSearchResults(result.results);
    if (result.results.length > 0) {
      await selectSearchResult(result.results[0]);
    }
  }

  async function executeImpact(target: string) {
    setLoadingGraph(true);
    setErrorGraph(null);
    setPerspective("impact");
    try {
      const payload = await getImpact(target);
      setGraph(payload);
      clearSelection();
      setDetailsTitle(`Impact: ${target}`);
      setDetails(payload.metadata);
      setInspectorOpen(true);
    } catch (err) {
      setErrorGraph(asError(err));
    } finally {
      setLoadingGraph(false);
    }
  }

  async function executeNeighborhood(nodeId: string) {
    setLoadingGraph(true);
    setErrorGraph(null);
    setPerspective("neighborhood");
    try {
      const payload = await getNeighborhood(nodeId, 2);
      setGraph(payload);
      setSelectedNodeId(nodeId);
      setSelectedEdgeId(null);
      await loadNodeDetails(nodeId);
    } catch (err) {
      setErrorGraph(asError(err));
    } finally {
      setLoadingGraph(false);
    }
  }

  async function selectSearchResult(result: SearchResult) {
    const nodeId = result.id;
    if (!nodeInGraph(nodeId)) {
      await executeNeighborhood(nodeId);
      return;
    }
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(null);
    await loadNodeDetails(nodeId);
  }

  async function loadNodeDetails(nodeId: string) {
    setLoadingDetails(true);
    setErrorDetails(null);
    try {
      const [nodeDetails, nodeRelations] = await Promise.all([
        getNode(nodeId),
        getNodeRelations(nodeId).catch(() => ({} as NodeRelations)),
      ]);
      setDetails(nodeDetails);
      setRelations(nodeRelations);
      setDetailsTitle(`Node: ${nodeId}`);
      setInspectorOpen(true);
    } catch (err) {
      setErrorDetails(asError(err));
    } finally {
      setLoadingDetails(false);
    }
  }

  async function selectProcess(process: ProcessSummary) {
    const nodeId = process.node_id ?? `process:${process.id}`;
    if (!nodeInGraph(nodeId)) {
      await executeNeighborhood(nodeId);
    }
    try {
      const detail = await getProcess(process.id);
      setSelectedNodeId(nodeId);
      setSelectedEdgeId(null);
      setDetailsTitle(`Process: ${process.label}`);
      setDetails(detail);
      setRelations({
        processes: [{ id: process.id, label: process.label, process_type: process.process_type }],
      });
      setInspectorOpen(true);
    } catch {
      // ignore detail load failure; process list item still selected
    }
  }

  function nodeInGraph(nodeId: string): boolean {
    return graph?.nodes.some((n) => n.id === nodeId) ?? false;
  }

  function clearSelection() {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }

  function toggleNodeKind(kind: string) {
    setSelectedNodeKinds((prev) => toggleFilter(prev, kind));
  }

  function toggleEdgeType(type: string) {
    setSelectedEdgeTypes((prev) => toggleFilter(prev, type));
  }

  return (
    <div className="app-shell">
      <TopQueryBar
        summary={summary}
        query={query}
        onQueryChange={setQuery}
        onRunQuery={() => void runQuery()}
        onAskClick={() => {
          setDetailsTitle("Ask CodeGraphKB");
          setDetails({
            endpoint: "POST /api/context",
            selected_node_ids: selectedNodeId ? [selectedNodeId] : [],
          });
          setRelations(null);
          setInspectorOpen(true);
        }}
        selectedView={selectedView}
        onViewChange={(view) => {
          setSelectedView(view);
          setQuery(view);
          void executeView(view);
        }}
        execution={execution}
        layoutStatus={layoutStatus}
      />

      <div className="main-layout">
        <LeftRail>
          <GraphInfoPanel summary={summary} />
          <PerspectivesPanel active={perspective} onSelectView={(view) => void executeView(view)} />
          <FilterPanel
            nodeKinds={nodeKindCounts}
            edgeTypes={edgeTypeCounts}
            selectedNodeKinds={selectedNodeKinds}
            selectedEdgeTypes={selectedEdgeTypes}
            onToggleNodeKind={toggleNodeKind}
            onToggleEdgeType={toggleEdgeType}
          />
          <FileTreePanel
            tree={fileTree}
            loading={loadingTree}
            error={errorTree}
            onSelectFile={(path) => void selectSearchResult({ id: `file:${path}`, label: path, kind: "file", file_path: path })}
          />
          <ProcessPanel
            processes={processes}
            loading={loadingProcesses}
            error={errorProcesses}
            onSelectProcess={(process) => void selectProcess(process)}
          />
          {searchResults.length > 0 ? (
            <section className="panel">
              <h3>Search Results</h3>
              <ul>
                {searchResults.slice(0, 15).map((result) => (
                  <li key={result.id}>
                    <button type="button" onClick={() => void selectSearchResult(result)}>
                      <span>{result.label}</span>
                      <small>{result.kind}</small>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </LeftRail>

        <GraphScene
          perspective={perspective}
          graph={graph}
          loading={loadingGraph}
          error={errorGraph}
          selectedNodeKinds={selectedNodeKinds}
          selectedEdgeTypes={selectedEdgeTypes}
          selectedNodeId={selectedNodeId}
          selectedEdgeId={selectedEdgeId}
          onNodeClick={(nodeId) => {
            setSelectedNodeId(nodeId);
            setSelectedEdgeId(null);
            void loadNodeDetails(nodeId);
          }}
          onEdgeClick={(edgeId, edgePayload) => {
            setSelectedEdgeId(edgeId);
            setSelectedNodeId(null);
            setDetailsTitle(`Edge: ${edgeId}`);
            setDetails(edgePayload);
            setRelations(null);
            setInspectorOpen(true);
          }}
          onStageClick={clearSelection}
          onQuickAction={(action) => void executeView(action === "framework" ? "framework" : action)}
          onLayoutStatusChange={setLayoutStatus}
        />

        <InspectorDrawer
          open={inspectorOpen}
          title={detailsTitle}
          details={details}
          relations={relations}
          loading={loadingDetails}
          error={errorDetails}
          onClose={() => setInspectorOpen(false)}
        />
      </div>

      <StatusBar summary={summary} nodeCount={graph?.nodes.length ?? 0} edgeCount={graph?.edges.length ?? 0} />
    </div>
  );
}

function counts(items: string[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const item of items) {
    out[item] = (out[item] ?? 0) + 1;
  }
  return out;
}

function toggleFilter(source: Set<string>, value: string): Set<string> {
  const next = new Set(source);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  return next;
}

function asError(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
