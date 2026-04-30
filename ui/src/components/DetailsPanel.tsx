interface DetailsPanelProps {
  title: string;
  details: unknown;
  loading: boolean;
  error: string | null;
}

export function DetailsPanel({ title, details, loading, error }: DetailsPanelProps) {
  return (
    <aside className="details-panel">
      <div className="panel-header">
        <h2>Details</h2>
      </div>
      {loading ? <p className="muted">Loading details...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {!loading && !error && details == null ? (
        <p className="muted">Click a search result, process, or impact item to inspect metadata.</p>
      ) : null}
      {!loading && !error && details != null ? (
        <>
          <h3>{title}</h3>
          <pre>{JSON.stringify(details, null, 2)}</pre>
        </>
      ) : null}
    </aside>
  );
}
