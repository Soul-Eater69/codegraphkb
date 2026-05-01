import { useMemo, useState } from "react";
import type { NodeRelations } from "../types/graph";

type InspectorTab = "Details" | "Relations" | "Processes" | "Impact" | "Context" | "Raw";

interface DetailsPanelProps {
  title: string;
  details: unknown;
  loading: boolean;
  error: string | null;
  relations?: NodeRelations | null;
  collapsed?: boolean;
}

const tabs: InspectorTab[] = ["Details", "Relations", "Processes", "Impact", "Context", "Raw"];

export function DetailsPanel({ title, details, loading, error, relations, collapsed = false }: DetailsPanelProps) {
  const [tab, setTab] = useState<InspectorTab>("Details");

  const detailNode = useMemo(() => {
    if (!details || typeof details !== "object") {
      return null;
    }
    const maybeNode = (details as { node?: Record<string, unknown> }).node;
    return maybeNode && typeof maybeNode === "object" ? maybeNode : null;
  }, [details]);

  if (collapsed) {
    return (
      <aside className="details-panel details-collapsed">
        <div className="panel-header">
          <h2>Inspector</h2>
        </div>
      </aside>
    );
  }

  return (
    <aside className="details-panel">
      <div className="panel-header">
        <h2>Inspector</h2>
        <p className="muted">{title}</p>
      </div>

      <div className="inspector-tabs">
        {tabs.map((name) => (
          <button key={name} type="button" className={tab === name ? "active" : ""} onClick={() => setTab(name)}>
            {name}
          </button>
        ))}
      </div>

      <div className="inspector-content">
        {loading ? <p className="muted">Loading details...</p> : null}
        {error ? <p className="error">{error}</p> : null}
        {!loading && !error && details == null ? (
          <p className="muted">Click a node, edge, process, or search result to inspect metadata and relations.</p>
        ) : null}
        {!loading && !error && details != null ? (
          <>
            {tab === "Details" ? <DetailsView detailNode={detailNode} details={details} /> : null}
            {tab === "Relations" ? <RelationsView relations={relations} details={details} /> : null}
            {tab === "Processes" ? <ProcessesView details={details} relations={relations} /> : null}
            {tab === "Impact" ? <ImpactView details={details} /> : null}
            {tab === "Context" ? <ContextView details={details} /> : null}
            {tab === "Raw" ? <pre>{JSON.stringify(details, null, 2)}</pre> : null}
          </>
        ) : null}
      </div>
    </aside>
  );
}

function DetailsView({ detailNode, details }: { detailNode: Record<string, unknown> | null; details: unknown }) {
  if (!detailNode) {
    return <pre>{JSON.stringify(details, null, 2)}</pre>;
  }
  return (
    <div className="kv-grid">
      <Field k="ID" v={detailNode.id} />
      <Field k="Kind" v={detailNode.kind} />
      <Field k="Name" v={detailNode.label ?? detailNode.name} />
      <Field k="Qualified" v={detailNode.qualified_name} />
      <Field k="File" v={detailNode.file_path} />
      <Field k="Lines" v={lineRange(detailNode.start_line, detailNode.end_line)} />
      <Field k="Signature" v={detailNode.signature} />
      <Field k="Return Type" v={detailNode.return_type} />
      <Field k="Parser" v={detailNode.parser_backend} />
      <Field k="Semantic" v={detailNode.semantic_backend} />
      <Field k="Confidence" v={detailNode.confidence} />
    </div>
  );
}

function RelationsView({ relations, details }: { relations?: NodeRelations | null; details: unknown }) {
  const rel = relations ?? extractRelations(details);
  const items = [
    ["Callers", rel.callers ?? []],
    ["Callees", rel.callees ?? []],
    ["Tests", rel.tests ?? []],
    ["Processes", rel.processes ?? []],
    ["Routes", rel.routes ?? []],
    ["Imports", rel.imports ?? []],
  ] as const;
  return (
    <div className="relation-groups">
      {items.map(([label, group]) => (
        <section key={label}>
          <h4>{label}</h4>
          {group.length === 0 ? <p className="muted">None</p> : null}
          <ul>
            {group.slice(0, 20).map((item, idx) => (
              <li key={`${label}-${idx}`}>
                <span>{String((item as Record<string, unknown>).label ?? (item as Record<string, unknown>).qualified_name ?? (item as Record<string, unknown>).id ?? "item")}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function ProcessesView({ details, relations }: { details: unknown; relations?: NodeRelations | null }) {
  const rel = relations ?? extractRelations(details);
  const procs = rel.processes ?? [];
  if (procs.length === 0) {
    return <p className="muted">No process traces associated with this selection.</p>;
  }
  return (
    <ul>
      {procs.map((proc, idx) => (
        <li key={`proc-${idx}`}>
          <span>{String((proc as Record<string, unknown>).label ?? (proc as Record<string, unknown>).id ?? "process")}</span>
          <small>{String((proc as Record<string, unknown>).type ?? (proc as Record<string, unknown>).process_type ?? "")}</small>
        </li>
      ))}
    </ul>
  );
}

function ImpactView({ details }: { details: unknown }) {
  if (!details || typeof details !== "object") {
    return <p className="muted">No impact details for current selection.</p>;
  }
  const metadata = (details as { metadata?: Record<string, unknown> }).metadata ?? {};
  return (
    <div className="kv-grid">
      <Field k="Target" v={metadata.target} />
      <Field k="Depth" v={metadata.max_depth} />
      <Field k="Nodes" v={metadata.node_count} />
      <Field k="Edges" v={metadata.edge_count} />
      <Field k="View" v={metadata.view} />
    </div>
  );
}

function ContextView({ details }: { details: unknown }) {
  return (
    <div className="context-panel">
      <p className="muted">
        Use selected nodes and processes as pinned context for context packs. Endpoint: <code>POST /api/context</code>.
      </p>
      <pre>{JSON.stringify({ selected: details }, null, 2)}</pre>
    </div>
  );
}

function Field({ k, v }: { k: string; v: unknown }) {
  return (
    <div className="kv-row">
      <span>{k}</span>
      <strong>{v == null || v === "" ? "—" : String(v)}</strong>
    </div>
  );
}

function lineRange(start: unknown, end: unknown): string {
  if (typeof start === "number" && typeof end === "number") {
    return `${start}-${end}`;
  }
  return "—";
}

function extractRelations(details: unknown): NodeRelations {
  if (!details || typeof details !== "object") {
    return {};
  }
  const relationships = (details as { relationships?: Record<string, unknown> }).relationships;
  if (!relationships) {
    return {};
  }
  return {
    callers: asList(relationships.callers),
    callees: asList(relationships.callees),
    tests: asList(relationships.related_tests ?? relationships.tests),
    processes: asList(relationships.processes),
    routes: asList(relationships.routes),
    imports: asList(relationships.imports),
  };
}

function asList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is Record<string, unknown> => typeof item === "object" && item != null);
}
