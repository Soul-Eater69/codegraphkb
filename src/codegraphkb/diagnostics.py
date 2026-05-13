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
    from codegraphkb.core.languages import LanguageProviderRegistry
    from codegraphkb.core.parsers import ParserBackend

    store = kb._open_store()
    try:
        parser_pref = store.get_meta("parser_backend_pref") or "auto"
        try:
            backend = ParserBackend(parser_pref)
        except ValueError:
            backend = ParserBackend.AUTO

        stale: list[str] = []
        backend_counts: dict[str, int] = {}
        fallback_files: list[dict[str, str]] = []
        for path in sorted(store.known_files()):
            file = store.get_file(path)
            if file is None:
                continue
            target = parser_signature(file.language, backend)
            actual = store.get_meta(f"file_parser:{path}")
            if actual != target:
                stale.append(path)
            actual_backend = store.get_meta(f"file_parser_actual:{path}") or ""
            if actual_backend:
                backend_counts[actual_backend] = backend_counts.get(actual_backend, 0) + 1
            if (store.get_meta(f"file_parser_fallback:{path}") or "false") == "true":
                fallback_files.append({
                    "path": path,
                    "preferred": store.get_meta(f"file_parser_preferred:{path}") or "",
                    "actual": actual_backend,
                    "warning": store.get_meta(f"file_parser_warning:{path}") or "",
                })

        provider_status = LanguageProviderRegistry.default(parser_backend=backend).diagnostics()
        ts_probe = _typescript_semantic_probe(str(kb.config.repo_path))
        if "typescript" in provider_status:
            provider_status["typescript"]["semantic_available"] = bool(ts_probe.get("available"))
            if ts_probe.get("available"):
                provider_status["typescript"]["status"] = "semantic"

        embedding_model = store.get_meta("embedding_model") or ""
        embedding_count = store.embedding_count()
        object_types = _object_type_counts(store)
        frameworks = _detected_frameworks(store)
        edge_types = _edge_type_counts(store)
        framework_object_counts = _framework_object_counts(object_types, edge_types)
        process_counts = _process_counts(store)
        role_counts = store.object_role_counts()
        parameter_types = store.parameter_counts_by_type()
        edge_resolution = store.edge_resolution_stats()
        edge_resolution_by_type = store.edge_resolution_by_type()
        unresolved_by_language = store.unresolved_edges_by_language()
        top_unresolved = store.top_unresolved_edge_names(limit=25)
        resolution_strategy_counts = store.edge_resolution_strategy_counts()
        parser_fallback_rate = (
            len(fallback_files) / store.file_count()
            if store.file_count() else 0.0
        )
        import_bindings = store.import_binding_count()
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
            "parser_backend_counts": backend_counts,
            "parser_fallback_count": len(fallback_files),
            "parser_fallback_files": fallback_files[:25],
            "providers": provider_status,
            "embedding_enabled": embedding_count > 0,
            "embedding_provider": embedding_provider,
            "embedding_model": embedding_model,
            "embedding_model_loaded": embedding_stub and embedding_count > 0,
            "embedding_stub_mode": embedding_stub,
            "embedding_load_state": _embedding_load_state(embedding_model, embedding_count),
            "semantic_backends": _semantic_backends(str(kb.config.repo_path)),
            "embeddings": embedding_count,
            "indexed_file_count": store.file_count(),
            "symbol_count": store.symbol_count(),
            "edge_count": store.edge_count(),
            "edge_resolution": edge_resolution,
            "edge_resolution_by_type": edge_resolution_by_type,
            "edge_resolution_rate": edge_resolution["resolution_rate"],
            "resolved_edge_count": edge_resolution["resolved"],
            "unresolved_edge_count": edge_resolution["unresolved"],
            "unresolved_edges_by_language": unresolved_by_language,
            "top_unresolved_edge_names": top_unresolved,
            "resolution_strategy_counts": resolution_strategy_counts,
            "parser_fallback_rate": parser_fallback_rate,
            "import_binding_count": import_bindings,
            "parameter_count": store.parameter_count(),
            "parameter_type_counts": parameter_types,
            "object_type_counts": object_types,
            "edge_type_counts": edge_types,
            "framework_object_counts": framework_object_counts,
            "process_counts": process_counts,
            "role_counts": role_counts,
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
        "parameter_count": int(doctor.get("parameter_count") or 0),
        "object_type_counts": doctor.get("object_type_counts") or {},
        "parameter_type_counts": doctor.get("parameter_type_counts") or {},
        "role_counts": doctor.get("role_counts") or {},
        "doctor": doctor,
    }


