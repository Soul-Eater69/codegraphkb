"""Phase 3.1 — TypeScript semantic adapter tests.

Three layers, each independently runnable:

1. Pure-Python merge logic (no Node/helper required).
2. Adapter discovery + doctor probe (no Node/helper required).
3. End-to-end with the real Node helper (skipped if helper not built).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.graph_schema import EdgeType, PrecisionLevel
from codegraphkb.core.semantic.merge import (
    SEMANTIC_BACKEND_ID,
    merge_semantic_result,
)
from codegraphkb.core.semantic.protocol import (
    SemanticFileResult,
    SemanticReference,
    SemanticResult,
    SemanticSymbol,
    SemanticTypeFact,
)
from codegraphkb.core.semantic.typescript_adapter import (
    TypeScriptSemanticAdapter,
    find_helper,
)
from codegraphkb.core.store import GraphStore


REPO_ROOT = Path(__file__).resolve().parent.parent
EXPRESS_FIXTURE = REPO_ROOT / "examples" / "ts-semantic-express"
HELPER_DIST = REPO_ROOT / "helpers" / "ts-semantic" / "dist" / "index.js"


# --------------------------------------------------------------------------
# Layer 1: pure-Python merge logic.
# --------------------------------------------------------------------------

def _seed_python_repo(tmp_path: Path) -> Path:
    """Create a tiny Python repo so we have rough syntax CALLS to upgrade.

    The merge logic is language-agnostic; we use Python here so the test runs
    without Node.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "module.py").write_text(
        "def helper():\n    return 1\n\n"
        "def caller():\n    helper()\n"
    )
    return repo


def test_merge_upgrades_existing_rough_edge(tmp_path: Path) -> None:
    repo = _seed_python_repo(tmp_path)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    semantic = SemanticResult(
        language="typescript",  # merge logic doesn't actually inspect language
        adapter=SEMANTIC_BACKEND_ID,
        adapter_version="0.1.0",
        repo_path=str(repo),
        files=[
            SemanticFileResult(
                path="module.py",
                references=[
                    SemanticReference(
                        from_symbol="module.caller",
                        to_symbol="module.helper",
                        edge_type=EdgeType.CALLS.value,
                        confidence=0.94,
                        precision_level=3,
                        reason="TypeChecker resolved target symbol",
                    )
                ],
            )
        ],
    )

    store = GraphStore(kb.config.db_path)
    try:
        stats = merge_semantic_result(store, semantic)
        assert stats.edges_upgraded == 1
        assert stats.edges_inserted == 0
        rows = store._conn.execute(
            "SELECT precision_level, confidence, extraction_source, dst_qname "
            "FROM edges WHERE src_qname='module.caller' AND edge_type='CALLS'"
        ).fetchall()
        assert any(
            r["precision_level"] == int(PrecisionLevel.LANGUAGE_SEMANTIC)
            and r["confidence"] >= 0.9
            and r["extraction_source"] == SEMANTIC_BACKEND_ID
            and r["dst_qname"] == "module.helper"
            for r in rows
        ), f"expected upgraded row, got {[dict(r) for r in rows]}"
    finally:
        store.close()


def test_merge_inserts_new_edge_when_no_rough_match(tmp_path: Path) -> None:
    repo = _seed_python_repo(tmp_path)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    semantic = SemanticResult(
        language="typescript",
        adapter=SEMANTIC_BACKEND_ID,
        adapter_version="0.1.0",
        repo_path=str(repo),
        files=[
            SemanticFileResult(
                path="module.py",
                references=[
                    SemanticReference(
                        from_symbol="module.caller",
                        to_symbol="module.helper",
                        edge_type=EdgeType.ACCESSES.value,
                        confidence=0.88,
                        precision_level=3,
                        reason="TypeChecker resolved property",
                    )
                ],
            )
        ],
    )

    store = GraphStore(kb.config.db_path)
    try:
        stats = merge_semantic_result(store, semantic)
        assert stats.edges_inserted == 1
        # Re-running should NOT duplicate the edge.
        stats2 = merge_semantic_result(store, semantic)
        assert stats2.edges_inserted == 0
        rows = store._conn.execute(
            "SELECT COUNT(*) AS n FROM edges "
            "WHERE src_qname='module.caller' AND edge_type='ACCESSES'"
        ).fetchone()
        assert rows["n"] == 1
    finally:
        store.close()


