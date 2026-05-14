"""Lightweight Go parser for indexing-oriented code intelligence."""
from __future__ import annotations

import re

from codegraphkb.core.parsers.base import (
    ExtractResult,
    ImportBinding,
    ParsedEdge,
    ParsedSymbol,
)
from codegraphkb.core.parsers.regex_utils import (
    find_matching_brace,
    line_number,
    module_from_path,
    normalize_route_path,
)
from codegraphkb.core.scanner import SourceFile

GO_PARSER_VERSION = 1

_PACKAGE_RE = re.compile(r"(?m)^\s*package\s+([A-Za-z_]\w*)\b")
_IMPORT_BLOCK_RE = re.compile(r"(?ms)^\s*import\s*\((?P<body>.*?)\)")
_IMPORT_LINE_RE = re.compile(
    r"""(?mx)^\s*import\s+(?:(?P<alias>[A-Za-z_]\w*|[._])\s+)?["'](?P<module>[^"']+)["']"""
)
_IMPORT_IN_BLOCK_RE = re.compile(
    r"""(?m)^\s*(?:(?P<alias>[A-Za-z_]\w*|[._])\s+)?["'](?P<module>[^"']+)["']"""
)
_TYPE_RE = re.compile(r"(?m)^\s*type\s+(?P<name>[A-Za-z_]\w*)\s+(?P<kind>struct|interface)\s*\{")
_FUNC_RE = re.compile(
    r"""(?mx)
    ^\s*func\s+
    (?:
        \(\s*(?P<recv_name>[A-Za-z_]\w*)\s+(?P<recv_ptr>\*)?(?P<recv_type>[A-Za-z_]\w*)\s*\)\s*
    )?
    (?P<name>[A-Za-z_]\w*)\s*
    \((?P<params>[^)]*)\)\s*
    (?P<return>[^{\n]*)\{
    """
)
_CONST_RE = re.compile(
    r"(?m)^\s*(?P<kind>const|var)\s+(?:\(\s*)?(?P<name>[A-Za-z_]\w*)\b(?P<rest>[^\n]*)"
)
_CALL_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\(")
_ROUTER_RE = re.compile(
    r"""\b[A-Za-z_]\w*\.(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*
        \(\s*["'](?P<path>[^"']+)["']\s*,\s*(?P<handler>[A-Za-z_]\w*)""",
    re.VERBOSE,
)
_HANDLE_FUNC_RE = re.compile(
    r"""\b(?:http\.)?HandleFunc\s*\(\s*["'](?P<path>[^"']+)["']\s*,\s*(?P<handler>[A-Za-z_]\w*)""",
    re.VERBOSE,
)
_GO_KEYWORDS = frozenset({
    "if", "for", "switch", "select", "return", "go", "defer", "range",
    "func", "make", "new", "append", "len", "cap", "copy", "delete",
    "panic", "recover", "close", "complex", "real", "imag",
})


def parse_go(source: SourceFile) -> ExtractResult:
    text = source.content
    rel = source.rel_path
    package = _detect_package(text) or module_from_path(rel, ".go")
    symbols: list[ParsedSymbol] = []
    edges: list[ParsedEdge] = []
    imports: list[ImportBinding] = []

    for module, alias, start in _iter_imports(text):
        line = line_number(text, start)
        local = alias if alias and alias not in {".", "_"} else module.rsplit("/", 1)[-1]
        edges.append(ParsedEdge(
            src_qualified_name=package,
            dst_name=module,
            edge_type="IMPORTS",
            line=line,
            extraction_source="regex",
            reason="go.import",
        ))
        if local and local not in {".", "_"}:
            imports.append(ImportBinding(
                file_path=rel,
                local_name=local,
                imported_name=local,
                source_module=module,
                import_kind="named",
                line=line,
                reason="go.import",
                metadata={"alias": alias or ""},
            ))

    for m in _TYPE_RE.finditer(text):
        name = m.group("name")
        kind = "struct" if m.group("kind") == "struct" else "interface"
        open_pos = m.end() - 1
        close_pos = find_matching_brace(text, open_pos)
        qname = _qname(package, name)
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=qname,
            start_line=line_number(text, m.start()),
            end_line=line_number(text, close_pos),
            signature=" ".join(text[m.start():m.end()].split()),
            parent_qualified_name=package or None,
            extras={"language": "go"},
        ))

    function_symbols: dict[str, str] = {}
    for m in _FUNC_RE.finditer(text):
        name = m.group("name")
        recv_type = m.group("recv_type") or ""
        params = (m.group("params") or "").strip()
        return_type = (m.group("return") or "").strip()
        open_pos = m.end() - 1
        close_pos = find_matching_brace(text, open_pos)
        line = line_number(text, m.start())
        if recv_type:
            owner = _qname(package, recv_type)
            kind = "method"
            qname = f"{owner}.{name}"
            signature = f"func ({m.group('recv_name')} {m.group('recv_ptr') or ''}{recv_type}) {name}({params}) {return_type}".strip()
            parent = owner
        else:
            kind = "test_block" if name.startswith("Test") and "testing.T" in params else "function"
            qname = _qname(package, name)
            signature = f"func {name}({params}) {return_type}".strip()
            parent = package or None
        function_symbols[name] = qname
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=qname,
            start_line=line,
            end_line=line_number(text, close_pos),
            signature=signature,
            return_type=return_type,
            parent_qualified_name=parent,
            extras={
                "language": "go",
                "receiver": f"{m.group('recv_ptr') or ''}{recv_type}" if recv_type else "",
            },
        ))
        body = text[m.end():close_pos]
        for call in _calls_in(body):
            edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=call,
                edge_type="CALLS",
                confidence=0.55,
                extraction_source="regex",
                line=line,
                reason="go.call",
            ))

    for m in _CONST_RE.finditer(text):
        name = m.group("name")
        kind = "constant" if m.group("kind") == "const" else "variable"
        if name in {"const", "var"}:
            continue
        qname = _qname(package, name)
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=qname,
            start_line=line_number(text, m.start()),
            end_line=line_number(text, m.start()),
            signature=f"{m.group('kind')} {name}{m.group('rest').strip()}",
            parent_qualified_name=package or None,
            extras={"language": "go"},
        ))

    _append_routes(text, package, function_symbols, symbols, edges)
    _append_test_edges(symbols, edges, function_symbols)
    return ExtractResult(symbols=symbols, edges=edges, imports=imports)


