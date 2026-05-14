import { useEffect, useState } from "react";
import { ProjectCard } from "../components/ProjectCard";
import { listProjects, type Project } from "../productApi";

interface Props {
  onNew: () => void;
  onOpen: (projectId: string) => void;
}

export function ProjectsPage({ onNew, onOpen }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void load();
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setProjects(await listProjects());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="product-page">
      <div className="product-page-heading">
        <div>
          <h1>Projects</h1>
          <p>{projects.length} local project{projects.length === 1 ? "" : "s"}</p>
        </div>
        <button type="button" onClick={onNew}>New Project</button>
      </div>
      {loading ? <p className="product-muted">Loading projects</p> : null}
      {error ? <p className="product-error-text">{error}</p> : null}
      {!loading && projects.length === 0 ? (
        <section className="product-empty">
          <h2>No Projects</h2>
          <button type="button" onClick={onNew}>New Project</button>
        </section>
      ) : null}
      <div className="projects-grid">
        {projects.map((project) => (
          <ProjectCard key={project.id} project={project} onOpen={onOpen} />
        ))}
      </div>
    </main>
  );
}
