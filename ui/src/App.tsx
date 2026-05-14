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
import ProductApp from "./product/ProductApp";
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
    maxNodes: 5000,
    maxEdges: 15000,
  },
};

export default function App() {
  if (window.location.pathname.startsWith("/projects")) {
    return <ProductApp />;
  }
  return <GraphExplorerApp />;
}

function GraphExplorerApp() {
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [perspective, setPerspective] = useState<Perspective>("none");
  const [selectedView, setSelectedView] = useState<GraphView>("full");
  const [execution, setExecution] = useState<QueryExecution>(EMPTY_EXECUTION);

  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [processes, setProcesses] = useState<ProcessSummary[]>([]);
  const [fileTree, setFileTree] = useState<FileTreeNode | null>(null);

  const [selectedNodeKinds, setSelectedNodeKinds] = useState<Set<string>>(new Set());
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState<Set<string>>(new Set());

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set());

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
  const [pendingAutoPerspective, setPendingAutoPerspective] = useState<Perspective | null>(null);

  const [errorGraph, setErrorGraph] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<string | null>(null);
  const [errorTree, setErrorTree] = useState<string | null>(null);
  const [errorProcesses, setErrorProcesses] = useState<string | null>(null);

  useEffect(() => {
    void loadSummary();
    void loadProcesses();
    void loadFileTree();
    void executeView("full");
  }, []);

  useEffect(() => {
    if (pendingAutoPerspective === "symbols") {
      const firstFile = findFirstFile(fileTree);
      if (firstFile) {
        setPendingAutoPerspective(null);
        void executeFileSymbols(firstFile.path);
      }
    }
    if (pendingAutoPerspective === "processes" && processes.length > 0) {
      setPendingAutoPerspective(null);
      void selectProcess(processes[0]);
    }
  }, [fileTree, pendingAutoPerspective, processes]);

  useEffect(() => {
    const q = query.trim();
    if (q.length < 2 || /^(repo|full|overview|processes|impact|neighborhood)\b/i.test(q)) {
      if (q.length === 0) {
        setSearchResults([]);
      }
      return;
    }
    const timer = window.setTimeout(() => {
      void searchNodes(q.replace(/^search\s+/i, "")).then((result) => {
        setSearchResults(result.results);
      }).catch(() => undefined);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query]);

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
    if (view === "symbols") {
      const firstFile = findFirstFile(fileTree);
      if (firstFile) {
        await selectSearchResult({
          id: `file:${firstFile.path}`,
          label: firstFile.path,
          kind: "file",
          file_path: firstFile.path,
        });
        return;
      }
      if (loadingTree) {
        setPendingAutoPerspective("symbols");
        showScopedEmpty("symbols", "Loading file tree, then the first file symbol scope will open.");
        return;
      }
    }
    if (view === "processes") {
      if (processes.length > 0) {
        await selectProcess(processes[0]);
        return;
      }
      if (loadingProcesses) {
        setPendingAutoPerspective("processes");
        showScopedEmpty("processes", "Loading process flows, then the first process will open.");
        return;
      }
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

  function showScopedEmpty(nextPerspective: Perspective, notice: string) {
    setGraph(null);
    setPerspective(nextPerspective);
    setExecution({ perspective: nextPerspective });
    setSceneNotice(notice);
    setErrorGraph(null);
    clearSelection();
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
    setSearchResults([]);
    setHighlightedNodeIds(new Set([nodeId]));
    if (nodeId.startsWith("file:")) {
      await executeFileSymbols(nodeId.slice("file:".length));
      return;
    }
    if (!nodeInGraph(nodeId)) {
      if (nodeId.startsWith("symbol:")) {
        await executeNeighborhood(nodeId, "calls");
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

  async function executeFileSymbols(filePath: string) {
    const nodeId = `file:${filePath}`;
    setLoadingGraph(true);
    setErrorGraph(null);
    setPerspective("symbols");
    setExecution({ perspective: "symbols", target: filePath });
    setSceneNotice("");
    try {
      const fileDetails = await getNode(nodeId);
      const relationships = fileDetails.relationships;
      const symbols = Array.isArray(relationships?.symbols)
        ? (relationships.symbols as Array<Record<string, unknown>>)
        : [];
      const symbolNodes = symbols.slice(0, 199).map((sym, index) => ({
        id: String(sym.id ?? `symbol:${filePath}:${index}`),
        label: String(sym.label ?? sym.name ?? sym.id ?? `symbol-${index}`),
        kind: String(sym.kind ?? "function"),
        file_path: filePath,
        start_line: typeof sym.start_line === "number" ? sym.start_line : undefined,
        end_line: typeof sym.end_line === "number" ? sym.end_line : undefined,
        metadata: sym,
      }));
      const payload: GraphPayload = {
        metadata: {
          view: "symbols",
          target: filePath,
          node_count: 1 + symbolNodes.length,
          edge_count: symbolNodes.length,
        },
        nodes: [
          {
            id: nodeId,
            label: filePath.split("/").pop() ?? filePath,
            kind: "file",
            file_path: filePath,
          },
          ...symbolNodes,
        ],
        edges: symbolNodes.map((node, index) => ({
          id: `contains:${filePath}:${index}`,
          source: nodeId,
          target: node.id,
          type: "CONTAINS",
          confidence: 1,
          precision_level: 3,
        })),
      };
      setGraph(payload);
      setSelectedNodeId(nodeId);
      setHighlightedNodeIds(new Set([nodeId]));
      setSelectedEdgeId(null);
      setDetails(fileDetails);
      setRelations((relationships ?? {}) as NodeRelations);
      setDetailsTitle(`File: ${filePath}`);
      setInspectorOpen(true);
    } catch (err) {
      setErrorGraph(asError(err));
    } finally {
      setLoadingGraph(false);
    }
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
    setHighlightedNodeIds(new Set());
    setRelations(null);
    setDetails(null);
    setInspectorOpen(false);
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
        searchResults={searchResults}
        onSelectSearchResult={(result) => void selectSearchResult(result)}
      />

      <div className="main-layout">
        <LeftRail>
          <GraphInfoPanel summary={summary} />
          <PerspectivesPanel active={perspective} onAction={(action) => void executeView(action)} />
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
          highlightedNodeIds={highlightedNodeIds}
          onNodeClick={(nodeId) => {
            setSelectedNodeId(nodeId);
            setSelectedEdgeId(null);
            setHighlightedNodeIds(new Set());
            const graphNode = graph?.nodes.find((node) => node.id === nodeId);
            setDetailsTitle(`Node: ${graphNode?.label ?? nodeId}`);
            setDetails(graphNode ? { node: graphNode } : { node: { id: nodeId } });
            setRelations(null);
            setInspectorOpen(true);
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
            void executeView(action);
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

function findFirstFile(node: FileTreeNode | null): FileTreeNode | null {
  return findFirstFileWithSymbols(node) ?? findFirstFileAny(node);
}

function findFirstFileWithSymbols(node: FileTreeNode | null): FileTreeNode | null {
  if (!node) {
    return null;
  }
  if (node.type === "file") {
    return (node.symbol_count ?? 0) > 0 ? node : null;
  }
  for (const child of node.children ?? []) {
    const found = findFirstFileWithSymbols(child);
    if (found) {
      return found;
    }
  }
  return null;
}

function findFirstFileAny(node: FileTreeNode | null): FileTreeNode | null {
  if (!node) {
    return null;
  }
  if (node.type === "file") {
    return node;
  }
  for (const child of node.children ?? []) {
    const found = findFirstFileAny(child);
    if (found) {
      return found;
    }
  }
  return null;
}
