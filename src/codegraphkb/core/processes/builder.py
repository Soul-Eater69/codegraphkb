"""Build process traces from the indexed graph.

The builder is intentionally simple:

* Pick an entrypoint (Route, FETCHES caller, or test_block).
* Walk outgoing edges, preferring high-priority types (CALLS first, then
  QUERIES / FETCHES / CALLS_EXTERNAL).
* Stop when the traversal hits a *terminal* edge type (QUERIES, FETCHES,
  CALLS_EXTERNAL), revisits a symbol (cycle), exhausts depth, or runs out of
  outgoing edges with confidence above the threshold.

Each Process records every step it took plus a cumulative confidence score
(geometric mean across step confidences). Persistence is handled separately
in ``persist.py`` so the builder stays pure.
"""
from __future__ import annotations

import math
import re
from typing import Iterable

from codegraphkb.core.processes.types import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MIN_STEP_CONFIDENCE,
    FOLLOW_EDGE_TYPES,
    PROCESS_API_FLOW,
    PROCESS_TEST_FLOW,
    PROCESS_UI_TO_API_FLOW,
    Process,
    ProcessStep,
    TERMINAL_EDGE_TYPES,
)
from codegraphkb.core.store import EdgeRow, GraphStore, SymbolRow


_EDGE_PRIORITY = {edge: idx for idx, edge in enumerate(FOLLOW_EDGE_TYPES)}


def build_processes(
    store: GraphStore,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    min_step_confidence: float = DEFAULT_MIN_STEP_CONFIDENCE,
) -> list[Process]:
    """Return every process the builder could derive from the current graph."""
    processes: list[Process] = []
    seen_ids: set[str] = set()

    for route in store.symbols_by_kind("route"):
        proc = _build_api_flow(
            store, route,
            max_depth=max_depth,
            min_step_confidence=min_step_confidence,
        )
        if proc and proc.id not in seen_ids:
            processes.append(proc)
            seen_ids.add(proc.id)

    for proc in _build_ui_to_api_flows(
        store,
        max_depth=max_depth,
        min_step_confidence=min_step_confidence,
    ):
        if proc.id not in seen_ids:
            processes.append(proc)
            seen_ids.add(proc.id)

    for tb in store.symbols_by_kind("test_block"):
        proc = _build_test_flow(
            store, tb,
            max_depth=max_depth,
            min_step_confidence=min_step_confidence,
        )
        if proc and proc.id not in seen_ids:
            processes.append(proc)
            seen_ids.add(proc.id)

    return processes


# --------------------------------------------------------------------------
# API flow: Route -> handler -> CALLS chain -> terminal
# --------------------------------------------------------------------------

def _build_api_flow(store: GraphStore, route: SymbolRow,
                    *, max_depth: int, min_step_confidence: float) -> Process | None:
    handles = store.outgoing(route.qualified_name, ["HANDLES_ROUTE"])
    handles = [e for e in handles if e.confidence >= min_step_confidence]
    if not handles:
        return None
    handler_edge = handles[0]
    handler_qname = _resolve_dst(store, handler_edge)
    if not handler_qname:
        return None

    visited = {route.qualified_name, handler_qname}
    steps: list[ProcessStep] = [ProcessStep(
        step=1,
        src_qname=route.qualified_name,
        dst_qname=handler_qname,
        edge_type="HANDLES_ROUTE",
        confidence=handler_edge.confidence,
        metadata={
            "stage": "route_to_handler",
            "http_method": (handler_edge.metadata or {}).get("http_method", ""),
            "path": (handler_edge.metadata or {}).get("path", ""),
        },
    )]

    middleware_edges = store.outgoing(route.qualified_name, ["USES_MIDDLEWARE"])
    middleware_qnames = [
        e.dst_qname or e.dst_name for e in middleware_edges
    ] if middleware_edges else []

    _walk_chain(store, handler_qname, visited, steps,
                max_depth=max_depth,
                min_step_confidence=min_step_confidence)

    terminal = steps[-1].dst_qname
    confidence = _aggregate_confidence(steps)
    label = _route_label(route)
    proc_id = _slug(f"{PROCESS_API_FLOW}::{route.qualified_name}")
    return Process(
        id=proc_id,
        label=label,
        process_type=PROCESS_API_FLOW,
        entrypoint_id=route.qualified_name,
        terminal_id=terminal,
        steps=steps,
        confidence=confidence,
        metadata={
            "framework": (route.extras or {}).get("framework", ""),
            "http_method": (route.extras or {}).get("http_method", ""),
            "path": (route.extras or {}).get("path", ""),
            "handler": (route.extras or {}).get("handler", ""),
            "middleware": middleware_qnames,
            "language": "typescript",
        },
    )


def _route_label(route: SymbolRow) -> str:
    method = (route.extras or {}).get("http_method") or ""
    path = (route.extras or {}).get("path") or ""
    if method and path:
        return f"{method} {path}"
    return route.name


# --------------------------------------------------------------------------
# UI-to-API flow: caller -> FETCHES -> api_consumer (optional Route link)
# --------------------------------------------------------------------------

