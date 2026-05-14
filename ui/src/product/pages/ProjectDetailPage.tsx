import { useEffect, useState } from "react";
import { JobStatus } from "../components/JobStatus";
import { StatsPanel } from "../components/StatsPanel";
import {
  getLatestJob,
  getProject,
  getProjectFiles,
  getProjectStats,
  getProjectSymbols,
  reindexProject,
  type IndexJob,
  type Project,
  type ProjectFile,
  type ProjectStats,
  type ProjectSymbol,
} from "../productApi";

interface Props {
  projectId: string;
  onBack: () => void;
  onAsk: () => void;
  onPrepareEdit: () => void;
}

export function ProjectDetailPage({ projectId, onBack, onAsk, onPrepareEdit }: Props) {
  const [project, setProject] = useState<Project | null>(null);
  const [job, setJob] = useState<IndexJob | null>(null);
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [symbols, setSymbols] = useState<ProjectSymbol[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reindexing, setReindexing] = useState(false);

  useEffect(() => {
    void load();
  }, [projectId]);

  useEffect(() => {
    if (!project || project.status === "ready" || project.status === "failed") {
      return;
    }
    const timer = window.setInterval(() => {
      void load(false);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [project?.status, projectId]);

  async function load(showLoading = true) {
    if (showLoading) {
      setLoading(true);
    }
    setError(null);
    try {
      const nextProject = await getProject(projectId);
      const nextJob = await getLatestJob(projectId);
      setProject(nextProject);
      setJob(nextJob);
      if (nextProject.status === "ready") {
        const [nextStats, nextFiles, nextSymbols] = await Promise.all([
          getProjectStats(projectId),
          getProjectFiles(projectId),
          getProjectSymbols(projectId),
        ]);
        setStats(nextStats);
        setFiles(nextFiles);
        setSymbols(nextSymbols);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function triggerReindex() {
    setReindexing(true);
    setError(null);
    try {
      await reindexProject(projectId, true);
      await load(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setReindexing(false);
    }
  }

  const ready = project?.status === "ready";

  return (
    <main className="product-page">
      <div className="product-page-heading">
        <div>
          <h1>{project?.name ?? "Project"}</h1>
          <p>{project?.source_ref ?? projectId}</p>
        </div>
        <div className="product-actions">
          <button type="button" onClick={onBack}>Projects</button>
          <button type="button" onClick={() => void triggerReindex()} disabled={reindexing}>{reindexing ? "Indexing" : "Reindex"}</button>
        </div>
      </div>
      {loading ? <p className="product-muted">Loading project</p> : null}
      {error ? <p className="product-error-text">{error}</p> : null}
      <JobStatus project={project} job={job} />
      {ready ? (
        <>
          <div className="product-action-tabs">
            <button type="button" onClick={onAsk}>Ask</button>
            <button type="button" onClick={onPrepareEdit}>Prepare Edit</button>
          </div>
          <StatsPanel stats={stats} />
          <section className="product-panel">
            <div className="product-panel-heading">
              <h2>Files</h2>
              <span>{files.length}</span>
            </div>
            <div className="data-table-wrap">
              <table className="product-table">
                <thead>
                  <tr>
                    <th>Path</th>
                    <th>Language</th>
                    <th>Symbols</th>
                  </tr>
                </thead>
                <tbody>
                  {files.slice(0, 80).map((file) => (
                    <tr key={file.path}>
                      <td>{file.path}</td>
                      <td>{file.language}</td>
                      <td>{file.symbol_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="product-panel">
            <div className="product-panel-heading">
              <h2>Symbols</h2>
              <span>{symbols.length}</span>
            </div>
            <div className="data-table-wrap">
              <table className="product-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Kind</th>
                    <th>File</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.slice(0, 80).map((symbol) => (
                    <tr key={symbol.qualified_name}>
                      <td>{symbol.qualified_name}</td>
                      <td>{symbol.kind}</td>
                      <td>{symbol.file_path}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