def _detect_package(text: str) -> str:
    match = _PACKAGE_RE.search(text)
    return match.group(1) if match else ""


def _iter_imports(text: str):
    consumed: list[tuple[int, int]] = []
    for block in _IMPORT_BLOCK_RE.finditer(text):
        consumed.append((block.start(), block.end()))
        body = block.group("body")
        for m in _IMPORT_IN_BLOCK_RE.finditer(body):
            yield m.group("module"), (m.group("alias") or ""), block.start("body") + m.start()
    for m in _IMPORT_LINE_RE.finditer(text):
        if any(start <= m.start() < end for start, end in consumed):
            continue
        yield m.group("module"), (m.group("alias") or ""), m.start()


def _calls_in(body: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _CALL_RE.finditer(body):
        name = m.group(1)
        if name in _GO_KEYWORDS or name.split(".", 1)[0] in _GO_KEYWORDS:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _append_routes(
    text: str,
    package: str,
    function_symbols: dict[str, str],
    symbols: list[ParsedSymbol],
    edges: list[ParsedEdge],
) -> None:
    for m in _ROUTER_RE.finditer(text):
        _add_route(
            method=m.group("method"),
            path=m.group("path"),
            handler=m.group("handler"),
            package=package,
            line=line_number(text, m.start()),
            function_symbols=function_symbols,
            symbols=symbols,
            edges=edges,
        )
    for m in _HANDLE_FUNC_RE.finditer(text):
        _add_route(
            method="ANY",
            path=m.group("path"),
            handler=m.group("handler"),
            package=package,
            line=line_number(text, m.start()),
            function_symbols=function_symbols,
            symbols=symbols,
            edges=edges,
        )


def _add_route(
    *,
    method: str,
    path: str,
    handler: str,
    package: str,
    line: int,
    function_symbols: dict[str, str],
    symbols: list[ParsedSymbol],
    edges: list[ParsedEdge],
) -> None:
    route_path = normalize_route_path(path)
    route_qname = f"route::{method} {route_path}"
    handler_qname = function_symbols.get(handler) or _qname(package, handler)
    if not any(s.qualified_name == route_qname for s in symbols):
        symbols.append(ParsedSymbol(
            kind="route",
            name=f"{method} {route_path}",
            qualified_name=route_qname,
            start_line=line,
            end_line=line,
            signature=f"{method} {route_path}",
            parent_qualified_name=handler_qname,
            extras={
                "language": "go",
                "http_method": method,
                "path": route_path,
                "handler": handler_qname,
            },
        ))
    edges.append(ParsedEdge(
        src_qualified_name=route_qname,
        dst_name=handler_qname,
        dst_qname=handler_qname if handler in function_symbols else None,
        edge_type="ROUTES_TO",
        confidence=0.9,
        extraction_source="regex",
        line=line,
        reason="go.http_route",
    ))


def _append_test_edges(
    symbols: list[ParsedSymbol],
    edges: list[ParsedEdge],
    function_symbols: dict[str, str],
) -> None:
    for sym in symbols:
        if sym.kind != "test_block":
            continue
        for edge in [e for e in edges if e.src_qualified_name == sym.qualified_name and e.edge_type == "CALLS"]:
            target_name = edge.dst_name.rsplit(".", 1)[-1]
            target_qname = function_symbols.get(target_name)
            if not target_qname:
                continue
            edges.append(ParsedEdge(
                src_qualified_name=sym.qualified_name,
                dst_name=target_qname,
                dst_qname=target_qname,
                edge_type="TESTS",
                confidence=0.75,
                extraction_source="regex",
                line=edge.line,
                reason="go.test_calls_symbol",
            ))


def _qname(package: str, name: str) -> str:
    return f"{package}.{name}" if package else name
