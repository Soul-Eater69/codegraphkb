"""Flask + Django route detector (URL patterns + decorator-based)."""
from __future__ import annotations

import ast
import re

from codegraphkb.core.extractors.base import (
    EDGE_ROUTE_HANDLED_BY, FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile


def detect_flask(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    text = source.content
    is_flask = "flask" in text.lower()
    is_django = "django" in text.lower() or "urls.py" in source.rel_path.lower()
    if not (is_flask or is_django):
        return FrameworkExtraction()

    out = FrameworkExtraction()
    if is_flask:
        out.extra_symbols.extend(_scan_flask_routes(source))
        out.extra_edges.extend(_flask_edges(out.extra_symbols))
        if out.extra_symbols:
            out.detected_frameworks.append("flask")
    if is_django:
        django_syms = _scan_django_urls(source)
        out.extra_symbols.extend(django_syms)
        out.extra_edges.extend(_flask_edges(django_syms))
        if django_syms:
            out.detected_frameworks.append("django")
    return out


def _scan_flask_routes(source: SourceFile) -> list[ParsedSymbol]:
    try:
        tree = ast.parse(source.content)
    except SyntaxError:
        return []
    syms: list[ParsedSymbol] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            attr = target.attr if isinstance(target, ast.Attribute) else None
            if attr not in {"route", "get", "post", "put", "delete", "patch"}:
                continue
            args = decorator.args if isinstance(decorator, ast.Call) else []
            path = "?"
            if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
                path = args[0].value
            method = (attr or "ANY").upper() if attr != "route" else "ANY"
            qname = f"flask::{method} {path}"
            syms.append(ParsedSymbol(
                kind="route",
                name=f"{method} {path}",
                qualified_name=qname,
                start_line=getattr(decorator, "lineno", node.lineno),
                end_line=node.lineno,
                signature=f"Flask route {method} {path} -> {node.name}",
                extras={"framework": "flask", "http_method": method,
                        "path": path, "handler": node.name},
            ))
    return syms


def _scan_django_urls(source: SourceFile) -> list[ParsedSymbol]:
    """Scan for `path('...', view)` / `re_path('...', view)` entries in urls.py."""
    syms: list[ParsedSymbol] = []
    pat = re.compile(
        r"\b(?:path|re_path|url)\(\s*['\"]([^'\"]+)['\"]\s*,\s*([A-Za-z_][\w.]*)"
    )
    for m in pat.finditer(source.content):
        url_path = m.group(1)
        view = m.group(2).split(".")[-1]
        line = source.content[: m.start()].count("\n") + 1
        qname = f"django::ANY {url_path}"
        syms.append(ParsedSymbol(
            kind="route",
            name=f"ANY {url_path}",
            qualified_name=qname,
            start_line=line,
            end_line=line,
            signature=f"Django URL {url_path} -> {view}",
            extras={"framework": "django", "http_method": "ANY",
                    "path": url_path, "handler": view},
        ))
    return syms


def _flask_edges(routes: list[ParsedSymbol]) -> list[ParsedEdge]:
    out: list[ParsedEdge] = []
    for r in routes:
        handler = (r.extras or {}).get("handler")
        if not handler:
            continue
        out.append(ParsedEdge(
            src_qualified_name=r.qualified_name,
            dst_name=handler,
            edge_type=EDGE_ROUTE_HANDLED_BY,
            confidence=0.9,
            extraction_source="extractor:flask_django",
            line=r.start_line,
        ))
    return out
