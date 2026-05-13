"""Graph export helpers for static visualization and tool-agnostic JSON."""
from __future__ import annotations

import json
import os
from typing import Any

from codegraphkb.core.graph_schema import GRAPH_SCHEMA_VERSION
from codegraphkb.core.processes import get_process, list_processes
from codegraphkb.core.store import GraphStore


VIEW_FULL = "full"
VIEW_REPO = "repo"
VIEW_SYMBOLS = "symbols"
VIEW_CALLS = "calls"
VIEW_PROCESSES = "processes"
VIEW_FRAMEWORK = "framework"

VIEWS = (
    VIEW_FULL,
    VIEW_REPO,
    VIEW_SYMBOLS,
    VIEW_CALLS,
    VIEW_PROCESSES,
    VIEW_FRAMEWORK,
)

_CALL_EDGE_TYPES = (
    "CALLS",
    "ACCESSES",
    "INSTANTIATES",
    "EXTENDS",
    "IMPLEMENTS",
    "HAS_METHOD",
)

_FRAMEWORK_EDGE_TYPES = (
    "HANDLES_ROUTE",
    "ROUTES_TO",
    "ROUTE_HANDLED_BY",
    "TESTS",
    "TESTS_SYMBOL",
    "QUERIES",
    "FETCHES",
    "CALLS_EXTERNAL",
    "USES_MIDDLEWARE",
    "MODEL_USED_BY",
    "READS_ENV_VAR",
)

_FRAMEWORK_KINDS = (
    "route",
    "test_block",
    "model",
    "api_consumer",
    "env_var",
    "component",
)

_CALL_NODE_KINDS = (
    "function",
    "method",
    "constructor",
    "class",
    "interface",
    "type_alias",
    "component",
    "module",
)


