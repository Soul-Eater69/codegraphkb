"""Symbol alias / concept expansion (Phase 2.5 PR 9).

For each symbol, build an alias text that helps BM25 connect natural-language
queries (e.g. "token budget governor") to function names (e.g. `estimate_tokens`).

Sources combined into the alias text:
  - identifier sub-tokens (camel/snake split)
  - file path tokens
  - capsule + docstring text
  - calls/imports/extends names (graph neighbors)
  - kind-specific concept words (e.g. `route` -> `endpoint api http`)
  - heuristic synonyms for stems found in the symbol name
"""
from __future__ import annotations

import re

from codegraphkb.core.parsers.base import ParsedEdge, ParsedSymbol

_KIND_CONCEPTS: dict[str, list[str]] = {
    "route": ["endpoint", "api", "http", "handler", "route"],
    "component": ["component", "ui", "react", "view", "render"],
    "test": ["test", "spec", "verify", "assert", "expectation"],
    "class": ["class", "type", "model"],
    "method": ["method", "operation"],
    "function": ["function", "operation"],
}

_STEM_CONCEPTS: list[tuple[re.Pattern, list[str]]] = [
    # rough query-language ↔ identifier-stem expansions
    (re.compile(r"token", re.I), ["token", "budget", "context", "size", "prompt", "count", "cost"]),
    (re.compile(r"estimate", re.I), ["estimate", "predict", "approximate"]),
    (re.compile(r"truncate", re.I), ["truncate", "limit", "trim", "cut", "shrink", "fit"]),
    (re.compile(r"capsule", re.I), ["capsule", "summary", "card", "compact"]),
    (re.compile(r"retriev", re.I), ["retrieve", "fetch", "get", "lookup", "search"]),
    (re.compile(r"index", re.I), ["index", "ingest", "build", "scan"]),
    (re.compile(r"parse", re.I), ["parse", "extract", "ast", "structure"]),
    (re.compile(r"embed", re.I), ["embed", "vector", "semantic", "similarity"]),
    (re.compile(r"auth", re.I), ["auth", "authentication", "login", "session", "token", "permission"]),
    (re.compile(r"upload", re.I), ["upload", "file", "save", "ingest"]),
    (re.compile(r"router?", re.I), ["route", "endpoint", "api", "url"]),
    (re.compile(r"score|rank", re.I), ["score", "rank", "sort", "priority"]),
    (re.compile(r"graph", re.I), ["graph", "neighbor", "edge", "node", "traverse"]),
    (re.compile(r"impact", re.I), ["impact", "affected", "blast", "radius", "callers"]),
    (re.compile(r"refactor", re.I), ["refactor", "rewrite", "reorganize"]),
    (re.compile(r"validate", re.I), ["validate", "check", "verify", "ensure"]),
    (re.compile(r"config", re.I), ["config", "configuration", "settings", "option"]),
    (re.compile(r"store|persist", re.I), ["store", "persist", "save", "database"]),
    (re.compile(r"scan", re.I), ["scan", "walk", "traverse", "discover"]),
    (re.compile(r"ignore", re.I), ["ignore", "exclude", "filter", "skip"]),
    (re.compile(r"hybrid|rrf", re.I), ["hybrid", "fuse", "fusion", "rrf", "combine"]),
    (re.compile(r"budget", re.I), ["budget", "limit", "allocate", "share", "cap"]),
    (re.compile(r"governor", re.I), ["governor", "control", "policy", "regulate"]),
    (re.compile(r"mcp", re.I), ["mcp", "tool", "context", "protocol"]),
]


def build_alias_text(
    sym: ParsedSymbol,
    file_path: str,
    outgoing_edges: list[ParsedEdge],
) -> str:
    """Generate a single string of alias terms for a symbol's BM25 doc.

    Returns space-separated terms; the indexer's tokenizer will split it further.
    """
    parts: list[str] = []
    parts.extend(_split_identifier(sym.name))
    parts.extend(_split_identifier(sym.qualified_name.split(".")[-1]))
    parts.extend(_path_tokens(file_path))

    if sym.kind in _KIND_CONCEPTS:
        parts.extend(_KIND_CONCEPTS[sym.kind])

    # Concept synonyms based on stems in the symbol name
    for pattern, expansions in _STEM_CONCEPTS:
        if pattern.search(sym.name) or pattern.search(sym.qualified_name):
            parts.extend(expansions)

    # Graph neighbors (calls/imports/extends/routes_to) — names only
    seen: set[str] = set()
    for edge in outgoing_edges:
        if edge.edge_type not in {"CALLS", "IMPORTS", "EXTENDS", "ROUTES_TO"}:
            continue
        last = edge.dst_name.rsplit(".", 1)[-1]
        for tok in _split_identifier(last):
            if tok and tok not in seen:
                seen.add(tok)
                parts.append(tok)

    # Routes carry path + method as searchable text.
    if sym.kind == "route" and sym.extras:
        method = str(sym.extras.get("http_method") or "")
        path = str(sym.extras.get("path") or "")
        if method:
            parts.append(method.lower())
        if path:
            parts.extend(re.findall(r"[A-Za-z][A-Za-z0-9_]+", path))

    return " ".join(parts)


def _split_identifier(name: str) -> list[str]:
    out: list[str] = []
    for chunk in re.split(r"[._\-/]+", name):
        if not chunk:
            continue
        for m in re.finditer(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", chunk):
            tok = m.group(0).lower()
            if len(tok) > 1:
                out.append(tok)
    return out


def _path_tokens(path: str) -> list[str]:
    out: list[str] = []
    for chunk in re.split(r"[/\\]+", path):
        for m in re.finditer(r"[A-Za-z][A-Za-z0-9_]+", chunk):
            tok = m.group(0).lower()
            if len(tok) > 1 and tok not in {"py", "ts", "tsx", "js", "jsx"}:
                out.append(tok)
    return out
