import type { ProcessSummary } from "../types/graph";

interface ProcessPanelProps {
  processes: ProcessSummary[];
  loading: boolean;
  error: string | null;
  onSelectProcess: (processId: string) => void;
}

export function ProcessPanel({ processes, loading, error, onSelectProcess }: ProcessPanelProps) {
  return (
    <div className="process-panel">
      <h3>Processes</h3>
      {loading ? <p className="muted">Loading processes...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {!loading && !error && processes.length === 0 ? <p className="muted">No processes found in this index.</p> : null}
      <ul>
        {processes.map((proc) => (
          <li key={proc.id}>
            <button type="button" onClick={() => onSelectProcess(proc.id)}>
              <span>{proc.label}</span>
              <small>
                {proc.process_type} · conf {proc.confidence.toFixed(2)} · steps {proc.step_count}
              </small>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
