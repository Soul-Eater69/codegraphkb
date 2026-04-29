"""Next.js routes — both `app/` (file-based) and `pages/` (legacy).

For `app/<segment>/route.ts` we emit a Route per exported HTTP-method function
(`export async function GET()`). For `pages/api/x.ts` we emit ANY route.
"""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_ROUTE_HANDLED_BY, FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_NEXT_HANDLER_RE = re.compile(
    r"export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b"
)


def detect_nextjs(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    rel = source.rel_path.replace("\\", "/")
    if "/app/" not in "/" + rel + "/" and "/pages/" not in "/" + rel + "/":
        return FrameworkExtraction()

    out = FrameworkExtraction()
    if "/app/" in "/" + rel + "/" and rel.endswith(("route.ts", "route.tsx",
                                                     "route.js", "route.jsx")):
        url_path = _app_route_path(rel)
        for m in _NEXT_HANDLER_RE.finditer(source.content):
            method = m.group(1)
            line = source.content[: m.start()].count("\n") + 1
            qname = f"nextjs::{method} {url_path}"
            out.extra_symbols.append(ParsedSymbol(
                kind="route",
                name=f"{method} {url_path}",
                qualified_name=qname,
                start_line=line,
                end_line=line,
                signature=f"Next.js route {method} {url_path}",
                extras={"framework": "nextjs", "http_method": method,
                        "path": url_path, "handler": method},
            ))
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=method,
                edge_type=EDGE_ROUTE_HANDLED_BY,
                confidence=0.9,
                extraction_source="extractor:nextjs",
                line=line,
            ))
    elif "/pages/api/" in "/" + rel + "/":
        url_path = _pages_api_path(rel)
        qname = f"nextjs::ANY {url_path}"
        out.extra_symbols.append(ParsedSymbol(
            kind="route",
            name=f"ANY {url_path}",
            qualified_name=qname,
            start_line=1,
            end_line=1,
            signature=f"Next.js pages API route {url_path}",
            extras={"framework": "nextjs_pages", "http_method": "ANY",
                    "path": url_path, "handler": "default"},
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


def _app_route_path(rel: str) -> str:
    """Map `src/app/api/users/[id]/route.ts` → `/api/users/[id]`."""
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
