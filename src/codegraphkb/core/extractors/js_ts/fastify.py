"""Fastify route detector.

Two forms are supported:

* ``fastify.METHOD(path, ..., handler)`` — same shape as Express, but on a
  ``fastify`` / ``app`` (only when the file imports fastify) receiver.
* ``fastify.route({ method, url, handler, preHandler })`` — config-object form.

Emits a ``Route`` symbol plus ``HANDLES_ROUTE`` (and the legacy
``ROUTE_HANDLED_BY``) edge.
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

_FASTIFY_RECEIVERS = ("fastify", "app", "server", "instance")

_METHOD_CALL_RE = re.compile(
    r"""\b(?P<obj>%s)\.
        (?P<method>get|post|put|patch|delete|head|options|all)
        \s*\(\s*
        ["'`](?P<path>[^"'`]+)["'`]
        (?P<rest>[^)]*)
    """ % "|".join(_FASTIFY_RECEIVERS),
    re.VERBOSE,
)
_ROUTE_OBJ_RE = re.compile(
    r"""\b(?P<obj>%s)\.route\s*\(\s*\{(?P<body>[^}]*)\}""" % "|".join(_FASTIFY_RECEIVERS),
    re.VERBOSE,
)
_KV_RE = re.compile(r"""([A-Za-z_][\w]*)\s*:\s*(['"`][^'"`]*['"`]|[A-Za-z_$][\w$.]*)""")
_LIST_IDENT_RE = re.compile(r"\b([A-Za-z_$][\w$.]*)")


def detect_fastify(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    text = source.content
    if "fastify" not in text.lower():
        return FrameworkExtraction()

    out = FrameworkExtraction()

    # Form 1: fastify.METHOD(path, ..., handler)
    for m in _METHOD_CALL_RE.finditer(text):
        obj = m.group("obj").lower()
        method = m.group("method").upper()
        path = m.group("path")
        rest = m.group("rest") or ""
        line = text[: m.start()].count("\n") + 1

        names = _identifiers(rest)
        if not names:
            continue
        handler = names[-1].rsplit(".", 1)[-1]
        middlewares = [n.rsplit(".", 1)[-1] for n in names[:-1]]
        _emit_route(out, method, path, handler, middlewares, line, obj)

    # Form 2: fastify.route({ method, url, handler, preHandler })
    for m in _ROUTE_OBJ_RE.finditer(text):
        obj = m.group("obj").lower()
        body = m.group("body") or ""
        line = text[: m.start()].count("\n") + 1
        kv = {k.lower(): v for k, v in _KV_RE.findall(body)}
        method_raw = _strip_quotes(kv.get("method", ""))
        url = _strip_quotes(kv.get("url", "") or kv.get("path", ""))
        handler_token = kv.get("handler", "")
        if not (method_raw and url and handler_token):
            continue
        method = method_raw.upper()
        handler = handler_token.rsplit(".", 1)[-1]
        middlewares: list[str] = []
        for key in ("prehandler", "onrequest", "preparsing", "preserialization"):
            mw_token = kv.get(key)
            if not mw_token:
                continue
            for ident in _LIST_IDENT_RE.findall(mw_token):
                if ident:
                    middlewares.append(ident.rsplit(".", 1)[-1])
        _emit_route(out, method, url, handler, middlewares, line, obj)

    if out.extra_symbols:
        out.detected_frameworks.append("fastify")
    return out


def _emit_route(out: FrameworkExtraction, method: str, path: str,
                handler: str, middlewares: list[str], line: int, obj: str) -> None:
    qname = f"fastify::{method} {path}"
    out.extra_symbols.append(ParsedSymbol(
        kind="route",
        name=f"{method} {path}",
        qualified_name=qname,
        start_line=line,
        end_line=line,
        signature=f"fastify route {method} {path} -> {handler}",
        extras={
            "framework": "fastify", "object": obj,
            "http_method": method, "path": path,
            "handler": handler, "middleware": middlewares,
        },
    ))
    out.extra_edges.append(ParsedEdge(
        src_qualified_name=qname,
        dst_name=handler,
        edge_type=EDGE_HANDLES_ROUTE,
        confidence=0.85,
        extraction_source="extractor:fastify",
        line=line,
        metadata={"http_method": method, "path": path, "framework": "fastify"},
    ))
    out.extra_edges.append(ParsedEdge(
        src_qualified_name=qname,
        dst_name=handler,
        edge_type=EDGE_ROUTE_HANDLED_BY,
        confidence=0.85,
        extraction_source="extractor:fastify",
        line=line,
    ))
    for mw in middlewares:
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=qname,
            dst_name=mw,
            edge_type=EDGE_USES_MIDDLEWARE,
            confidence=0.7,
            extraction_source="extractor:fastify",
            line=line,
        ))


def _identifiers(arg_chunk: str) -> list[str]:
    out: list[str] = []
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
                m = _LIST_IDENT_RE.match(piece)
                if m and m.group(1) not in {"function", "async"}:
                    out.append(m.group(1))
            cur, arrow = [], False
            continue
        if ch == ">" and cur and cur[-1] == "=":
            arrow = True
        cur.append(ch)
    piece = "".join(cur).strip()
    if piece and not arrow:
        m = _LIST_IDENT_RE.match(piece)
        if m and m.group(1) not in {"function", "async"}:
            out.append(m.group(1))
    return out


def _strip_quotes(value: str) -> str:
    if value and value[0] in ("'", '"', "`") and value[-1] == value[0]:
        return value[1:-1]
    return value
