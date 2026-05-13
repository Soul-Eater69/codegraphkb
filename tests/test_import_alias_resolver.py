"""Phase 4.2 — Python import alias resolution end-to-end."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.parsers.python_parser import parse_python
from codegraphkb.core.scanner import SourceFile


def _src(rel: str, content: str) -> SourceFile:
    return SourceFile(
        rel_path=rel, abs_path=Path(rel), language="python",
        content=content, content_hash="h", size_bytes=len(content),
    )


# ---------- parser-side: ImportBinding emission ----------

def test_python_parser_emits_aliased_import_from() -> None:
    result = parse_python(_src("pkg/mod.py", (
        "from a.b import c as d\n"
        "def f():\n    return d()\n"
    )))
    aliases = [b for b in result.imports if b.local_name == "d"]
    assert len(aliases) == 1
    b = aliases[0]
    assert b.imported_name == "c"
    assert b.source_module == "a.b"
    assert b.import_kind == "named"


def test_python_parser_emits_relative_import() -> None:
    result = parse_python(_src("pkg/sub/mod.py", "from .x import y\n"))
    rel = [b for b in result.imports if b.local_name == "y"]
    assert rel and rel[0].source_module == ".x"
    assert rel[0].metadata.get("level") == 1


def test_python_parser_emits_module_alias() -> None:
    result = parse_python(_src("m.py", "import a.b as ab\n"))
    rec = [b for b in result.imports if b.local_name == "ab"]
    assert rec and rec[0].imported_name == "a.b"
    assert rec[0].import_kind == "default"


def test_python_parser_skips_star_import() -> None:
    result = parse_python(_src("m.py", "from a import *\n"))
    # Star imports don't bind a single local name; nothing in bindings.
    assert all(b.imported_name != "*" for b in result.imports)


# ---------- end-to-end on a fixture repo ----------

@pytest.fixture()
def alias_repo(tmp_path: Path) -> Path:
    """Repo where module ``caller`` calls ``buildPack`` via an alias.

    Layout:
        retrieval.py     -> defines buildPack
        caller.py        -> from retrieval import buildPack as pack; pack()
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "retrieval.py").write_text(
        "def buildPack(task):\n    return task\n",
        encoding="utf-8",
    )
    (repo / "caller.py").write_text(
        "from retrieval import buildPack as pack\n"
        "\n"
        "def run(task):\n"
        "    return pack(task)\n",
        encoding="utf-8",
    )
    return repo


def test_alias_resolver_rewrites_call_via_alias(alias_repo: Path) -> None:
    kb = CodeGraphKB(alias_repo)
    stats = kb.index()

    # At minimum one alias binding got resolved and one edge rewritten.
    assert stats.alias_bindings_total >= 1
    assert stats.alias_bindings_resolved >= 1
    assert stats.alias_edges_rewritten >= 1

    # Verify the actual edge now points at the real target.
    store = kb._open_store()
    try:
        rows = store._conn.execute("""
            SELECT src_qname, dst_qname, dst_name, edge_type, extraction_source,
                   metadata_json
            FROM edges
            WHERE src_qname='caller.run' AND dst_name='pack'
        """).fetchall()
        assert rows, "expected a CALLS edge for caller.run -> pack"
        row = rows[0]
        assert row["dst_qname"] == "retrieval.buildPack"
        assert "import-alias-resolver" in (row["extraction_source"] or "")
        # Audit metadata
        import json
        md = json.loads(row["metadata_json"] or "{}")
        assert md.get("resolution_strategy") == "import_alias"
        assert md.get("original_dst_name") == "pack"
        assert md.get("selected_candidate") == "retrieval.buildPack"
    finally:
        store.close()


def test_alias_resolver_persists_target_qname(alias_repo: Path) -> None:
    kb = CodeGraphKB(alias_repo)
    kb.index()
    store = kb._open_store()
    try:
        row = store._conn.execute(
            "SELECT target_qname FROM imports "
            "WHERE file_path='caller.py' AND local_name='pack'"
        ).fetchone()
        assert row is not None
        assert row["target_qname"] == "retrieval.buildPack"
    finally:
        store.close()


