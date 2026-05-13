"""Phase 4.1 — ExtractResult contract and edge-resolution diagnostics."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.parsers.base import (
    ConfigRead,
    ConstantBinding,
    ExtractResult,
    ImportBinding,
    IndexDiagnostic,
    ParsedEdge,
    ParsedSymbol,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(FIXTURE, dest)
    return dest


# ---------- ExtractResult contract ----------

def test_extract_result_defaults_are_typed_empty_lists() -> None:
    """Old parsers that only pass symbols/edges must still construct cleanly."""
    result = ExtractResult(symbols=[], edges=[])
    assert result.imports == []
    assert result.constants == []
    assert result.configs == []
    assert result.diagnostics == []


def test_extract_result_accepts_new_fields() -> None:
    imp = ImportBinding(
        file_path="a.py", local_name="pack", imported_name="buildPack",
        source_module="./retrieval", import_kind="named",
    )
    const = ConstantBinding(
        file_path="config.py", qualified_name="config.DEFAULT_BUDGET",
        name="DEFAULT_BUDGET", value_repr="6000",
    )
    cfg = ConfigRead(
        file_path="config.py", src_qualified_name="config.load_llm_config",
        key="ANTHROPIC_API_KEY", kind="env_var",
    )
    diag = IndexDiagnostic(
        severity="warning", code="parser_fallback",
        message="tree-sitter unavailable, fell back to regex",
        file_path="a.py",
    )
    result = ExtractResult(
        symbols=[], edges=[],
        imports=[imp], constants=[const], configs=[cfg], diagnostics=[diag],
    )
    assert result.imports[0].local_name == "pack"
    assert result.constants[0].qualified_name == "config.DEFAULT_BUDGET"
    assert result.configs[0].key == "ANTHROPIC_API_KEY"
    assert result.diagnostics[0].code == "parser_fallback"


def test_parsed_edge_carries_dst_qname_optional() -> None:
    """ParsedEdge.dst_qname is None by default; producers may pre-resolve."""
    e1 = ParsedEdge(src_qualified_name="a.foo", dst_name="bar", edge_type="CALLS")
    assert e1.dst_qname is None

    e2 = ParsedEdge(
        src_qualified_name="a.foo", dst_name="bar", edge_type="CALLS",
        dst_qname="b.bar",
    )
    assert e2.dst_qname == "b.bar"


def test_parsed_symbol_construction_unchanged() -> None:
    """Sanity: the symbol contract still accepts its prior shape."""
    s = ParsedSymbol(
        kind="function", name="foo", qualified_name="m.foo",
        start_line=1, end_line=2,
    )
    assert s.parameters == []
    assert s.extras == {}


# ---------- doctor edge-resolution diagnostics ----------

def test_doctor_report_includes_edge_resolution_fields(repo: Path) -> None:
    kb = CodeGraphKB(repo)
    kb.index()
    from codegraphkb.diagnostics import collect_doctor_report
    report = collect_doctor_report(kb)

    # Numeric counts
    assert "edge_count" in report
    assert "resolved_edge_count" in report
    assert "unresolved_edge_count" in report
    assert (report["resolved_edge_count"] + report["unresolved_edge_count"]
            == report["edge_count"])

    # Rate is a float in [0, 1]
    rate = report["edge_resolution_rate"]
    assert isinstance(rate, float)
    assert 0.0 <= rate <= 1.0

    # Structured edge_resolution block
    er = report["edge_resolution"]
    assert er["total"] == report["edge_count"]
    assert er["resolved"] == report["resolved_edge_count"]
    assert er["unresolved"] == report["unresolved_edge_count"]
    assert er["resolution_rate"] == rate

    # Unresolved breakdown shapes
    assert isinstance(report["unresolved_edges_by_language"], dict)
    assert isinstance(report["top_unresolved_edge_names"], list)
    for row in report["top_unresolved_edge_names"]:
        assert {"dst_name", "edge_type", "count"} <= set(row.keys())
        assert isinstance(row["count"], int)

    # Parser fallback rate
    assert isinstance(report["parser_fallback_rate"], float)
    assert 0.0 <= report["parser_fallback_rate"] <= 1.0


def test_edge_resolution_stats_empty_db(tmp_path: Path) -> None:
    """Empty index: rate is 0.0, no division-by-zero."""
    from codegraphkb.core.store import GraphStore
    store = GraphStore(tmp_path / "graph.sqlite")
    try:
        stats = store.edge_resolution_stats()
        assert stats == {
            "total": 0, "resolved": 0, "unresolved": 0, "resolution_rate": 0.0,
        }
        assert store.unresolved_edges_by_language() == {}
        assert store.top_unresolved_edge_names() == []
    finally:
        store.close()


# ---------- doctor --unresolved CLI view ----------

def test_doctor_unresolved_view_runs(repo: Path) -> None:
    """Smoke: the --unresolved view renders without raising."""
    from click.testing import CliRunner
    from codegraphkb.cli import cli

    kb = CodeGraphKB(repo)
    kb.index()

    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", str(repo), "--unresolved"])
    assert result.exit_code == 0, result.output
    assert "unresolved edges" in result.output.lower()
