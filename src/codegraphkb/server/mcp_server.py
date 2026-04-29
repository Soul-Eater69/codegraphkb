"""Minimal MCP server (stdio JSON-RPC 2.0).

Implements just enough of the Model Context Protocol for Claude Desktop / Cursor /
Windsurf to discover and invoke CodeGraphKB tools without any extra dependency.

Phase 2 tools added on top of the original five:
  - prepare_edit_context   (the most useful one for coding agents)
  - get_related_tests
  - get_callers_and_callees
  - resolve_symbol
  - explain_context_selection
"""
from __future__ import annotations

import json
import sys
from typing import Any

from codegraphkb.api import CodeGraphKB
from codegraphkb.config import DEFAULT_TOKEN_BUDGET

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "codegraphkb", "version": "0.2.0"}

TOOLS = [
    {
        "name": "search_code_graph",
        "description": "Search the indexed code graph for symbols by keyword, name, or path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_symbol_context",
        "description": "Return the capsule, signature, and source snippet for a qualified symbol name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "qualified_name": {"type": "string"},
                "include_source": {"type": "boolean", "default": True},
            },
            "required": ["qualified_name"],
        },
    },
    {
        "name": "get_minimal_context_for_task",
        "description": "Assemble a token-budgeted context pack for a coding task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "token_budget": {"type": "integer", "default": DEFAULT_TOKEN_BUDGET},
                "intent": {"type": "string"},
                "mode": {"type": "string"},
                "retrieval": {"type": "string", "default": "auto",
                              "enum": ["auto", "bm25", "hybrid", "vector"]},
                "pinned_files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task"],
        },
    },
    {
        "name": "prepare_edit_context",
        "description": (
            "Edit-mode context pack: returns files likely to edit, related tests, "
            "callers/callees, capsules, exact snippets, and an audit of why each "
            "item was included. Use this before generating code changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "token_budget": {"type": "integer", "default": 6000},
                "pinned_files": {"type": "array", "items": {"type": "string"}},
                "retrieval": {"type": "string", "default": "auto"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "get_impact_analysis",
        "description": "Return callers, routes, and tests affected by a file or symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
    },
    {
        "name": "get_related_tests",
        "description": "Return tests that exercise a symbol (or its file).",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
    },
    {
        "name": "get_callers_and_callees",
        "description": "List immediate callers and callees of a symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "resolve_symbol",
        "description": "Resolve a name or path to one or more concrete symbols.",
        "inputSchema": {
            "type": "object",
            "properties": {"name_or_path": {"type": "string"}},
            "required": ["name_or_path"],
        },
    },
    {
        "name": "plan_validation_commands",
        "description": "Suggest commands to run after editing (PR 17): targeted_test, "
                       "typecheck, lint, build, etc. Detects from package.json, "
                       "pyproject.toml, Makefile, go.mod, Cargo.toml.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "changed_files": {"type": "array", "items": {"type": "string"}},
                "related_tests": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["task"],
        },
    },
    {
        "name": "preview_patch_impact",
        "description": "PR 18 — show what may break if a file or symbol is edited: "
                       "affected routes, callers, tests, env vars, plus a risk level.",
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
    },
    {
        "name": "explain_context_selection",
        "description": (
            "Run retrieval for a task and return a structured explanation: which "
            "signals selected each item, score breakdown, graph path, confidence."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "token_budget": {"type": "integer", "default": DEFAULT_TOKEN_BUDGET},
                "retrieval": {"type": "string", "default": "auto"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "get_file_summary",
        "description": "Return symbols and capsules for a single file in the indexed repo.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]


def run_stdio(repo_path: str) -> None:
    kb = CodeGraphKB(repo_path)
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _write(_error(None, -32700, "parse error"))
            continue
        response = _dispatch(kb, request)
        if response is not None:
            _write(response)


def _dispatch(kb: CodeGraphKB, request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _ok(req_id, {"tools": TOOLS})
    if method == "tools/call":
        return _handle_tool(kb, req_id, params)
    if method == "ping":
        return _ok(req_id, {})
    return _error(req_id, -32601, f"Method not found: {method}")


def _handle_tool(kb: CodeGraphKB, req_id, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name", "")
    args = params.get("arguments") or {}
    try:
        if name == "search_code_graph":
            text = _search(kb, args)
        elif name == "get_symbol_context":
            text = _symbol_context(kb, args)
        elif name == "get_minimal_context_for_task":
            text = _minimal_context(kb, args)
        elif name == "prepare_edit_context":
            return _structured(req_id, _prepare_edit_context(kb, args))
        elif name == "get_impact_analysis":
            text = _impact(kb, args)
        elif name == "get_related_tests":
            return _structured(req_id, _related_tests_v2(kb, args))
        elif name == "plan_validation_commands":
            return _structured(req_id, _plan_validation(kb, args))
        elif name == "preview_patch_impact":
            return _structured(req_id, _patch_impact(kb, args))
        elif name == "get_callers_and_callees":
            return _structured(req_id, _callers_callees(kb, args))
        elif name == "resolve_symbol":
            return _structured(req_id, _resolve_symbol(kb, args))
        elif name == "explain_context_selection":
            return _structured(req_id, _explain_selection(kb, args))
        elif name == "get_file_summary":
            text = _file_summary(kb, args)
        else:
            return _error(req_id, -32602, f"Unknown tool: {name}")
    except FileNotFoundError as exc:
        return _ok(req_id, {
            "content": [{"type": "text", "text": str(exc)}],
            "isError": True,
        })
    except Exception as exc:
        return _ok(req_id, {
            "content": [{"type": "text", "text": f"Error: {exc}"}],
            "isError": True,
        })
    return _ok(req_id, {"content": [{"type": "text", "text": text}], "isError": False})


# ---------- tool handlers ----------

def _search(kb: CodeGraphKB, args: dict) -> str:
    query = args.get("query", "")
    limit = int(args.get("limit", 10))
    hits = kb.find_symbol(query)
    out = [f"Search results for `{query}`:"]
    for sym in hits[:limit]:
        out.append(f"- {sym.kind} `{sym.qualified_name}` — {sym.file_path}:{sym.start_line}-{sym.end_line}")
    if len(hits) <= 1:
        pack = kb.retrieve_context(query, token_budget=2000)
        for it in pack.items[:limit]:
            out.append(f"- {it.title}  ({it.file_path}:{it.start_line}-{it.end_line})")
    return "\n".join(out) if len(out) > 1 else f"No matches for `{query}`."


def _symbol_context(kb: CodeGraphKB, args: dict) -> str:
    qname = args["qualified_name"]
    include_source = bool(args.get("include_source", True))
    hits = kb.find_symbol(qname)
    if not hits:
        return f"No symbol matched `{qname}`."
    sym = hits[0]
    pack = kb.retrieve_context(
        f"Explain {sym.qualified_name}",
        token_budget=4000 if include_source else 1500,
        pinned_files=[sym.file_path],
        mode="edit" if include_source else "explain",
    )
    return pack.to_prompt()


def _minimal_context(kb: CodeGraphKB, args: dict) -> str:
    pack = kb.retrieve_context(
        args["task"],
        token_budget=int(args.get("token_budget", DEFAULT_TOKEN_BUDGET)),
        intent=args.get("intent"),
        mode=args.get("mode"),
        pinned_files=args.get("pinned_files") or [],
        retrieval=args.get("retrieval", "auto"),
    )
    return pack.to_prompt()


def _prepare_edit_context(kb: CodeGraphKB, args: dict) -> dict:
    """PR 20 — full Phase 3 edit-context pack (workflow.prepare_edit_context)."""
    from codegraphkb import workflow as workflow_mod
    task = args["task"]
    budget = int(args.get("token_budget", 6000))
    pinned = args.get("pinned_files") or []
    pack = workflow_mod.prepare_edit_context(
        kb, task, token_budget=budget, pinned_files=pinned,
    )
    return pack.to_dict()


def _impact(kb: CodeGraphKB, args: dict) -> str:
    return kb.impact(args["target"]).to_prompt()


def _related_tests_v2(kb: CodeGraphKB, args: dict) -> dict:
    """PR 16 — uses the workflow module's signal-rich test discovery."""
    from codegraphkb import workflow as workflow_mod
    target = args["target"]
    if args.get("task"):
        results = workflow_mod._related_tests_from_task(kb, target)
    else:
        results = workflow_mod.get_related_tests(kb, target)
    return {
        "target": target,
        "related_tests": [vars(r) for r in results],
    }


def _plan_validation(kb: CodeGraphKB, args: dict) -> dict:
    """PR 17 — suggest validation commands."""
    from codegraphkb import workflow as workflow_mod
    cmds = workflow_mod.plan_validation_commands(
        kb, args["task"],
        args.get("changed_files") or [],
        args.get("related_tests") or [],
    )
    return {"task": args["task"], "commands": [vars(c) for c in cmds]}


def _patch_impact(kb: CodeGraphKB, args: dict) -> dict:
    """PR 18 — affected routes/symbols/tests/config + risk level."""
    from codegraphkb import workflow as workflow_mod
    return workflow_mod.preview_patch_impact(kb, args["target"])


def _callers_callees(kb: CodeGraphKB, args: dict) -> dict:
    info = kb.callers_and_callees(args["symbol"])
    return {
        "symbol": args["symbol"],
        "callers": [_sym_dict(s) for s in info["callers"]],
        "callees": [_sym_dict(s) for s in info["callees"]],
    }


def _resolve_symbol(kb: CodeGraphKB, args: dict) -> dict:
    matches = kb.resolve_symbol(args["name_or_path"])
    return {
        "query": args["name_or_path"],
        "matches": [_sym_dict(s) for s in matches],
    }


def _explain_selection(kb: CodeGraphKB, args: dict) -> dict:
    pack = kb.retrieve_context(
        args["task"],
        token_budget=int(args.get("token_budget", DEFAULT_TOKEN_BUDGET)),
        retrieval=args.get("retrieval", "auto"),
    )
    return {
        "task": args["task"],
        "intent": pack.intent.value,
        "mode": pack.mode.value,
        "audit": pack.audit,
        "selected": [_item_dict(it) for it in pack.items],
    }


def _file_summary(kb: CodeGraphKB, args: dict) -> str:
    path = args["path"]
    pack = kb.retrieve_context(
        f"Summarize file {path}",
        pinned_files=[path],
        token_budget=4000,
    )
    return pack.to_prompt()


# ---------- helpers ----------

def _item_dict(it) -> dict:
    return {
        "kind": it.kind,
        "title": it.title,
        "file_path": it.file_path,
        "start_line": it.start_line,
        "end_line": it.end_line,
        "tokens": it.tokens,
        "retrieval_sources": it.retrieval_sources,
        "score_breakdown": it.score_breakdown.as_dict(),
        "graph_path": it.graph_path,
        "confidence": it.confidence,
        "reason": it.reason,
    }


def _sym_dict(s) -> dict:
    return {
        "qualified_name": s.qualified_name,
        "kind": s.kind,
        "file_path": s.file_path,
        "start_line": s.start_line,
        "end_line": s.end_line,
        "signature": s.signature,
    }


def _structured(req_id, payload: dict) -> dict:
    """Wrap a JSON payload as MCP tool content (text + structuredContent)."""
    return _ok(req_id, {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
        "structuredContent": payload,
        "isError": False,
    })


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _ok(req_id, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