def _build_ui_to_api_flows(store: GraphStore, *, max_depth: int,
                           min_step_confidence: float) -> list[Process]:
    rows = store._conn.execute(
        "SELECT src_qname, dst_qname, dst_name, edge_type, confidence, "
        "extraction_source, line, column, precision_level, reason, "
        "metadata_json FROM edges WHERE edge_type='FETCHES' "
        "ORDER BY src_qname, line"
    ).fetchall()
    routes_by_path = _index_routes_by_path(store)
    processes: list[Process] = []
    seen: set[str] = set()
    for row in rows:
        edge = _row_to_edge(row)
        if edge.confidence < min_step_confidence:
            continue
        caller = edge.src_qname
        consumer = edge.dst_qname or edge.dst_name
        if not consumer:
            continue
        meta = edge.metadata or {}
        method = meta.get("http_method", "")
        url = meta.get("url", "")
        proc_id = _slug(f"{PROCESS_UI_TO_API_FLOW}::{caller}::{method}::{url}")
        if proc_id in seen:
            continue
        seen.add(proc_id)
        steps: list[ProcessStep] = [ProcessStep(
            step=1,
            src_qname=caller,
            dst_qname=consumer,
            edge_type="FETCHES",
            confidence=edge.confidence,
            metadata={
                "stage": "client_to_consumer",
                "http_method": method,
                "url": url,
                "client": meta.get("client", ""),
            },
        )]
        # Optional: link to a matching Route in the same repo.
        matched_route = _match_route(routes_by_path, method, url)
        if matched_route is not None:
            steps.append(ProcessStep(
                step=2,
                src_qname=consumer,
                dst_qname=matched_route.qualified_name,
                edge_type="ROUTES_TO",
                confidence=0.8,
                metadata={
                    "stage": "consumer_to_route",
                    "matched_path": (matched_route.extras or {}).get("path", ""),
                },
            ))
            # Continue walking from the matched route's handler if available.
            handler_edges = store.outgoing(
                matched_route.qualified_name, ["HANDLES_ROUTE"],
            )
            if handler_edges:
                handler_qname = _resolve_dst(store, handler_edges[0])
                if handler_qname:
                    steps.append(ProcessStep(
                        step=len(steps) + 1,
                        src_qname=matched_route.qualified_name,
                        dst_qname=handler_qname,
                        edge_type="HANDLES_ROUTE",
                        confidence=handler_edges[0].confidence,
                        metadata={"stage": "route_to_handler"},
                    ))
                    visited = {caller, consumer,
                               matched_route.qualified_name, handler_qname}
                    _walk_chain(store, handler_qname, visited, steps,
                                max_depth=max_depth,
                                min_step_confidence=min_step_confidence)

        terminal = steps[-1].dst_qname
        confidence = _aggregate_confidence(steps)
        label = f"{(method or 'CALL').upper()} {url}".strip()
        processes.append(Process(
            id=proc_id,
            label=label or caller,
            process_type=PROCESS_UI_TO_API_FLOW,
            entrypoint_id=caller,
            terminal_id=terminal,
            steps=steps,
            confidence=confidence,
            metadata={
                "client": meta.get("client", ""),
                "http_method": method,
                "url": url,
                "matched_route_qname": (
                    matched_route.qualified_name if matched_route else ""
                ),
                "language": "typescript",
            },
        ))
    return processes


def _index_routes_by_path(store: GraphStore) -> dict[str, list[SymbolRow]]:
    out: dict[str, list[SymbolRow]] = {}
    for route in store.symbols_by_kind("route"):
        path = (route.extras or {}).get("path") or ""
        if not path:
            continue
        out.setdefault(_normalize_path(path), []).append(route)
    return out


def _match_route(routes_by_path: dict[str, list[SymbolRow]],
                 method: str, url: str) -> SymbolRow | None:
    if not url:
        return None
    norm = _normalize_path(url)
    candidates = routes_by_path.get(norm)
    if not candidates:
        return None
    method_u = (method or "").upper()
    for r in candidates:
        rmethod = ((r.extras or {}).get("http_method") or "").upper()
        if rmethod == method_u or rmethod == "ANY":
            return r
    return candidates[0]


def _normalize_path(path: str) -> str:
    # Strip leading slash and trailing slash; collapse `:id`/`[id]` to `:param`
    # so /orders/:id and /orders/[id] match.
    p = path.strip("/").lower()
    p = re.sub(r"\[[^\]]+\]", ":param", p)
    p = re.sub(r":[a-z0-9_]+", ":param", p)
    return p


# --------------------------------------------------------------------------
# Test flow: test_block -> TESTS -> target -> CALLS chain (depth-limited)
# --------------------------------------------------------------------------