def _object_type_counts(store) -> dict[str, int]:
    rows = store._conn.execute(
        "SELECT kind, COUNT(*) AS n FROM symbols GROUP BY kind"
    ).fetchall()
    return {r["kind"]: int(r["n"]) for r in rows}


def _edge_type_counts(store) -> dict[str, int]:
    rows = store._conn.execute(
        "SELECT edge_type, COUNT(*) AS n FROM edges GROUP BY edge_type"
    ).fetchall()
    return {r["edge_type"]: int(r["n"]) for r in rows}


def _process_counts(store) -> dict[str, int]:
    rows = store._conn.execute(
        "SELECT process_type, COUNT(*) AS n FROM processes GROUP BY process_type"
    ).fetchall()
    counts = {r["process_type"]: int(r["n"]) for r in rows}
    total = store._conn.execute("SELECT COUNT(*) AS n FROM processes").fetchone()
    counts["total"] = int((total["n"] if total else 0))
    return counts


def _framework_object_counts(object_types: dict[str, int],
                              edge_types: dict[str, int]) -> dict[str, int]:
    """Friendly summary used by ``codegraph stats`` and the doctor report.

    Aggregates per-framework concern counts so users can see at a glance how
    many routes, tests, queries, and external fetches the index found.
    """
    return {
        "routes": int(object_types.get("route", 0)),
        "test_blocks": int(object_types.get("test_block", 0)),
        "models": int(object_types.get("model", 0)),
        "api_consumers": int(object_types.get("api_consumer", 0)),
        "components": int(object_types.get("component", 0)),
        "env_vars": int(object_types.get("env_var", 0)),
        "constants": int(object_types.get("constant", 0)),
        "config_keys": int(object_types.get("config_key", 0)),
        "handles_route_edges": int(edge_types.get("HANDLES_ROUTE", 0)),
        "tests_edges": int(edge_types.get("TESTS", 0)),
        "queries_edges": int(edge_types.get("QUERIES", 0)),
        "fetches_edges": int(edge_types.get("FETCHES", 0)),
        "calls_external_edges": int(edge_types.get("CALLS_EXTERNAL", 0)),
        "uses_middleware_edges": int(edge_types.get("USES_MIDDLEWARE", 0)),
        "reads_env_var_edges": int(edge_types.get("READS_ENV_VAR", 0)),
        "reads_constant_edges": int(edge_types.get("READS_CONSTANT", 0)),
        "reads_config_key_edges": int(edge_types.get("READS_CONFIG_KEY", 0)),
    }


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


def _semantic_backends(repo_path: str | None = None) -> dict[str, dict]:
    # TypeScript adapter is probed for real (Phase 3.1); other languages remain
    # placeholders until their adapters land.
    ts_entry = _typescript_semantic_probe(repo_path)
    return {
        "typescript": ts_entry,
        "python": {"adapter": "pyright/basedpyright", "available": False},
        "go": {"adapter": "go/packages", "available": False},
        "java": {"adapter": "jdt", "available": False},
        "csharp": {"adapter": "roslyn", "available": False},
    }


def _typescript_semantic_probe(repo_path: str | None) -> dict:
    from codegraphkb.core.semantic.typescript_adapter import (
        ADAPTER_VERSION,
        TypeScriptSemanticAdapter,
        find_helper,
    )

    adapter = TypeScriptSemanticAdapter()
    location = find_helper(repo_path)
    node_ok = adapter.node_available()
    available = node_ok and location.built
    entry: dict[str, Any] = {
        "adapter": "typescript-compiler-api",
        "available": available,
        "helper_path": str(location.helper_path),
        "version": ADAPTER_VERSION,
        "node_available": node_ok,
    }
    if not available:
        if not node_ok:
            entry["reason"] = "node executable not found on PATH"
        else:
            entry["reason"] = location.reason
    return entry


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
