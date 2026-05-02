"""Neo4j export helpers.

The exporter intentionally consumes the same tool-agnostic graph payload used
by JSON/HTML exports. That makes Neo4j a verification target for what
CodeGraphKB actually extracted, not a second graph model with different rules.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Neo4jRows:
    nodes: list[dict[str, Any]]
    node_label_ids: dict[str, list[str]]
    relationships_by_type: dict[str, list[dict[str, Any]]]
    skipped_edges: int


def push_graph_to_neo4j(
    payload: dict[str, Any],
    *,
    uri: str,
    user: str,
    password: str,
    database: str | None = None,
    clear: bool = True,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Push an exported graph payload to Neo4j over Bolt."""
    try:
        from neo4j import GraphDatabase  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency is optional
        raise RuntimeError(
            "Neo4j export requires the optional neo4j driver. "
            "Install it with: pip install -e \".[neo4j]\""
        ) from exc

    rows = prepare_neo4j_rows(payload)
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            session.run(
                "CREATE CONSTRAINT codegraph_node_id IF NOT EXISTS "
                "FOR (n:CodeGraphNode) REQUIRE n.id IS UNIQUE"
            ).consume()
            if clear:
                session.run("MATCH (n:CodeGraphNode) DETACH DELETE n").consume()

            for batch in _chunks(rows.nodes, batch_size):
                session.run(
                    """
                    UNWIND $rows AS row
                    MERGE (n:CodeGraphNode {id: row.id})
                    SET n += row.props
                    """,
                    rows=batch,
                ).consume()

            for label, ids in sorted(rows.node_label_ids.items()):
                for batch in _chunks(ids, batch_size):
                    session.run(
                        f"""
                        UNWIND $ids AS id
                        MATCH (n:CodeGraphNode {{id: id}})
                        SET n:{label}
                        """,
                        ids=batch,
                    ).consume()

            for rel_type, rel_rows in sorted(rows.relationships_by_type.items()):
                for batch in _chunks(rel_rows, batch_size):
                    session.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (source:CodeGraphNode {{id: row.source}})
                        MATCH (target:CodeGraphNode {{id: row.target}})
                        MERGE (source)-[rel:{rel_type} {{id: row.id}}]->(target)
                        SET rel += row.props
                        """,
                        rows=batch,
                    ).consume()

            db_counts = {
                "nodes": session.run(
                    "MATCH (n:CodeGraphNode) RETURN count(n) AS n"
                ).single()["n"],
                "relationships": session.run(
                    "MATCH (:CodeGraphNode)-[r]->(:CodeGraphNode) RETURN count(r) AS n"
                ).single()["n"],
            }
    finally:
        driver.close()

    node_kinds = Counter(row["props"].get("kind", "unknown") for row in rows.nodes)
    edge_types = Counter()
    for rel_type, rel_rows in rows.relationships_by_type.items():
        edge_types[rel_type] += len(rel_rows)
    return {
        "uri": uri,
        "database": database or "default",
        "clear": clear,
        "input": {
            "nodes": len(payload.get("nodes", [])),
            "edges": len(payload.get("edges", [])),
            "view": (payload.get("metadata") or {}).get("view"),
            "repo_path": (payload.get("metadata") or {}).get("repo_path"),
        },
        "imported": {
            "nodes": len(rows.nodes),
            "relationships": sum(len(v) for v in rows.relationships_by_type.values()),
            "skipped_edges": rows.skipped_edges,
            "node_kinds": dict(sorted(node_kinds.items())),
            "edge_types": dict(sorted(edge_types.items())),
        },
        "database_counts": db_counts,
    }


def prepare_neo4j_rows(payload: dict[str, Any]) -> Neo4jRows:
    """Prepare Neo4j-safe node/relationship rows without opening Neo4j."""
    metadata = payload.get("metadata") or {}
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []

    node_ids: set[str] = set()
    node_rows: list[dict[str, Any]] = []
    label_ids: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        node_id = str(node["id"])
        node_ids.add(node_id)
        kind = str(node.get("kind") or "unknown")
        props = _node_props(node, metadata)
        node_rows.append({"id": node_id, "props": props})
        label_ids[_kind_label(kind)].append(node_id)
        role = str(node.get("role") or props.get("role") or "")
        if role:
            label_ids[_role_label(role)].append(node_id)

    rel_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped_edges = 0
    for edge in edges:
        if not isinstance(edge, dict):
            skipped_edges += 1
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_ids or target not in node_ids:
            skipped_edges += 1
            continue
        rel_type = _relationship_type(str(edge.get("type") or "UNKNOWN"))
        rel_rows[rel_type].append(
            {
                "id": str(edge.get("id") or f"{source}->{target}:{rel_type}"),
                "source": source,
                "target": target,
                "props": _edge_props(edge),
            }
        )

    return Neo4jRows(
        nodes=node_rows,
        node_label_ids=dict(label_ids),
        relationships_by_type=dict(rel_rows),
        skipped_edges=skipped_edges,
    )


def _node_props(node: dict[str, Any], graph_metadata: dict[str, Any]) -> dict[str, Any]:
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    props = {
        "id": str(node.get("id") or ""),
        "label": str(node.get("label") or node.get("id") or ""),
        "kind": str(node.get("kind") or "unknown"),
        "role": str(node.get("role") or metadata.get("role") or ""),
        "file_path": str(node.get("file_path") or ""),
        "repo_path": str(graph_metadata.get("repo_path") or ""),
        "metadata_json": _json(metadata),
    }
    role_confidence = node.get("role_confidence", metadata.get("role_confidence"))
    if role_confidence is not None:
        props["role_confidence"] = float(role_confidence or 0.0)
    if metadata.get("roles") is not None:
        props["roles_json"] = _json(metadata.get("roles"))
    for key in ("start_line", "end_line"):
        value = node.get(key)
        if value is not None:
            props[key] = _int_or_zero(value)
    for key in (
        "qualified_name",
        "signature",
        "return_type",
        "declared_type",
        "parser_backend",
        "semantic_backend",
    ):
        value = metadata.get(key)
        if value is not None:
            props[key] = str(value)
    return props


def _edge_props(edge: dict[str, Any]) -> dict[str, Any]:
    metadata = edge.get("metadata") if isinstance(edge.get("metadata"), dict) else {}
    props = {
        "id": str(edge.get("id") or ""),
        "type": str(edge.get("type") or "UNKNOWN"),
        "confidence": float(edge.get("confidence") or 0.0),
        "precision_level": _int_or_zero(edge.get("precision_level") or 0),
        "extraction_source": str(edge.get("extraction_source") or ""),
        "reason": str(edge.get("reason") or ""),
        "metadata_json": _json(metadata),
    }
    if edge.get("line") is not None:
        props["line"] = _int_or_zero(edge.get("line"))
    return props


def _kind_label(kind: str) -> str:
    parts = _identifier_parts(kind)
    if not parts:
        return "CodeGraphUnknown"
    return "CodeGraph" + "".join(part.capitalize() for part in parts)


def _role_label(role: str) -> str:
    parts = _identifier_parts(role)
    if not parts:
        return "CodeGraphRoleUnknown"
    return "CodeGraphRole" + "".join(part.capitalize() for part in parts)


def _relationship_type(edge_type: str) -> str:
    parts = _identifier_parts(edge_type)
    return "_".join(part.upper() for part in parts) or "UNKNOWN"


def _identifier_parts(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", value)


def _json(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"))


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _chunks(items: list[Any], size: int) -> list[list[Any]]:
    safe_size = max(1, int(size or 500))
    return [items[i : i + safe_size] for i in range(0, len(items), safe_size)]
