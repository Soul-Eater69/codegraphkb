from __future__ import annotations

from pathlib import Path

from codegraphkb.core.exporters.graph_exporter import export_graph
from codegraphkb.core.exporters.neo4j_exporter import prepare_neo4j_rows
from codegraphkb.core.store import GraphStore


def test_prepare_neo4j_rows_groups_labels_relationships_and_skips_dangling_edges() -> None:
    payload = {
        "metadata": {"view": "framework", "repo_path": "/repo"},
        "nodes": [
            {
                "id": "symbol:fastapi::GET /health",
                "label": "GET /health",
                "kind": "route",
                "metadata": {"qualified_name": "fastapi::GET /health"},
            },
            {
                "id": "symbol:app.health",
                "label": "health",
                "kind": "function",
                "file_path": "app.py",
                "start_line": 1,
                "end_line": 3,
            },
        ],
        "edges": [
            {
                "id": "edge:1",
                "source": "symbol:fastapi::GET /health",
                "target": "symbol:app.health",
                "type": "ROUTES_TO",
                "confidence": 0.9,
                "precision_level": 1,
            },
            {
                "id": "edge:dangling",
                "source": "symbol:missing",
                "target": "symbol:app.health",
                "type": "CALLS",
            },
        ],
    }

    rows = prepare_neo4j_rows(payload)

    assert len(rows.nodes) == 2
    assert "symbol:fastapi::GET /health" in rows.node_label_ids["CodeGraphRoute"]
    assert "symbol:app.health" in rows.node_label_ids["CodeGraphFunction"]
    assert len(rows.relationships_by_type["ROUTES_TO"]) == 1
    assert rows.relationships_by_type["ROUTES_TO"][0]["props"]["confidence"] == 0.9
    assert rows.skipped_edges == 1


def test_framework_export_includes_routes_to_edges(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "graph.db")
    try:
        file_id = store.upsert_file(
            path="app.py",
            language="python",
            content_hash="hash",
            size_bytes=10,
            content="def health(): pass\n",
            indexed_at="now",
        )
        store.insert_symbol(
            file_id=file_id,
            kind="route",
            name="GET /health",
            qualified_name="fastapi::GET /health",
            parent_qname=None,
            start_line=1,
            end_line=1,
            signature="",
            docstring="",
            capsule="",
            extras={},
        )
        store.insert_symbol(
            file_id=file_id,
            kind="function",
            name="health",
            qualified_name="app.health",
            parent_qname=None,
            start_line=1,
            end_line=2,
            signature="health()",
            docstring="",
            capsule="",
            extras={},
        )
        store.insert_edges([
            (
                "fastapi::GET /health",
                "app.health",
                "health",
                "ROUTES_TO",
                0.8,
                "test",
                1,
            )
        ])

        payload = export_graph(store, view="framework", repo_path=str(tmp_path))
    finally:
        store.close()

    assert any(node["kind"] == "route" for node in payload["nodes"])
    assert any(node["kind"] == "function" for node in payload["nodes"])
    assert any(edge["type"] == "ROUTES_TO" for edge in payload["edges"])