def test_merge_skips_unresolved_references(tmp_path: Path) -> None:
    repo = _seed_python_repo(tmp_path)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    semantic = SemanticResult(
        language="typescript",
        adapter=SEMANTIC_BACKEND_ID,
        adapter_version="0.1.0",
        repo_path=str(repo),
        files=[
            SemanticFileResult(
                path="module.py",
                references=[
                    SemanticReference(
                        from_symbol="module.caller",
                        to_symbol=None,
                        edge_type=EdgeType.CALLS.value,
                        confidence=0.6,
                        precision_level=3,
                        reason="unresolved",
                    )
                ],
            )
        ],
    )

    store = GraphStore(kb.config.db_path)
    try:
        stats = merge_semantic_result(store, semantic)
        assert stats.edges_inserted == 0
        assert stats.edges_upgraded == 0
    finally:
        store.close()


def test_merge_inserts_type_facts_idempotently(tmp_path: Path) -> None:
    repo = _seed_python_repo(tmp_path)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    semantic = SemanticResult(
        language="typescript",
        adapter=SEMANTIC_BACKEND_ID,
        adapter_version="0.1.0",
        repo_path=str(repo),
        files=[
            SemanticFileResult(
                path="module.py",
                types=[
                    SemanticTypeFact(
                        owner_symbol="module.helper",
                        name="(return)",
                        kind="return",
                        declared_type="int",
                        inferred_type="int",
                    ),
                ],
            )
        ],
    )

    store = GraphStore(kb.config.db_path)
    try:
        stats = merge_semantic_result(store, semantic)
        assert stats.types_inserted == 1
        stats2 = merge_semantic_result(store, semantic)
        assert stats2.types_inserted == 0
        n = store._conn.execute(
            "SELECT COUNT(*) AS n FROM types WHERE owner_qname='module.helper'"
        ).fetchone()["n"]
        assert n == 1
    finally:
        store.close()


def test_merge_enriches_symbol_return_type(tmp_path: Path) -> None:
    repo = _seed_python_repo(tmp_path)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    semantic = SemanticResult(
        language="typescript",
        adapter=SEMANTIC_BACKEND_ID,
        adapter_version="0.1.0",
        repo_path=str(repo),
        files=[
            SemanticFileResult(
                path="module.py",
                symbols=[
                    SemanticSymbol(
                        id="module.py::module.helper",
                        name="helper",
                        kind="function",
                        qualified_name="module.helper",
                        signature="helper() -> int",
                        return_type="int",
                        start_line=1,
                        end_line=2,
                    )
                ],
            )
        ],
    )

    store = GraphStore(kb.config.db_path)
    try:
        stats = merge_semantic_result(store, semantic)
        assert stats.symbols_enriched == 1
        row = store._conn.execute(
            "SELECT return_type, signature, semantic_backend FROM symbols "
            "WHERE qualified_name='module.helper'"
        ).fetchone()
        assert row["return_type"] == "int"
        assert row["semantic_backend"] == SEMANTIC_BACKEND_ID
    finally:
        store.close()


# --------------------------------------------------------------------------
# Layer 2: adapter discovery + doctor probe.
# --------------------------------------------------------------------------

def test_adapter_unavailable_when_helper_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CODEGRAPHKB_TS_SEMANTIC_HELPER", str(tmp_path / "nope.js"))
    adapter = TypeScriptSemanticAdapter()
    assert adapter.available(str(tmp_path)) is False


