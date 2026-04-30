"""Phase 3.0A foundation-hardening tests.

Covers:
- Fix 1: TypeScript provider does not parse twice.
- Fix 2: Doctor reports actual parser backend / fallback files.
- Fix 3: Stale edges removed when symbols disappear.
- Fix 4: Migrations run safely on empty / partial / existing DBs.
- Fix 5: Doctor reports provider status.
- Fix 6: PhaseRunner DAG validation (duplicate / missing / cycle / topo sort).
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.graph_schema import EdgeType, PrecisionLevel
from codegraphkb.core.languages import LanguageProviderRegistry
from codegraphkb.core.languages.typescript.provider import TypeScriptLanguageProvider
from codegraphkb.core.parsers import ParserBackend
from codegraphkb.core.parsers import registry as parser_registry_module
from codegraphkb.core.pipeline import (
    PhaseResult,
    PhaseRunner,
    PipelineConfigError,
    PipelineCycleError,
)
from codegraphkb.core.scanner import SourceFile
from codegraphkb.core.store import GraphStore


FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


# --------------------------------------------------------------------------
# Fix 1: TypeScript provider should not parse twice.
# --------------------------------------------------------------------------

def _ts_source(content: str = "function hi(){return 1}\n") -> SourceFile:
    return SourceFile(
        rel_path="a.ts",
        abs_path=Path("a.ts"),
        language="typescript",
        content=content,
        content_hash="hash",
        size_bytes=len(content),
    )


def test_typescript_provider_reuses_parse_result(monkeypatch) -> None:
    provider = TypeScriptLanguageProvider(backend=ParserBackend.REGEX)
    src = _ts_source()

    syntax = provider.parse_syntax(src)
    assert syntax.extraction is not None, "parse_syntax must carry extraction"

    calls = {"n": 0}
    real_parse = parser_registry_module.parse

    def counted(*a, **kw):
        calls["n"] += 1
        return real_parse(*a, **kw)

    monkeypatch.setattr(
        "codegraphkb.core.languages.typescript.provider.parse", counted
    )
    extraction = provider.extract_symbols(src, syntax)
    assert extraction is syntax.extraction
    assert calls["n"] == 0, "extract_symbols must not re-invoke parse"


def test_typescript_provider_does_not_parse_twice(monkeypatch) -> None:
    src = _ts_source()
    provider = TypeScriptLanguageProvider(backend=ParserBackend.REGEX)

    calls = {"n": 0}
    real_parse = parser_registry_module.parse

    def counted(*a, **kw):
        calls["n"] += 1
        return real_parse(*a, **kw)

    monkeypatch.setattr(
        "codegraphkb.core.languages.typescript.provider.parse", counted
    )
    syntax = provider.parse_syntax(src)
    provider.extract_symbols(src, syntax)
    assert calls["n"] == 1


# --------------------------------------------------------------------------
# Fix 2: parser backend metadata + doctor reports.
# --------------------------------------------------------------------------

def test_doctor_reports_actual_parser_backend(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    kb.index()
    report = kb.doctor()
    counts = report.get("parser_backend_counts") or {}
    assert counts, "parser_backend_counts should be populated after indexing"
    # The fixture is Python-only; we expect 'ast' to appear.
    assert "ast" in counts
    assert counts["ast"] >= 1


def test_parser_signature_uses_actual_backend(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    kb.index()
    store = GraphStore(kb.config.db_path)
    try:
        any_actual = False
        for path in store.known_files():
            actual = store.get_meta(f"file_parser_actual:{path}")
            sig = store.get_meta(f"file_parser_signature:{path}")
            preferred = store.get_meta(f"file_parser_preferred:{path}")
            assert actual is not None
            assert sig is not None
            assert preferred is not None
            # Signature must mention actual backend, not "auto".
            assert "auto" not in sig
            any_actual = True
        assert any_actual
    finally:
        store.close()


def test_doctor_reports_parser_fallbacks(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "legacy.js").write_text("function add(a,b){return a+b}\n")

    kb = CodeGraphKB(repo)
    # AUTO + force regex would normally not flag fallback. Simulate fallback by
    # flipping the meta after indexing.
    kb.index(parser="auto")

    store = GraphStore(kb.config.db_path)
    try:
        store.set_meta("file_parser_fallback:legacy.js", "true")
        store.set_meta("file_parser_actual:legacy.js", "regex")
        store.set_meta("file_parser_preferred:legacy.js", "auto")
        store.set_meta(
            "file_parser_warning:legacy.js",
            "tree-sitter unavailable; used regex fallback",
        )
    finally:
        store.close()

    report = kb.doctor()
    assert report.get("parser_fallback_count") == 1
    files = report.get("parser_fallback_files") or []
    assert len(files) == 1
    entry = files[0]
    assert entry["path"] == "legacy.js"
    assert entry["actual"] == "regex"
    assert entry["preferred"] == "auto"
    assert "tree-sitter" in entry["warning"]


def test_doctor_reports_provider_status(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    kb.index()
    report = kb.doctor()
    providers = report.get("providers") or {}
    assert "python" in providers
    assert "typescript" in providers
    py = providers["python"]
    assert py["syntax_provider"] == "python"
    assert py["parser_backend"] == "ast"
    assert py["semantic_backend"] == "pyright/basedpyright"
    assert py["semantic_available"] is False
    assert py["status"] == "syntax-only"


def test_doctor_reports_syntax_only_status(repo: Path, monkeypatch) -> None:
    # Force the TypeScript semantic helper to look unavailable so all providers
    # report the syntax-only baseline.
    monkeypatch.setenv("CODEGRAPHKB_TS_SEMANTIC_HELPER", str(repo / "missing.js"))
    kb = CodeGraphKB(repo)
    kb.index()
    report = kb.doctor()
    providers = report.get("providers") or {}
    for entry in providers.values():
        assert entry["status"] == "syntax-only"
        assert entry["semantic_available"] is False


# --------------------------------------------------------------------------
# Fix 3: stale edges are removed when symbols disappear.
# --------------------------------------------------------------------------

def test_reindex_removes_edges_for_deleted_symbol(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "module.py"
    target.write_text(
        "def helper():\n"
        "    return 1\n"
        "\n"
        "def old_func():\n"
        "    helper()\n"
    )
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    store = GraphStore(kb.config.db_path)
    try:
        # baseline: at least one edge from old_func
        rows = store._conn.execute(
            "SELECT COUNT(*) AS n FROM edges WHERE src_qname LIKE '%old_func'"
        ).fetchone()
        assert rows["n"] >= 1
    finally:
        store.close()

    # Remove old_func and re-index.
    target.write_text("def helper():\n    return 1\n")
    kb.index(force=True)

    store = GraphStore(kb.config.db_path)
    try:
        rows = store._conn.execute(
            "SELECT COUNT(*) AS n FROM edges WHERE src_qname LIKE '%old_func'"
        ).fetchone()
        assert rows["n"] == 0, "edges from removed symbol must be deleted"
    finally:
        store.close()


def test_reindex_removes_incoming_edges_to_deleted_symbol(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "module.py"
    target.write_text(
        "def helper():\n"
        "    return 1\n"
        "\n"
        "def caller():\n"
        "    helper()\n"
    )
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    store = GraphStore(kb.config.db_path)
    try:
        store._conn.execute(
            "UPDATE edges SET dst_qname='module.helper' "
            "WHERE dst_name='helper' AND dst_qname IS NULL"
        )
        store._conn.commit()
    finally:
        store.close()

    # Remove helper, keep caller.
    target.write_text("def caller():\n    return 1\n")
    kb.index(force=True)

    store = GraphStore(kb.config.db_path)
    try:
        rows = store._conn.execute(
            "SELECT COUNT(*) AS n FROM edges WHERE dst_qname='module.helper'"
        ).fetchone()
        assert rows["n"] == 0
    finally:
        store.close()


def test_reindex_preserves_edges_for_unchanged_other_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def foo():\n    return 1\n")
    (repo / "b.py").write_text("from a import foo\n\ndef bar():\n    foo()\n")

    kb = CodeGraphKB(repo)
    kb.index(force=True)
    store = GraphStore(kb.config.db_path)
    try:
        before = store._conn.execute(
            "SELECT COUNT(*) AS n FROM edges WHERE src_qname LIKE '%bar'"
        ).fetchone()["n"]
    finally:
        store.close()

    # Change a.py only.
    (repo / "a.py").write_text("def foo():\n    return 2\n")
    kb.index()

    store = GraphStore(kb.config.db_path)
    try:
        after = store._conn.execute(
            "SELECT COUNT(*) AS n FROM edges WHERE src_qname LIKE '%bar'"
        ).fetchone()["n"]
        assert after == before
    finally:
        store.close()


# --------------------------------------------------------------------------
# Fix 4: migrations are safe for empty / partial / existing DBs.
# --------------------------------------------------------------------------

def test_migration_handles_empty_existing_db_file(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite"
    # Touch an empty file so `is_new_db` is False.
    db_path.write_bytes(b"")
    sqlite3.connect(str(db_path)).close()

    store = GraphStore(db_path)
    try:
        rows = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r["name"] for r in rows}
        assert {"meta", "files", "symbols", "edges"} <= names
    finally:
        store.close()


def test_migration_handles_db_with_only_meta_table(tmp_path: Path) -> None:
    db_path = tmp_path / "partial.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
    )
    conn.commit()
    conn.close()

    store = GraphStore(db_path)
    try:
        rows = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r["name"] for r in rows}
        assert {"meta", "files", "symbols", "edges", "types",
                "callsites", "imports", "processes"} <= names
        # And the symbols table has all schema-v3 columns.
        cols = {r["name"] for r in store._conn.execute(
            "PRAGMA table_info(symbols)"
        ).fetchall()}
        assert {"return_type", "declared_type", "parser_backend",
                "metadata_json"} <= cols
    finally:
        store.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "graph.sqlite"
    GraphStore(db_path).close()
    # Re-open repeatedly; no errors and column set is stable.
    cols_first = None
    for _ in range(3):
        store = GraphStore(db_path)
        try:
            cols = sorted(
                r["name"]
                for r in store._conn.execute("PRAGMA table_info(edges)").fetchall()
            )
            if cols_first is None:
                cols_first = cols
            else:
                assert cols == cols_first
        finally:
            store.close()


# --------------------------------------------------------------------------
# Fix 6: PhaseRunner DAG validation.
# --------------------------------------------------------------------------

@dataclass
class _Phase:
    name: str
    dependencies: tuple[str, ...] = ()
    seen: list[str] | None = None

    def run(self, ctx: dict[str, Any]) -> PhaseResult:
        if self.seen is not None:
            self.seen.append(self.name)
        return PhaseResult(name=self.name, output=self.name)


def test_phase_runner_topological_sort() -> None:
    seen: list[str] = []
    parse = _Phase("parse", ("scan",), seen=seen)
    scan = _Phase("scan", (), seen=seen)
    runner = PhaseRunner([parse, scan])
    runner.run()
    assert seen == ["scan", "parse"]


def test_phase_runner_rejects_duplicate_names() -> None:
    with pytest.raises(PipelineConfigError):
        PhaseRunner([_Phase("a"), _Phase("a")])


def test_phase_runner_rejects_missing_dependency() -> None:
    with pytest.raises(PipelineConfigError):
        PhaseRunner([_Phase("a", ("ghost",))])


def test_phase_runner_detects_cycle() -> None:
    a = _Phase("a", ("b",))
    b = _Phase("b", ("a",))
    with pytest.raises(PipelineCycleError):
        PhaseRunner([a, b])
