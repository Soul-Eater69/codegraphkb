"""``codegraph start .`` — one-command local experience.

The flow is intentionally simple so users can stop reading docs:

1. Index the repo (unless ``--no-index``).
2. Generate artifacts in ``<repo>/.codegraphkb/`` (graph.json, graph.html, report, mcp.json,
   edit_plan_example.md).
3. Register / refresh a ``local_path`` Product API project pointing at the repo.
4. Start the Product API server on ``host:port`` (blocking).
5. Optionally open the browser.

The helper is designed so unit tests can exercise the prep phase without binding a real
socket — pass ``start_server=False`` to skip uvicorn.
"""
from __future__ import annotations

import os
import sys
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from codegraphkb.api import CodeGraphKB
from codegraphkb.ux.artifacts import ArtifactPaths, GeneratedArtifacts, generate_artifacts


@dataclass
class StartResult:
    repo: Path
    host: str
    port: int
    artifact_paths: ArtifactPaths
    artifacts: GeneratedArtifacts
    project_id: str | None = None
    index_stats: dict | None = None
    server_started: bool = False
    lines: list[str] = field(default_factory=list)


def start_local_experience(
    repo: Path | str,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    no_index: bool = False,
    force: bool = False,
    embed: bool = False,
    parser: str = "auto",
    semantic: str = "auto",
    start_server: bool = True,
    register_project: bool = True,
    on_message: Callable[[str], None] | None = None,
) -> StartResult:
    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        raise FileNotFoundError(f"Repo not found: {repo_path}")
    if not repo_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {repo_path}")

    def say(msg: str) -> None:
        if on_message is not None:
            on_message(msg)

    kb = CodeGraphKB(repo_path)
    index_stats: dict | None = None

    if not no_index:
        say(f"Indexing {repo_path}")
        stats = kb.index(
            force=force,
            embed=embed,
            parser=parser,
            semantic=None if semantic == "none" else semantic,
        )
        index_stats = {
            "files_indexed": stats.files_indexed,
            "files_scanned": stats.files_scanned,
            "symbols": stats.symbols,
            "edges": stats.edges,
        }

    say("Generating artifacts")
    artifacts = generate_artifacts(kb)

    project_id: str | None = None
    if register_project:
        try:
            project_id = _ensure_local_project(repo_path)
        except Exception as exc:  # pragma: no cover - non-fatal
            say(f"Warning: could not register product project: {exc}")

    base_url = f"http://{host}:{port}"
    lines = _render_summary(
        repo_path=repo_path,
        base_url=base_url,
        artifacts=artifacts.paths,
        project_id=project_id,
    )

    result = StartResult(
        repo=repo_path,
        host=host,
        port=port,
        artifact_paths=artifacts.paths,
        artifacts=artifacts,
        project_id=project_id,
        index_stats=index_stats,
        lines=lines,
    )

    if not start_server:
        return result

    for line in lines:
        say(line)

    if open_browser:
        try:
            webbrowser.open(_landing_url(base_url, project_id))
        except Exception:  # pragma: no cover - browser open is best-effort
            pass

    say(f"Starting Product API on {base_url} (Ctrl-C to stop)")
    _run_server(host=host, port=port)
    result.server_started = True
    return result


def _ensure_local_project(repo_path: Path) -> str | None:
    """Register or reuse a ``local_path`` project for ``repo_path`` in the product DB.

    Returns the project id, or ``None`` if FastAPI/Product DB is unavailable.
    """
    try:
        from codegraphkb.product import projects
        from codegraphkb.product.db import initialize_app_db
        from codegraphkb.product.settings import load_settings
    except Exception:
        return None

    settings = load_settings()
    initialize_app_db(settings)

    workspace_str = str(repo_path)
    for project in projects.list_projects(settings=settings):
        if project.source_type == "local_path" and project.workspace_path == workspace_str:
            if project.status != "ready":
                projects.mark_project_status(project.id, "ready", settings=settings)
            projects.touch_last_indexed(project.id, settings=settings) if hasattr(
                projects, "touch_last_indexed"
            ) else None
            return project.id

    project = projects.create_project(
        source_type="local_path",
        source_ref=str(repo_path),
        workspace_path=repo_path,
        name=repo_path.name,
        status="ready",
        settings=settings,
    )
    return project.id


def _landing_url(base_url: str, project_id: str | None) -> str:
    if project_id:
        return f"{base_url}/projects/{project_id}"
    return f"{base_url}/projects"


def _render_summary(
    *,
    repo_path: Path,
    base_url: str,
    artifacts: ArtifactPaths,
    project_id: str | None,
) -> list[str]:
    lines = [
        "",
        "CodeGraphKB ready.",
        "",
        f"Repo:           {repo_path}",
        f"Local UI:       {base_url}",
    ]
    if project_id:
        lines.append(f"Project:        {base_url}/projects/{project_id}")
    lines.extend(
        [
            f"Report:         {artifacts.report}",
            f"Graph JSON:     {artifacts.graph_json}",
            f"Graph HTML:     {artifacts.graph_html}",
            f"MCP config:     {artifacts.mcp_config}",
            "",
            "Try:",
            '  codegraph ask "How does authentication work?"',
            '  codegraph prepare-edit "Add refresh token rotation"',
            "",
        ]
    )
    return lines


def _run_server(*, host: str, port: int) -> None:  # pragma: no cover - requires uvicorn
    try:
        import uvicorn  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Install codegraphkb[api] to use `codegraph start` (uvicorn missing)."
        ) from exc

    # Build the FastAPI app *after* artifacts so any import-time failure surfaces here,
    # not in the middle of indexing.
    from codegraphkb.server.product_api import build_product_app

    app = build_product_app()
    uvicorn.run(app, host=host, port=port)


def emit_to_stdout() -> Callable[[str], None]:
    """Default on_message handler — prints to stderr so it does not pollute scripted stdout."""

    def _emit(msg: str) -> None:
        print(msg, file=sys.stderr)

    return _emit


def write_iterable(lines: Iterable[str], stream=None) -> None:
    stream = stream or sys.stdout
    for line in lines:
        stream.write(line + os.linesep)
