"""Production engine foundation tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from codegraphkb.core.graph_schema import EdgeType, PrecisionLevel
from codegraphkb.core.languages import LanguageProviderRegistry
from codegraphkb.core.scanner import SourceFile
from codegraphkb.core.store import GraphStore
from codegraphkb.core.semantic.adapter_runner import run_semantic_adapter
from codegraphkb.core.semantic.protocol import SemanticResult


def _source(rel_path: str, language: str, content: str) -> SourceFile:
    return SourceFile(
        rel_path=rel_path,
        abs_path=Path(rel_path),
        language=language,
        content=content,
        content_hash="hash",
        size_bytes=len(content),
    )


def test_provider_registry_uses_python_provider() -> None:
    src = _source("app.py", "python", "def hello():\n    return 'hi'\n")
    result, choice = LanguageProviderRegistry.default().parse_and_extract(src)
    assert choice.provider_id == "python"
    assert choice.parser_backend == "ast"
    assert any(sym.name == "hello" for sym in result.symbols)


def test_provider_registry_falls_back_for_unknown_language() -> None:
    src = _source("main.rs", "rust", "fn main() {}\n")
    result, choice = LanguageProviderRegistry.default().parse_and_extract(src)
    assert result.symbols == []
    assert choice.fallback_used is True
    assert choice.provider_id == "none"


def test_store_migrates_existing_database_with_edge_metadata(tmp_path: Path) -> None:
    db = tmp_path / "graph.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL UNIQUE,
        language TEXT NOT NULL,
        hash TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        indexed_at TEXT NOT NULL,
        content TEXT NOT NULL
    );
    CREATE TABLE symbols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        qualified_name TEXT NOT NULL,
        parent_qname TEXT,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        signature TEXT,
        docstring TEXT,
        capsule TEXT,
        extras TEXT
    );
    CREATE TABLE edges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        src_qname TEXT NOT NULL,
        dst_qname TEXT,
        dst_name TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        confidence REAL NOT NULL,
        extraction_source TEXT NOT NULL,
        line INTEGER
    );
    """)
    conn.commit()
    conn.close()

    store = GraphStore(db)
    try:
        columns = {row["name"] for row in store._conn.execute("PRAGMA table_info(edges)").fetchall()}
        assert {"precision_level", "reason", "metadata_json", "created_at"} <= columns
        store.insert_edges([
            ("a", None, "b", EdgeType.CALLS.value, 0.9, "test", 1, 2,
             int(PrecisionLevel.CODEGRAPH_RESOLVER), "unit test", {"x": 1}, ""),
        ])
        row = store._conn.execute("SELECT precision_level, reason FROM edges").fetchone()
        assert row["precision_level"] == int(PrecisionLevel.CODEGRAPH_RESOLVER)
        assert row["reason"] == "unit test"
    finally:
        store.close()


class _UnavailableAdapter:
    id = "pyright"
    language = "python"
    precision_level = 3

    def available(self, repo_path: str) -> bool:
        return False

    def analyze_repo(self, repo_path: str, files: list[str]) -> SemanticResult:
        raise AssertionError("should not run")


def test_semantic_adapter_unavailable_falls_back() -> None:
    result = run_semantic_adapter(_UnavailableAdapter(), ".", ["app.py"])
    assert result.available is False
    assert result.result is None
    assert "syntax fallback" in result.warnings[0]
