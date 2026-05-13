"""Merge SemanticResult facts into the SQLite graph.

The semantic adapter enriches the existing syntax graph rather than replacing
it. Rules:

* If a semantic CALLS/ACCESSES reference resolves a rough syntax edge that
  already exists (same src qname + same dst_name), upgrade that row's
  ``dst_qname``, ``confidence``, ``precision_level``, ``reason``, and record
  the semantic backend in ``metadata_json``.
* If no syntax edge matches but the reference has a resolved target, insert a
  new edge at ``precision_level=3`` (LANGUAGE_SEMANTIC).
* Type facts are stored in the ``types`` table.
* Symbol type facts (return_type, signature) overwrite the matching symbol's
  semantic columns when the qname matches an indexed symbol.

The merge is intentionally conservative: only edges that *resolve* across the
graph are upgraded — unresolved references stay rough and do not pollute the
graph with low-confidence semantic edges.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from codegraphkb.core.graph_schema import PrecisionLevel
from codegraphkb.core.semantic.protocol import (
    SemanticParameter,
    SemanticReference,
    SemanticResult,
    SemanticSymbol,
    SemanticTypeFact,
)
from codegraphkb.core.store import GraphStore


SEMANTIC_BACKEND_ID = "typescript-compiler-api"


@dataclass
class MergeStats:
    edges_upgraded: int = 0
    edges_inserted: int = 0
    types_inserted: int = 0
    symbols_enriched: int = 0
    parameters_merged: int = 0


def merge_semantic_result(
    store: GraphStore,
    result: SemanticResult,
    *,
    backend_version: str = "0.1.0",
) -> MergeStats:
    stats = MergeStats()
    now = datetime.now(timezone.utc).isoformat()

    for file_result in result.files:
        for symbol in file_result.symbols:
            symbol_exists = _enrich_symbol(store, symbol, backend_version)
            if symbol_exists:
                stats.symbols_enriched += 1
            if symbol_exists and symbol.parameters:
                _replace_semantic_parameters(store, symbol.parameters)
                stats.parameters_merged += len(symbol.parameters)

        for ref in file_result.references:
            if ref.to_symbol is None:
                # Conservative: do not insert unresolved semantic edges.
                continue
            upgraded = _upgrade_existing_edge(store, ref, now)
            if upgraded:
                stats.edges_upgraded += 1
                continue
            if _insert_semantic_edge(store, ref, now):
                stats.edges_inserted += 1

        for type_fact in file_result.types:
            if _insert_type_fact(store, type_fact):
                stats.types_inserted += 1

    return stats


def _enrich_symbol(store: GraphStore, symbol: SemanticSymbol,
                   backend_version: str) -> bool:
    row = store.find_symbol(symbol.qualified_name)
    if row is None:
        return False
    fields: list[tuple[str, object]] = []
    if symbol.return_type:
        fields.append(("return_type", symbol.return_type))
    if symbol.signature:
        fields.append(("signature", symbol.signature))
    fields.append(("semantic_backend", SEMANTIC_BACKEND_ID))
    fields.append(("semantic_version", backend_version))
    set_clause = ", ".join(f"{name}=?" for name, _ in fields)
    params = [value for _, value in fields] + [symbol.qualified_name]
    with store.transaction() as cx:
        cx.execute(
            f"UPDATE symbols SET {set_clause} WHERE qualified_name=?",
            params,
        )
    return True


def _upgrade_existing_edge(store: GraphStore, ref: SemanticReference,
                           created_at: str) -> bool:
    """Upgrade the first matching rough edge to semantic precision.

    Match key: (src_qname, edge_type, dst_name). We look up the rough edge by
    the *target name*, not its qname, since the syntax pass leaves dst_qname
    NULL until ``resolve_edge_targets`` runs.
    """
    target_name = ref.to_symbol.split(".")[-1] if ref.to_symbol else ""
    candidates = store._conn.execute(
        "SELECT id, dst_qname, precision_level, metadata_json FROM edges "
        "WHERE src_qname=? AND edge_type=? AND dst_name=? "
        "ORDER BY id ASC",
        (ref.from_symbol, ref.edge_type, target_name),
    ).fetchall()
    if not candidates:
        return False
    row = candidates[0]
    try:
        meta = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    except (TypeError, json.JSONDecodeError):
        meta = {}
    meta["semantic_backend"] = SEMANTIC_BACKEND_ID
    if ref.receiver_type:
        meta["receiver_type"] = ref.receiver_type
    if ref.call_form:
        meta["call_form"] = ref.call_form
    meta["upgraded_at"] = created_at
    with store.transaction() as cx:
        cx.execute(
            "UPDATE edges SET dst_qname=?, confidence=?, precision_level=?, "
            "reason=?, extraction_source=?, metadata_json=? WHERE id=?",
            (
                ref.to_symbol,
                float(ref.confidence),
                int(PrecisionLevel.LANGUAGE_SEMANTIC),
                ref.reason,
                SEMANTIC_BACKEND_ID,
                json.dumps(meta),
                row["id"],
            ),
        )
    return True


def _insert_semantic_edge(store: GraphStore, ref: SemanticReference,
                          created_at: str) -> bool:
    """Insert a fresh semantic edge unless one already exists.

    Returns True when a row was inserted.
    """
    target_name = ref.to_symbol.split(".")[-1] if ref.to_symbol else ""
    existing = store._conn.execute(
        "SELECT 1 FROM edges WHERE src_qname=? AND dst_qname=? "
        "AND edge_type=? AND extraction_source=?",
        (ref.from_symbol, ref.to_symbol, ref.edge_type, SEMANTIC_BACKEND_ID),
    ).fetchone()
    if existing:
        return False
    metadata = {
        "semantic_backend": SEMANTIC_BACKEND_ID,
        "call_form": ref.call_form or "",
        "receiver_type": ref.receiver_type or "",
        "inserted_at": created_at,
    }
    store.insert_edges([(
        ref.from_symbol,
        ref.to_symbol,
        target_name,
        ref.edge_type,
        float(ref.confidence),
        SEMANTIC_BACKEND_ID,
        None,        # line
        None,        # column
        int(PrecisionLevel.LANGUAGE_SEMANTIC),
        ref.reason,
        metadata,
        created_at,
    )])
    return True


def _insert_type_fact(store: GraphStore, type_fact: SemanticTypeFact) -> bool:
    existing = store._conn.execute(
        "SELECT 1 FROM types WHERE owner_qname=? AND name=? AND kind=?",
        (type_fact.owner_symbol, type_fact.name, type_fact.kind),
    ).fetchone()
    if existing:
        with store.transaction() as cx:
            cx.execute(
                "UPDATE types SET declared_type=?, inferred_type=?, "
                "confidence=?, precision_level=?, metadata_json=? "
                "WHERE owner_qname=? AND name=? AND kind=?",
                (
                    type_fact.declared_type,
                    type_fact.inferred_type,
                    0.9,
                    int(PrecisionLevel.LANGUAGE_SEMANTIC),
                    json.dumps({"semantic_backend": SEMANTIC_BACKEND_ID}),
                    type_fact.owner_symbol,
                    type_fact.name,
                    type_fact.kind,
                ),
            )
        return False
    with store.transaction() as cx:
        cx.execute(
            "INSERT INTO types(owner_qname, name, kind, declared_type, "
            "inferred_type, confidence, precision_level, metadata_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                type_fact.owner_symbol,
                type_fact.name,
                type_fact.kind,
                type_fact.declared_type,
                type_fact.inferred_type,
                0.9,
                int(PrecisionLevel.LANGUAGE_SEMANTIC),
                json.dumps({"semantic_backend": SEMANTIC_BACKEND_ID}),
            ),
        )
    return True


def _replace_semantic_parameters(
    store: GraphStore,
    parameters: list[SemanticParameter],
) -> None:
    if not parameters:
        return
    owner = parameters[0].owner_symbol
    rows = [
        {
            "name": p.name,
            "position": p.position,
            "declared_type": p.declared_type,
            "inferred_type": p.inferred_type,
            "default_value": p.default_value,
            "is_optional": p.is_optional,
            "is_variadic": p.is_variadic,
            "confidence": p.confidence,
            "precision_level": int(PrecisionLevel.LANGUAGE_SEMANTIC),
            "extraction_source": SEMANTIC_BACKEND_ID,
            "metadata": {
                "semantic_backend": SEMANTIC_BACKEND_ID,
                "owner_symbol": p.owner_symbol,
            },
        }
        for p in parameters
    ]
    store.replace_parameters_for_symbol(owner, rows)
