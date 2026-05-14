import type { IndexJob, Project } from "../productApi";

interface Props {
  project: Project | null;
  job: IndexJob | null;
}

export function JobStatus({ project, job }: Props) {
  const status = job?.status ?? project?.status ?? "created";
  return (
    <section className="product-panel job-status-panel">
      <div className="product-panel-heading">
        <h2>Index Job</h2>
        <span className={`status-pill status-${status}`}>{status}</span>
      </div>
      <div className="job-grid">
        <Metric label="Files" value={job?.files_indexed ?? 0} />
        <Metric label="Symbols" value={job?.symbols ?? 0} />
        <Metric label="Edges" value={job?.edges ?? 0} />
      </div>
      <p className="product-muted">{job?.progress_message || project?.error_message || "No job yet"}</p>
      {job?.error_message ? <p className="product-error-text">{job.error_message}</p> : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  );
}
