"""Express + Fastify route detector for JS/TS."""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_ROUTE_HANDLED_BY, FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_ROUTE_RE = re.compile(
    r"""\b(?P<obj>app|router|fastify|server)\.
        (?P<method>get|post|put|patch|delete|head|options|all|use)
        \s*\(\s*
        ["'`](?P<path>[^"'`]+)["'`]
        \s*,\s*
        (?P<handler>[A-Za-z_$][\w$.]*)
    """,
    re.VERBOSE,
)


def detect_express(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    if not any(needle in source.content for needle in ("express", "fastify", ".get(", ".post(")):
        return FrameworkExtraction()
    out = FrameworkExtraction()
    for m in _ROUTE_RE.finditer(source.content):
        method = m.group("method").upper()
        path = m.group("path")
        handler = m.group("handler").rsplit(".", 1)[-1]
        line = source.content[: m.start()].count("\n") + 1
        framework = "fastify" if "fastify" in m.group("obj").lower() else "express"
        qname = f"{framework}::{method} {path}"
        out.extra_symbols.append(ParsedSymbol(
            kind="route",
            name=f"{method} {path}",
            qualified_name=qname,
            start_line=line,
            end_line=line,
            signature=f"{framework} route {method} {path} -> {handler}",
            extras={"framework": framework, "http_method": method,
                    "path": path, "handler": handler},
        ))
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=qname,
            dst_name=handler,
            edge_type=EDGE_ROUTE_HANDLED_BY,
            confidence=0.85,
            extraction_source=f"extractor:{framework}",
            line=line,
        ))
    if out.extra_symbols:
        out.detected_frameworks.append("express_or_fastify")
    return out
