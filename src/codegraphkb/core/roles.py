"""Object-role inference for CodeGraphKB graph nodes.

Roles sit above raw syntax kinds. A symbol can be a ``function`` while also
being inferred as a service, repository, handler, test, and so on. The
classifier intentionally uses multiple auditable signals instead of treating
tree-sitter or AST syntax as semantic truth.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from codegraphkb.core.store import GraphStore

ROLE_CONTROLLER = "controller"
ROLE_HANDLER = "handler"
ROLE_SERVICE = "service"
ROLE_REPOSITORY = "repository"
ROLE_MODEL = "model"
ROLE_SCHEMA = "schema"
ROLE_VALIDATOR = "validator"
ROLE_MIDDLEWARE = "middleware"
ROLE_CLIENT = "client"
ROLE_EXTERNAL_SERVICE = "external_service"
ROLE_CONFIG = "config"
ROLE_TEST = "test"
ROLE_FIXTURE = "fixture"
ROLE_JOB = "job"
ROLE_UTILITY = "utility"

SIGNAL_PATH = "path"
SIGNAL_NAME = "name"
SIGNAL_DECORATOR = "decorator"
SIGNAL_FRAMEWORK = "framework"
SIGNAL_SEMANTIC_TYPE = "semantic_type"
SIGNAL_GRAPH_POSITION = "graph_position"
SIGNAL_IMPORT = "import"
SIGNAL_DOCSTRING = "docstring"

_ROUTE_EDGE_TYPES = {"HANDLES_ROUTE", "ROUTES_TO", "ROUTE_HANDLED_BY"}
_EXTERNAL_EDGE_TYPES = {"FETCHES", "CALLS_EXTERNAL"}
_TEST_EDGE_TYPES = {"TESTS", "TESTS_SYMBOL", "COVERS_ROUTE", "COVERS_PROCESS"}
_DB_EDGE_TYPES = {"QUERIES", "MODEL_USED_BY"}


@dataclass(frozen=True)
class RoleSignal:
    source: str
    value: str
    confidence: float
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        data = {
            "source": self.source,
            "value": self.value,
            "confidence": round(float(self.confidence), 4),
            "reason": self.reason,
        }
        if self.metadata:
            data["metadata"] = self.metadata
        return data


@dataclass(frozen=True)
class ObjectRole:
    node_id: str
    role: str
    confidence: float
    reason: str
    signals: list[RoleSignal]

    @property
    def id(self) -> str:
        return f"{self.node_id}|{self.role}"


def classify_roles(store: GraphStore) -> list[ObjectRole]:
    """Infer auditable object roles for symbols in the current store."""
    symbols = _symbol_rows(store)
    edges = _edge_rows(store)
    by_qname = {row["qualified_name"]: row for row in symbols}
    incoming, outgoing = _edge_indexes(edges)

    candidates: dict[str, dict[str, list[RoleSignal]]] = {}

    for row in symbols:
        _classify_from_kind_path_name(row, candidates)
        _classify_from_metadata(row, candidates)

    _classify_from_framework_edges(edges, by_qname, candidates)
    _classify_from_graph_position(symbols, incoming, outgoing, candidates)

    roles: list[ObjectRole] = []
    for node_id, role_map in candidates.items():
        for role, signals in role_map.items():
            if not signals:
                continue
            confidence = _combine_confidence(signals)
            if confidence < 0.55:
                continue
            roles.append(
                ObjectRole(
                    node_id=node_id,
                    role=role,
                    confidence=confidence,
                    reason=_summarize_reason(signals),
                    signals=sorted(signals, key=lambda s: s.confidence, reverse=True),
                )
            )
    roles.sort(key=lambda r: (r.node_id, -r.confidence, r.role))
    return roles


def object_roles_to_rows(
    roles: list[ObjectRole],
    *,
    created_at: str | None = None,
) -> list[tuple]:
    """Convert roles to DB rows accepted by ``GraphStore.replace_object_roles``."""
    at = created_at or datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    for role in roles:
        rows.append(
            (
                role.id,
                role.node_id,
                role.role,
                round(float(role.confidence), 4),
                role.reason,
                json.dumps([signal.as_dict() for signal in role.signals], sort_keys=True),
                at,
            )
        )
    return rows


def _classify_from_kind_path_name(
    row: dict[str, Any],
    candidates: dict[str, dict[str, list[RoleSignal]]],
) -> None:
    node_id = _node_id(row)
    path = _norm(row.get("file_path"))
    name_raw = str(row.get("name") or "")
    qname_raw = str(row.get("qualified_name") or "")
    kind = _norm(row.get("kind"))
    haystack = f"{path} {name_raw} {qname_raw}"

    if kind == "route":
        _add(candidates, node_id, ROLE_HANDLER, SIGNAL_FRAMEWORK, kind, 0.78,
             "framework route node is an application entrypoint")
    if kind in {"test", "test_block"}:
        _add(candidates, node_id, ROLE_TEST, SIGNAL_FRAMEWORK, kind, 0.9,
             "test symbol kind")
    if kind == "fixture":
        _add(candidates, node_id, ROLE_FIXTURE, SIGNAL_FRAMEWORK, kind, 0.9,
             "fixture symbol kind")
    if kind in {"model", "orm_model", "database_table"}:
        _add(candidates, node_id, ROLE_MODEL, SIGNAL_FRAMEWORK, kind, 0.86,
             "framework model/table symbol kind")
    if kind in {"env_var", "config_key"}:
        _add(candidates, node_id, ROLE_CONFIG, SIGNAL_FRAMEWORK, kind, 0.86,
             "configuration symbol kind")
    if kind == "api_consumer":
        _add(candidates, node_id, ROLE_CLIENT, SIGNAL_FRAMEWORK, kind, 0.84,
             "API consumer symbol kind")

    path_roles = [
        (ROLE_CONTROLLER, ("controller", "controllers"), 0.7),
        (ROLE_HANDLER, ("route", "routes", "handler", "handlers", "api"), 0.68),
        (ROLE_SERVICE, ("service", "services", "usecase", "usecases"), 0.72),
        (ROLE_REPOSITORY, ("repository", "repositories", "repo", "repos", "dao", "persistence"), 0.74),
        (ROLE_MODEL, ("model", "models", "entity", "entities"), 0.72),
        (ROLE_SCHEMA, ("schema", "schemas", "dto", "dtos", "types"), 0.68),
        (ROLE_VALIDATOR, ("validator", "validators", "validation"), 0.68),
        (ROLE_MIDDLEWARE, ("middleware", "middlewares"), 0.76),
        (ROLE_CLIENT, ("client", "clients", "sdk", "api_client"), 0.7),
        (ROLE_CONFIG, ("config", "configs", "settings", "env"), 0.68),
        (ROLE_TEST, ("test", "tests", "__tests__", "spec"), 0.78),
        (ROLE_FIXTURE, ("fixture", "fixtures", "conftest"), 0.78),
        (ROLE_JOB, ("job", "jobs", "task", "tasks", "worker", "workers", "queues"), 0.68),
    ]
    for role, needles, confidence in path_roles:
        if _path_has(path, needles):
            _add(candidates, node_id, role, SIGNAL_PATH, path, confidence,
                 f"path suggests {role}")

    name_roles = [
        (ROLE_CONTROLLER, ("controller",), 0.68),
        (ROLE_HANDLER, ("handler", "route", "endpoint", "view"), 0.66),
        (ROLE_SERVICE, ("service", "usecase", "manager"), 0.68),
        (ROLE_REPOSITORY, ("repository", "repo", "dao"), 0.7),
        (ROLE_MODEL, ("model", "entity"), 0.66),
        (ROLE_SCHEMA, ("schema", "dto", "payload", "request", "response"), 0.62),
        (ROLE_VALIDATOR, ("validator", "validate", "validation"), 0.68),
        (ROLE_MIDDLEWARE, ("middleware",), 0.72),
        (ROLE_CLIENT, ("client", "adapter", "provider"), 0.64),
        (ROLE_EXTERNAL_SERVICE, ("external", "thirdparty", "gateway"), 0.62),
        (ROLE_CONFIG, ("config", "settings", "env"), 0.62),
        (ROLE_TEST, ("test", "spec", "should"), 0.7),
        (ROLE_FIXTURE, ("fixture",), 0.72),
        (ROLE_JOB, ("job", "task", "worker", "queue", "consumer"), 0.64),
    ]
    for role, needles, confidence in name_roles:
        if _contains_wordish(haystack, needles):
            _add(candidates, node_id, role, SIGNAL_NAME, row.get("name") or "", confidence,
                 f"name suggests {role}")


def _classify_from_metadata(
    row: dict[str, Any],
    candidates: dict[str, dict[str, list[RoleSignal]]],
) -> None:
    node_id = _node_id(row)
    blob = _metadata_blob(row)

    decorators = [
        ("fastapi route decorator", ROLE_HANDLER, ("@app.get", "@app.post", "@router.get", "@router.post", "fastapi"), 0.86),
        ("flask route decorator", ROLE_HANDLER, ("@app.route", "@blueprint.route", "flask"), 0.84),
        ("django view/url metadata", ROLE_HANDLER, ("django", "urlpatterns", "path("), 0.78),
        ("pytest fixture decorator", ROLE_FIXTURE, ("pytest.fixture", "@fixture"), 0.88),
        ("celery task decorator", ROLE_JOB, ("celery", "@shared_task", "@app.task"), 0.84),
        ("middleware decorator", ROLE_MIDDLEWARE, ("middleware", "@app.middleware"), 0.82),
    ]
    for reason, role, needles, confidence in decorators:
        if any(needle in blob for needle in needles):
            _add(candidates, node_id, role, SIGNAL_DECORATOR, reason, confidence, reason)

    semantic_checks = [
        (ROLE_SCHEMA, ("pydantic", "basemodel", "zod", "yup", "schema"), 0.76),
        (ROLE_MODEL, ("sqlalchemy", "django.db.models", "prisma", "model"), 0.76),
        (ROLE_CLIENT, ("axios", "fetch", "requests", "httpx", "aiohttp"), 0.72),
        (ROLE_EXTERNAL_SERVICE, ("openai", "stripe", "twilio", "s3", "redis", "http"), 0.64),
        (ROLE_CONFIG, ("os.environ", "process.env", "dotenv", "settings"), 0.72),
    ]
    for role, needles, confidence in semantic_checks:
        if any(needle in blob for needle in needles):
            _add(candidates, node_id, role, SIGNAL_SEMANTIC_TYPE, ",".join(needles), confidence,
                 f"metadata/type/imports suggest {role}")


def _classify_from_framework_edges(
    edges: list[dict[str, Any]],
    by_qname: dict[str, dict[str, Any]],
    candidates: dict[str, dict[str, list[RoleSignal]]],
) -> None:
    for edge in edges:
        edge_type = str(edge.get("edge_type") or "")
        src = str(edge.get("src_qname") or "")
        dst = str(edge.get("dst_qname") or edge.get("dst_name") or "")
        if edge_type in _ROUTE_EDGE_TYPES:
            if dst in by_qname:
                _add(candidates, f"symbol:{dst}", ROLE_HANDLER, SIGNAL_FRAMEWORK, edge_type, 0.88,
                     f"{edge_type} marks this symbol as a route handler")
            if src in by_qname and by_qname[src].get("kind") != "route":
                _add(candidates, f"symbol:{src}", ROLE_HANDLER, SIGNAL_FRAMEWORK, edge_type, 0.8,
                     f"{edge_type} marks this symbol as route-adjacent")
        if edge_type in _DB_EDGE_TYPES and src in by_qname:
            _add(candidates, f"symbol:{src}", ROLE_REPOSITORY, SIGNAL_FRAMEWORK, edge_type, 0.84,
                 f"{edge_type} indicates database/model access")
        if edge_type in _EXTERNAL_EDGE_TYPES and src in by_qname:
            _add(candidates, f"symbol:{src}", ROLE_CLIENT, SIGNAL_FRAMEWORK, edge_type, 0.82,
                 f"{edge_type} indicates outbound API/client behavior")
        if edge_type in _TEST_EDGE_TYPES and src in by_qname:
            _add(candidates, f"symbol:{src}", ROLE_TEST, SIGNAL_FRAMEWORK, edge_type, 0.84,
                 f"{edge_type} connects this symbol to tests")


def _classify_from_graph_position(
    symbols: list[dict[str, Any]],
    incoming: dict[str, list[dict[str, Any]]],
    outgoing: dict[str, list[dict[str, Any]]],
    candidates: dict[str, dict[str, list[RoleSignal]]],
) -> None:
    for row in symbols:
        qname = row["qualified_name"]
        node_id = _node_id(row)
        inc = incoming.get(qname, [])
        out = outgoing.get(qname, [])

        called_by_handler = any(
            edge.get("edge_type") in {"CALLS", "ROUTES_TO", "HANDLES_ROUTE"}
            and _has_role(candidates, edge.get("src_qname"), ROLE_HANDLER)
            for edge in inc
        )
        calls_repository = any(
            edge.get("edge_type") in {"CALLS", "QUERIES", "MODEL_USED_BY"}
            and (
                _has_role(candidates, edge.get("dst_qname"), ROLE_REPOSITORY)
                or str(edge.get("edge_type")) in _DB_EDGE_TYPES
            )
            for edge in out
        )
        calls_external = any(str(edge.get("edge_type")) in _EXTERNAL_EDGE_TYPES for edge in out)
        tested_only = bool(inc) and all(str(edge.get("edge_type")) in _TEST_EDGE_TYPES for edge in inc)

        if called_by_handler and calls_repository:
            _add(candidates, node_id, ROLE_SERVICE, SIGNAL_GRAPH_POSITION, qname, 0.88,
                 "called by a handler and calls a repository/database edge")
        elif called_by_handler and out and not _has_role(candidates, qname, ROLE_HANDLER):
            _add(candidates, node_id, ROLE_SERVICE, SIGNAL_GRAPH_POSITION, qname, 0.72,
                 "called by a handler and participates in downstream calls")

        if calls_repository:
            _add(candidates, node_id, ROLE_SERVICE, SIGNAL_GRAPH_POSITION, qname, 0.68,
                 "symbol sits above repository/database access")
        if calls_external and not _has_role(candidates, qname, ROLE_HANDLER):
            _add(candidates, node_id, ROLE_CLIENT, SIGNAL_GRAPH_POSITION, qname, 0.72,
                 "symbol issues outbound API calls")
        if tested_only:
            _add(candidates, node_id, ROLE_TEST, SIGNAL_GRAPH_POSITION, qname, 0.62,
                 "symbol is only connected through test edges")

        incoming_calls = [edge for edge in inc if edge.get("edge_type") == "CALLS"]
        outgoing_calls = [edge for edge in out if edge.get("edge_type") == "CALLS"]
        if len(incoming_calls) >= 5 and not outgoing_calls:
            _add(candidates, node_id, ROLE_UTILITY, SIGNAL_GRAPH_POSITION, qname, 0.56,
                 "many callers and few downstream calls suggest shared utility")


def _add(
    candidates: dict[str, dict[str, list[RoleSignal]]],
    node_id: str,
    role: str,
    source: str,
    value: str,
    confidence: float,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    candidates.setdefault(node_id, {}).setdefault(role, []).append(
        RoleSignal(
            source=source,
            value=str(value or ""),
            confidence=max(0.0, min(0.99, float(confidence))),
            reason=reason,
            metadata=metadata or {},
        )
    )


def _symbol_rows(store: GraphStore) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        "SELECT s.*, f.path AS file_path, f.language AS language "
        "FROM symbols s JOIN files f ON s.file_id = f.id "
        "ORDER BY s.qualified_name"
    ).fetchall()
    return [dict(row) for row in rows]


def _edge_rows(store: GraphStore) -> list[dict[str, Any]]:
    rows = store._conn.execute("SELECT * FROM edges ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def _edge_indexes(
    edges: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    incoming: dict[str, list[dict[str, Any]]] = {}
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        src = edge.get("src_qname")
        dst = edge.get("dst_qname")
        if src:
            outgoing.setdefault(str(src), []).append(edge)
        if dst:
            incoming.setdefault(str(dst), []).append(edge)
    return incoming, outgoing


def _node_id(row: dict[str, Any]) -> str:
    return f"symbol:{row['qualified_name']}"


def _has_role(
    candidates: dict[str, dict[str, list[RoleSignal]]],
    qname: Any,
    role: str,
) -> bool:
    if not qname:
        return False
    return role in candidates.get(f"symbol:{qname}", {})


def _combine_confidence(signals: list[RoleSignal]) -> float:
    product = 1.0
    for signal in signals:
        product *= 1.0 - max(0.0, min(0.99, signal.confidence))
    return round(min(0.98, 1.0 - product), 4)


def _summarize_reason(signals: list[RoleSignal]) -> str:
    top = sorted(signals, key=lambda s: s.confidence, reverse=True)[:3]
    return "; ".join(signal.reason for signal in top)


def _norm(value: Any) -> str:
    return str(value or "").replace("\\", "/").lower()


def _path_has(path: str, needles: tuple[str, ...]) -> bool:
    parts = [p for p in re.split(r"[/_.\\-]+", path) if p]
    return any(needle in parts or needle in path for needle in needles)


def _contains_wordish(value: str, needles: tuple[str, ...]) -> bool:
    value = _split_wordish(value)
    return any(needle in value for needle in needles)


def _split_wordish(value: str) -> set[str]:
    chunks = re.split(r"[^a-zA-Z0-9]+", value)
    words: set[str] = set()
    for chunk in chunks:
        if not chunk:
            continue
        words.add(chunk.lower())
        for piece in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", chunk):
            if piece:
                words.add(piece.lower())
    return words


def _metadata_blob(row: dict[str, Any]) -> str:
    pieces: list[Any] = [
        row.get("signature"),
        row.get("docstring"),
        row.get("return_type"),
        row.get("declared_type"),
        row.get("semantic_backend"),
        row.get("parser_backend"),
    ]
    for key in ("extras", "metadata_json"):
        raw = row.get(key)
        try:
            pieces.append(json.loads(raw) if isinstance(raw, str) else raw)
        except (TypeError, json.JSONDecodeError):
            pieces.append(raw)
    try:
        return json.dumps(pieces, sort_keys=True).lower()
    except (TypeError, ValueError):
        return " ".join(str(p) for p in pieces).lower()


def role_counts(roles: list[ObjectRole]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for role in roles:
        counts[role.role] = counts.get(role.role, 0) + 1
    return counts
