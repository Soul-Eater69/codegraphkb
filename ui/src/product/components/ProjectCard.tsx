import type { Project } from "../productApi";

interface Props {
  project: Project;
  onOpen: (projectId: string) => void;
}

export function ProjectCard({ project, onOpen }: Props) {
  return (
    <article className="product-card project-card">
      <div>
        <div className="product-card-title">{project.name}</div>
        <div className="product-card-meta">{project.source_type} · {project.source_ref}</div>
      </div>
      <div className="project-card-footer">
        <span className={`status-pill status-${project.status}`}>{project.status}</span>
        <button type="button" onClick={() => onOpen(project.id)}>Open</button>
      </div>
    </article>
  );
}
