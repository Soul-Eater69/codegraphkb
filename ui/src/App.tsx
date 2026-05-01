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
const VIEW_CAPS: Record<GraphView, { maxNodes: number; maxEdges: number; nodeKinds?: string[]; edgeTypes?: string[] }> = {
  repo: {
    maxNodes: 500,
    maxEdges: 700,
    nodeKinds: ["repo", "folder", "file"],
    edgeTypes: ["CONTAINS"],
  },
  symbols: {
    maxNodes: 200,
    maxEdges: 320,
    nodeKinds: ["file", "class", "function", "method", "interface", "type_alias", "enum"],
    edgeTypes: ["CONTAINS", "DEFINES", "IMPLEMENTS", "EXTENDS"],
  },
  calls: {
    maxNodes: 150,
    maxEdges: 300,
    edgeTypes: ["CALLS", "ACCESSES", "IMPLEMENTS", "EXTENDS"],
  },
  framework: {
    maxNodes: 300,
    maxEdges: 450,
    edgeTypes: ["HANDLES_ROUTE", "USES_MIDDLEWARE", "TESTS", "QUERIES", "FETCHES", "CALLS_EXTERNAL"],
  },
  processes: {
    maxNodes: 200,
    maxEdges: 260,
  },
  full: {
    maxNodes: 0,
    maxEdges: 0,
  },
};

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
  const [sceneNotice, setSceneNotice] = useState<string>("Choose a perspective or search for a symbol to start.");

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
    if (view === "full") {
      setErrorGraph("Full graph is disabled in the UI. Use focused perspectives.");
      return;
    }
    if (view === "symbols") {
      setGraph(null);
      setPerspective("symbols");
      setExecution({ perspective: "symbols", view: "symbols" });
      setSceneNotice("Symbols view requires a selected file or search result.");
      return;
    }
    if (view === "calls") {
      setGraph(null);
      setPerspective("calls");
      setExecution({ perspective: "calls", view: "calls" });
      setSceneNotice("Call graph requires a selected symbol. Search and select a symbol first.");
      return;
    }
    if (view === "framework") {
      setGraph(null);
      setPerspective("framework");
      setExecution({ perspective: "framework", view: "framework" });
      setSceneNotice("Framework view requires selecting a route/test/model target first.");
      return;
    }
    if (view === "processes") {
      setGraph(null);
      setPerspective("processes");
      setExecution({ perspective: "processes", view: "processes" });
      setSceneNotice("Select one process from the left panel to render an ordered flow.");
      return;
    }
    setLoadingGraph(true);
    setErrorGraph(null);
    setSceneNotice("");
    setPerspective(view);
    setExecution({ perspective: view, view });
    try {
      const caps = VIEW_CAPS[view];
      const payload = await getGraph(view, {
        maxNodes: caps.maxNodes,
        maxEdges: caps.maxEdges,
        nodeKinds: caps.nodeKinds,
        edgeTypes: caps.edgeTypes,
      });
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
    if (parsed.perspective === "calls" || parsed.perspective === "symbols" || parsed.perspective === "framework") {
      if (!parsed.target) {
        setErrorGraph(`${parsed.perspective} view requires a selected target.`);
        setGraph(null);
        setPerspective(parsed.perspective);
        return;
      }
      await runSearchQuery(parsed.target);
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
    const q = term.trim().replace(/^search\s+/i, "");
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
    setSceneNotice("");
    try {
      const payload = await getImpact(target, { depth: 1, maxNodes: 150, maxEdges: 300 });
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

  async function executeNeighborhood(nodeId: string, asPerspective: Perspective = "neighborhood") {
    setLoadingGraph(true);
    setErrorGraph(null);
    setPerspective(asPerspective);
    setSceneNotice("");
    try {
      const payload = await getNeighborhood(nodeId, asPerspective === "neighborhood" ? 1 : 2, {
        maxNodes: asPerspective === "calls" ? 150 : asPerspective === "symbols" ? 200 : 200,
        maxEdges: asPerspective === "calls" ? 300 : 320,
      });
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
      if (nodeId.startsWith("symbol:")) {
        await executeNeighborhood(nodeId, "calls");
      } else if (nodeId.startsWith("file:")) {
        await executeNeighborhood(nodeId, "symbols");
      } else if (nodeId.startsWith("process:")) {
        await executeNeighborhood(nodeId, "processes");
      } else {
        await executeNeighborhood(nodeId, "neighborhood");
      }
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
    await executeNeighborhood(nodeId, "processes");
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
          <PerspectivesPanel
            active={perspective}
            onAction={(action) => {
              if (action === "repo" || action === "processes") {
                void executeView(action);
                return;
              }
              setGraph(null);
              setPerspective(action);
              setExecution({ perspective: action });
              if (action === "calls") {
                setSceneNotice("Call graph requires a selected symbol. Search first.");
              } else if (action === "symbols") {
                setSceneNotice("Symbols view requires a selected file or symbol.");
              } else {
                setSceneNotice("Framework view requires a focused entrypoint selection.");
              }
            }}
          />
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
          notice={sceneNotice}
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
          onQuickAction={(action) => {
            if (action === "repo" || action === "processes") {
              void executeView(action);
              return;
            }
            setGraph(null);
            setPerspective(action);
            setExecution({ perspective: action });
            if (action === "calls") {
              setSceneNotice("Use search to select a symbol, then explore its call neighborhood.");
            } else if (action === "symbols") {
              setSceneNotice("Select a file from the file tree or search a symbol to scope Symbols view.");
            } else {
              setSceneNotice("Select a route/test/model target first to open a bounded Framework view.");
            }
          }}
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
