"""Next.js routes — both `app/` (file-based) and `pages/` (legacy).

For ``app/<segment>/route.ts`` we emit one Route per exported HTTP-method
function (``export async function GET()``). The Route's HANDLES_ROUTE edge
points at the function's qname so it lines up with the syntax/semantic graph
without needing an additional resolution pass.

For ``pages/api/x.ts`` we emit a single ANY route bound to the file's default
export (when present) or to the file qname.
"""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_HANDLES_ROUTE,
    EDGE_ROUTE_HANDLED_BY,
    FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_NEXT_HANDLER_RE = re.compile(
    r"export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b"
)


def detect_nextjs(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    rel = source.rel_path.replace("\\", "/")
    padded = "/" + rel + "/"
    if "/app/" not in padded and "/pages/" not in padded:
        return FrameworkExtraction()

    out = FrameworkExtraction()
    file_qname = _file_qname(rel)
    symbols_by_name = {s.name: s for s in extract.symbols}

    if "/app/" in padded and rel.endswith(("route.ts", "route.tsx",
                                           "route.js", "route.jsx")):
        url_path = _app_route_path(rel)
        for m in _NEXT_HANDLER_RE.finditer(source.content):
            method = m.group(1)
            line = source.content[: m.start()].count("\n") + 1
            handler_qname = _handler_qname(symbols_by_name, file_qname, method)
            qname = f"nextjs::{method} {url_path}"
            out.extra_symbols.append(ParsedSymbol(
                kind="route",
                name=f"{method} {url_path}",
                qualified_name=qname,
                start_line=line,
                end_line=line,
                signature=f"Next.js route {method} {url_path}",
                extras={
                    "framework": "nextjs", "http_method": method,
                    "path": url_path, "handler": method,
                    "handler_qname": handler_qname,
                },
            ))
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=method,
                edge_type=EDGE_HANDLES_ROUTE,
                confidence=0.9,
                extraction_source="extractor:nextjs",
                line=line,
                metadata={
                    "http_method": method, "path": url_path,
                    "framework": "nextjs",
                    "resolved_handler_qname": handler_qname or "",
                },
            ))
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=method,
                edge_type=EDGE_ROUTE_HANDLED_BY,
                confidence=0.9,
                extraction_source="extractor:nextjs",
                line=line,
            ))
    elif "/pages/api/" in padded:
        url_path = _pages_api_path(rel)
        qname = f"nextjs::ANY {url_path}"
        handler_qname = _handler_qname(symbols_by_name, file_qname, "default")
        out.extra_symbols.append(ParsedSymbol(
            kind="route",
            name=f"ANY {url_path}",
            qualified_name=qname,
            start_line=1,
            end_line=1,
            signature=f"Next.js pages API route {url_path}",
            extras={
                "framework": "nextjs_pages", "http_method": "ANY",
                "path": url_path, "handler": "default",
                "handler_qname": handler_qname,
            },
        ))
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=qname,
            dst_name="default",
            edge_type=EDGE_HANDLES_ROUTE,
            confidence=0.85,
            extraction_source="extractor:nextjs_pages",
            line=1,
            metadata={
                "http_method": "ANY", "path": url_path,
                "framework": "nextjs_pages",
                "resolved_handler_qname": handler_qname or "",
            },
        ))
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=qname,
            dst_name="default",
            edge_type=EDGE_ROUTE_HANDLED_BY,
            confidence=0.85,
            extraction_source="extractor:nextjs_pages",
            line=1,
        ))

    if out.extra_symbols:
        out.detected_frameworks.append("nextjs")
    return out


def _handler_qname(symbols_by_name: dict, file_qname: str, name: str) -> str | None:
    sym = symbols_by_name.get(name)
    if sym is not None:
        return sym.qualified_name
    return f"{file_qname}.{name}" if file_qname else None


def _file_qname(rel: str) -> str:
    no_ext = re.sub(r"\.[tj]sx?$", "", rel)
    return no_ext.replace("\\", "/").replace("/", ".")


def _app_route_path(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    try:
        idx = parts.index("app")
    except ValueError:
        return "/"
    parts = parts[idx + 1: -1]  # strip the `route.*` filename
    return "/" + "/".join(p for p in parts if not (p.startswith("(") and p.endswith(")")))


def _pages_api_path(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    try:
        idx = parts.index("pages")
    except ValueError:
        return "/"
    parts = parts[idx + 1:]
    last = parts[-1]
    last = re.sub(r"\.[tj]sx?$", "", last)
    if last == "index":
        parts = parts[:-1]
    else:
        parts = parts[:-1] + [last]
    return "/" + "/".join(parts)
