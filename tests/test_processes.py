"""Phase 3.3 — process map tests.

Layered the same way as Phase 3.1's TS semantic tests:

1. Pure-Python builder behaviour against a synthetic graph.
2. Persistence + read APIs.
3. End-to-end against the express fixture, with the semantic adapter on
   when the helper is built (skipped otherwise).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.graph_schema import EdgeType, PrecisionLevel
from codegraphkb.core.processes import (
    PROCESS_API_FLOW,
    PROCESS_TEST_FLOW,
    PROCESS_UI_TO_API_FLOW,
    build_processes,
    find_processes_for_symbol,
    get_process,
    list_processes,
    replace_processes,
)
from codegraphkb.core.processes.builder import _normalize_path
from codegraphkb.core.store import GraphStore


REPO_ROOT = Path(__file__).resolve().parent.parent
EXPRESS_PROCESS_FIXTURE = REPO_ROOT / "examples" / "ts-process-express"
HELPER_DIST = REPO_ROOT / "helpers" / "ts-semantic" / "dist" / "index.js"


# --------------------------------------------------------------------------
# Layer 1 — synthetic-graph builder tests.
# --------------------------------------------------------------------------

@pytest.fixture()
def kb_with_python_repo(tmp_path: Path) -> CodeGraphKB:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text(
        "def helper():\n    return 1\n\n"
        "def caller():\n    helper()\n"
    )
    kb = CodeGraphKB(repo)
    kb.index(force=True)
    return kb


def _seed_route_chain(store: GraphStore) -> None:
    """Insert a synthetic Route + handler chain on top of the python fixture
    so the builder has something to walk."""
    # Pretend `module.helper` is the terminal QUERIES target; insert a Route
    # node and the chain Route -> caller -> helper -> Order(model).
    file_id = store._conn.execute("SELECT id FROM files LIMIT 1").fetchone()["id"]
    with store.transaction() as cx:
        cx.execute(
            "INSERT INTO symbols(file_id, kind, name, qualified_name, parent_qname, "
            "start_line, end_line, signature, docstring, capsule, extras, "
            "return_type, declared_type, visibility, is_exported, parser_backend, "
            "parser_version, semantic_backend, semantic_version, content_hash, "
            "metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (file_id, "route", "POST /orders/:id/cancel",
             "express::POST /orders/:id/cancel", None, 1, 1,
             "express route POST /orders/:id/cancel -> caller", "", "",
             '{"framework": "express", "http_method": "POST", '
             '"path": "/orders/:id/cancel", "handler": "caller"}',
             "", "", "", 0, "regex", "1", "", "", "", "{}"),
        )
    store.insert_edges([
        # Route -> handler
        ("express::POST /orders/:id/cancel", "module.caller", "caller",
         EdgeType.HANDLES_ROUTE.value, 0.85, "extractor:express",
         1, None, int(PrecisionLevel.SYNTAX), "route handler", {}, ""),
        # Handler -> helper (CALLS)
        ("module.caller", "module.helper", "helper",
         EdgeType.CALLS.value, 0.94, "typescript-compiler-api",
         5, None, int(PrecisionLevel.LANGUAGE_SEMANTIC), "TypeChecker resolved", {}, ""),
        # Helper QUERIES Order (terminal)
        ("module.helper", "prisma::Order", "Order",
         EdgeType.QUERIES.value, 0.85, "extractor:prisma",
         2, None, int(PrecisionLevel.SYNTAX), "prisma query",
         {"operation": "findMany"}, ""),
    ])


def test_builder_creates_api_flow_with_full_chain(kb_with_python_repo: CodeGraphKB) -> None:
    store = GraphStore(kb_with_python_repo.config.db_path)
    try:
        _seed_route_chain(store)
        processes = build_processes(store)
        api = [p for p in processes if p.process_type == PROCESS_API_FLOW]
        assert len(api) == 1
        proc = api[0]
        # Full chain: Route -> caller -> helper -> Order(QUERIES)
        edges = [s.edge_type for s in proc.steps]
        assert edges == ["HANDLES_ROUTE", "CALLS", "QUERIES"]
        assert proc.entrypoint_id == "express::POST /orders/:id/cancel"
        assert proc.terminal_id == "prisma::Order"
        assert proc.label == "POST /orders/:id/cancel"
        assert 0.5 < proc.confidence <= 1.0
    finally:
        store.close()


def test_builder_stops_at_max_depth(kb_with_python_repo: CodeGraphKB) -> None:
    store = GraphStore(kb_with_python_repo.config.db_path)
    try:
        _seed_route_chain(store)
        processes = build_processes(store, max_depth=2)
        api = [p for p in processes if p.process_type == PROCESS_API_FLOW][0]
        assert len(api.steps) == 2
    finally:
        store.close()


def test_builder_detects_cycle(kb_with_python_repo: CodeGraphKB) -> None:
    store = GraphStore(kb_with_python_repo.config.db_path)
    try:
        _seed_route_chain(store)
        # Add a cycle: helper -> caller (would loop back).
        store.insert_edges([(
            "module.helper", "module.caller", "caller",
            EdgeType.CALLS.value, 0.9, "synthetic",
            None, None, int(PrecisionLevel.SYNTAX), "cycle", {}, "",
        )])
        processes = build_processes(store, max_depth=10)
        api = [p for p in processes if p.process_type == PROCESS_API_FLOW][0]
        # The chain should still be 3 steps and not loop.
        assert len(api.steps) <= 4
        visited = {api.entrypoint_id}
        for step in api.steps:
            assert step.dst_qname not in visited or step.edge_type in {"QUERIES", "FETCHES", "CALLS_EXTERNAL"}
            visited.add(step.dst_qname)
    finally:
        store.close()


def test_builder_skips_low_confidence_edges(kb_with_python_repo: CodeGraphKB) -> None:
    store = GraphStore(kb_with_python_repo.config.db_path)
    try:
        _seed_route_chain(store)
        # Replace the QUERIES edge with a low-confidence one.
        with store.transaction() as cx:
            cx.execute(
                "UPDATE edges SET confidence=0.2 WHERE edge_type='QUERIES' "
                "AND src_qname='module.helper'"
            )
        processes = build_processes(store, min_step_confidence=0.5)
        api = [p for p in processes if p.process_type == PROCESS_API_FLOW][0]
        # We should have stopped before the low-confidence QUERIES edge.
        assert all(s.edge_type != "QUERIES" for s in api.steps)
        assert len(api.steps) == 2  # HANDLES_ROUTE, CALLS
    finally:
        store.close()


# --------------------------------------------------------------------------
# Layer 2 — persistence and read APIs.
# --------------------------------------------------------------------------

def test_persist_writes_processes_and_step_in_process_edges(
    kb_with_python_repo: CodeGraphKB,
) -> None:
    store = GraphStore(kb_with_python_repo.config.db_path)
    try:
        _seed_route_chain(store)
        processes = build_processes(store)
        replace_processes(store, processes)

        # processes table populated.
        rows = store._conn.execute("SELECT * FROM processes").fetchall()
        assert len(rows) == len(processes)

        # process_steps populated.
        n_steps = store._conn.execute(
            "SELECT COUNT(*) AS n FROM process_steps"
        ).fetchone()["n"]
        assert n_steps == sum(p.step_count for p in processes)

        # STEP_IN_PROCESS edges written.
        step_edges = store._conn.execute(
            "SELECT COUNT(*) AS n FROM edges WHERE edge_type='STEP_IN_PROCESS'"
        ).fetchone()["n"]
        assert step_edges == n_steps

        # list_processes returns the rows.
        listed = list_processes(store)
        assert len(listed) == len(processes)

        # get_process returns a process with steps.
        proc_id = listed[0]["id"]
        full = get_process(store, proc_id)
        assert full is not None
        assert full["step_count"] == len(full["steps"])
    finally:
        store.close()


def test_replace_processes_is_idempotent(kb_with_python_repo: CodeGraphKB) -> None:
    store = GraphStore(kb_with_python_repo.config.db_path)
    try:
        _seed_route_chain(store)
        procs = build_processes(store)
        replace_processes(store, procs)
        before = store._conn.execute(
            "SELECT COUNT(*) AS n FROM processes"
        ).fetchone()["n"]
        replace_processes(store, procs)
        after = store._conn.execute(
            "SELECT COUNT(*) AS n FROM processes"
        ).fetchone()["n"]
        assert before == after
        # STEP_IN_PROCESS edges should not duplicate either.
        n_step_edges = store._conn.execute(
            "SELECT COUNT(*) AS n FROM edges WHERE edge_type='STEP_IN_PROCESS'"
        ).fetchone()["n"]
        assert n_step_edges == sum(p.step_count for p in procs)
    finally:
        store.close()


def test_find_processes_for_symbol(kb_with_python_repo: CodeGraphKB) -> None:
    store = GraphStore(kb_with_python_repo.config.db_path)
    try:
        _seed_route_chain(store)
        replace_processes(store, build_processes(store))
        traces = find_processes_for_symbol(store, "module.caller")
        assert traces, "process touching module.caller should be found"
        ids = {t["id"] for t in traces}
        assert any("api_flow" in i for i in ids)
    finally:
        store.close()


def test_normalize_path_matches_express_and_nextjs() -> None:
    assert _normalize_path("/orders/:id/cancel") == _normalize_path("/orders/[id]/cancel")
    assert _normalize_path("/orders/:id/cancel") == "orders/:param/cancel"


# --------------------------------------------------------------------------
# Layer 3 — end-to-end against the Express fixture.
# --------------------------------------------------------------------------

helper_built = HELPER_DIST.exists()


@pytest.fixture()
def express_repo(tmp_path: Path, monkeypatch) -> Path:
    if helper_built:
        monkeypatch.setenv("CODEGRAPHKB_TS_SEMANTIC_HELPER", str(HELPER_DIST))
    dest = tmp_path / "repo"
    shutil.copytree(EXPRESS_PROCESS_FIXTURE, dest)
    return dest


def test_index_with_semantic_yields_full_express_api_flow(express_repo: Path) -> None:
    if not helper_built:
        pytest.skip("TypeScript semantic helper not built")
    kb = CodeGraphKB(express_repo)
    stats = kb.index(force=True, parser="regex", semantic="typescript")
    assert stats.processes_built >= 1
    assert "api_flow" in stats.processes_by_type

    procs = kb.list_processes(process_type="api_flow")
    cancel = [p for p in procs if "POST /orders/:id/cancel" in p["label"]]
    assert cancel, f"expected api_flow for POST /orders/:id/cancel, got {procs}"

    full = kb.get_process(cancel[0]["id"])
    assert full is not None
    edges = [s["metadata"]["edge_type"] for s in full["steps"]]
    # Full chain: Route -> handler (HANDLES_ROUTE)
    #          -> service (CALLS)
    #          -> payment (CALLS)
    assert edges[0] == "HANDLES_ROUTE"
    assert edges[1:].count("CALLS") >= 2
    qnames = [s["dst_qname"] for s in full["steps"]]
    assert any("cancelOrderHandler" in q for q in qnames)
    assert any("cancelOrder" in q for q in qnames)
    assert any("refundPayment" in q for q in qnames)


def test_index_emits_ui_to_api_and_test_flow(express_repo: Path) -> None:
    kb = CodeGraphKB(express_repo)
    kb.index(force=True, parser="regex")
    by_type = {p["process_type"] for p in kb.list_processes()}
    assert "ui_to_api_flow" in by_type
    assert "test_flow" in by_type
    assert "api_flow" in by_type


def test_doctor_reports_process_counts(express_repo: Path) -> None:
    kb = CodeGraphKB(express_repo)
    kb.index(force=True, parser="regex")
    report = kb.doctor()
    counts = report.get("process_counts") or {}
    assert counts.get("total", 0) >= 3
    assert "api_flow" in counts
    assert "ui_to_api_flow" in counts


def test_workflow_pack_attaches_process_traces(express_repo: Path) -> None:
    from codegraphkb.workflow import prepare_edit_context

    kb = CodeGraphKB(express_repo)
    kb.index(force=True, parser="regex")
    pack = prepare_edit_context(kb, "Add support for cancelling an order with a refund")
    assert pack.process_traces, "edit context should include relevant process traces"
    assert any(t.get("process_type") == "api_flow" for t in pack.process_traces)


def test_cli_process_list_and_show(express_repo: Path) -> None:
    import subprocess
    import sys

    kb = CodeGraphKB(express_repo)
    kb.index(force=True, parser="regex")
    listing = subprocess.run(
        [sys.executable, "-m", "codegraphkb", "process", "list",
         "--repo", str(express_repo), "--json"],
        capture_output=True, text=True, check=True,
    )
    import json as _json
    data = _json.loads(listing.stdout)
    assert isinstance(data, list) and data
    sample_id = data[0]["id"]
    show = subprocess.run(
        [sys.executable, "-m", "codegraphkb", "process", "show", sample_id,
         "--repo", str(express_repo), "--json"],
        capture_output=True, text=True, check=True,
    )
    detail = _json.loads(show.stdout)
    assert detail["id"] == sample_id
    assert detail["steps"]
