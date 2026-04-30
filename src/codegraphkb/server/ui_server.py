"""Local-first interactive UI server for CodeGraphKB."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraphkb.api import CodeGraphKB
from codegraphkb.config import DEFAULT_TOKEN_BUDGET
from codegraphkb.core.store import GraphStore


def build_ui_app(repo_path: str):
    from fastapi import Body, FastAPI, HTTPException, Query  # type: ignore
    from fastapi.responses import FileResponse, HTMLResponse  # type: ignore
    from fastapi.staticfiles import StaticFiles  # type: ignore

    kb = CodeGraphKB(repo_path)
    app = FastAPI(title="CodeGraphKB UI", version="0.1.0")

    repo_ui_dist = _resolve_ui_dist(repo_path)
    repo_ui_index = repo_ui_dist / "index.html" if repo_ui_dist is not None else None
    repo_ui_assets = repo_ui_dist / "assets" if repo_ui_dist is not None else None

    fallback_static_dir = Path(__file__).resolve().parent / "static"
    fallback_static_index = fallback_static_dir / "index.html"

    if repo_ui_assets and repo_ui_assets.exists():
        app.mount("/assets", StaticFiles(directory=str(repo_ui_assets)), name="ui-assets")
    elif fallback_static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(fallback_static_dir)), name="static")

    @app.get("/", include_in_schema=False)
    def ui_home():
        if repo_ui_index and repo_ui_index.exists():
            return FileResponse(repo_ui_index)
        if fallback_static_index.exists():
            return FileResponse(fallback_static_index)
        return HTMLResponse(_fallback_html())

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": "0.1.0"}

    @app.get("/api/summary")
    def summary() -> dict[str, Any]:
        try:
            stats = kb.stats()
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        store = _open_store_or_404(kb)
        try:
            node_kind_rows = store._conn.execute(
                "SELECT kind, COUNT(*) AS n FROM symbols GROUP BY kind"
            ).fetchall()
            edge_type_rows = store._conn.execute(
                "SELECT edge_type, COUNT(*) AS n FROM edges GROUP BY edge_type"
            ).fetchall()
        finally:
            store.close()
        process_count = len(kb.list_processes(limit=100000))
        doctor = kb.doctor()
        stale = doctor.get("stale_file_count", 0)
        return {
            "repo": Path(stats["repo_path"]).name,
            "repo_path": stats["repo_path"],
            "files": stats["files"],
            "symbols": stats["symbols"],
            "edges": stats["edges"],
            "processes": process_count,
            "languages": stats.get("languages", {}),
            "indexed_at": stats.get("last_indexed_at"),
            "index_health": "ok" if stale == 0 else "stale",
            "stale_files": stale,
            "node_kinds": {r["kind"]: int(r["n"]) for r in node_kind_rows},
            "edge_types": {r["edge_type"]: int(r["n"]) for r in edge_type_rows},
            "index_health_details": {
                "schema_version": stats.get("schema_version"),
                "parser_backend_pref": stats.get("parser_backend_pref"),
                "embedding_model": stats.get("embedding_model"),
                "stale_files": stale,
                "doctor": doctor,
            },
        }

    @app.get("/api/graph")
    def graph(
        view: str = Query("repo"),
        max_nodes: int | None = Query(default=None, ge=1),
        max_edges: int | None = Query(default=None, ge=1),
        node_kinds: str | None = None,
        edge_types: str | None = None,
    ) -> dict[str, Any]:
        try:
            payload = kb.export_graph(view=view, max_nodes=max_nodes, max_edges=max_edges)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        kinds = _csv_set(node_kinds)
        edges = _csv_set(edge_types)
        if kinds or edges:
            payload = _filter_graph(payload, allowed_kinds=kinds, allowed_edge_types=edges)
        return payload

    @app.get("/api/search")
    def search(q: str = Query(..., min_length=1), limit: int = Query(25, ge=1, le=200)) -> dict[str, Any]:
        store = _open_store_or_404(kb)
        try:
            return {"query": q, "results": _search_graph(store, kb, q, limit)}
        finally:
            store.close()

    @app.get("/api/files/tree")
    def files_tree() -> dict[str, Any]:
        store = _open_store_or_404(kb)
        try:
            return _build_file_tree(store, kb)
        finally:
            store.close()

    @app.get("/api/node/{node_id:path}/relations")
    def node_relations(node_id: str) -> dict[str, Any]:
        store = _open_store_or_404(kb)
        try:
            details = _node_details(store, kb, node_id)
        finally:
            store.close()
        if details is None:
            raise HTTPException(404, f"Node `{node_id}` not found")
        return _node_relations(details)

    @app.get("/api/node/{node_id:path}")
    def node_details(node_id: str) -> dict[str, Any]:
        store = _open_store_or_404(kb)
        try:
            details = _node_details(store, kb, node_id)
        finally:
            store.close()
        if details is None:
            raise HTTPException(404, f"Node `{node_id}` not found")
        return details

    @app.get("/api/neighborhood")
    def neighborhood(
        node_id: str,
        depth: int = Query(2, ge=1, le=4),
        max_nodes: int | None = Query(default=1200, ge=1),
        max_edges: int | None = Query(default=3200, ge=1),
    ) -> dict[str, Any]:
        if node_id.startswith("process:"):
            proc_id = node_id.split(":", 1)[1]
            proc = kb.get_process(proc_id)
            if proc is None:
                raise HTTPException(404, f"Process `{proc_id}` not found")
            store = _open_store_or_404(kb)
            try:
                payload = _process_to_graph(store=store, process=proc)
            finally:
                store.close()
            payload["metadata"]["view"] = "neighborhood"
            payload["metadata"]["seed_node"] = node_id
            return payload

        target = _target_from_node_id(node_id)
        if target is None:
            raise HTTPException(400, "node_id must start with symbol:, file:, or process:")
        payload = kb.export_impact_graph(
            target,
            max_depth=depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
        payload["metadata"]["view"] = "neighborhood"
        payload["metadata"]["seed_node"] = node_id
        return payload

    @app.get("/api/processes")
    def processes(process_type: str | None = None, limit: int = Query(100, ge=1, le=2000)) -> dict[str, Any]:
        raw = kb.list_processes(process_type=process_type, limit=limit)
        return {"processes": [_with_process_node_id(p) for p in raw]}

    @app.get("/api/processes/{process_id}")
    def process_details(process_id: str) -> dict[str, Any]:
        proc = kb.get_process(process_id)
        if proc is None:
            raise HTTPException(404, f"Process `{process_id}` not found")
        return _with_process_node_id(proc)

    @app.get("/api/impact")
    def impact(
        target: str,
        depth: int = Query(2, ge=1, le=4),
        max_nodes: int | None = Query(default=1200, ge=1),
        max_edges: int | None = Query(default=3200, ge=1),
    ) -> dict[str, Any]:
        payload = kb.export_impact_graph(
            target,
            max_depth=depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
        payload["metadata"]["view"] = "impact"
        return payload

    @app.post("/api/context")
    def context(req: dict[str, Any] = Body(...)) -> dict[str, Any]:
        task = str(req.get("task") or "").strip()
        if not task:
            raise HTTPException(400, "`task` is required")
        mode = req.get("mode") or "edit"
        selected_node_ids = [str(x) for x in (req.get("selected_node_ids") or [])]
        pinned_files_req = [str(x) for x in (req.get("pinned_files") or [])]
        token_budget_raw = req.get("token_budget", DEFAULT_TOKEN_BUDGET)
        retrieval = str(req.get("retrieval") or "auto")
        try:
            token_budget = int(token_budget_raw)
        except (TypeError, ValueError):
            raise HTTPException(400, "`token_budget` must be an integer")
        if token_budget <= 0:
            raise HTTPException(400, "`token_budget` must be > 0")

        store = _open_store_or_404(kb)
        try:
            inferred_pins = _pinned_files_from_selected(store, kb, selected_node_ids)
        finally:
            store.close()
        pinned = sorted(set(pinned_files_req + inferred_pins))
        pack = kb.retrieve_context(
            task,
            token_budget=token_budget,
            mode=mode,
            pinned_files=pinned,
            retrieval=retrieval,
        )
        return {
            "context_pack": pack.to_prompt(),
            "selected_node_ids": selected_node_ids,
            "pinned_files": pinned,
            "files_likely_to_edit": pack.files_likely_to_edit,
            "related_tests": pack.related_tests,
            "process_traces": getattr(pack, "process_traces", []),
            "audit": pack.audit,
            "context": _pack_dict(pack),
        }

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith("api/") or full_path == "health":
            raise HTTPException(404, "Not found")
        if repo_ui_dist is not None:
            candidate = repo_ui_dist / full_path
            if candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            if repo_ui_index and repo_ui_index.exists():
                return FileResponse(repo_ui_index)
        if fallback_static_index.exists():
            return FileResponse(fallback_static_index)
        return HTMLResponse(_fallback_html())

    return app


def run_ui(repo_path: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn  # type: ignore

    app = build_ui_app(repo_path)
    uvicorn.run(app, host=host, port=port, log_level="info")


def _open_store_or_404(kb: CodeGraphKB) -> GraphStore:
    try:
        return kb._open_store()
    except FileNotFoundError as exc:
        raise _http_404(str(exc)) from exc


def _http_404(msg: str):
    from fastapi import HTTPException  # type: ignore

    return HTTPException(404, msg)


def _resolve_ui_dist(repo_path: str) -> Path | None:
    root = Path(repo_path).resolve()
    dist = root / "ui" / "dist"
    if dist.exists() and dist.is_dir():
        return dist
    return None


def _csv_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {p.strip() for p in raw.split(",") if p.strip()}


def _filter_graph(
    payload: dict[str, Any],
    *,
    allowed_kinds: set[str],
    allowed_edge_types: set[str],
) -> dict[str, Any]:
    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])

    if allowed_kinds:
        nodes = [n for n in nodes if n.get("kind") in allowed_kinds]
    node_ids = {n.get("id") for n in nodes}

    filtered_edges = []
    for e in edges:
        if allowed_edge_types and e.get("type") not in allowed_edge_types:
            continue
        if e.get("source") not in node_ids or e.get("target") not in node_ids:
            continue
        filtered_edges.append(e)
    payload["nodes"] = nodes
    payload["edges"] = filtered_edges
    payload.setdefault("metadata", {})
    payload["metadata"]["node_count"] = len(nodes)
    payload["metadata"]["edge_count"] = len(filtered_edges)
    return payload


def _search_graph(store: GraphStore, kb: CodeGraphKB, query: str, limit: int) -> list[dict[str, Any]]:
    q = query.strip()
    like = f"%{q}%"
    results: list[dict[str, Any]] = []

    file_rows = store._conn.execute(
        "SELECT path, language FROM files "
        "WHERE path LIKE ? ORDER BY path LIMIT ?",
        (like, limit),
    ).fetchall()
    for row in file_rows:
        results.append(
            {
                "id": f"file:{row['path'].replace(chr(92), '/')}",
                "label": Path(row["path"]).name,
                "kind": "file",
                "file_path": row["path"],
                "score": 1.0,
            }
        )

    sym_rows = store._conn.execute(
        "SELECT s.kind, s.name, s.qualified_name, f.path AS file_path, s.start_line, s.end_line "
        "FROM symbols s JOIN files f ON s.file_id = f.id "
        "WHERE s.name LIKE ? OR s.qualified_name LIKE ? OR f.path LIKE ? "
        "ORDER BY s.name LIMIT ?",
        (like, like, like, limit),
    ).fetchall()
    for row in sym_rows:
        results.append(
            {
                "id": f"symbol:{row['qualified_name']}",
                "label": row["name"],
                "kind": row["kind"],
                "file_path": row["file_path"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "score": 0.9,
            }
        )

    for proc in kb.list_processes(limit=limit):
        label = (proc.get("label") or "").lower()
        pid = (proc.get("id") or "").lower()
        if q.lower() in label or q.lower() in pid:
            results.append(
                {
                    "id": f"process:{proc['id']}",
                    "label": proc["label"],
                    "kind": "process",
                    "score": 0.8,
                }
            )

    deduped: dict[str, dict[str, Any]] = {}
    for item in results:
        deduped.setdefault(item["id"], item)
    return list(deduped.values())[:limit]


def _node_details(store: GraphStore, kb: CodeGraphKB, node_id: str) -> dict[str, Any] | None:
    if node_id.startswith("symbol:"):
        qname = node_id.split(":", 1)[1]
        sym = store.find_symbol(qname)
        if sym is None:
            return None
        callers = [_edge_ref(e.src_qname, e.edge_type, e.confidence) for e in store.incoming(qname, ["CALLS", "HANDLES_ROUTE", "TESTS", "TESTS_SYMBOL"])]
        callees = [_edge_ref(e.dst_qname or e.dst_name, e.edge_type, e.confidence) for e in store.outgoing(qname, ["CALLS", "QUERIES", "FETCHES", "CALLS_EXTERNAL", "USES_MIDDLEWARE"])]
        tests = [{"id": f"symbol:{t.qualified_name}", "label": t.name, "kind": t.kind, "file_path": t.file_path} for t in kb.related_tests(qname)]
        processes = kb.find_processes_for_symbol(qname, limit=20)
        return {
            "node": {
                "id": node_id,
                "label": sym.name,
                "kind": sym.kind,
                "qualified_name": sym.qualified_name,
                "file_path": sym.file_path,
                "start_line": sym.start_line,
                "end_line": sym.end_line,
                "signature": sym.signature,
                "metadata": sym.extras,
            },
            "relationships": {
                "callers": callers,
                "callees": callees,
                "related_tests": tests,
                "processes": [{"id": p["id"], "label": p["label"], "type": p["process_type"], "confidence": p["confidence"]} for p in processes],
            },
        }

    if node_id.startswith("file:"):
        rel = node_id.split(":", 1)[1]
        row = store._conn.execute(
            "SELECT path, language, size_bytes, indexed_at FROM files WHERE path=?",
            (rel,),
        ).fetchone()
        if row is None:
            return None
        syms = store.symbols_in_file(rel)
        return {
            "node": {
                "id": node_id,
                "label": Path(rel).name,
                "kind": "file",
                "file_path": rel,
                "metadata": {
                    "language": row["language"],
                    "size_bytes": row["size_bytes"],
                    "indexed_at": row["indexed_at"],
                    "symbol_count": len(syms),
                },
            },
            "relationships": {
                "symbols": [
                    {"id": f"symbol:{s.qualified_name}", "label": s.name, "kind": s.kind,
                     "start_line": s.start_line, "end_line": s.end_line}
                    for s in syms
                ]
            },
        }

    if node_id.startswith("process:"):
        proc_id = node_id.split(":", 1)[1]
        proc = kb.get_process(proc_id)
        if proc is None:
            return None
        return {"node": {"id": node_id, "label": proc["label"], "kind": "process"}, "process": proc}

    if node_id.startswith("folder:"):
        folder = node_id.split(":", 1)[1]
        rows = store._conn.execute(
            "SELECT path FROM files WHERE path LIKE ? ORDER BY path LIMIT 200",
            (f"{folder}/%",),
        ).fetchall()
        return {
            "node": {"id": node_id, "label": Path(folder).name or folder, "kind": "folder"},
            "relationships": {
                "files": [{"id": f"file:{r['path']}", "label": Path(r["path"]).name, "kind": "file"} for r in rows]
            },
        }
    return None


def _edge_ref(qname: str, edge_type: str, confidence: float) -> dict[str, Any]:
    return {
        "id": f"symbol:{qname}" if qname else "symbol:?",
        "qualified_name": qname,
        "edge_type": edge_type,
        "confidence": confidence,
    }


def _target_from_node_id(node_id: str) -> str | None:
    if ":" not in node_id:
        return None
    kind, value = node_id.split(":", 1)
    if kind in {"symbol", "file"}:
        return value
    return None


def _pinned_files_from_selected(store: GraphStore, kb: CodeGraphKB, node_ids: list[str]) -> list[str]:
    files: set[str] = set()
    for node_id in node_ids:
        if node_id.startswith("file:"):
            files.add(node_id.split(":", 1)[1])
            continue
        if node_id.startswith("symbol:"):
            qname = node_id.split(":", 1)[1]
            sym = store.find_symbol(qname)
            if sym:
                files.add(sym.file_path)
            continue
        if node_id.startswith("process:"):
            proc_id = node_id.split(":", 1)[1]
            proc = kb.get_process(proc_id)
            if not proc:
                continue
            for step in proc.get("steps", []):
                for qname in (step.get("src_qname"), step.get("dst_qname")):
                    if not qname:
                        continue
                    sym = store.find_symbol(qname)
                    if sym:
                        files.add(sym.file_path)
    return sorted(files)


def _process_to_graph(*, store: GraphStore, process: dict[str, Any]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    proc_node_id = f"process:{process['id']}"
    nodes[proc_node_id] = {
        "id": proc_node_id,
        "label": process["label"],
        "kind": "process",
        "file_path": "",
        "metadata": {"process_type": process["process_type"]},
    }
    for step in process.get("steps", []):
        src = step["src_qname"]
        dst = step["dst_qname"]
        for qname in (src, dst):
            if not qname:
                continue
            nid = f"symbol:{qname}"
            if nid in nodes:
                continue
            sym = store.find_symbol(qname)
            nodes[nid] = {
                "id": nid,
                "label": sym.name if sym else qname.rsplit(".", 1)[-1],
                "kind": sym.kind if sym else "symbol",
                "file_path": sym.file_path if sym else "",
                "metadata": {"qualified_name": qname},
            }
        edges.append(
            {
                "id": f"step:{process['id']}:{step['step']}",
                "source": f"symbol:{src}",
                "target": f"symbol:{dst}",
                "type": (step.get("metadata") or {}).get("edge_type", "STEP_IN_PROCESS"),
                "confidence": step["confidence"],
                "precision_level": 3,
                "metadata": {"step": step["step"], "process_id": process["id"]},
            }
        )
    return {
        "metadata": {
            "view": "processes",
            "process_id": process["id"],
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def _pack_dict(pack) -> dict[str, Any]:
    return {
        "intent": pack.intent.value,
        "mode": pack.mode.value,
        "retrieval_mode": pack.retrieval_mode,
        "estimated_tokens": pack.estimated_tokens,
        "graph_paths": pack.graph_paths,
        "files_likely_to_edit": pack.files_likely_to_edit,
        "related_tests": pack.related_tests,
        "process_traces": getattr(pack, "process_traces", []),
        "audit": pack.audit,
        "items": [
            {
                "kind": it.kind,
                "title": it.title,
                "file_path": it.file_path,
                "start_line": it.start_line,
                "end_line": it.end_line,
                "score": it.score,
                "tokens": it.tokens,
                "retrieval_sources": it.retrieval_sources,
                "graph_path": it.graph_path,
                "confidence": it.confidence,
                "reason": it.reason,
                "body": it.body,
            }
            for it in pack.items
        ],
        "repo_map": pack.repo_map,
    }


def _with_process_node_id(process: dict[str, Any]) -> dict[str, Any]:
    pid = str(process.get("id", "")).strip()
    out = dict(process)
    if pid:
        out["node_id"] = f"process:{pid}"
    return out


def _node_relations(details: dict[str, Any]) -> dict[str, Any]:
    relationships = details.get("relationships") if isinstance(details, dict) else None
    if not isinstance(relationships, dict):
        return {
            "callers": [],
            "callees": [],
            "tests": [],
            "processes": [],
            "routes": [],
            "imports": [],
        }
    return {
        "callers": relationships.get("callers", []),
        "callees": relationships.get("callees", []),
        "tests": relationships.get("related_tests", relationships.get("tests", [])),
        "processes": relationships.get("processes", []),
        "routes": relationships.get("routes", []),
        "imports": relationships.get("imports", []),
    }


def _build_file_tree(store: GraphStore, kb: CodeGraphKB) -> dict[str, Any]:
    repo_root = str(kb.config.repo_path.resolve())
    rows = store._conn.execute(
        "SELECT f.path AS path, COUNT(s.id) AS symbol_count "
        "FROM files f LEFT JOIN symbols s ON s.file_id = f.id "
        "GROUP BY f.path ORDER BY f.path"
    ).fetchall()

    root: dict[str, Any] = {
        "name": Path(repo_root).name or repo_root,
        "type": "folder",
        "path": "",
        "children": [],
        "file_count": 0,
        "symbol_count": 0,
    }
    folder_index: dict[str, dict[str, Any]] = {"": root}

    def ensure_folder(path: str) -> dict[str, Any]:
        if path in folder_index:
            return folder_index[path]
        parent_path = "/".join(path.split("/")[:-1]) if "/" in path else ""
        parent = ensure_folder(parent_path)
        folder = {
            "name": path.split("/")[-1],
            "type": "folder",
            "path": path,
            "children": [],
            "file_count": 0,
            "symbol_count": 0,
        }
        parent["children"].append(folder)
        folder_index[path] = folder
        return folder

    for row in rows:
        raw_path = str(row["path"]).replace("\\", "/")
        symbol_count = int(row["symbol_count"] or 0)
        parts = [p for p in raw_path.split("/") if p]
        parent_path = ""
        if len(parts) > 1:
            for part in parts[:-1]:
                parent_path = f"{parent_path}/{part}" if parent_path else part
                ensure_folder(parent_path)
        parent = ensure_folder(parent_path)
        parent["children"].append(
            {
                "name": parts[-1] if parts else raw_path,
                "type": "file",
                "path": raw_path,
                "symbol_count": symbol_count,
            }
        )
        root["file_count"] += 1
        root["symbol_count"] += symbol_count

    def finalize(node: dict[str, Any]) -> tuple[int, int]:
        if node.get("type") == "file":
            return 1, int(node.get("symbol_count", 0))
        files = 0
        symbols = 0
        children = node.get("children", [])
        for child in children:
            child_files, child_symbols = finalize(child)
            files += child_files
            symbols += child_symbols
        node["file_count"] = files
        node["symbol_count"] = symbols
        children.sort(key=lambda c: (c.get("type") != "folder", c.get("name", "")))
        return files, symbols

    finalize(root)
    return root


def _fallback_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CodeGraphKB UI</title>
  <style>
    body{margin:0;background:#0f1117;color:#e8edf5;font-family:ui-sans-serif,Segoe UI,Arial;padding:32px}
    .card{max-width:760px;border:1px solid #2a3242;border-radius:8px;padding:18px;background:#161a22}
    code{background:#0b0f18;padding:2px 6px;border-radius:6px}
    a{color:#8cb4ff}
  </style>
</head>
<body>
  <div class="card">
    <h2>CodeGraphKB UI Backend Running</h2>
    <p>No built frontend assets were found yet. API is available under <code>/api/*</code>.</p>
    <p>Start here: <a href="/api/summary">/api/summary</a></p>
  </div>
</body>
</html>
"""
