"""Persist Process objects into the graph store.

Writes to:

* ``processes``       — one row per Process
* ``process_steps``   — one row per step
* ``edges``           — one ``STEP_IN_PROCESS`` row per step

The persistence is rebuilt from scratch each time the indexer rebuilds
processes; we delete previously written process rows + STEP_IN_PROCESS edges
first so reruns stay deterministic.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from codegraphkb.core.graph_schema import EdgeType, PrecisionLevel
from codegraphkb.core.processes.types import Process
from codegraphkb.core.store import GraphStore


PROCESS_EXTRACTION_SOURCE = "process-builder"


def replace_processes(store: GraphStore, processes: list[Process]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with store.transaction() as cx:
        cx.execute("DELETE FROM processes")
        cx.execute("DELETE FROM process_steps")
        cx.execute(
            "DELETE FROM edges WHERE edge_type=? AND extraction_source=?",
            (EdgeType.STEP_IN_PROCESS.value, PROCESS_EXTRACTION_SOURCE),
        )
    for proc in processes:
        _persist_process(store, proc, now)


def _persist_process(store: GraphStore, proc: Process, created_at: str) -> None:
    with store.transaction() as cx:
        cx.execute(
            "INSERT INTO processes(id, label, process_type, entrypoint_id, "
            "terminal_id, step_count, confidence, metadata_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                proc.id,
                proc.label,
                proc.process_type,
                proc.entrypoint_id,
                proc.terminal_id,
                proc.step_count,
                float(proc.confidence),
                json.dumps(proc.metadata or {}),
            ),
        )
        for step in proc.steps:
            cx.executemany(
                "INSERT INTO process_steps(process_id, step, src_qname, "
                "dst_qname, confidence, metadata_json) VALUES (?,?,?,?,?,?)",
                [(
                    proc.id,
                    step.step,
                    step.src_qname,
                    step.dst_qname,
                    float(step.confidence),
                    json.dumps({**(step.metadata or {}), "edge_type": step.edge_type}),
                )],
            )

    edge_rows: list[tuple] = []
    for step in proc.steps:
        edge_rows.append((
            step.src_qname,
            step.dst_qname,
            step.dst_qname.rsplit(".", 1)[-1],
            EdgeType.STEP_IN_PROCESS.value,
            float(step.confidence),
            PROCESS_EXTRACTION_SOURCE,
            None,           # line
            None,           # column
            int(PrecisionLevel.LANGUAGE_SEMANTIC),
            f"step {step.step} of {proc.id}",
            {
                "process_id": proc.id,
                "step": step.step,
                "edge_type": step.edge_type,
                "process_type": proc.process_type,
            },
            created_at,
        ))
    if edge_rows:
        store.insert_edges(edge_rows)


# --------------------------------------------------------------------------
# Read-side helpers
# --------------------------------------------------------------------------

def list_processes(store: GraphStore, *, process_type: str | None = None,
                    limit: int | None = None) -> list[dict]:
    sql = (
        "SELECT id, label, process_type, entrypoint_id, terminal_id, "
        "step_count, confidence, metadata_json FROM processes"
    )
    params: list = []
    if process_type:
        sql += " WHERE process_type = ?"
        params.append(process_type)
    sql += " ORDER BY confidence DESC, id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = store._conn.execute(sql, params).fetchall()
    return [_row_to_process_dict(r) for r in rows]


def get_process(store: GraphStore, process_id: str) -> dict | None:
    row = store._conn.execute(
        "SELECT id, label, process_type, entrypoint_id, terminal_id, "
        "step_count, confidence, metadata_json FROM processes WHERE id = ?",
        (process_id,),
    ).fetchone()
    if row is None:
        return None
    proc = _row_to_process_dict(row)
    steps = store._conn.execute(
        "SELECT step, src_qname, dst_qname, confidence, metadata_json "
        "FROM process_steps WHERE process_id = ? ORDER BY step ASC",
        (process_id,),
    ).fetchall()
    proc["steps"] = [
        {
            "step": int(s["step"]),
            "src_qname": s["src_qname"],
            "dst_qname": s["dst_qname"],
            "confidence": float(s["confidence"] or 0.0),
            "metadata": _safe_meta(s["metadata_json"]),
        }
        for s in steps
    ]
    return proc


def find_processes_for_symbol(store: GraphStore, qname: str,
                               limit: int = 10) -> list[dict]:
    """Return processes whose entrypoint, terminal, or any step touches qname."""
    rows = store._conn.execute(
        """
        SELECT p.id FROM processes p
        WHERE p.entrypoint_id = ?
           OR p.terminal_id = ?
           OR EXISTS (
              SELECT 1 FROM process_steps ps
              WHERE ps.process_id = p.id
                AND (ps.src_qname = ? OR ps.dst_qname = ?)
           )
        ORDER BY p.confidence DESC
        LIMIT ?
        """,
        (qname, qname, qname, qname, int(limit)),
    ).fetchall()
    return [get_process(store, r["id"]) for r in rows]


def _row_to_process_dict(row) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "process_type": row["process_type"],
        "entrypoint_id": row["entrypoint_id"],
        "terminal_id": row["terminal_id"],
        "step_count": int(row["step_count"] or 0),
        "confidence": float(row["confidence"] or 0.0),
        "metadata": _safe_meta(row["metadata_json"]),
    }


def _safe_meta(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}
