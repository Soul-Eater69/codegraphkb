import { useEffect, useMemo, useState } from "react";
import { AskProjectPage } from "./pages/AskProjectPage";
import { CreateProjectPage } from "./pages/CreateProjectPage";
import { PrepareEditPage } from "./pages/PrepareEditPage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ProjectsPage } from "./pages/ProjectsPage";

type Route =
  | { name: "projects" }
  | { name: "new" }
  | { name: "detail"; projectId: string }
  | { name: "ask"; projectId: string }
  | { name: "prepare"; projectId: string };

export default function ProductApp() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const route = useMemo(() => parseRoute(path), [path]);

  function navigate(nextPath: string) {
    window.history.pushState({}, "", nextPath);
    setPath(window.location.pathname);
  }

  return (
    <div className="product-shell">
      <header className="product-topbar">
        <button type="button" className="product-brand-button" onClick={() => navigate("/projects")}>
          <span className="product-brand-mark">CG</span>
          <span>CodeGraphKB</span>
        </button>
        <nav>
          <button type="button" onClick={() => navigate("/projects")}>Projects</button>
          <button type="button" onClick={() => navigate("/projects/new")}>New</button>
          <a href="/">Graph</a>
        </nav>
      </header>
      {route.name === "projects" ? (
        <ProjectsPage onNew={() => navigate("/projects/new")} onOpen={(id) => navigate(`/projects/${id}`)} />
      ) : null}
      {route.name === "new" ? (
        <CreateProjectPage onBack={() => navigate("/projects")} onCreated={(id) => navigate(`/projects/${id}`)} />
      ) : null}
      {route.name === "detail" ? (
        <ProjectDetailPage
          projectId={route.projectId}
          onBack={() => navigate("/projects")}
          onAsk={() => navigate(`/projects/${route.projectId}/ask`)}
          onPrepareEdit={() => navigate(`/projects/${route.projectId}/prepare-edit`)}
        />
      ) : null}
      {route.name === "ask" ? (
        <AskProjectPage projectId={route.projectId} onBack={() => navigate(`/projects/${route.projectId}`)} />
      ) : null}
      {route.name === "prepare" ? (
        <PrepareEditPage projectId={route.projectId} onBack={() => navigate(`/projects/${route.projectId}`)} />
      ) : null}
    </div>
  );
}

function parseRoute(path: string): Route {
  const parts = path.replace(/\/+$/, "").split("/").filter(Boolean);
  if (parts[0] !== "projects") {
    return { name: "projects" };
  }
  if (parts.length === 1) {
    return { name: "projects" };
  }
  if (parts[1] === "new") {
    return { name: "new" };
  }
  const projectId = decodeURIComponent(parts[1] ?? "");
  if (parts[2] === "ask") {
    return { name: "ask", projectId };
  }
  if (parts[2] === "prepare-edit") {
    return { name: "prepare", projectId };
  }
  return { name: "detail", projectId };
}