def export_graph(
    store: GraphStore,
    *,
    view: str = VIEW_FULL,
    repo_path: str | None = None,
    max_nodes: int | None = None,
    max_edges: int | None = None,
) -> dict[str, Any]:
    """Return a graph payload with metadata/nodes/edges for a view."""
    if view not in VIEWS:
        raise ValueError(f"Unknown view `{view}`. Valid views: {', '.join(VIEWS)}")

    if view == VIEW_PROCESSES:
        return _export_processes_view(
            store,
            repo_path=repo_path,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    files = _file_rows(store)
    symbols = _symbol_rows(store)

    if view == VIEW_REPO:
        folder_nodes = _folder_nodes_for(files)
        nodes.update(folder_nodes)
        for file_row in files:
            file_node = _file_node(file_row)
            nodes[file_node["id"]] = file_node
            folder_id = _folder_id_for_file(file_row["path"])
            if folder_id and folder_id in nodes:
                edges.append(_contains_edge(folder_id, file_node["id"]))

    elif view == VIEW_SYMBOLS:
        for file_row in files:
            file_node = _file_node(file_row)
            nodes[file_node["id"]] = file_node
        for sym_row in symbols:
            sym_node = _symbol_node(sym_row)
            nodes[sym_node["id"]] = sym_node
        for pair in _file_symbol_pairs(store):
            file_id = _file_id(pair["file_path"])
            symbol_id = _symbol_id(pair["qualified_name"])
            if file_id in nodes and symbol_id in nodes:
                edges.append(_contains_edge(file_id, symbol_id))

    elif view == VIEW_CALLS:
        for sym_row in symbols:
            if sym_row["kind"] in _CALL_NODE_KINDS:
                sym_node = _symbol_node(sym_row)
                nodes[sym_node["id"]] = sym_node
        _append_db_edges(store, nodes, edges, _CALL_EDGE_TYPES)

    elif view == VIEW_FRAMEWORK:
        by_qname = {s["qualified_name"]: s for s in symbols}
        for sym_row in symbols:
            if sym_row["kind"] in _FRAMEWORK_KINDS:
                sym_node = _symbol_node(sym_row)
                nodes[sym_node["id"]] = sym_node
        for edge_row in _edge_rows(store, edge_types=_FRAMEWORK_EDGE_TYPES):
            src_id = _qname_to_node_id(edge_row["src_qname"])
            dst_qname = edge_row["dst_qname"] or edge_row["dst_name"]
            dst_id = _qname_to_node_id(dst_qname)
            src_qname = edge_row["src_qname"]
            if src_id not in nodes and src_qname in by_qname:
                nodes[src_id] = _symbol_node(by_qname[src_qname])
            if dst_id not in nodes and dst_qname in by_qname:
                nodes[dst_id] = _symbol_node(by_qname[dst_qname])
            if src_id in nodes and dst_id in nodes:
                edge = _edge_to_dict(edge_row)
                edge["source"] = src_id
                edge["target"] = dst_id
                edges.append(edge)

    else:  # VIEW_FULL
        for file_row in files:
            file_node = _file_node(file_row)
            nodes[file_node["id"]] = file_node
        for sym_row in symbols:
            sym_node = _symbol_node(sym_row)
            nodes[sym_node["id"]] = sym_node
        for pair in _file_symbol_pairs(store):
            file_id = _file_id(pair["file_path"])
            symbol_id = _symbol_id(pair["qualified_name"])
            if file_id in nodes and symbol_id in nodes:
                edges.append(_contains_edge(file_id, symbol_id))
        _append_db_edges(store, nodes, edges, edge_types=None)

    if max_nodes is not None and len(nodes) > max_nodes:
        nodes = _trim_nodes(nodes, max_nodes)
        allowed = set(nodes)
        edges = [e for e in edges if e["source"] in allowed and e["target"] in allowed]

    if max_edges is not None and len(edges) > max_edges:
        edges = sorted(
            edges,
            key=lambda e: (-float(e.get("confidence", 0.0)), int(e.get("precision_level", 1))),
        )[:max_edges]

    _attach_roles(store, nodes)
    _attach_parameters(store, nodes)

    return {
        "metadata": _metadata(store, view, repo_path, len(nodes), len(edges)),
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def _append_db_edges(
    store: GraphStore,
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    edge_types: tuple[str, ...] | None,
) -> None:
    for row in _edge_rows(store, edge_types=edge_types):
        edge = _edge_to_dict(row)
        source_id = _qname_to_node_id(edge["source"])
        target_id = _qname_to_node_id(edge["target"])
        if source_id not in nodes or target_id not in nodes:
            continue
        edge["source"] = source_id
        edge["target"] = target_id
        edges.append(edge)


def _export_processes_view(
    store: GraphStore,
    *,
    repo_path: str | None,
    max_nodes: int | None,
    max_edges: int | None,
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for summary in list_processes(store):
        proc = get_process(store, summary["id"])
        if proc is None:
            continue

        proc_node_id = f"process:{proc['id']}"
        nodes[proc_node_id] = {
            "id": proc_node_id,
            "label": proc["label"],
            "kind": "process",
            "file_path": "",
            "metadata": {
                "process_type": proc["process_type"],
                "confidence": proc["confidence"],
                "step_count": proc["step_count"],
                "entrypoint": proc["entrypoint_id"],
                "terminal": proc["terminal_id"],
                **(proc.get("metadata") or {}),
            },
        }

        for step in proc.get("steps", []):
            src_id = _qname_to_node_id(step["src_qname"])
            dst_id = _qname_to_node_id(step["dst_qname"])
            if src_id not in nodes:
                nodes[src_id] = _symbol_or_fallback_node(store, step["src_qname"])
            if dst_id not in nodes:
                nodes[dst_id] = _symbol_or_fallback_node(store, step["dst_qname"])

            step_meta = step.get("metadata") or {}
            step_type = step_meta.get("edge_type", "STEP_IN_PROCESS")
            edges.append(
                {
                    "id": f"step:{proc['id']}:{step['step']}",
                    "source": src_id,
                    "target": dst_id,
                    "type": step_type,
                    "confidence": float(step["confidence"]),
                    "precision_level": int(step_meta.get("precision_level", 3)),
                    "extraction_source": "process-builder",
                    "reason": f"step {step['step']} of {proc['id']}",
                    "line": None,
                    "metadata": {
                        "process_id": proc["id"],
                        "process_type": proc["process_type"],
                        "step": step["step"],
                        **step_meta,
                    },
                }
            )
            edges.append(
                {
                    "id": f"member:{proc['id']}:{step['step']}:{step['src_qname']}",
                    "source": proc_node_id,
                    "target": src_id,
                    "type": "MEMBER_OF",
                    "confidence": float(proc["confidence"]),
                    "precision_level": 3,
                    "extraction_source": "process-builder",
                    "reason": "process member",
                    "line": None,
                    "metadata": {
                        "process_id": proc["id"],
                        "step": step["step"],
                    },
                }
            )

    if max_nodes is not None and len(nodes) > max_nodes:
        nodes = _trim_nodes(nodes, max_nodes)
        allowed = set(nodes)
        edges = [e for e in edges if e["source"] in allowed and e["target"] in allowed]
    if max_edges is not None and len(edges) > max_edges:
        edges = edges[:max_edges]

    _attach_roles(store, nodes)
    _attach_parameters(store, nodes)

    return {
        "metadata": _metadata(store, VIEW_PROCESSES, repo_path, len(nodes), len(edges)),
        "nodes": list(nodes.values()),
        "edges": edges,
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
    label = (qname or "?").rsplit(".", 1)[-1]
    return {
        "id": _qname_to_node_id(qname),
        "label": label,
        "kind": "symbol",
        "file_path": "",
        "metadata": {"qualified_name": qname},
    }


def _metadata(
    store: GraphStore,
    view: str,
    repo_path: str | None,
    node_count: int,
    edge_count: int,
) -> dict[str, Any]:
    return {
        "repo_path": repo_path or store.get_meta("repo_path") or "",
        "view": view,
        "schema_version": GRAPH_SCHEMA_VERSION,
        "schema_version_indexed": store.get_meta("schema_version") or "",
        "node_count": node_count,
        "edge_count": edge_count,
        "indexed_at": store.get_meta("last_indexed_at") or "",
    }


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


def _attach_parameters(store: GraphStore, nodes: dict[str, dict[str, Any]]) -> None:
    params_by_owner = store.parameters_by_owner()
    for node in nodes.values():
        metadata = node.setdefault("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            node["metadata"] = metadata
        qname = metadata.get("qualified_name")
        if not qname:
            node_id = str(node.get("id") or "")
            qname = node_id.split(":", 1)[1] if node_id.startswith("symbol:") else ""
        params = params_by_owner.get(str(qname))
        if not params:
            continue
        metadata["parameters"] = params
        node["parameters"] = params


def _file_rows(store: GraphStore) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        "SELECT id, path, language, hash, size_bytes FROM files ORDER BY path"
    ).fetchall()
    return [dict(r) for r in rows]


def _symbol_rows(
    store: GraphStore,
    *,
    kinds: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    if kinds:
        placeholders = ",".join("?" * len(kinds))
        rows = store._conn.execute(
            "SELECT s.*, f.path AS file_path "
            "FROM symbols s JOIN files f ON s.file_id = f.id "
            f"WHERE s.kind IN ({placeholders}) "
            "ORDER BY s.qualified_name",
            kinds,
        ).fetchall()
    else:
        rows = store._conn.execute(
            "SELECT s.*, f.path AS file_path "
            "FROM symbols s JOIN files f ON s.file_id = f.id "
            "ORDER BY s.qualified_name"
        ).fetchall()
    return [dict(r) for r in rows]


def _file_symbol_pairs(store: GraphStore) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        "SELECT s.qualified_name, f.path AS file_path "
        "FROM symbols s JOIN files f ON s.file_id = f.id "
        "ORDER BY f.path, s.start_line"
    ).fetchall()
    return [dict(r) for r in rows]


def _edge_rows(
    store: GraphStore,
    *,
    edge_types: tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    if edge_types is None:
        rows = store._conn.execute(
            "SELECT * FROM edges WHERE edge_type != 'STEP_IN_PROCESS' ORDER BY id"
        ).fetchall()
    else:
        placeholders = ",".join("?" * len(edge_types))
        rows = store._conn.execute(
            f"SELECT * FROM edges WHERE edge_type IN ({placeholders}) ORDER BY id",
            edge_types,
        ).fetchall()
    return [dict(r) for r in rows]


def _contains_edge(source: str, target: str) -> dict[str, Any]:
    return {
        "id": f"contains:{source}->{target}",
        "source": source,
        "target": target,
        "type": "CONTAINS",
        "confidence": 1.0,
        "precision_level": 1,
        "extraction_source": "scanner",
        "reason": "file containment",
        "line": None,
        "metadata": {"extraction_source": "scanner"},
    }


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


def _file_node(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": _file_id(row["path"]),
        "label": os.path.basename(row["path"]),
        "kind": "file",
        "file_path": row["path"],
        "metadata": {
            "language": row["language"],
            "size_bytes": int(row.get("size_bytes") or 0),
        },
    }


def _symbol_node(row: dict[str, Any]) -> dict[str, Any]:
    extras = {}
    if row.get("extras"):
        try:
            extras = json.loads(row["extras"])
        except (TypeError, ValueError):
            extras = {}
    return {
        "id": _symbol_id(row["qualified_name"]),
        "label": row["name"],
        "kind": row["kind"],
        "file_path": row.get("file_path") or "",
        "start_line": int(row.get("start_line") or 0),
        "end_line": int(row.get("end_line") or 0),
        "metadata": {
            "qualified_name": row["qualified_name"],
            "signature": row.get("signature") or "",
            "return_type": row.get("return_type") or "",
            "declared_type": row.get("declared_type") or "",
            "parser_backend": row.get("parser_backend") or "",
            "semantic_backend": row.get("semantic_backend") or "",
            "is_exported": bool(row.get("is_exported")),
            "extras": extras,
        },
    }


def _folder_nodes_for(file_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    folders: dict[str, dict[str, Any]] = {}
    for row in file_rows:
        parts = row["path"].replace("\\", "/").split("/")
        for depth in range(1, len(parts)):
            folder_path = "/".join(parts[:depth])
            if not folder_path:
                continue
            folder_id = _folder_id(folder_path)
            if folder_id in folders:
                continue
            folders[folder_id] = {
                "id": folder_id,
                "label": parts[depth - 1] or "/",
                "kind": "folder",
                "file_path": folder_path,
                "metadata": {"folder_path": folder_path},
            }
    return folders


def _folder_id_for_file(file_path: str) -> str | None:
    parts = file_path.replace("\\", "/").rsplit("/", 1)
    if len(parts) < 2 or not parts[0]:
        return None
    return _folder_id(parts[0])


def _trim_nodes(nodes: dict[str, dict[str, Any]], limit: int) -> dict[str, dict[str, Any]]:
    priority = {
        "process": 0,
        "route": 1,
        "test_block": 1,
        "model": 1,
        "api_consumer": 1,
        "folder": 2,
        "file": 2,
        "function": 3,
        "method": 3,
        "class": 4,
        "interface": 4,
        "type_alias": 5,
        "variable": 6,
    }
    ranked = sorted(
        nodes.items(),
        key=lambda item: (priority.get(item[1].get("kind", ""), 9), item[0]),
    )
    return dict(ranked[:limit])


def _file_id(path: str) -> str:
    return f"file:{path.replace(chr(92), '/')}"


def _folder_id(path: str) -> str:
    return f"folder:{path.replace(chr(92), '/')}"


def _symbol_id(qname: str) -> str:
    return f"symbol:{qname}"


def _qname_to_node_id(qname: str) -> str:
    if not qname:
        return "symbol:?"
    if qname.startswith(("file:", "symbol:", "folder:", "process:")):
        return qname
    if qname.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")) and "/" in qname:
        return _file_id(qname)
    return _symbol_id(qname)
