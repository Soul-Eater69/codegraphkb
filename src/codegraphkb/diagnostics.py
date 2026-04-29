"""Diagnostic snapshots for regression comparability."""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from codegraphkb.core.parsers import is_treesitter_available
from codegraphkb.versioning import (
    CAPSULE_VERSION,
    RETRIEVAL_VERSION,
    SCHEMA_VERSION,
    parser_signature,
)


def collect_run_environment(repo_path: str | Path) -> dict[str, Any]:
    repo = Path(repo_path).resolve()
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "repo_root": str(repo),
        "git_sha": _git(repo, "rev-parse", "HEAD") or "",
        "dirty_worktree": bool(_git(repo, "status", "--porcelain")),
    }


def collect_doctor_report(kb) -> dict[str, Any]:
    from codegraphkb.core.parsers import ParserBackend

    store = kb._open_store()
    try:
        parser_pref = store.get_meta("parser_backend_pref") or "auto"
        try:
            backend = ParserBackend(parser_pref)
        except ValueError:
            backend = ParserBackend.AUTO

        stale: list[str] = []
        for path in sorted(store.known_files()):
            file = store.get_file(path)
            if file is None:
                continue
            target = parser_signature(file.language, backend)
            actual = store.get_meta(f"file_parser:{path}")
            if actual != target:
                stale.append(path)

        embedding_model = store.get_meta("embedding_model") or ""
        embedding_count = store.embedding_count()
        object_types = _object_type_counts(store)
        frameworks = _detected_frameworks(store)
        embedding_stub = embedding_model.startswith("hash-stub")
        embedding_provider = _embedding_provider(embedding_model)
        return {
            "repo_root": str(kb.config.repo_path),
            "database_path": str(kb.config.db_path),
            "db_path": str(kb.config.db_path),
            "schema_version_current": SCHEMA_VERSION,
            "schema_version_indexed": store.get_meta("schema_version"),
            "schema_version": store.get_meta("schema_version"),
            "capsule_version_current": CAPSULE_VERSION,
            "capsule_version_indexed": store.get_meta("capsule_version"),
            "retrieval_version_current": RETRIEVAL_VERSION,
            "parser_backend": parser_pref,
            "parser_backend_preferred": parser_pref,
            "parser_version": {
                "python": parser_signature("python", backend),
                "javascript": parser_signature("javascript", backend),
                "typescript": parser_signature("typescript", backend),
            },
            "tree_sitter_available": is_treesitter_available(),
            "embedding_enabled": embedding_count > 0,
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
            "embedding_model_loaded": embedding_stub and embedding_count > 0,
            "embedding_stub_mode": embedding_stub,
            "embedding_load_state": _embedding_load_state(embedding_model, embedding_count),
            "semantic_backends": _semantic_backends(),
            "embeddings": embedding_count,
            "indexed_file_count": store.file_count(),
            "symbol_count": store.symbol_count(),
            "edge_count": store.edge_count(),
            "object_type_counts": object_types,
            "frameworks": frameworks,
            "languages": store.file_languages(),
            "stale_files_for_parser": stale[:25],
            "stale_file_count": len(stale),
            "last_indexed_at": store.get_meta("last_indexed_at"),
        }
    finally:
        store.close()


def compact_index_state(doctor: dict[str, Any]) -> dict[str, Any]:
    return {
        "db_path": doctor.get("db_path") or doctor.get("database_path") or "",
        "schema_version": doctor.get("schema_version_indexed") or "",
        "parser_backend": doctor.get("parser_backend") or "",
        "parser_version": doctor.get("parser_version") or {},
        "embedding_enabled": bool(doctor.get("embedding_enabled")),
        "embedding_model": doctor.get("embedding_model") or "",
        "embedding_stub_mode": bool(doctor.get("embedding_stub_mode")),
        "indexed_file_count": int(doctor.get("indexed_file_count") or 0),
        "symbol_count": int(doctor.get("symbol_count") or 0),
        "edge_count": int(doctor.get("edge_count") or 0),
        "object_type_counts": doctor.get("object_type_counts") or {},
        "doctor": doctor,
    }


def _object_type_counts(store) -> dict[str, int]:
    rows = store._conn.execute(
        "SELECT kind, COUNT(*) AS n FROM symbols GROUP BY kind"
    ).fetchall()
    return {r["kind"]: int(r["n"]) for r in rows}


def _detected_frameworks(store) -> dict[str, int]:
    rows = store._conn.execute(
        "SELECT key FROM meta WHERE key LIKE 'framework:%'"
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        parts = row["key"].split(":", 2)
        if len(parts) == 3:
            counts[parts[2]] = counts.get(parts[2], 0) + 1
    return counts


def _embedding_provider(model: str) -> str:
    if not model:
        return "none"
    if model.startswith("hash-stub"):
        return "hash-stub"
    if model.startswith("fastembed:"):
        return "fastembed"
    if model.startswith("st:"):
        return "sentence-transformers"
    return "unknown"


def _embedding_load_state(model: str, count: int) -> str:
    if count <= 0 or not model:
        return "none"
    if model.startswith("hash-stub"):
        return "stub-loaded"
    return "real-indexed-unverified"


def _semantic_backends() -> dict[str, dict]:
    # Foundation PR: adapters are optional and not auto-installed. Later PRs
    # should replace these checks with concrete adapter probes.
    return {
        "typescript": {"adapter": "typescript-compiler-api", "available": False},
        "python": {"adapter": "pyright/basedpyright", "available": False},
        "go": {"adapter": "go/packages", "available": False},
        "java": {"adapter": "jdt", "available": False},
        "csharp": {"adapter": "roslyn", "available": False},
    }


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
