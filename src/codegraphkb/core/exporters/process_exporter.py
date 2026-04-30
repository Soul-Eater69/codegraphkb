"""Process export facade."""
from __future__ import annotations

from typing import Any

from codegraphkb.core.exporters.graph_exporter import VIEW_PROCESSES, export_graph
from codegraphkb.core.processes import list_processes
from codegraphkb.core.store import GraphStore


def export_processes(
    store: GraphStore,
    *,
    repo_path: str | None = None,
    max_nodes: int | None = None,
    max_edges: int | None = None,
) -> dict[str, Any]:
    """Export process summaries plus graph nodes/edges."""
    graph = export_graph(
        store,
        view=VIEW_PROCESSES,
        repo_path=repo_path,
        max_nodes=max_nodes,
        max_edges=max_edges,
    )
    summaries = list_processes(store)
    return {
        "metadata": graph["metadata"],
        "process_count": len(summaries),
        "processes": summaries,
        "nodes": graph["nodes"],
        "edges": graph["edges"],
    }