def _build_test_flow(store: GraphStore, tb: SymbolRow, *,
                     max_depth: int, min_step_confidence: float) -> Process | None:
    edges = store.outgoing(tb.qualified_name, ["TESTS"])
    edges = [e for e in edges if e.confidence >= min_step_confidence - 0.05]
    if not edges:
        return None
    # Pick the TESTS edge with the highest confidence; if multiple, keep the
    # one with the most informative dst (resolved qname > raw name).
    edges.sort(
        key=lambda e: (1 if e.dst_qname else 0, e.confidence),
        reverse=True,
    )
    primary = edges[0]
    target_qname = _resolve_dst(store, primary)
    if not target_qname:
        return None
    visited = {tb.qualified_name, target_qname}
    steps: list[ProcessStep] = [ProcessStep(
        step=1,
        src_qname=tb.qualified_name,
        dst_qname=target_qname,
        edge_type="TESTS",
        confidence=primary.confidence,
        metadata={
            "stage": "test_to_target",
            "block_label": (primary.metadata or {}).get("block_label", ""),
        },
    )]
    _walk_chain(store, target_qname, visited, steps,
                max_depth=max(2, max_depth // 2),
                min_step_confidence=min_step_confidence)
    terminal = steps[-1].dst_qname
    confidence = _aggregate_confidence(steps)
    label = tb.name or tb.qualified_name
    proc_id = _slug(f"{PROCESS_TEST_FLOW}::{tb.qualified_name}")
    return Process(
        id=proc_id,
        label=label,
        process_type=PROCESS_TEST_FLOW,
        entrypoint_id=tb.qualified_name,
        terminal_id=terminal,
        steps=steps,
        confidence=confidence,
        metadata={
            "framework": (tb.extras or {}).get("framework", ""),
            "block_kind": (tb.extras or {}).get("block_kind", ""),
            "language": "typescript",
        },
    )


# --------------------------------------------------------------------------
# Shared chain walker
# --------------------------------------------------------------------------

def _walk_chain(store: GraphStore, start: str, visited: set[str],
                steps: list[ProcessStep], *, max_depth: int,
                min_step_confidence: float) -> None:
    current = start
    while len(steps) < max_depth:
        next_edges = _next_step_edges(store, current, visited,
                                      min_step_confidence=min_step_confidence)
        if not next_edges:
            return
        edge = next_edges[0]
        dst = _resolve_dst(store, edge)
        if not dst:
            return
        steps.append(ProcessStep(
            step=len(steps) + 1,
            src_qname=current,
            dst_qname=dst,
            edge_type=edge.edge_type,
            confidence=edge.confidence,
            metadata=_step_metadata(edge),
        ))
        if edge.edge_type in TERMINAL_EDGE_TYPES:
            return
        if dst in visited:
            return
        visited.add(dst)
        current = dst


def _next_step_edges(store: GraphStore, src: str, visited: set[str],
                     *, min_step_confidence: float) -> list[EdgeRow]:
    edges = store.outgoing(src, list(FOLLOW_EDGE_TYPES))
    out: list[EdgeRow] = []
    for e in edges:
        if e.confidence < min_step_confidence:
            continue
        # Skip self-edges and edges into nodes we've already visited.
        dst = e.dst_qname or e.dst_name
        if dst in visited and e.edge_type not in TERMINAL_EDGE_TYPES:
            continue
        if dst == src:
            continue
        out.append(e)
    out.sort(
        key=lambda e: (
            _EDGE_PRIORITY.get(e.edge_type, 99),
            -e.confidence,
            -e.precision_level,
        ),
    )
    return out


def _resolve_dst(store: GraphStore, edge: EdgeRow) -> str | None:
    if edge.dst_qname:
        return edge.dst_qname
    if not edge.dst_name:
        return None
    sym = store.find_symbol(edge.dst_name)
    if sym is not None:
        return sym.qualified_name
    matches = store.find_symbols_by_name(edge.dst_name, limit=2)
    if len(matches) == 1:
        return matches[0].qualified_name
    return None


def _step_metadata(edge: EdgeRow) -> dict:
    meta = dict(edge.metadata or {})
    meta.setdefault("extraction_source", edge.extraction_source)
    meta.setdefault("precision_level", edge.precision_level)
    return meta


def _aggregate_confidence(steps: Iterable[ProcessStep]) -> float:
    values = [max(0.01, min(1.0, s.confidence)) for s in steps]
    if not values:
        return 0.0
    # Geometric mean — punishes the weakest link without going to zero.
    log_sum = sum(math.log(v) for v in values)
    return float(math.exp(log_sum / len(values)))


_SLUG_RE = re.compile(r"[^a-zA-Z0-9._:/-]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("_", text)[:200]


# --------------------------------------------------------------------------
# Local edge-row helper (avoids circular import on store internals)
# --------------------------------------------------------------------------

def _row_to_edge(row) -> EdgeRow:
    import json as _json
    try:
        meta = _json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    except (TypeError, ValueError):
        meta = {}
    return EdgeRow(
        src_qname=row["src_qname"],
        dst_qname=row["dst_qname"],
        dst_name=row["dst_name"],
        edge_type=row["edge_type"],
        confidence=row["confidence"],
        line=row["line"],
        column=row["column"] if "column" in row.keys() else None,
        precision_level=int(row["precision_level"]) if "precision_level" in row.keys() else 1,
        extraction_source=row["extraction_source"] if "extraction_source" in row.keys() else "",
        reason=row["reason"] if "reason" in row.keys() else "",
        metadata=meta,
    )
