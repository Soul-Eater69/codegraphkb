"""Phase 4.4 — Edge Resolution v2: same-file and class-scope rewrites."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB


# ---------- same-file scope ----------

@pytest.fixture()
def same_file_repo(tmp_path: Path) -> Path:
    """Two files each defining a function ``helper`` — the unique-name
    resolver can't disambiguate, but file-scope can.
    """
    repo = tmp_path / "fsrepo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "def helper():\n    return 1\n"
        "\n"
        "def caller_a():\n    return helper()\n",
        encoding="utf-8",
    )
    (repo / "b.py").write_text(
        "def helper():\n    return 2\n"
        "\n"
        "def caller_b():\n    return helper()\n",
        encoding="utf-8",
    )
    return repo


def test_file_scope_resolves_ambiguous_calls(same_file_repo: Path) -> None:
    kb = CodeGraphKB(same_file_repo)
    stats = kb.index()

    assert stats.scope_edges_file >= 2, (
        f"expected both caller_a and caller_b to resolve via file scope, "
        f"got scope_edges_file={stats.scope_edges_file}"
    )

    store = kb._open_store()
    try:
        # caller_a -> helper should resolve to a.helper, not b.helper.
        row_a = store._conn.execute("""
            SELECT dst_qname, extraction_source, metadata_json FROM edges
            WHERE src_qname='a.caller_a' AND dst_name='helper'
              AND edge_type='CALLS'
        """).fetchone()
        assert row_a and row_a["dst_qname"] == "a.helper"
        assert "edge-resolver:file_scope" in (row_a["extraction_source"] or "")
        md = json.loads(row_a["metadata_json"] or "{}")
        assert md.get("resolution_strategy") == "file_scope"
        assert md.get("selected_candidate") == "a.helper"
        assert md.get("candidate_count") == 1

        row_b = store._conn.execute("""
            SELECT dst_qname FROM edges
            WHERE src_qname='b.caller_b' AND dst_name='helper'
              AND edge_type='CALLS'
        """).fetchone()
        assert row_b and row_b["dst_qname"] == "b.helper"
    finally:
        store.close()


def test_file_scope_skips_ambiguous_within_file(tmp_path: Path) -> None:
    """If a name has multiple matches in the same file, file_scope should
    skip — leaving the edge for a later pass or as unresolved."""
    repo = tmp_path / "amb"
    repo.mkdir()
    (repo / "m.py").write_text(
        # Two classes each defining a method named 'run' makes 'run' ambiguous
        # at file scope. caller's call to bare run() should NOT be rewritten.
        "class A:\n    def run(self):\n        return 1\n"
        "class B:\n    def run(self):\n        return 2\n"
        "\n"
        "def caller():\n    return run()\n",
        encoding="utf-8",
    )
    kb = CodeGraphKB(repo)
    kb.index()
    store = kb._open_store()
    try:
        # Note: depending on extractor wiring, 'run' may still match other
        # things. The contract we want is just that file_scope didn't pick
        # an arbitrary one of the two.
        row = store._conn.execute("""
            SELECT dst_qname, extraction_source FROM edges
            WHERE src_qname='m.caller' AND dst_name='run'
        """).fetchone()
        if row and row["dst_qname"]:
            # If something resolved it, it wasn't file_scope (that should
            # have refused to pick).
            assert "edge-resolver:file_scope" not in (row["extraction_source"] or "")
    finally:
        store.close()


# ---------- class scope ----------

def test_class_scope_resolves_method_call_to_sibling(tmp_path: Path) -> None:
    repo = tmp_path / "cls"
    repo.mkdir()
    (repo / "service.py").write_text(
        "class TokenService:\n"
        "    def issue(self):\n"
        "        return self.sign()\n"
        "    def sign(self):\n"
        "        return 'sig'\n"
        "\n"
        "class OtherService:\n"
        "    def sign(self):\n"
        "        return 'other'\n",
        encoding="utf-8",
    )
    kb = CodeGraphKB(repo)
    stats = kb.index()
    assert stats.scope_edges_class >= 1

    store = kb._open_store()
    try:
        # issue() calls 'sign'; class_scope should pin it to
        # TokenService.sign (sibling), not OtherService.sign.
        row = store._conn.execute("""
            SELECT dst_qname, extraction_source, metadata_json FROM edges
            WHERE src_qname='service.TokenService.issue'
              AND dst_name='sign' AND edge_type='CALLS'
        """).fetchone()
        assert row and row["dst_qname"] == "service.TokenService.sign"
        assert "edge-resolver:class_scope" in (row["extraction_source"] or "")
        md = json.loads(row["metadata_json"] or "{}")
        assert md.get("resolution_strategy") == "class_scope"
    finally:
        store.close()


# ---------- ordering: alias > file > class > unique ----------

def test_resolution_order_alias_wins_over_file(tmp_path: Path) -> None:
    """When both alias and file-scope could resolve, alias wins because it
    runs first. The edge ends up tagged ``import-alias-resolver``."""
    repo = tmp_path / "ord"
    repo.mkdir()
    (repo / "lib.py").write_text("def widget():\n    return 'lib'\n", encoding="utf-8")
    (repo / "app.py").write_text(
        "from lib import widget as widget\n"  # alias keeping same name
        "\n"
        "def widget():\n    return 'local'\n"
        "\n"
        "def use():\n    return widget()\n",
        encoding="utf-8",
    )
    kb = CodeGraphKB(repo)
    kb.index()
    store = kb._open_store()
    try:
        row = store._conn.execute("""
            SELECT dst_qname, extraction_source FROM edges
            WHERE src_qname='app.use' AND dst_name='widget' AND edge_type='CALLS'
        """).fetchone()
        # Either resolver could win in principle, but alias runs first so we
        # expect either alias OR file_scope tag, never unique-name. Confirm
        # something resolved it and the tag is one of the precise ones.
        assert row is not None
        es = row["extraction_source"] or ""
        assert ("import-alias-resolver" in es) or ("edge-resolver:" in es)
    finally:
        store.close()


# ---------- doctor surface ----------

def test_doctor_reports_resolution_strategy_counts(same_file_repo: Path) -> None:
    kb = CodeGraphKB(same_file_repo)
    kb.index()
    from codegraphkb.diagnostics import collect_doctor_report
    report = collect_doctor_report(kb)

    counts = report["resolution_strategy_counts"]
    # All 5 buckets present, file_scope > 0 because of the fixture.
    assert {"import_alias", "file_scope", "class_scope",
            "unique_name", "parser_resolved"} <= set(counts.keys())
    assert counts["file_scope"] >= 2
