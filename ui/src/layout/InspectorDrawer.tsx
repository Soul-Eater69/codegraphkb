import { useMemo, useState } from "react";
import type { NodeRelations } from "../types/graph";

type InspectorTab = "Summary" | "Relations" | "Process" | "Impact" | "Context" | "Raw";

interface InspectorDrawerProps {
  open: boolean;
  title: string;
  details: unknown;
  relations: NodeRelations | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

const tabs: InspectorTab[] = ["Summary", "Relations", "Process", "Impact", "Context", "Raw"];

export function InspectorDrawer({
  open,
  title,
  details,
  relations,
  loading,
  error,
  onClose,
}: InspectorDrawerProps) {
  const [tab, setTab] = useState<InspectorTab>("Summary");
  const summary = useMemo(() => extractSummary(details), [details]);

  return (
    <aside className={`inspector ${open ? "open" : "closed"}`}>
      {!open ? (
        <button type="button" className="inspector-open" onClick={() => setTab("Summary")}>
          Inspector ▸
        </button>
      ) : (
        <>
          <div className="inspector-header">
            <h3>Inspector</h3>
            <button type="button" onClick={onClose}>
              ✕
            </button>
          </div>
          <p className="muted">{title}</p>
          <div className="inspector-tabs">
            {tabs.map((name) => (
              <button key={name} type="button" className={tab === name ? "active" : ""} onClick={() => setTab(name)}>
                {name}
              </button>
            ))}
          </div>
          <div className="inspector-body">
            {loading ? <p className="muted">Loading…</p> : null}
            {error ? <p className="error">{error}</p> : null}
            {!loading && !error && details == null ? <p className="muted">Select a node, edge, process, or impact result.</p> : null}
            {!loading && !error && details != null && tab === "Summary" ? (
              <div className="kv">
                {Object.entries(summary).map(([key, value]) => (
                  <div className="kv-row" key={key}>
                    <span>{key}</span>
                    <strong>{String(value)}</strong>
                  </div>
                ))}
              </div>
            ) : null}
            {!loading && !error && tab === "Relations" ? <RelationsView relations={relations} /> : null}
            {!loading && !error && tab === "Process" ? <ProcessView details={details} relations={relations} /> : null}
            {!loading && !error && tab === "Impact" ? <ImpactView details={details} /> : null}
            {!loading && !error && tab === "Context" ? <ContextView details={details} /> : null}
            {!loading && !error && tab === "Raw" && details != null ? <pre>{JSON.stringify(details, null, 2)}</pre> : null}
          </div>
        </>
      )}
    </aside>
  );
}

function extractSummary(details: unknown): Record<string, unknown> {
  if (!details || typeof details !== "object") {
    return {};
  }
  const asRecord = details as Record<string, unknown>;
  const node = asRecord.node && typeof asRecord.node === "object" ? (asRecord.node as Record<string, unknown>) : null;
  if (node) {
    return {
      id: node.id ?? "—",
      kind: node.kind ?? "—",
      label: node.label ?? node.name ?? "—",
      qname: node.qualified_name ?? "—",
      file: node.file_path ?? "—",
      lines:
        typeof node.start_line === "number" && typeof node.end_line === "number"
          ? `${node.start_line}-${node.end_line}`
          : "—",
    };
  }
  return {
    type: asRecord.type ?? asRecord.view ?? "selection",
    source: asRecord.source ?? "—",
    target: asRecord.target ?? "—",
    confidence: asRecord.confidence ?? "—",
  };
}

function RelationsView({ relations }: { relations: NodeRelations | null }) {
  const groups: Array<[string, unknown[]]> = [
    ["callers", relations?.callers ?? []],
    ["callees", relations?.callees ?? []],
    ["tests", relations?.tests ?? []],
    ["processes", relations?.processes ?? []],
    ["routes", relations?.routes ?? []],
    ["imports", relations?.imports ?? []],
  ];
  return (
    <div className="relations-list">
      {groups.map(([name, items]) => (
        <section key={name}>
          <h4>{name}</h4>
          {items.length === 0 ? <p className="muted">None</p> : null}
          <ul>
            {items.slice(0, 20).map((item, idx) => {
              const rec = item as Record<string, unknown>;
              const label = rec.label ?? rec.id ?? rec.qualified_name ?? `item-${idx}`;
              return (
                <li key={`${name}-${idx}`}>
                  <span>{String(label)}</span>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

function ProcessView({ details, relations }: { details: unknown; relations: NodeRelations | null }) {
  const processList = relations?.processes ?? [];
  if (processList.length > 0) {
    return (
      <ul>
        {processList.map((item, idx) => (
          <li key={`process-${idx}`}>{String((item as Record<string, unknown>).label ?? (item as Record<string, unknown>).id ?? "process")}</li>
        ))}
      </ul>
    );
  }
  if (details && typeof details === "object" && Array.isArray((details as { steps?: unknown[] }).steps)) {
    const steps = (details as { steps: unknown[] }).steps;
    return (
      <ul>
        {steps.map((step, idx) => (
          <li key={`step-${idx}`}>{JSON.stringify(step)}</li>
        ))}
      </ul>
    );
  }
  return <p className="muted">No process data available.</p>;
}

function ImpactView({ details }: { details: unknown }) {
  if (!details || typeof details !== "object") {
    return <p className="muted">No impact metadata available.</p>;
  }
  const rec = details as Record<string, unknown>;
  const metadata =
    rec.metadata && typeof rec.metadata === "object"
      ? (rec.metadata as Record<string, unknown>)
      : rec;
  return (
    <div className="kv">
      {["target", "view", "node_count", "edge_count", "max_depth"].map((key) => (
        <div className="kv-row" key={key}>
          <span>{key}</span>
          <strong>{String(metadata[key] ?? "—")}</strong>
        </div>
      ))}
    </div>
  );
}

function ContextView({ details }: { details: unknown }) {
  return (
    <div className="context-help">
      <p>Use selected graph nodes as pinned context.</p>
      <p className="muted">Endpoint: POST /api/context</p>
      {details ? <pre>{JSON.stringify(details, null, 2)}</pre> : null}
    </div>
  );
}
