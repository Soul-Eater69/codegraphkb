"""Compact LLM-readable summary cards for symbols (Context Capsules)."""
from __future__ import annotations

from codegraphkb.core.parsers.base import ParsedEdge, ParsedSymbol


def build_symbol_capsule(symbol: ParsedSymbol, file_path: str,
                         outgoing_edges: list[ParsedEdge]) -> str:
    """Generate a small markdown capsule for a single symbol.

    Capsules are intentionally short — they replace exact source for many queries.
    """
    lines = [
        f"### {symbol.kind.title()}: {symbol.qualified_name}",
        f"- File: `{file_path}:{symbol.start_line}-{symbol.end_line}`",
    ]
    if symbol.signature:
        lines.append(f"- Signature: `{symbol.signature}`")
    if symbol.docstring:
        first_line = symbol.docstring.strip().splitlines()[0][:240]
        lines.append(f"- Doc: {first_line}")
    if symbol.kind == "route" and symbol.extras:
        method = symbol.extras.get("http_method", "?")
        path = symbol.extras.get("path", "?")
        lines.append(f"- HTTP: `{method} {path}`")

    calls = sorted({e.dst_name for e in outgoing_edges if e.edge_type == "CALLS"})
    if calls:
        lines.append(f"- Calls: {', '.join(calls[:12])}" + (" …" if len(calls) > 12 else ""))
    extends = [e.dst_name for e in outgoing_edges if e.edge_type == "EXTENDS"]
    if extends:
        lines.append(f"- Extends: {', '.join(extends)}")
    routes = [e.dst_name for e in outgoing_edges if e.edge_type == "ROUTES_TO"]
    if routes:
        lines.append(f"- Handler: {', '.join(routes)}")
    return "\n".join(lines)
