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
import { AskPanel } from "./components/AskPanel";
import { DetailsPanel } from "./components/DetailsPanel";
import { FiltersPanel } from "./components/FiltersPanel";
import { GraphCanvas } from "./components/GraphCanvas";
import { ImpactPanel } from "./components/ImpactPanel";
import { ProcessPanel } from "./components/ProcessPanel";
import { Sidebar, type SidebarTab } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import type {
  FileTreeNode,
  GraphPayload,
  GraphView,
  NodeRelations,
  ProcessSummary,
  SearchResult,
  SummaryResponse,
} from "./types/graph";

export default function App() {
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [view, setView] = useState<GraphView>("repo");
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [processes, setProcesses] = useState<ProcessSummary[]>([]);
  const [impactGraph, setImpactGraph] = useState<GraphPayload | null>(null);
  const [fileTree, setFileTree] = useState<FileTreeNode | null>(null);

  const [activeTab, setActiveTab] = useState<SidebarTab>("Explorer");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [impactTarget, setImpactTarget] = useState("");
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);

  const [selectedDetailsTitle, setSelectedDetailsTitle] = useState("Selection");
  const [selectedDetails, setSelectedDetails] = useState<unknown>(null);
  const [selectedRelations, setSelectedRelations] = useState<NodeRelations | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set());

  const [selectedNodeKinds, setSelectedNodeKinds] = useState<Set<string>>(new Set());
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState<Set<string>>(new Set());

  const [loadingSummary, setLoadingSummary] = useState(false);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [loadingProcesses, setLoadingProcesses] = useState(false);
  const [loadingImpact, setLoadingImpact] = useState(false);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [loadingExplorer, setLoadingExplorer] = useState(false);

  const [errorSummary, setErrorSummary] = useState<string | null>(null);
  const [errorGraph, setErrorGraph] = useState<string | null>(null);
  const [errorProcesses, setErrorProcesses] = useState<string | null>(null);
  const [errorImpact, setErrorImpact] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<string | null>(null);
  const [errorExplorer, setErrorExplorer] = useState<string | null>(null);

  useEffect(() => {
    void loadSummary();
    void loadProcesses();
    void loadFileTree();
  }, []);

  useEffect(() => {
    void loadGraph(view);
  }, [view]);

  const nodeKindCounts = useMemo(
    () => countValues(graph?.nodes.map((n) => n.kind) ?? []),
    [graph],
  );
  const edgeTypeCounts = useMemo(
    () => countValues(graph?.edges.map((e) => e.type) ?? []),
    [graph],
  );

  const groupedSearch = useMemo(() => groupSearchResults(searchResults), [searchResults]);

  async function loadSummary() {
    setLoadingSummary(true);
    setErrorSummary(null);
    try {
      setSummary(await getSummary());
    } catch (err) {
      setErrorSummary(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingSummary(false);
    }
  }

  async function loadGraph(nextView: GraphView) {
    setLoadingGraph(true);
    setErrorGraph(null);
    try {
      const payload = await getGraph(nextView);
      setGraph(payload);
      setSelectedDetailsTitle(`Perspective: ${nextView}`);
      setSelectedDetails(payload.metadata);
      setSelectedRelations(null);
      setSelectedNodeKinds(new Set());
      setSelectedEdgeTypes(new Set());
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setHighlightedNodeIds(new Set());
    } catch (err) {
      setErrorGraph(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingGraph(false);
    }
  }

  async function loadProcesses() {
    setLoadingProcesses(true);
    setErrorProcesses(null);
    try {
      setProcesses(await getProcesses());
    } catch (err) {
      setErrorProcesses(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingProcesses(false);
    }
  }

  async function loadFileTree() {
    setLoadingExplorer(true);
    setErrorExplorer(null);
    try {
      setFileTree(await getFilesTree());
    } catch (err) {
      setErrorExplorer(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingExplorer(false);
    }
  }

  async function runSearch() {
    const q = searchQuery.trim();
    if (!q) {
      setSearchResults([]);
      return;
    }
    setLoadingSearch(true);
    setErrorDetails(null);
    try {
      const res = await searchNodes(q);
      setSearchResults(res.results);
      if (res.results.length > 0) {
        await selectSearchResult(res.results[0]);
      } else {
        setSelectedDetailsTitle(`Search: ${q}`);
        setSelectedDetails({ query: q, results: [] });
        setSelectedRelations(null);
      }
    } catch (err) {
      setErrorDetails(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingSearch(false);
    }
  }

  async function selectSearchResult(result: SearchResult) {
    setLoadingDetails(true);
    setErrorDetails(null);
    try {
      if (!isNodeVisibleInGraph(result.id)) {
        const neighborhood = await getNeighborhood(result.id, 2);
        setGraph(neighborhood);
        setSelectedDetailsTitle(`Neighborhood: ${result.label}`);
        setSelectedDetails(neighborhood.metadata);
      }
      const [details, relations] = await Promise.all([
        getNode(result.id),
        getNodeRelations(result.id).catch(() => ({})),
      ]);
      setSelectedDetailsTitle(`Node: ${result.label}`);
      setSelectedDetails(details);
      setSelectedRelations(relations as NodeRelations);
      setSelectedNodeId(result.id);
      setSelectedEdgeId(null);
      setHighlightedNodeIds(new Set([result.id]));
    } catch (err) {
      setErrorDetails(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDetails(false);
    }
  }

  async function selectProcess(processId: string) {
    setLoadingDetails(true);
    setErrorDetails(null);
    try {
      const proc = await getProcess(processId);
      const processNodeId = proc.node_id ?? `process:${processId}`;
      if (!isNodeVisibleInGraph(processNodeId)) {
        const neighborhood = await getNeighborhood(processNodeId, 2);
        setGraph(neighborhood);
      }
      setSelectedDetailsTitle(`Process: ${proc.label}`);
      setSelectedDetails(proc);
      setSelectedRelations({
        processes: [{ id: proc.id, label: proc.label, process_type: proc.process_type }],
      });
      setSelectedNodeId(processNodeId);
      setSelectedEdgeId(null);
      setHighlightedNodeIds(new Set([processNodeId]));
    } catch (err) {
      setErrorDetails(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDetails(false);
    }
  }

  async function runImpact() {
    const target = impactTarget.trim();
    if (!target) {
      return;
    }
    setLoadingImpact(true);
    setErrorImpact(null);
    try {
      const payload = await getImpact(target);
      setImpactGraph(payload);
      setGraph(payload);
      setSelectedDetailsTitle(`Impact: ${target}`);
      setSelectedDetails(payload);
      setSelectedRelations(null);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setHighlightedNodeIds(new Set());
      setActiveTab("Impact");
    } catch (err) {
      setErrorImpact(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingImpact(false);
    }
  }

  function toggleNodeKind(kind: string) {
    setSelectedNodeKinds((prev) => toggleSelection(prev, kind));
  }

  function toggleEdgeType(type: string) {
    setSelectedEdgeTypes((prev) => toggleSelection(prev, type));
  }

  async function selectNodeById(nodeId: string) {
    setLoadingDetails(true);
    setErrorDetails(null);
    try {
      const [details, relations] = await Promise.all([
        getNode(nodeId),
        getNodeRelations(nodeId).catch(() => ({})),
      ]);
      const label = extractNodeLabel(details) ?? nodeId;
      setSelectedDetailsTitle(`Node: ${label}`);
      setSelectedDetails(details);
      setSelectedRelations(relations as NodeRelations);
      setSelectedNodeId(nodeId);
      setSelectedEdgeId(null);
      setHighlightedNodeIds(new Set([nodeId]));
    } catch (err) {
      setErrorDetails(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDetails(false);
    }
  }

  function clearSelection() {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setSelectedRelations(null);
    setHighlightedNodeIds(new Set());
  }

  function isNodeVisibleInGraph(nodeId: string): boolean {
    if (!graph) {
      return false;
    }
    return graph.nodes.some((n) => n.id === nodeId);
  }

  return (
    <div className="app-shell">
      <TopBar
        summary={summary}
        view={view}
        onViewChange={setView}
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        onSearchSubmit={() => void runSearch()}
        loading={loadingSearch}
        onAskClick={() => {
          setSelectedDetailsTitle("Ask CodeGraphKB");
          setSelectedDetails({
            note: "Generate a context pack using selected nodes via POST /api/context.",
            selected_node_ids: selectedNodeId ? [selectedNodeId] : [],
          });
          setSelectedRelations(null);
        }}
        leftCollapsed={leftCollapsed}
        rightCollapsed={rightCollapsed}
        onToggleLeft={() => setLeftCollapsed((v) => !v)}
        onToggleRight={() => setRightCollapsed((v) => !v)}
      />

      {errorSummary ? <div className="top-error">{errorSummary}</div> : null}
      {loadingSummary ? <div className="top-info">Loading summary...</div> : null}

      <main
        className={`main-layout ${leftCollapsed ? "left-collapsed" : ""} ${rightCollapsed ? "right-collapsed" : ""}`}
      >
        <Sidebar activeTab={activeTab} onTabChange={setActiveTab} collapsed={leftCollapsed}>
          {activeTab === "Explorer" ? (
            <div className="explorer-panel">
              <h3>Repository</h3>
              <p className="muted">{summary?.repo_path ?? "No summary loaded."}</p>
              <h3>Search Results</h3>
              {Object.entries(groupedSearch).map(([group, items]) => (
                <section key={group}>
                  <h4>{group}</h4>
                  <ul>
                    {items.map((result) => (
                      <li key={result.id}>
                        <button type="button" onClick={() => void selectSearchResult(result)}>
                          <span>{result.label}</span>
                          <small>
                            {result.kind} · {result.file_path ?? result.id}
                          </small>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
              {searchResults.length === 0 ? <p className="muted">Search to start graph investigation.</p> : null}

              <h3>File Explorer</h3>
              {loadingExplorer ? <p className="muted">Loading tree...</p> : null}
              {errorExplorer ? <p className="error">{errorExplorer}</p> : null}
              {!loadingExplorer && !errorExplorer && fileTree ? (
                <div className="tree-root">{renderTree(fileTree, (path) => void selectSearchResult({ id: `file:${path}`, label: path.split("/").pop() ?? path, kind: "file", file_path: path }))}</div>
              ) : null}
            </div>
          ) : null}

          {activeTab === "Filters" ? (
            <FiltersPanel
              nodeKindCounts={nodeKindCounts}
              edgeTypeCounts={edgeTypeCounts}
              selectedNodeKinds={selectedNodeKinds}
              selectedEdgeTypes={selectedEdgeTypes}
              onToggleNodeKind={toggleNodeKind}
              onToggleEdgeType={toggleEdgeType}
            />
          ) : null}

          {activeTab === "Processes" ? (
            <ProcessPanel
              processes={processes}
              loading={loadingProcesses}
              error={errorProcesses}
              onSelectProcess={(id) => void selectProcess(id)}
            />
          ) : null}

          {activeTab === "Impact" ? (
            <ImpactPanel
              impactTarget={impactTarget}
              onImpactTargetChange={setImpactTarget}
              onRunImpact={() => void runImpact()}
              loading={loadingImpact}
              error={errorImpact}
              impactGraph={impactGraph}
            />
          ) : null}

          <AskPanel
            onOpen={() => {
              setSelectedDetailsTitle("Ask CodeGraphKB");
              setSelectedDetails({
                task: "Describe or edit from selected graph elements.",
                endpoint: "POST /api/context",
              });
              setSelectedRelations(null);
            }}
          />
        </Sidebar>

        <GraphCanvas
          view={view}
          graph={graph}
          loading={loadingGraph}
          error={errorGraph}
          selectedNodeKinds={selectedNodeKinds}
          selectedEdgeTypes={selectedEdgeTypes}
          selectedNodeId={selectedNodeId}
          selectedEdgeId={selectedEdgeId}
          highlightedNodeIds={highlightedNodeIds}
          nodeKindCounts={nodeKindCounts}
          edgeTypeCounts={edgeTypeCounts}
          onNodeSelect={(nodeId) => void selectNodeById(nodeId)}
          onStageClick={clearSelection}
          onEdgeSelect={(edgeId, edgeData) => {
            setSelectedEdgeId(edgeId);
            setSelectedNodeId(null);
            setSelectedRelations(null);
            setSelectedDetailsTitle(`Edge: ${edgeId}`);
            setSelectedDetails(edgeData);
          }}
          onClearSelection={clearSelection}
          onRequestView={setView}
        />

        <DetailsPanel
          title={selectedDetailsTitle}
          details={selectedDetails}
          relations={selectedRelations}
          loading={loadingDetails}
          error={errorDetails}
          collapsed={rightCollapsed}
        />
      </main>
    </div>
  );
}

function countValues(values: string[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const v of values) {
    counts[v] = (counts[v] ?? 0) + 1;
  }
  return counts;
}

function toggleSelection(source: Set<string>, value: string): Set<string> {
  const next = new Set(source);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  return next;
}

function extractNodeLabel(details: unknown): string | null {
  if (typeof details !== "object" || details == null) {
    return null;
  }
  const node = (details as { node?: Record<string, unknown> }).node;
  if (!node) {
    return null;
  }
  const label = node.label;
  return typeof label === "string" ? label : null;
}

function groupSearchResults(results: SearchResult[]): Record<string, SearchResult[]> {
  const groups: Record<string, SearchResult[]> = {
    Files: [],
    Functions: [],
    Classes: [],
    Routes: [],
    Processes: [],
    Tests: [],
    Other: [],
  };

  for (const item of results) {
    const kind = item.kind.toLowerCase();
    if (kind === "file") {
      groups.Files.push(item);
    } else if (kind.includes("function") || kind === "method") {
      groups.Functions.push(item);
    } else if (kind === "class" || kind === "interface") {
      groups.Classes.push(item);
    } else if (kind.includes("route")) {
      groups.Routes.push(item);
    } else if (kind.includes("process")) {
      groups.Processes.push(item);
    } else if (kind.includes("test")) {
      groups.Tests.push(item);
    } else {
      groups.Other.push(item);
    }
  }

  return Object.fromEntries(Object.entries(groups).filter(([, arr]) => arr.length > 0));
}

function renderTree(node: FileTreeNode, onFileClick: (path: string) => void, depth = 0): JSX.Element {
  if (node.type === "file") {
    return (
      <button type="button" className="tree-file" style={{ paddingLeft: `${8 + depth * 12}px` }} onClick={() => onFileClick(node.path)}>
        {node.name}
        <small>{node.symbol_count ?? 0}</small>
      </button>
    );
  }

  return (
    <details className="tree-folder" open={depth < 1}>
      <summary>
        <span>{node.name || "repo"}</span>
        <small>{node.file_count ?? 0}</small>
      </summary>
      <div>
        {(node.children ?? []).map((child) => (
          <div key={`${child.type}:${child.path}`}>
            {renderTree(child, onFileClick, depth + 1)}
          </div>
        ))}
      </div>
    </details>
  );
}
