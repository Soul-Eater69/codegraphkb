"""Phase 3.4 export tests."""
from __future__ import annotations

from pathlib import Path

from codegraphkb import CodeGraphKB
from codegraphkb.core.processes import PROCESS_API_FLOW, Process, ProcessStep, replace_processes
from codegraphkb.core.store import GraphStore


def _build_python_repo(repo: Path) -> None:
    (repo / "app" / "routes").mkdir(parents=True, exist_ok=True)
    (repo / "app" / "services").mkdir(parents=True, exist_ok=True)
    (repo / "app" / "repositories").mkdir(parents=True, exist_ok=True)
    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "app" / "routes" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "app" / "services" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "app" / "repositories" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "app" / "routes" / "users.py").write_text(
        "from app.services.user_service import create_user\n\n"
        "def create_user_route(payload):\n"
        "    return create_user(payload)\n",
        encoding="utf-8",
    )
    (repo / "app" / "services" / "user_service.py").write_text(
        "from app.repositories.user_repository import save_user\n\n"
        "def create_user(payload):\n"
        "    user = {\"email\": payload[\"email\"], \"name\": payload[\"name\"]}\n"
        "    return save_user(user)\n",
        encoding="utf-8",
    )
    (repo / "app" / "repositories" / "user_repository.py").write_text(
        "def save_user(user):\n"
        "    return user\n",
        encoding="utf-8",
    )


def test_export_graph_json_has_nodes_edges(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    payload = kb.export_graph(view="full")
    assert payload["nodes"], "expected at least one node"
    assert payload["edges"], "expected at least one edge"
    assert payload["metadata"]["view"] == "full"
    assert any(n["kind"] == "function" for n in payload["nodes"])


def test_export_graph_view_filters(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    repo_view = kb.export_graph(view="repo")
    kinds = {n["kind"] for n in repo_view["nodes"]}
    assert kinds.issubset({"folder", "file"})
    assert all(e["type"] == "CONTAINS" for e in repo_view["edges"])

    calls_view = kb.export_graph(view="calls")
    assert all(e["type"] in {"CALLS", "ACCESSES", "INSTANTIATES", "EXTENDS", "IMPLEMENTS", "HAS_METHOD"}
               for e in calls_view["edges"])


def test_export_graph_html_contains_embedded_data(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    out = tmp_path / "graph.html"
    _build_python_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    kb.export_graph_html(view="symbols", out=out)
    html = out.read_text(encoding="utf-8")
    assert "vis-network" in html
    assert 'id="graph-data"' in html
    assert '"view":"symbols"' in html


def test_export_impact_graph_contains_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    payload = kb.export_impact_graph("create_user")
    assert payload["metadata"]["view"] == "impact"
    assert payload["metadata"]["target"] == "create_user"
    assert payload["nodes"]
    assert any(n.get("metadata", {}).get("is_target") for n in payload["nodes"])


def test_export_processes_contains_steps(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    store = GraphStore(kb.config.db_path)
    try:
        symbols = list(store.all_symbols())
        assert len(symbols) >= 2
        src = symbols[0].qualified_name
        dst = symbols[1].qualified_name
        proc = Process(
            id="proc:test-flow",
            label="test flow",
            process_type=PROCESS_API_FLOW,
            entrypoint_id=src,
            terminal_id=dst,
            steps=[
                ProcessStep(
                    step=1,
                    src_qname=src,
                    dst_qname=dst,
                    edge_type="CALLS",
                    confidence=0.9,
                )
            ],
            confidence=0.9,
        )
        replace_processes(store, [proc])
    finally:
        store.close()

    payload = kb.export_processes()
    assert payload["process_count"] >= 1
    assert payload["nodes"]
    assert any(e.get("metadata", {}).get("step") == 1 for e in payload["edges"])
