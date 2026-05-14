"""Optional FastAPI server. Lazy imports so the package works without FastAPI installed."""
from __future__ import annotations

from typing import Any

from codegraphkb.api import CodeGraphKB
from codegraphkb.config import DEFAULT_TOKEN_BUDGET


def build_app(repo_path: str):
    from fastapi import FastAPI, HTTPException  # type: ignore
    from pydantic import BaseModel  # type: ignore

    kb = CodeGraphKB(repo_path)
    app = FastAPI(title="CodeGraphKB", version="0.1.0")

    class AskRequest(BaseModel):
        question: str
        token_budget: int = DEFAULT_TOKEN_BUDGET
        intent: str | None = None
        pinned_files: list[str] = []
        model: str | None = None
        context_only: bool = False

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": "0.1.0"}

    @app.get("/stats")
    def stats() -> dict[str, Any]:
        try:
            return kb.stats()
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/languages")
    def languages() -> dict[str, Any]:
        return kb.supported_languages()

    @app.get("/projects/{project_id}/languages")
    def project_languages(project_id: str) -> dict[str, Any]:
        try:
            payload = kb.project_languages()
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc))
        return {"project_id": project_id, **payload}

    @app.post("/index")
    def index(force: bool = False) -> dict[str, Any]:
        s = kb.index(force=force)
        return {
            "files_scanned": s.files_scanned,
            "files_indexed": s.files_indexed,
            "files_unchanged": s.files_unchanged,
            "files_removed": s.files_removed,
            "symbols": s.symbols,
            "edges": s.edges,
        }

    @app.post("/ask")
    def ask(req: AskRequest) -> dict[str, Any]:
        if req.context_only:
            pack = kb.retrieve_context(
                req.question,
                token_budget=req.token_budget,
                intent=req.intent,
                pinned_files=req.pinned_files,
            )
            return _pack_dict(pack)
        result = kb.ask(
            req.question,
            token_budget=req.token_budget,
            intent=req.intent,
            model=req.model,
            pinned_files=req.pinned_files,
        )
        return {
            "question": result.question,
            "answer": result.answer,
            "model": result.llm.model,
            "used_llm": result.llm.used_llm,
            "context": _pack_dict(result.context),
        }

    @app.get("/impact")
    def impact(target: str) -> dict[str, Any]:
        return _pack_dict(kb.impact(target))

    return app


def run_api(repo_path: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn  # type: ignore
    app = build_app(repo_path)
    uvicorn.run(app, host=host, port=port, log_level="info")


def _pack_dict(pack) -> dict[str, Any]:
    return {
        "intent": pack.intent.value,
        "estimated_tokens": pack.estimated_tokens,
        "graph_paths": pack.graph_paths,
        "files_likely_to_edit": pack.files_likely_to_edit,
        "repo_map": pack.repo_map,
        "items": [
            {
                "kind": it.kind, "title": it.title, "file_path": it.file_path,
                "start_line": it.start_line, "end_line": it.end_line,
                "score": it.score, "tokens": it.tokens, "body": it.body,
            }
            for it in pack.items
        ],
    }
