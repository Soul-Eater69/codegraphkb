"""Minimal MCP server (stdio JSON-RPC 2.0).

Implements just enough of the Model Context Protocol for Claude Desktop / Cursor
/ Windsurf to discover and invoke CodeGraphKB tools without any extra dependency.

Tools exposed:
  - search_code_graph
  - get_symbol_context
  - get_minimal_context_for_task
  - get_impact_analysis
  - get_file_summary
"""
from __future__ import annotations

import json
import sys
from typing import Any

from codegraphkb.api import CodeGraphKB
from codegraphkb.config import DEFAULT_TOKEN_BUDGET

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "codegraphkb", "version": "0.1.0"}

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
                "pinned_files": {"type": "array", "items": {"type": "string"}},
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
    # Lazily verify the index exists; surface a friendly error on first call.
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
        elif name == "get_impact_analysis":
            text = _impact(kb, args)
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


def _search(kb: CodeGraphKB, args: dict) -> str:
    query = args.get("query", "")
    limit = int(args.get("limit", 10))
    hits = kb.find_symbol(query)
    out = [f"Search results for `{query}`:"]
    for sym in hits[:limit]:
        out.append(f"- {sym.kind} `{sym.qualified_name}` — {sym.file_path}:{sym.start_line}-{sym.end_line}")
    if len(hits) <= 1:
        # fall back to retrieval-style search
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
    )
    return pack.to_prompt()


def _minimal_context(kb: CodeGraphKB, args: dict) -> str:
    task = args["task"]
    budget = int(args.get("token_budget", DEFAULT_TOKEN_BUDGET))
    intent = args.get("intent")
    pinned = args.get("pinned_files") or []
    pack = kb.retrieve_context(task, token_budget=budget, intent=intent, pinned_files=pinned)
    return pack.to_prompt()


def _impact(kb: CodeGraphKB, args: dict) -> str:
    return kb.impact(args["target"]).to_prompt()


def _file_summary(kb: CodeGraphKB, args: dict) -> str:
    path = args["path"]
    pack = kb.retrieve_context(f"Summarize file {path}", pinned_files=[path], token_budget=4000)
    return pack.to_prompt()


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _ok(req_id, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
