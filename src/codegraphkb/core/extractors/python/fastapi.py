"""FastAPI route detector. Already partially handled in the python parser, but
this surfaces them as first-class `route` objects with framework="fastapi" and
adds `ROUTE_HANDLED_BY` edges from the route to its handler (vs. the existing
ROUTES_TO direction)."""
from __future__ import annotations

import ast

from codegraphkb.core.extractors.base import (
    EDGE_ROUTE_HANDLED_BY, FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options",
                 "api_route", "websocket"}


def detect_fastapi(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    if "fastapi" not in source.content.lower():
        return FrameworkExtraction()
    try:
        tree = ast.parse(source.content)
    except SyntaxError:
        return FrameworkExtraction()

    out = FrameworkExtraction()
    detected = False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            method_name = ""
            if isinstance(target, ast.Attribute):
                method_name = target.attr
            elif isinstance(target, ast.Name):
                method_name = target.id
            if method_name.lower() not in _HTTP_METHODS:
                continue
            args = decorator.args if isinstance(decorator, ast.Call) else []
            path = "?"
            if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                path = args[0].value
            method = method_name.upper() if method_name != "api_route" else "ANY"
            handler_qname = node.name  # parser's qname will resolve via dst_name
            route_qname = f"fastapi::{method} {path}"
            detected = True
            out.extra_symbols.append(ParsedSymbol(
                kind="route",
                name=f"{method} {path}",
                qualified_name=route_qname,
                start_line=getattr(decorator, "lineno", node.lineno),
                end_line=node.lineno,
                signature=f"FastAPI route {method} {path} -> {node.name}",
                extras={
                    "framework": "fastapi",
                    "http_method": method,
                    "path": path,
                    "handler": node.name,
                },
            ))
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=route_qname,
                dst_name=node.name,
                edge_type=EDGE_ROUTE_HANDLED_BY,
                confidence=0.95,
                extraction_source="extractor:fastapi",
                line=getattr(decorator, "lineno", node.lineno),
            ))
    if detected:
        out.detected_frameworks.append("fastapi")
    return out
