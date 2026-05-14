"""Multi-project local product API for CodeGraphKB."""

from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from uuid import uuid4

from codegraphkb.api import CodeGraphKB
from codegraphkb.config import DEFAULT_TOKEN_BUDGET
from codegraphkb.core.store import GraphStore
from codegraphkb.product import jobs, projects
from codegraphkb.product.git import clone_public_repo, validate_public_github_url
from codegraphkb.product.models import (
    InvalidRequestError,
    JobNotFoundError,
    ProductError,
    ProjectNotFoundError,
    UploadTooLargeError,
)
from codegraphkb.product.serializers import (
    serialize_context_pack,
    serialize_edit_context_pack,
    serialize_job,
    serialize_project,
    serialize_stats,
)
from codegraphkb.product.settings import ProductSettings, load_settings
from codegraphkb.product.workspace import create_project_workspace, enforce_repo_limits
from codegraphkb.product.zip_upload import extract_zip_safely
from codegraphkb.workflow import prepare_edit_context


API_VERSION = "0.1.0"


class ProductAPIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


def build_product_app():
    from fastapi import BackgroundTasks, Body, FastAPI, Query, Request  # type: ignore
    from fastapi.exceptions import RequestValidationError  # type: ignore
    from fastapi.middleware.cors import CORSMiddleware  # type: ignore
    from fastapi.responses import JSONResponse  # type: ignore

    settings = load_settings()
    app = FastAPI(title="CodeGraphKB Product API", version=API_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8765",
            "http://127.0.0.1:8765",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ProductAPIError)
    def api_error_handler(_request, exc: ProductAPIError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(ProductError)
    def product_error_handler(_request, exc: ProductError):
        status, code = _status_for_product_error(exc)
        return JSONResponse(
            status_code=status,
            content={"error": {"code": code, "message": str(exc)}},
        )

    @app.exception_handler(RequestValidationError)
    def validation_error_handler(_request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_REQUEST", "message": str(exc)}},
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": API_VERSION}

    @app.post("/projects/github")
    def create_github_project(
        background_tasks: BackgroundTasks,
        req: dict[str, Any] = Body(...),
    ):
        url = validate_public_github_url(str(req.get("url") or ""))
        name = _optional_str(req.get("name"))
        project = projects.create_project_from_github(url, name, settings=settings)
        try:
            clone_public_repo(url, Path(project.workspace_path))
            enforce_repo_limits(
                Path(project.workspace_path),
                settings.max_repo_files,
                settings.max_file_mb,
            )
        except Exception as exc:
            projects.mark_project_status(project.id, "failed", str(exc), settings=settings)
            raise _bad_request(str(exc)) from exc

        job = jobs.create_index_job(project.id, settings=settings)
        background_tasks.add_task(
            jobs.run_index_job,
            job.id,
            project.id,
            force=True,
            settings=settings,
        )
        return {"project_id": project.id, "status": project.status, "job_id": job.id}

    @app.post("/projects/upload")
    async def upload_project(request: Request, background_tasks: BackgroundTasks):
        upload = await _read_multipart_upload(request)
        if not upload["filename"]:
            raise ProductAPIError(400, "INVALID_UPLOAD", "Multipart field `file` is required")
        max_bytes = settings.max_zip_mb * 1024 * 1024
        if len(upload["content"]) > max_bytes:
            raise ProductAPIError(
                413,
                "UPLOAD_TOO_LARGE",
                f"ZIP file is larger than {settings.max_zip_mb} MB",
            )

        project_id = str(uuid4())
        workspace = create_project_workspace(project_id, settings=settings)
        project = projects.create_project(
            source_type="zip_upload",
            source_ref=upload["filename"],
            workspace_path=workspace,
            name=upload["name"] or None,
            status="importing",
            project_id=project_id,
            settings=settings,
        )
        zip_path = _write_upload_zip(settings, project.id, upload["content"])
        try:
            repo_root = extract_zip_safely(zip_path, workspace, settings.max_zip_mb)
            enforce_repo_limits(repo_root, settings.max_repo_files, settings.max_file_mb)
            projects.update_project_workspace(project.id, repo_root, settings=settings)
            projects.mark_project_status(project.id, "indexing", settings=settings)
        except Exception as exc:
            projects.mark_project_status(project.id, "failed", str(exc), settings=settings)
            raise

        job = jobs.create_index_job(project.id, settings=settings)
        background_tasks.add_task(
            jobs.run_index_job,
            job.id,
            project.id,
            force=True,
            settings=settings,
        )
        return {"project_id": project.id, "status": "indexing", "job_id": job.id}

    @app.get("/projects")
    def list_projects(debug: bool = False) -> dict[str, Any]:
        return {
            "projects": [
                serialize_project(project, debug=debug)
                for project in projects.list_projects(settings=settings)
            ]
        }

    @app.get("/projects/{project_id}")
    def get_project(project_id: str, debug: bool = False) -> dict[str, Any]:
        project = projects.get_project(project_id, settings=settings)
        return serialize_project(project, debug=debug)

    @app.get("/projects/{project_id}/jobs/latest")
    def latest_job(project_id: str) -> dict[str, Any]:
        job = jobs.latest_job_for_project(project_id, settings=settings)
        if job is None:
            raise ProductAPIError(404, "INDEX_JOB_NOT_FOUND", "No index job exists for project")
        return serialize_job(job)

    @app.post("/projects/{project_id}/index")
    def reindex_project(
        project_id: str,
        background_tasks: BackgroundTasks,
        req: dict[str, Any] = Body(default_factory=dict),
    ) -> dict[str, Any]:
        projects.get_project(project_id, settings=settings)
        job = jobs.create_index_job(project_id, settings=settings)
        background_tasks.add_task(
            jobs.run_index_job,
            job.id,
            project_id,
            force=bool(req.get("force", False)),
            settings=settings,
        )
        return {"project_id": project_id, "status": "indexing", "job_id": job.id}

    @app.post("/projects/{project_id}/ask")
    def ask_project(project_id: str, req: dict[str, Any] = Body(...)) -> dict[str, Any]:
        project = _ready_project(project_id, settings)
        kb = CodeGraphKB(project.workspace_path)
        question = str(req.get("question") or "").strip()
        if not question:
            raise ProductAPIError(400, "INVALID_REQUEST", "`question` is required")
        token_budget = _int_req(req.get("token_budget"), DEFAULT_TOKEN_BUDGET)
        pinned_files = _string_list(req.get("pinned_files"))
        retrieval = str(req.get("retrieval") or "auto")
        intent = _optional_str(req.get("intent"))
        mode = _optional_str(req.get("mode"))
        if bool(req.get("context_only", False)):
            pack = kb.retrieve_context(
                question,
                token_budget=token_budget,
                intent=intent,
                mode=mode,
                pinned_files=pinned_files,
                retrieval=retrieval,
            )
            return serialize_context_pack(pack)
        result = kb.ask(
            question,
            token_budget=token_budget,
            intent=intent,
            mode=mode,
            model=_optional_str(req.get("model")),
            pinned_files=pinned_files,
            retrieval=retrieval,
        )
        return {
            "question": result.question,
            "answer": result.answer,
            "model": result.llm.model,
            "used_llm": result.llm.used_llm,
            "context": serialize_context_pack(result.context),
        }

    @app.post("/projects/{project_id}/prepare-edit")
    def prepare_edit_project(
        project_id: str,
        req: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        project = _ready_project(project_id, settings)
        kb = CodeGraphKB(project.workspace_path)
        task = str(req.get("task") or "").strip()
        if not task:
            raise ProductAPIError(400, "INVALID_REQUEST", "`task` is required")
        pack = prepare_edit_context(
            kb,
            task,
            token_budget=_int_req(req.get("token_budget"), 6000),
            pinned_files=_string_list(req.get("pinned_files")),
        )
        return serialize_edit_context_pack(pack)

    @app.get("/projects/{project_id}/impact")
    def impact_project(project_id: str, target: str = Query(..., min_length=1)) -> dict[str, Any]:
        project = _ready_project(project_id, settings)
        kb = CodeGraphKB(project.workspace_path)
        return serialize_context_pack(kb.impact(target))

    @app.get("/projects/{project_id}/stats")
    def project_stats(project_id: str, debug: bool = False) -> dict[str, Any]:
        project = _ready_project(project_id, settings)
        return serialize_stats(CodeGraphKB(project.workspace_path).stats(), debug=debug)

    @app.get("/projects/{project_id}/files")
    def project_files(project_id: str, limit: int = Query(500, ge=1, le=5000)) -> dict[str, Any]:
        project = _ready_project(project_id, settings)
        store = _open_store(project.workspace_path)
        try:
            rows = store._conn.execute(
                "SELECT f.path, f.language, f.size_bytes, f.indexed_at, COUNT(s.id) AS symbol_count "
                "FROM files f LEFT JOIN symbols s ON s.file_id = f.id "
                "GROUP BY f.id ORDER BY f.path LIMIT ?",
                (limit,),
            ).fetchall()
            return {
                "files": [
                    {
                        "path": row["path"],
                        "language": row["language"],
                        "size_bytes": int(row["size_bytes"]),
                        "indexed_at": row["indexed_at"],
                        "symbol_count": int(row["symbol_count"] or 0),
                    }
                    for row in rows
                ]
            }
        finally:
            store.close()

    @app.get("/projects/{project_id}/symbols")
    def project_symbols(
        project_id: str,
        kind: str | None = None,
        limit: int = Query(100, ge=1, le=1000),
    ) -> dict[str, Any]:
        project = _ready_project(project_id, settings)
        store = _open_store(project.workspace_path)
        try:
            if kind:
                rows = store._conn.execute(
                    "SELECT s.kind, s.name, s.qualified_name, f.path AS file_path, "
                    "s.start_line, s.end_line, s.signature "
                    "FROM symbols s JOIN files f ON f.id=s.file_id "
                    "WHERE s.kind=? ORDER BY s.qualified_name LIMIT ?",
                    (kind, limit),
                ).fetchall()
            else:
                rows = store._conn.execute(
                    "SELECT s.kind, s.name, s.qualified_name, f.path AS file_path, "
                    "s.start_line, s.end_line, s.signature "
                    "FROM symbols s JOIN files f ON f.id=s.file_id "
                    "ORDER BY s.qualified_name LIMIT ?",
                    (limit,),
                ).fetchall()
            return {"symbols": [_symbol_row(row) for row in rows]}
        finally:
            store.close()

    @app.get("/projects/{project_id}/graph/summary")
    def graph_summary(project_id: str, view: str = "full") -> dict[str, Any]:
        project = _ready_project(project_id, settings)
        payload = CodeGraphKB(project.workspace_path).export_graph(view=view)
        metadata = dict(payload.get("metadata") or {})
        return {
            "metadata": metadata,
            "node_count": len(payload.get("nodes", [])),
            "edge_count": len(payload.get("edges", [])),
        }

    return app


def _ready_project(project_id: str, settings: ProductSettings):
    project = projects.get_project(project_id, settings=settings)
    if project.status != "ready":
        raise ProductAPIError(409, "PROJECT_NOT_READY", "Project is not ready.")
    return project


def _open_store(workspace_path: str) -> GraphStore:
    kb = CodeGraphKB(workspace_path)
    try:
        return kb._open_store()
    except FileNotFoundError as exc:
        raise ProductAPIError(404, "INDEX_NOT_FOUND", str(exc)) from exc


async def _read_multipart_upload(request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        raise ProductAPIError(400, "INVALID_UPLOAD", "Expected multipart/form-data")
    body = await request.body()
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\nMIME-Version: 1.0\n\n".encode("utf-8") + body
    )
    out: dict[str, Any] = {"filename": "", "content": b"", "name": ""}
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition != "form-data":
            continue
        field_name = part.get_param("name", header="content-disposition")
        if field_name == "file":
            out["filename"] = Path(part.get_filename() or "upload.zip").name
            out["content"] = part.get_payload(decode=True) or b""
        elif field_name == "name":
            payload = part.get_payload(decode=True) or b""
            out["name"] = payload.decode(part.get_content_charset() or "utf-8", errors="ignore").strip()
    return out


def _write_upload_zip(settings: ProductSettings, project_id: str, content: bytes) -> Path:
    upload_dir = settings.app_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{project_id}.zip"
    path.write_bytes(content)
    return path


def _symbol_row(row) -> dict[str, Any]:
    return {
        "kind": row["kind"],
        "name": row["name"],
        "qualified_name": row["qualified_name"],
        "file_path": row["file_path"],
        "start_line": row["start_line"],
        "end_line": row["end_line"],
        "signature": row["signature"],
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)] if str(value).strip() else []


def _int_req(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ProductAPIError(400, "INVALID_REQUEST", "Expected an integer value") from exc
    if parsed <= 0:
        raise ProductAPIError(400, "INVALID_REQUEST", "Integer values must be positive")
    return parsed


def _status_for_product_error(exc: ProductError) -> tuple[int, str]:
    if isinstance(exc, ProjectNotFoundError):
        return 404, "PROJECT_NOT_FOUND"
    if isinstance(exc, JobNotFoundError):
        return 404, "INDEX_JOB_NOT_FOUND"
    if isinstance(exc, UploadTooLargeError):
        return 413, "UPLOAD_TOO_LARGE"
    if isinstance(exc, InvalidRequestError):
        return 400, "INVALID_REQUEST"
    return 500, "INTERNAL_ERROR"


def _bad_request(message: str) -> ProductAPIError:
    return ProductAPIError(400, "INVALID_REQUEST", message)
