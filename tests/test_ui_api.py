"""Phase UI-1 backend API tests."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.core.processes import PROCESS_API_FLOW, Process, ProcessStep, replace_processes
from codegraphkb.core.store import GraphStore


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # type: ignore  # noqa: E402

from codegraphkb.server.ui_server import build_ui_app  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture()
def indexed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)
    _seed_process(kb)
    return repo


def _seed_process(kb: CodeGraphKB) -> None:
    store = GraphStore(kb.config.db_path)
    try:
        syms = list(store.all_symbols())
        if len(syms) < 2:
            return
        proc = Process(
            id="proc:test-ui",
            label="ui test process",
            process_type=PROCESS_API_FLOW,
            entrypoint_id=syms[0].qualified_name,
            terminal_id=syms[1].qualified_name,
            steps=[
                ProcessStep(
                    step=1,
                    src_qname=syms[0].qualified_name,
                    dst_qname=syms[1].qualified_name,
                    edge_type="CALLS",
                    confidence=0.9,
                )
            ],
            confidence=0.9,
        )
        replace_processes(store, [proc])
    finally:
        store.close()


def _client(repo: Path) -> TestClient:
    app = build_ui_app(str(repo))
    return TestClient(app)


def test_ui_graph_api(indexed_repo: Path) -> None:
    client = _client(indexed_repo)
    resp = client.get("/api/graph", params={"view": "symbols"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metadata"]["view"] == "symbols"
    assert payload["nodes"]
    assert payload["edges"]


def test_ui_languages_api(indexed_repo: Path) -> None:
    client = _client(indexed_repo)
    supported = client.get("/api/languages")
    assert supported.status_code == 200
    languages = {item["id"] for item in supported.json()["supported"]}
    assert {"python", "java", "go", "csharp", "rust", "kotlin"} <= languages

    stats = client.get("/api/projects/local/languages")
    assert stats.status_code == 200
    assert "languages" in stats.json()


def test_ui_search_api(indexed_repo: Path) -> None:
    client = _client(indexed_repo)
    resp = client.get("/api/search", params={"q": "upload"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["results"]


def test_ui_node_details_api(indexed_repo: Path) -> None:
    kb = CodeGraphKB(indexed_repo)
    graph = kb.export_graph(view="symbols")
    symbol_nodes = [n for n in graph["nodes"] if n["kind"] in {"function", "method"}]
    assert symbol_nodes
    node_id = symbol_nodes[0]["id"]

    client = _client(indexed_repo)
    resp = client.get(f"/api/node/{node_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["node"]["id"] == node_id
    assert "relationships" in payload


def test_ui_neighborhood_api(indexed_repo: Path) -> None:
    kb = CodeGraphKB(indexed_repo)
    graph = kb.export_graph(view="calls")
    symbol_nodes = [n for n in graph["nodes"] if n["id"].startswith("symbol:")]
    assert symbol_nodes
    node_id = symbol_nodes[0]["id"]

    client = _client(indexed_repo)
    resp = client.get("/api/neighborhood", params={"node_id": node_id, "depth": 2})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metadata"]["view"] == "neighborhood"
    assert payload["nodes"]


def test_ui_process_api(indexed_repo: Path) -> None:
    client = _client(indexed_repo)
    list_resp = client.get("/api/processes")
    assert list_resp.status_code == 200
    procs = list_resp.json()["processes"]
    assert procs

    proc_id = procs[0]["id"]
    detail_resp = client.get(f"/api/processes/{proc_id}")
    assert detail_resp.status_code == 200
    payload = detail_resp.json()
    assert payload["id"] == proc_id
    assert "steps" in payload


def test_ui_impact_api(indexed_repo: Path) -> None:
    client = _client(indexed_repo)
    resp = client.get("/api/impact", params={"target": "process_upload", "depth": 2})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metadata"]["view"] == "impact"
    assert payload["metadata"]["target"] == "process_upload"


def test_ui_context_api(indexed_repo: Path) -> None:
    kb = CodeGraphKB(indexed_repo)
    graph = kb.export_graph(view="symbols")
    symbol_nodes = [n for n in graph["nodes"] if n["id"].startswith("symbol:")]
    assert symbol_nodes

    client = _client(indexed_repo)
    resp = client.post(
        "/api/context",
        json={
            "task": "Update upload validation behavior",
            "mode": "edit",
            "selected_node_ids": [symbol_nodes[0]["id"]],
            "token_budget": 3000,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "context_pack" in payload
    assert payload["selected_node_ids"]
    assert "context" in payload
