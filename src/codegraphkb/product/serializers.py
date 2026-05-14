"""Response serializers for product API objects."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from codegraphkb.product.models import IndexJob, Project


def serialize_project(project: Project, *, debug: bool = False) -> dict[str, Any]:
    out = {
        "id": project.id,
        "name": project.name,
        "source_type": project.source_type,
        "source_ref": project.source_ref,
        "status": project.status,
        "error_message": project.error_message,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "last_indexed_at": project.last_indexed_at,
    }
    if debug:
        out["workspace_path"] = project.workspace_path
    return out


def serialize_job(job: IndexJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "status": job.status,
        "progress_message": job.progress_message,
        "error_message": job.error_message,
        "files_scanned": job.files_scanned,
        "files_indexed": job.files_indexed,
        "symbols": job.symbols,
        "edges": job.edges,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def serialize_context_pack(pack) -> dict[str, Any]:
    return {
        "intent": _value(getattr(pack, "intent", "")),
        "mode": _value(getattr(pack, "mode", "")),
        "retrieval_mode": getattr(pack, "retrieval_mode", ""),
        "estimated_tokens": getattr(pack, "estimated_tokens", 0),
        "graph_paths": getattr(pack, "graph_paths", []),
        "files_likely_to_edit": getattr(pack, "files_likely_to_edit", []),
        "related_tests": getattr(pack, "related_tests", []),
        "repo_map": getattr(pack, "repo_map", []),
        "audit": getattr(pack, "audit", {}),
        "items": [serialize_context_item(item) for item in getattr(pack, "items", [])],
    }


def serialize_context_item(item) -> dict[str, Any]:
    return {
        "kind": getattr(item, "kind", ""),
        "title": getattr(item, "title", ""),
        "file_path": getattr(item, "file_path", ""),
        "start_line": getattr(item, "start_line", None),
        "end_line": getattr(item, "end_line", None),
        "score": getattr(item, "score", 0.0),
        "tokens": getattr(item, "tokens", 0),
        "body": getattr(item, "body", ""),
        "retrieval_sources": list(getattr(item, "retrieval_sources", []) or []),
        "reason": getattr(item, "reason", ""),
    }


def serialize_edit_context_pack(pack) -> dict[str, Any]:
    if hasattr(pack, "to_dict"):
        return _sanitize(pack.to_dict())
    if is_dataclass(pack):
        return _sanitize(asdict(pack))
    return _sanitize(dict(pack))


def serialize_stats(stats: dict[str, Any], *, debug: bool = False) -> dict[str, Any]:
    out = dict(stats)
    if not debug:
        repo_path = out.pop("repo_path", None)
        out.pop("index_dir", None)
        if repo_path:
            out["repo_name"] = Path(str(repo_path)).name
    return out


def _value(value) -> str:
    return getattr(value, "value", value)


def _sanitize(value):
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if is_dataclass(value):
        return _sanitize(asdict(value))
    return value