def test_doctor_reports_typescript_semantic_status(tmp_path: Path) -> None:
    # Seed a Python-only repo so the index works without Node tools.
    repo = _seed_python_repo(tmp_path)
    kb = CodeGraphKB(repo)
    kb.index(force=True)
    report = kb.doctor()
    backends = report.get("semantic_backends") or {}
    ts = backends.get("typescript") or {}
    assert ts.get("adapter") == "typescript-compiler-api"
    assert "helper_path" in ts
    assert "version" in ts
    assert "node_available" in ts
    if not ts.get("available"):
        assert "reason" in ts


# --------------------------------------------------------------------------
# Layer 3: end-to-end with real helper. Skipped if helper not built.
# --------------------------------------------------------------------------

helper_built = HELPER_DIST.exists() and shutil.which("node") is not None
helper_skip_reason = (
    "TypeScript semantic helper not built or Node not available; "
    "run `cd helpers/ts-semantic && npm install && npm run build`."
)


@pytest.mark.skipif(not helper_built, reason=helper_skip_reason)
def test_helper_runs_against_express_fixture(tmp_path: Path) -> None:
    proc = subprocess.run(
        ["node", str(HELPER_DIST), "--repo", str(EXPRESS_FIXTURE), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["adapter"] == "typescript-compiler-api"
    files = {f["path"]: f for f in data["files"]}
    # The chain must show up: cancelOrder -> refundPayment.
    svc = files["src/services/order.service.ts"]
    resolved = [
        r for r in svc["references"]
        if r["edge_type"] == "CALLS"
        and r["to_symbol"] == "src.utils.payment.refundPayment"
    ]
    assert resolved, "cancelOrder should resolve refundPayment via TypeChecker"
    assert resolved[0]["confidence"] >= 0.9
    assert resolved[0]["precision_level"] == 3


@pytest.mark.skipif(not helper_built, reason=helper_skip_reason)
def test_index_with_semantic_typescript_upgrades_chain(tmp_path: Path) -> None:
    dest = tmp_path / "express-repo"
    shutil.copytree(EXPRESS_FIXTURE, dest)
    kb = CodeGraphKB(dest)
    stats = kb.index(force=True, parser="regex", semantic="typescript")

    assert stats.semantic_backends.get("typescript", {}).get("available") is True
    assert stats.semantic_backends["typescript"]["edges_upgraded"] >= 1

    store = GraphStore(kb.config.db_path)
    try:
        chain = [
            ("src.routes.order.routes.registerOrderRoutes",
             "src.controllers.order.controller.cancelOrderHandler"),
            ("src.controllers.order.controller.cancelOrderHandler",
             "src.services.order.service.cancelOrder"),
            ("src.services.order.service.cancelOrder",
             "src.utils.payment.refundPayment"),
        ]
        for src, dst in chain:
            row = store._conn.execute(
                "SELECT precision_level, confidence, extraction_source "
                "FROM edges WHERE src_qname=? AND dst_qname=? AND edge_type='CALLS' "
                "ORDER BY precision_level DESC LIMIT 1",
                (src, dst),
            ).fetchone()
            assert row is not None, f"missing semantic edge {src} -> {dst}"
            assert row["precision_level"] == int(PrecisionLevel.LANGUAGE_SEMANTIC)
            assert row["confidence"] >= 0.9
            assert row["extraction_source"] == SEMANTIC_BACKEND_ID

        type_count = store._conn.execute(
            "SELECT COUNT(*) AS n FROM types"
        ).fetchone()["n"]
        assert type_count > 0
    finally:
        store.close()


@pytest.mark.skipif(not helper_built, reason=helper_skip_reason)
def test_doctor_reports_typescript_semantic_available_when_built(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CODEGRAPHKB_TS_SEMANTIC_HELPER", str(HELPER_DIST))
    repo = _seed_python_repo(tmp_path)
    kb = CodeGraphKB(repo)
    kb.index(force=True)
    report = kb.doctor()
    ts = report["semantic_backends"]["typescript"]
    assert ts["available"] is True
    assert ts["helper_path"] == str(HELPER_DIST)
