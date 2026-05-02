"""Impact graph export."""
from __future__ import annotations

import json
from collections import deque
from typing import Any

from codegraphkb.core.graph_schema import GRAPH_SCHEMA_VERSION
from codegraphkb.core.store import GraphStore


_EDGE_TYPES = (
    "CALLS",
    "HANDLES_ROUTE",
    "ROUTE_HANDLED_BY",
    "TESTS",
    "TESTS_SYMBOL",
    "QUERIES",
    "FETCHES",
    "CALLS_EXTERNAL",
    "IMPORTS",
    "EXTENDS",
    "IMPLEMENTS",
    "USES_MIDDLEWARE",
)


def export_impact_graph(
    store: GraphStore,
    target: str,
    *,
    max_depth: int = 2,
    repo_path: str | None = None,
    max_nodes: int | None = None,
    max_edges: int | None = None,
) -> dict[str, Any]:
    """Return a local impact neighborhood for a file or symbol target."""
    seed_qnames = _resolve_targets(store, target)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for qname in seed_qnames:
        node = _symbol_or_fallback_node(store, qname)
        node.setdefault("metadata", {})
        node["metadata"]["is_target"] = True
        nodes[node["id"]] = node

    seen = set(seed_qnames)
    queue: deque[tuple[str, int]] = deque((q, 0) for q in seed_qnames)

    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for row in _edge_rows_touching(store, current):
            edge = _edge_to_dict(row)
            src_qname = row["src_qname"]
            dst_qname = row["dst_qname"] or row["dst_name"]
            src_id = _qname_to_node_id(src_qname)
            dst_id = _qname_to_node_id(dst_qname)
            if src_id not in nodes:
                nodes[src_id] = _symbol_or_fallback_node(store, src_qname)
            if dst_id not in nodes:
                nodes[dst_id] = _symbol_or_fallback_node(store, dst_qname)
            edge["source"] = src_id
            edge["target"] = dst_id
            edges.append(edge)

            if src_qname not in seen:
                seen.add(src_qname)
                queue.append((src_qname, depth + 1))
            if dst_qname not in seen:
                seen.add(dst_qname)
                queue.append((dst_qname, depth + 1))

    if max_nodes is not None and len(nodes) > max_nodes:
        keep = set(list(nodes.keys())[:max_nodes])
        nodes = {k: v for k, v in nodes.items() if k in keep}
        edges = [e for e in edges if e["source"] in keep and e["target"] in keep]
    if max_edges is not None and len(edges) > max_edges:
        edges = edges[:max_edges]

    deduped_edges = []
    seen_edge_ids = set()
    for edge in edges:
        if edge["id"] in seen_edge_ids:
            continue
        seen_edge_ids.add(edge["id"])
        deduped_edges.append(edge)

    _attach_roles(store, nodes)

    return {
        "metadata": {
            "repo_path": repo_path or store.get_meta("repo_path") or "",
            "view": "impact",
            "target": target,
            "resolved_targets": seed_qnames,
            "schema_version": GRAPH_SCHEMA_VERSION,
            "schema_version_indexed": store.get_meta("schema_version") or "",
            "node_count": len(nodes),
            "edge_count": len(deduped_edges),
            "indexed_at": store.get_meta("last_indexed_at") or "",
        },
        "nodes": list(nodes.values()),
        "edges": deduped_edges,
    }


def _resolve_targets(store: GraphStore, target: str) -> list[str]:
    if "/" in target or target.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        symbols = store.symbols_in_file(target)
        if symbols:
            return [s.qualified_name for s in symbols]
        return [target]
    sym = store.find_symbol(target)
    if sym:
        return [sym.qualified_name]
    by_name = store.find_symbols_by_name(target, limit=20)
    if by_name:
        return [s.qualified_name for s in by_name]
    return [target]


def _edge_rows_touching(store: GraphStore, qname: str) -> list[dict[str, Any]]:
    placeholders = ",".join("?" * len(_EDGE_TYPES))
    rows = store._conn.execute(
        "SELECT * FROM edges "
        "WHERE (src_qname = ? OR dst_qname = ?) "
        f"AND edge_type IN ({placeholders}) "
        "ORDER BY confidence DESC, id ASC",
        (qname, qname, *_EDGE_TYPES),
    ).fetchall()
    return [dict(r) for r in rows]


def _edge_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    raw_meta = row.get("metadata_json") or "{}"
    try:
        metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else dict(raw_meta or {})
    except (TypeError, ValueError):
        metadata = {}
    return {
        "id": f"edge:{row['id']}",
        "source": row["src_qname"],
        "target": row["dst_qname"] or row["dst_name"],
        "type": row["edge_type"],
        "confidence": float(row.get("confidence") or 0.0),
        "precision_level": int(row.get("precision_level") or 1),
        "extraction_source": row.get("extraction_source") or "",
        "reason": row.get("reason") or "",
        "line": row.get("line"),
        "metadata": metadata,
    }


def _symbol_or_fallback_node(store: GraphStore, qname: str) -> dict[str, Any]:
    symbol = store.find_symbol(qname)
    if symbol:
        return {
            "id": _symbol_id(symbol.qualified_name),
            "label": symbol.name,
            "kind": symbol.kind,
            "file_path": symbol.file_path,
            "start_line": symbol.start_line,
            "end_line": symbol.end_line,
            "metadata": {
                "qualified_name": symbol.qualified_name,
                "signature": symbol.signature or "",
            },
        }
    return {
        "id": _qname_to_node_id(qname),
        "label": qname.rsplit(".", 1)[-1] if qname else "?",
        "kind": "symbol",
        "file_path": "",
        "metadata": {"qualified_name": qname},
    }


def _symbol_id(qname: str) -> str:
    return f"symbol:{qname}"


def _file_id(path: str) -> str:
    return f"file:{path.replace(chr(92), '/')}"


def _qname_to_node_id(qname: str) -> str:
    if not qname:
        return "symbol:?"
    if qname.startswith(("file:", "symbol:", "folder:", "process:")):
        return qname
    if qname.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")) and "/" in qname:
        return _file_id(qname)
    return _symbol_id(qname)


def _attach_roles(store: GraphStore, nodes: dict[str, dict[str, Any]]) -> None:
    roles_by_node = store.object_roles_by_node()
    for node_id, node in nodes.items():
        roles = roles_by_node.get(node_id)
        if not roles:
            continue
        primary = roles[0]
        node["role"] = primary["role"]
        node["role_confidence"] = primary["confidence"]
        metadata = node.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            node["metadata"] = metadata
        metadata["roles"] = roles
        metadata["role"] = primary["role"]
        metadata["role_confidence"] = primary["confidence"]
