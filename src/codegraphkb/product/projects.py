"""Project metadata service for local product workflows."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from codegraphkb.product.db import app_db, initialize_app_db
from codegraphkb.product.models import (
    InvalidRequestError,
    Project,
    ProjectNotFoundError,
    ProjectStatus,
    SourceType,
)
from codegraphkb.product.settings import ProductSettings, load_settings
from codegraphkb.product.workspace import assert_inside_workspace, create_project_workspace


def create_project(
    *,
    source_type: SourceType,
    source_ref: str,
    workspace_path: Path,
    name: str | None = None,
    status: ProjectStatus = "created",
    project_id: str | None = None,
    settings: ProductSettings | None = None,
) -> Project:
    settings = settings or load_settings()
    initialize_app_db(settings)
    pid = project_id or str(uuid4())
    workspace = Path(workspace_path).resolve()
    assert_inside_workspace(workspace, settings.workspace_dir)
    now = _now()
    project = Project(
        id=pid,
        name=_clean_name(name) or _derive_name(source_ref, workspace),
        source_type=source_type,
        source_ref=source_ref,
        workspace_path=str(workspace),
        status=status,
        error_message="",
        created_at=now,
        updated_at=now,
        last_indexed_at=None,
    )
    with app_db(settings) as conn:
        conn.execute(
            "INSERT INTO projects(id, name, source_type, source_ref, workspace_path, "
            "status, error_message, created_at, updated_at, last_indexed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                project.id,
                project.name,
                project.source_type,
                project.source_ref,
                project.workspace_path,
                project.status,
                project.error_message,
                project.created_at,
                project.updated_at,
                project.last_indexed_at,
            ),
        )
    return project


def create_project_from_github(
    url: str,
    name: str | None = None,
    *,
    settings: ProductSettings | None = None,
) -> Project:
    settings = settings or load_settings()
    pid = str(uuid4())
    workspace = create_project_workspace(pid, settings=settings)
    return create_project(
        source_type="github_url",
        source_ref=url,
        workspace_path=workspace,
        name=name,
        status="importing",
        project_id=pid,
        settings=settings,
    )


def create_project_from_zip(
    filename: str,
    extracted_path: Path,
    name: str | None = None,
    *,
    settings: ProductSettings | None = None,
) -> Project:
    settings = settings or load_settings()
    return create_project(
        source_type="zip_upload",
        source_ref=filename,
        workspace_path=extracted_path,
        name=name,
        status="indexing",
        settings=settings,
    )


def get_project(project_id: str, *, settings: ProductSettings | None = None) -> Project:
    settings = settings or load_settings()
    with app_db(settings) as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if row is None:
        raise ProjectNotFoundError(f"Project `{project_id}` not found")
    return _project_from_row(row)


def list_projects(*, settings: ProductSettings | None = None) -> list[Project]:
    settings = settings or load_settings()
    with app_db(settings) as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE status != 'deleted' ORDER BY created_at DESC"
        ).fetchall()
    return [_project_from_row(row) for row in rows]


def mark_project_status(
    project_id: str,
    status: ProjectStatus,
    error_message: str = "",
    *,
    last_indexed_at: str | None = None,
    settings: ProductSettings | None = None,
) -> None:
    update_project_status(
        project_id,
        status,
        error_message=error_message,
        last_indexed_at=last_indexed_at,
        settings=settings,
    )


def update_project_status(
    project_id: str,
    status: ProjectStatus,
    *,
    error_message: str = "",
    last_indexed_at: str | None = None,
    settings: ProductSettings | None = None,
) -> None:
    settings = settings or load_settings()
    now = _now()
    with app_db(settings) as conn:
        cur = conn.execute(
            "UPDATE projects SET status=?, error_message=?, updated_at=?, "
            "last_indexed_at=COALESCE(?, last_indexed_at) WHERE id=?",
            (status, _truncate(error_message), now, last_indexed_at, project_id),
        )
        if cur.rowcount == 0:
            raise ProjectNotFoundError(f"Project `{project_id}` not found")


def update_project_workspace(
    project_id: str,
    workspace_path: Path,
    *,
    settings: ProductSettings | None = None,
) -> None:
    settings = settings or load_settings()
    workspace = Path(workspace_path).resolve()
    assert_inside_workspace(workspace, settings.workspace_dir)
    with app_db(settings) as conn:
        cur = conn.execute(
            "UPDATE projects SET workspace_path=?, updated_at=? WHERE id=?",
            (str(workspace), _now(), project_id),
        )
        if cur.rowcount == 0:
            raise ProjectNotFoundError(f"Project `{project_id}` not found")


def delete_project_metadata(project_id: str, *, settings: ProductSettings | None = None) -> None:
    update_project_status(project_id, "deleted", settings=settings)


def resolve_project_workspace(
    project_id: str,
    *,
    settings: ProductSettings | None = None,
) -> Path:
    settings = settings or load_settings()
    project = get_project(project_id, settings=settings)
    workspace = Path(project.workspace_path).resolve()
    assert_inside_workspace(workspace, settings.workspace_dir)
    if not workspace.exists() or not workspace.is_dir():
        raise InvalidRequestError(f"Workspace for project `{project_id}` is missing")
    return workspace


def _project_from_row(row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        source_type=row["source_type"],
        source_ref=row["source_ref"],
        workspace_path=row["workspace_path"],
        status=row["status"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_indexed_at=row["last_indexed_at"],
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_name(name: str | None) -> str:
    if not name:
        return ""
    return name.strip()[:120]


def _derive_name(source_ref: str, workspace: Path) -> str:
    ref = source_ref.strip().rstrip("/")
    if ref:
        stem = ref.rsplit("/", 1)[-1].removesuffix(".git")
        if stem:
            return stem[:120]
    return workspace.name[:120]


def _truncate(value: str, limit: int = 2000) -> str:
    return value[:limit]

