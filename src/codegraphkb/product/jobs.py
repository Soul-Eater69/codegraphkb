"""Local asynchronous index-job metadata and runner."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from codegraphkb.api import CodeGraphKB
from codegraphkb.product.db import app_db, initialize_app_db
from codegraphkb.product.models import IndexJob, JobNotFoundError
from codegraphkb.product.projects import get_project, mark_project_status
from codegraphkb.product.settings import ProductSettings, load_settings
from codegraphkb.product.workspace import enforce_repo_limits


def create_index_job(
    project_id: str,
    *,
    settings: ProductSettings | None = None,
) -> IndexJob:
    settings = settings or load_settings()
    initialize_app_db(settings)
    get_project(project_id, settings=settings)
    job = IndexJob(
        id=str(uuid4()),
        project_id=project_id,
        status="queued",
        progress_message="Queued",
        error_message="",
        files_scanned=0,
        files_indexed=0,
        symbols=0,
        edges=0,
        created_at=_now(),
        started_at=None,
        finished_at=None,
    )
    with app_db(settings) as conn:
        conn.execute(
            "INSERT INTO index_jobs(id, project_id, status, progress_message, "
            "error_message, files_scanned, files_indexed, symbols, edges, "
            "started_at, finished_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                job.id,
                job.project_id,
                job.status,
                job.progress_message,
                job.error_message,
                job.files_scanned,
                job.files_indexed,
                job.symbols,
                job.edges,
                job.started_at,
                job.finished_at,
                job.created_at,
            ),
        )
    return job


def get_index_job(job_id: str, *, settings: ProductSettings | None = None) -> IndexJob:
    settings = settings or load_settings()
    with app_db(settings) as conn:
        row = conn.execute("SELECT * FROM index_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise JobNotFoundError(f"Index job `{job_id}` not found")
    return _job_from_row(row)


def latest_job_for_project(
    project_id: str,
    *,
    settings: ProductSettings | None = None,
) -> IndexJob | None:
    settings = settings or load_settings()
    get_project(project_id, settings=settings)
    with app_db(settings) as conn:
        row = conn.execute(
            "SELECT * FROM index_jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    return _job_from_row(row) if row is not None else None


def run_index_job(
    job_id: str,
    project_id: str,
    *,
    force: bool = False,
    settings: ProductSettings | None = None,
) -> None:
    settings = settings or load_settings()
    try:
        project = get_project(project_id, settings=settings)
        _mark_job_running(job_id, settings=settings)
        mark_project_status(project_id, "indexing", settings=settings)
        workspace = Path(project.workspace_path).resolve()
        enforce_repo_limits(workspace, settings.max_repo_files, settings.max_file_mb)

        kb = CodeGraphKB(workspace)
        stats = kb.index(
            force=force,
            parser="auto",
            embed=True,
            semantic="auto",
            progress=lambda msg: update_job_progress(job_id, str(msg), settings=settings),
        )
        finished = _now()
        _mark_job_succeeded(
            job_id,
            files_scanned=getattr(stats, "files_scanned", 0),
            files_indexed=getattr(stats, "files_indexed", 0),
            symbols=getattr(stats, "symbols", 0),
            edges=getattr(stats, "edges", 0),
            finished_at=finished,
            settings=settings,
        )
        mark_project_status(
            project_id,
            "ready",
            last_indexed_at=finished,
            settings=settings,
        )
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        _mark_job_failed(job_id, message, settings=settings)
        try:
            mark_project_status(project_id, "failed", message, settings=settings)
        except Exception:
            pass


def update_job_progress(
    job_id: str,
    message: str,
    *,
    settings: ProductSettings | None = None,
) -> None:
    settings = settings or load_settings()
    with app_db(settings) as conn:
        cur = conn.execute(
            "UPDATE index_jobs SET progress_message=? WHERE id=?",
            (_truncate(message), job_id),
        )
        if cur.rowcount == 0:
            raise JobNotFoundError(f"Index job `{job_id}` not found")


def _mark_job_running(job_id: str, *, settings: ProductSettings) -> None:
    with app_db(settings) as conn:
        cur = conn.execute(
            "UPDATE index_jobs SET status='running', progress_message=?, started_at=? WHERE id=?",
            ("Indexing", _now(), job_id),
        )
        if cur.rowcount == 0:
            raise JobNotFoundError(f"Index job `{job_id}` not found")


def _mark_job_succeeded(
    job_id: str,
    *,
    files_scanned: int,
    files_indexed: int,
    symbols: int,
    edges: int,
    finished_at: str,
    settings: ProductSettings,
) -> None:
    with app_db(settings) as conn:
        cur = conn.execute(
            "UPDATE index_jobs SET status='succeeded', progress_message=?, error_message='', "
            "files_scanned=?, files_indexed=?, symbols=?, edges=?, finished_at=? WHERE id=?",
            (
                "Indexing complete",
                files_scanned,
                files_indexed,
                symbols,
                edges,
                finished_at,
                job_id,
            ),
        )
        if cur.rowcount == 0:
            raise JobNotFoundError(f"Index job `{job_id}` not found")


def _mark_job_failed(
    job_id: str,
    error_message: str,
    *,
    settings: ProductSettings | None = None,
) -> None:
    settings = settings or load_settings()
    with app_db(settings) as conn:
        conn.execute(
            "UPDATE index_jobs SET status='failed', progress_message=?, error_message=?, "
            "finished_at=COALESCE(finished_at, ?) WHERE id=?",
            ("Indexing failed", _truncate(error_message), _now(), job_id),
        )


def _job_from_row(row) -> IndexJob:
    return IndexJob(
        id=row["id"],
        project_id=row["project_id"],
        status=row["status"],
        progress_message=row["progress_message"],
        error_message=row["error_message"],
        files_scanned=int(row["files_scanned"]),
        files_indexed=int(row["files_indexed"]),
        symbols=int(row["symbols"]),
        edges=int(row["edges"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(value: str, limit: int = 2000) -> str:
    return value[:limit]

