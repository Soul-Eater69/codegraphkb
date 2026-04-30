import { useEffect, useMemo, useState } from "react";
import {
  getGraph,
  getImpact,
  getNode,
  getProcess,
  getProcesses,
  getSummary,
  searchNodes,
} from "./api/client";
import { AskPanel } from "./components/AskPanel";
import { DetailsPanel } from "./components/DetailsPanel";
import { FiltersPanel } from "./components/FiltersPanel";
import { GraphCanvasPlaceholder } from "./components/GraphCanvasPlaceholder";
import { ImpactPanel } from "./components/ImpactPanel";
import { ProcessPanel } from "./components/ProcessPanel";
import { Sidebar, type SidebarTab } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import type {
  GraphPayload,
  GraphView,
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

  const [activeTab, setActiveTab] = useState<SidebarTab>("Explorer");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [impactTarget, setImpactTarget] = useState("");

  const [selectedDetailsTitle, setSelectedDetailsTitle] = useState("Selection");
  const [selectedDetails, setSelectedDetails] = useState<unknown>(null);

  const [selectedNodeKinds, setSelectedNodeKinds] = useState<Set<string>>(new Set());
  const [selectedEdgeTypes, setSelectedEdgeTypes] = useState<Set<string>>(new Set());

  const [loadingSummary, setLoadingSummary] = useState(false);
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [loadingProcesses, setLoadingProcesses] = useState(false);
  const [loadingImpact, setLoadingImpact] = useState(false);
  const [loadingDetails, setLoadingDetails] = useState(false);

  const [errorSummary, setErrorSummary] = useState<string | null>(null);
  const [errorGraph, setErrorGraph] = useState<string | null>(null);
  const [errorProcesses, setErrorProcesses] = useState<string | null>(null);
  const [errorImpact, setErrorImpact] = useState<string | null>(null);
  const [errorDetails, setErrorDetails] = useState<string | null>(null);

  useEffect(() => {
    void loadSummary();
    void loadProcesses();
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

  const filteredCounts = useMemo(() => {
    const nodes = graph?.nodes ?? [];
    const edges = graph?.edges ?? [];
    const visibleNodes =
      selectedNodeKinds.size === 0
        ? nodes
        : nodes.filter((n) => selectedNodeKinds.has(n.kind));
    const visibleNodeIds = new Set(visibleNodes.map((n) => n.id));
    const visibleEdges = edges.filter((e) => {
      const typeVisible =
        selectedEdgeTypes.size === 0 || selectedEdgeTypes.has(e.type);
      return typeVisible && visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target);
    });
    return {
      nodeCount: visibleNodes.length,
      edgeCount: visibleEdges.length,
    };
  }, [graph, selectedNodeKinds, selectedEdgeTypes]);

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
      setSelectedDetailsTitle(`Graph: ${nextView}`);
      setSelectedDetails(payload.metadata);
      setSelectedNodeKinds(new Set());
      setSelectedEdgeTypes(new Set());
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
      const details = await getNode(result.id);
      setSelectedDetailsTitle(`Node: ${result.label}`);
      setSelectedDetails(details);
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
      setSelectedDetailsTitle(`Process: ${proc.label}`);
      setSelectedDetails(proc);
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
      setSelectedDetailsTitle(`Impact: ${target}`);
      setSelectedDetails(payload.metadata);
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
            note: "UI-2 placeholder. Selection-driven context generation lands in a later phase.",
            next_endpoint: "POST /api/context",
          });
        }}
      />

      <div className="status-row">
        {loadingSummary ? <span>Loading summary...</span> : null}
        {errorSummary ? <span className="error">{errorSummary}</span> : null}
        {!loadingSummary && !errorSummary && summary ? (
          <span>
            Files {summary.files ?? 0} · Symbols {summary.symbols ?? 0} · Edges {summary.edges ?? 0} · Processes{" "}
            {summary.processes ?? 0}
          </span>
        ) : null}
      </div>

      <main className="main-layout">
        <Sidebar activeTab={activeTab} onTabChange={setActiveTab}>
          {activeTab === "Explorer" ? (
            <div className="explorer-panel">
              <h3>Repository</h3>
              <p className="muted">{summary?.repo_path ?? "No summary loaded."}</p>
              <h3>Languages</h3>
              <ul>
                {Object.entries(summary?.languages ?? {}).map(([lang, count]) => (
                  <li key={lang}>
                    <span>{lang}</span>
                    <strong>{count}</strong>
                  </li>
                ))}
                {Object.keys(summary?.languages ?? {}).length === 0 ? (
                  <li className="muted">No language data.</li>
                ) : null}
              </ul>
              <h3>Search Results</h3>
              <ul>
                {searchResults.map((result) => (
                  <li key={result.id}>
                    <button type="button" onClick={() => void selectSearchResult(result)}>
                      <span>{result.label}</span>
                      <small>
                        {result.kind} · {result.file_path ?? result.id}
                      </small>
                    </button>
                  </li>
                ))}
                {searchResults.length === 0 ? <li className="muted">Search to inspect node details.</li> : null}
              </ul>
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
                note: "UI-2 placeholder. Use backend /api/context manually for now.",
              });
            }}
          />
        </Sidebar>

        <GraphCanvasPlaceholder
          view={view}
          graph={graph}
          filteredNodeCount={filteredCounts.nodeCount}
          filteredEdgeCount={filteredCounts.edgeCount}
          loading={loadingGraph}
          error={errorGraph}
        />

        <DetailsPanel
          title={selectedDetailsTitle}
          details={selectedDetails}
          loading={loadingDetails}
          error={errorDetails}
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