def test_alias_resolver_handles_relative_import(tmp_path: Path) -> None:
    repo = tmp_path / "rrepo"
    repo.mkdir()
    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (pkg / "client.py").write_text(
        "from .core import helper as h\n"
        "\n"
        "def call_it():\n"
        "    return h()\n",
        encoding="utf-8",
    )

    kb = CodeGraphKB(repo)
    stats = kb.index()
    assert stats.alias_edges_rewritten >= 1

    store = kb._open_store()
    try:
        row = store._conn.execute(
            "SELECT dst_qname FROM edges "
            "WHERE src_qname='pkg.client.call_it' AND dst_name='h'"
        ).fetchone()
        assert row and row["dst_qname"] == "pkg.core.helper"
    finally:
        store.close()


def test_doctor_reports_import_binding_count(alias_repo: Path) -> None:
    kb = CodeGraphKB(alias_repo)
    kb.index()
    from codegraphkb.diagnostics import collect_doctor_report
    report = collect_doctor_report(kb)
    assert report["import_binding_count"] >= 1


# ---------- unit tests on internal helpers ----------

def test_resolve_relative_module() -> None:
    from codegraphkb.core.import_resolver import _resolve_relative_module
    # `from .x import y` inside pkg.sub.mod -> pkg.sub.x
    assert _resolve_relative_module("pkg.sub.mod", ".x") == "pkg.sub.x"
    # `from ..x import y` inside pkg.sub.mod -> pkg.x
    assert _resolve_relative_module("pkg.sub.mod", "..x") == "pkg.x"
    # `from . import x` inside pkg.sub.mod -> pkg.sub (no tail)
    assert _resolve_relative_module("pkg.sub.mod", ".") == "pkg.sub"


# ---------- src/-layout package root detection ----------

def test_alias_resolver_handles_src_layout(tmp_path: Path) -> None:
    """``src/<pkg>`` layout: symbols stored as src.pkg.x, imports as pkg.x.

    The resolver must register both forms so ``from pkg.mod import foo``
    matches the symbol stored under ``src.pkg.mod.foo``.
    """
    repo = tmp_path / "srepo"
    (repo / "src" / "mypkg").mkdir(parents=True)
    (repo / "src" / "mypkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "mypkg" / "util.py").write_text(
        "def make_widget():\n    return 1\n",
        encoding="utf-8",
    )
    (repo / "src" / "mypkg" / "client.py").write_text(
        "from mypkg.util import make_widget as widget\n"
        "\n"
        "def use():\n"
        "    return widget()\n",
        encoding="utf-8",
    )

    kb = CodeGraphKB(repo)
    stats = kb.index()
    assert stats.alias_edges_rewritten >= 1, (
        "src/-layout fix should let the resolver rewrite the aliased call"
    )

    store = kb._open_store()
    try:
        row = store._conn.execute(
            "SELECT dst_qname FROM edges "
            "WHERE src_qname='src.mypkg.client.use' AND dst_name='widget'"
        ).fetchone()
        assert row is not None
        # Symbol qnames are still the on-disk form; the resolver just rewrites
        # the dst into whatever lookup form it found (we accept either).
        assert row["dst_qname"] in (
            "src.mypkg.util.make_widget", "mypkg.util.make_widget",
        )
    finally:
        store.close()


def test_apply_prefix_map_longest_match() -> None:
    from codegraphkb.core.import_resolver import _apply_prefix_map
    pmap = {"src.codegraphkb": "codegraphkb"}
    assert _apply_prefix_map("src.codegraphkb.x.y", pmap) == "codegraphkb.x.y"
    # No prefix → unchanged.
    assert _apply_prefix_map("other.module.foo", pmap) == "other.module.foo"
    # Non-prefix substring → unchanged (must be at start + dot boundary).
    assert _apply_prefix_map("notsrc.codegraphkb.x", pmap) == "notsrc.codegraphkb.x"
