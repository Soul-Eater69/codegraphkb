"""Express route detector.

Emits, for each `app|router.METHOD(path, ...handlers)`:

* a Route symbol  (``express::METHOD path``)
* ``Route --HANDLES_ROUTE--> handler``         (Phase 3.2 framework edge)
* ``Route --ROUTE_HANDLED_BY--> handler``      (legacy, kept for back-compat)
* ``Route --USES_MIDDLEWARE--> middleware``    (one per intermediate arg)

The handler is the *last* identifier in the call's argument list; everything
between the path and the handler is treated as middleware.

Fastify is detected separately (see ``fastify.py``); this module restricts
itself to Express-style ``app|router|server`` invocations to avoid duplicate
extraction.
"""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_HANDLES_ROUTE,
    EDGE_ROUTE_HANDLED_BY,
    EDGE_USES_MIDDLEWARE,
    FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

# Match `app|router|server.METHOD(  "path", ... )`. We capture the leading
# identifiers and let the post-processor split out handlers + middleware.
_ROUTE_HEAD_RE = re.compile(
    r"""\b(?P<obj>app|router|server)\.
        (?P<method>get|post|put|patch|delete|head|options|all|use)
        \s*\(\s*
        ["'`](?P<path>[^"'`]+)["'`]
        (?P<rest>[^)]*)
    """,
    re.VERBOSE,
)
_IDENT_RE = re.compile(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)")


def detect_express(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    text = source.content
    if not any(needle in text for needle in (
        "express", " from 'express'", "require('express",
        "app.get(", "app.post(", "app.put(", "app.patch(", "app.delete(",
        "router.get(", "router.post(", "router.put(", "router.patch(", "router.delete(",
    )):
        return FrameworkExtraction()

    out = FrameworkExtraction()
    for m in _ROUTE_HEAD_RE.finditer(text):
        obj = m.group("obj").lower()
        method = m.group("method").upper()
        path = m.group("path")
        rest = m.group("rest") or ""
        line = text[: m.start()].count("\n") + 1

        # Skip `app.use(...)` without a path mounted to a router — it's middleware
        # registration, not a route.
        if method == "USE":
            continue

        names = _identifiers(rest)
        if not names:
            continue
        handler = names[-1]
        middlewares = names[:-1]
        handler_short = handler.rsplit(".", 1)[-1]

        framework = "express"
        qname = f"{framework}::{method} {path}"
        out.extra_symbols.append(ParsedSymbol(
            kind="route",
            name=f"{method} {path}",
            qualified_name=qname,
            start_line=line,
            end_line=line,
            signature=f"{framework} route {method} {path} -> {handler}",
            extras={
                "framework": framework,
                "object": obj,
                "http_method": method,
                "path": path,
                "handler": handler_short,
                "middleware": middlewares,
            },
        ))
        # New (Phase 3.2): Route → handler with HANDLES_ROUTE.
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=qname,
            dst_name=handler_short,
            edge_type=EDGE_HANDLES_ROUTE,
            confidence=0.85,
            extraction_source=f"extractor:{framework}",
            line=line,
            metadata={
                "http_method": method, "path": path,
                "framework": framework, "handler_form": handler,
            },
        ))
        # Legacy edge kept so older callers/tests stay green.
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=qname,
            dst_name=handler_short,
            edge_type=EDGE_ROUTE_HANDLED_BY,
            confidence=0.85,
            extraction_source=f"extractor:{framework}",
            line=line,
        ))
        for mw in middlewares:
            mw_short = mw.rsplit(".", 1)[-1]
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=mw_short,
                edge_type=EDGE_USES_MIDDLEWARE,
                confidence=0.7,
                extraction_source=f"extractor:{framework}",
                line=line,
                metadata={"middleware_form": mw},
            ))

    if out.extra_symbols:
        out.detected_frameworks.append("express")
    return out


def _identifiers(arg_chunk: str) -> list[str]:
    """Pick out top-level identifier-arguments in a call's argument list.

    Skips anonymous handlers (``(req,res)=>...``) and inline literals — the
    syntax extractor already records those as anonymous functions.
    """
    out: list[str] = []
    # Cheap arrow-function/inline detection: bail out of an arg if we see ``=>``
    # before its terminating comma.
    depth = 0
    cur: list[str] = []
    arrow = False
    for ch in arg_chunk:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if depth == 0 and ch == ",":
            piece = "".join(cur).strip()
            if piece and not arrow:
                _emit_ident(piece, out)
            cur, arrow = [], False
            continue
        if ch == ">" and cur and cur[-1] == "=":
            arrow = True
        cur.append(ch)
    piece = "".join(cur).strip()
    if piece and not arrow:
        _emit_ident(piece, out)
    return out


def _emit_ident(piece: str, out: list[str]) -> None:
    m = _IDENT_RE.match(piece)
    if m and m.group(1) not in {"function", "async"}:
        out.append(m.group(1))


# Backwards-compatibility shim (older imports may still reference this).
_ROUTE_RE = _ROUTE_HEAD_RE
