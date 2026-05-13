"""Phase 4.4 — Edge Resolution v2.

The existing ``GraphStore.resolve_edge_targets`` only handles the
unique-global-name case: if exactly one symbol in the index has matching
``name``, it resolves the edge. That misses two very common scopes:

    1. **Same-file scope.** A function calls another function defined in the
       same file. Their ``dst_name`` collides with N other top-level symbols
       in the repo, so the unique-name resolver skips it.
    2. **Class scope.** A method calls ``self.helper()`` (or another method
       of the same class). The parser strips ``self.`` and stores the dst
       as just ``helper``, which collides with every other class's ``helper``.

This module adds two ordered passes that run *before* the broad unique-name
pass. Each pass:

    * picks only its eligible candidates
    * stamps the edge's ``extraction_source`` with a ``+`` tag
    * raises ``precision_level`` to ``CODEGRAPH_RESOLVER``
    * writes audit metadata (``resolution_strategy``, ``candidate_count``,
      ``original_dst_name``, ``selected_candidate``) so every rewrite is
      traceable in the doctor / impact views.

Resolution order overall (set by ``indexer.py``):

    alias-resolver (PR 2)
        → file-scope (this module)
        → class-scope (this module)
        → unique-global (store.resolve_edge_targets, last)
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from codegraphkb.core.graph_schema import PrecisionLevel


@dataclass
class EdgeResolverStats:
    file_scope_rewritten: int = 0
    class_scope_rewritten: int = 0

    @property
    def total_rewritten(self) -> int:
        return self.file_scope_rewritten + self.class_scope_rewritten


def resolve_edges_by_scope(store) -> EdgeResolverStats:
    """Run the file-scope and class-scope rewrite passes.

    Returns a ``EdgeResolverStats`` for the indexer/doctor. Mutates the store
    in place.
    """
    stats = EdgeResolverStats()
    stats.file_scope_rewritten = _resolve_by_file_scope(store)
    stats.class_scope_rewritten = _resolve_by_class_scope(store)
    return stats


def _resolve_by_file_scope(store) -> int:
    """For each unresolved edge whose source symbol lives in file F, look
    for symbols *defined in F* with matching ``dst_name``.

    Resolves the edge only when exactly one symbol in F has that name. That
    keeps precision high — most real code calls into one unambiguous local
    helper, and ambiguous cases (overloaded method names in the same file)
    stay unresolved for later passes / human review.
    """
    rows = store._conn.execute("""
        WITH unresolved AS (
            SELECT e.id, e.src_qname, e.dst_name, e.extraction_source,
                   e.metadata_json, s_src.file_id AS file_id
            FROM edges e
            JOIN symbols s_src ON s_src.qualified_name = e.src_qname
            WHERE e.dst_qname IS NULL
              AND e.dst_name IS NOT NULL AND e.dst_name != ''
        )
        SELECT u.id, u.src_qname, u.dst_name, u.extraction_source,
               u.metadata_json,
               (SELECT COUNT(*)
                  FROM symbols s WHERE s.file_id = u.file_id AND s.name = u.dst_name) AS cand_count,
               (SELECT s.qualified_name
                  FROM symbols s WHERE s.file_id = u.file_id AND s.name = u.dst_name
                  LIMIT 1) AS target_qname
        FROM unresolved u
    """).fetchall()
    return _apply_rewrites(store, rows, strategy="file_scope")


def _resolve_by_class_scope(store) -> int:
    """Resolve edges whose source is a method of class C, by searching for
    sibling members of C with matching ``dst_name``.

    Catches the very common case of ``self.helper()`` / ``this.helper()``
    being stored as a CALLS edge with ``dst_name='helper'``. We don't try
    to inspect inheritance here — that's a follow-up. We do unique-in-class
    matching so ambiguous cases fall through.
    """
    rows = store._conn.execute("""
        WITH unresolved AS (
            SELECT e.id, e.src_qname, e.dst_name, e.extraction_source,
                   e.metadata_json, s_src.parent_qname AS class_qname
            FROM edges e
            JOIN symbols s_src ON s_src.qualified_name = e.src_qname
            WHERE e.dst_qname IS NULL
              AND e.dst_name IS NOT NULL AND e.dst_name != ''
              AND s_src.parent_qname IS NOT NULL AND s_src.parent_qname != ''
        )
        SELECT u.id, u.src_qname, u.dst_name, u.extraction_source,
               u.metadata_json,
               (SELECT COUNT(*)
                  FROM symbols s
                  WHERE s.parent_qname = u.class_qname AND s.name = u.dst_name) AS cand_count,
               (SELECT s.qualified_name
                  FROM symbols s
                  WHERE s.parent_qname = u.class_qname AND s.name = u.dst_name
                  LIMIT 1) AS target_qname
        FROM unresolved u
    """).fetchall()
    return _apply_rewrites(store, rows, strategy="class_scope")


def _apply_rewrites(store, rows, *, strategy: str) -> int:
    """Apply a batch of in-scope rewrites where ``cand_count == 1``.

    Skips rows with 0 or >1 candidates so ambiguous cases fall through to a
    later pass (or stay unresolved with their reason). Each rewrite stamps
    audit metadata so a future debugger / doctor view can explain *why* the
    edge resolved the way it did.
    """
    updates = []
    for r in rows:
        if int(r["cand_count"]) != 1:
            continue
        target = r["target_qname"]
        if not target or target == r["src_qname"]:
            continue
        try:
            md = json.loads(r["metadata_json"] or "{}")
            if not isinstance(md, dict):
                md = {}
        except json.JSONDecodeError:
            md = {}
        md["resolution_strategy"] = strategy
        md["original_dst_name"] = r["dst_name"]
        md["selected_candidate"] = target
        md["candidate_count"] = int(r["cand_count"])

        prior_src = (r["extraction_source"] or "").strip()
        tag = f"edge-resolver:{strategy}"
        new_src = f"{prior_src}+{tag}" if prior_src else tag

        updates.append((
            target,
            int(PrecisionLevel.CODEGRAPH_RESOLVER),
            new_src,
            f"Resolved via {strategy}",
            json.dumps(md),
            r["id"],
        ))

    if not updates:
        return 0
    with store.transaction() as cx:
        cx.executemany(
            "UPDATE edges SET dst_qname=?, "
            "precision_level=MAX(precision_level, ?), "
            "extraction_source=?, reason=?, metadata_json=? "
            "WHERE id=?",
            updates,
        )
    return len(updates)
