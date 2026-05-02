import type { ProcessSummary } from "../types/graph";

interface ProcessPanelProps {
  processes: ProcessSummary[];
  loading: boolean;
  error: string | null;
  onSelectProcess: (process: ProcessSummary) => void;
}

export function ProcessPanel({ processes, loading, error, onSelectProcess }: ProcessPanelProps) {
  return (
    <section className="panel">
      <h3>Processes</h3>
      {loading ? <p className="muted">Loading processes...</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {processes.length === 0 && !loading && !error ? <p className="muted">No process flows in this index.</p> : null}
      <ul>
        {processes.slice(0, 20).map((process) => (
          <li key={process.id}>
            <button type="button" onClick={() => onSelectProcess(process)}>
              <span>{process.label}</span>
              <small>
                {process.process_type} - steps {process.step_count} - conf {process.confidence.toFixed(2)}
              </small>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
