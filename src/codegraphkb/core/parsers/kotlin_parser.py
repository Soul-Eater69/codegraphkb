"""Lightweight Kotlin parser for classes, functions, Spring routes, and tests."""
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
    first_string_literal,
    line_number,
    module_from_path,
    normalize_route_path,
)
from codegraphkb.core.scanner import SourceFile

KOTLIN_PARSER_VERSION = 1

_PACKAGE_RE = re.compile(r"(?m)^\s*package\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
_IMPORT_RE = re.compile(r"(?m)^\s*import\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\.\*)?)")
_CLASS_RE = re.compile(
    r"""(?msx)
    ^\s*
    (?:@\w[\w.]*(?:\([^)]*\))?\s*)*
    (?P<kind>class|interface|object)\s+
    (?P<name>[A-Za-z_]\w*)
    (?P<header>(?:[^\n{]|\n[ \t]+[^\n{]|\n\s*\)[^\n{]*)*)
    \{
    """
)
_DATA_CLASS_RE = re.compile(
    r"""(?mx)^\s*(?:@\w[\w.]*(?:\([^)]*\))?\s*)*data\s+class\s+(?P<name>[A-Za-z_]\w*)[^{\n]*$"""
)
_FUN_RE = re.compile(
    r"""(?mx)
    ^\s*
    (?:@\w[\w.]*(?:\([^)]*\))?\s*)*
    (?P<visibility>public|private|protected|internal)?\s*
    (?:suspend\s+|inline\s+|override\s+|open\s+|private\s+|public\s+|internal\s+|protected\s+)*
    fun\s+(?P<name>[A-Za-z_]\w*)\s*
    \((?P<params>[^)]*)\)\s*
    (?::\s*(?P<return>[A-Za-z_][\w.<>,?]*))?
    \s*(?P<body>[{=])
    """
)
_PROPERTY_RE = re.compile(
    r"(?m)^\s*(?P<const>const\s+)?(?P<kind>val|var)\s+(?P<name>[A-Za-z_]\w*)\s*(?::\s*(?P<type>[A-Za-z_][\w.<>,?]*))?"
)
_ANNOT_RE = re.compile(r"@(?P<name>\w[\w.]*)(?:\((?P<args>[^)]*)\))?")
_CALL_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\(")
_KOTLIN_KEYWORDS = frozenset({
    "if", "for", "while", "when", "return", "throw", "try", "catch",
    "require", "check", "also", "let", "run", "apply", "with",
})
_HTTP_ANNOTS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "PatchMapping": "PATCH",
    "DeleteMapping": "DELETE",
}


def parse_kotlin(source: SourceFile) -> ExtractResult:
    text = source.content
    rel = source.rel_path
    package = _detect_package(text) or module_from_path(rel, ".kt")
    symbols: list[ParsedSymbol] = []
    edges: list[ParsedEdge] = []
    imports: list[ImportBinding] = []

    for m in _IMPORT_RE.finditer(text):
        fq = m.group(1)
        if fq.endswith(".*"):
            local = ""
            source_mod = fq[:-2]
        else:
            local = fq.rsplit(".", 1)[-1]
            source_mod = fq.rsplit(".", 1)[0] if "." in fq else ""
        line = line_number(text, m.start())
        edges.append(ParsedEdge(
            src_qualified_name=package,
            dst_name=fq,
            edge_type="IMPORTS",
            line=line,
            extraction_source="regex",
            reason="kotlin.import",
        ))
        if local:
            imports.append(ImportBinding(
                file_path=rel,
                local_name=local,
                imported_name=local,
                source_module=source_mod,
                import_kind="named",
                line=line,
                reason="kotlin.import",
            ))

    class_spans = list(_collect_class_spans(text))
    class_ranges = [(s["body_start"], s["body_end"]) for s in class_spans if s["body_start"] >= 0]
    function_symbols: dict[str, str] = {}

    for span in class_spans:
        kind = span["kind"]
        if span["data"]:
            kind = "class"
        qname = _qname(package, span["name"])
        symbols.append(ParsedSymbol(
            kind=kind,
            name=span["name"],
            qualified_name=qname,
            start_line=span["start_line"],
            end_line=span["end_line"],
            signature=" ".join(text[span["start"]:span["decl_end"]].split()),
            parent_qualified_name=package or None,
            extras={
                "language": "kotlin",
                "kotlin_kind": "data_class" if span["data"] else span["kind"],
                "annotations": [a["name"] for a in span["annotations"]],
            },
        ))

    for span in class_spans:
        if span["body_start"] < 0:
            continue
        owner = _qname(package, span["name"])
        class_route = _class_route_prefix(span["annotations"])
        body = text[span["body_start"]:span["body_end"]]
        for m in _FUN_RE.finditer(body):
            attrs = _annots_before(body, m.start()) + _annots_in(m.group(0))
            name = m.group("name")
            qname = f"{owner}.{name}"
            function_symbols[name] = qname
            line = line_number(text, span["body_start"] + m.start())
            end = _function_end(body, m)
            kind = "test_block" if any(a["name"].endswith("Test") or a["name"] == "Test" for a in attrs) else "method"
            symbols.append(ParsedSymbol(
                kind=kind,
                name=name,
                qualified_name=qname,
                start_line=line,
                end_line=line_number(text, span["body_start"] + end),
                signature=f"fun {name}({(m.group('params') or '').strip()})",
                return_type=(m.group("return") or "").strip(),
                parent_qualified_name=owner,
                visibility=(m.group("visibility") or ""),
                extras={"language": "kotlin", "annotations": [a["name"] for a in attrs]},
            ))
            route = _method_route(attrs, class_route)
            if route:
                method, path = route
                _add_route(symbols, edges, method, path, qname, line)
            if m.group("body") == "{":
                body_start = m.end() - 1
                for call in _calls_in(body[body_start:end]):
                    edges.append(ParsedEdge(
                        src_qualified_name=qname,
                        dst_name=call,
                        edge_type="CALLS",
                        confidence=0.55,
                        extraction_source="regex",
                        line=line,
                        reason="kotlin.call",
                    ))
        for m in _PROPERTY_RE.finditer(body):
            name = m.group("name")
            kind = "constant" if m.group("const") or name.isupper() else "property"
            qname = f"{owner}.{name}"
            symbols.append(ParsedSymbol(
                kind=kind,
                name=name,
                qualified_name=qname,
                start_line=line_number(text, span["body_start"] + m.start()),
                end_line=line_number(text, span["body_start"] + m.start()),
                signature=f"{m.group('kind')} {name}",
                declared_type=(m.group("type") or "").strip(),
                parent_qualified_name=owner,
                extras={"language": "kotlin"},
            ))

    for m in _FUN_RE.finditer(text):
        if _inside_ranges(class_ranges, m.start()):
            continue
        attrs = _annots_before(text, m.start()) + _annots_in(m.group(0))
        name = m.group("name")
        qname = _qname(package, name)
        function_symbols[name] = qname
        end = _function_end(text, m)
        kind = "test_block" if any(a["name"].endswith("Test") or a["name"] == "Test" for a in attrs) else "function"
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=qname,
            start_line=line_number(text, m.start()),
            end_line=line_number(text, end),
            signature=f"fun {name}({(m.group('params') or '').strip()})",
            return_type=(m.group("return") or "").strip(),
            parent_qualified_name=package or None,
            visibility=(m.group("visibility") or ""),
            extras={"language": "kotlin", "annotations": [a["name"] for a in attrs]},
        ))
        if m.group("body") == "{":
            for call in _calls_in(text[m.end() - 1:end]):
                edges.append(ParsedEdge(
                    src_qualified_name=qname,
                    dst_name=call,
                    edge_type="CALLS",
                    confidence=0.55,
                    extraction_source="regex",
                    line=line_number(text, m.start()),
                    reason="kotlin.call",
                ))

    for m in _PROPERTY_RE.finditer(text):
        if _inside_ranges(class_ranges, m.start()):
            continue
        name = m.group("name")
        kind = "constant" if m.group("const") or name.isupper() else "property"
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=_qname(package, name),
            start_line=line_number(text, m.start()),
            end_line=line_number(text, m.start()),
            signature=f"{m.group('kind')} {name}",
            declared_type=(m.group("type") or "").strip(),
            parent_qualified_name=package or None,
            extras={"language": "kotlin"},
        ))

    _append_test_edges(symbols, edges, function_symbols)
    return ExtractResult(symbols=symbols, edges=edges, imports=imports)


def _detect_package(text: str) -> str:
    match = _PACKAGE_RE.search(text)
    return match.group(1) if match else ""


def _collect_class_spans(text: str):
    matched_starts: set[int] = set()
    for m in _CLASS_RE.finditer(text):
        matched_starts.add(m.start())
        body_start = m.end() - 1
        body_end = find_matching_brace(text, body_start)
        yield {
            "kind": m.group("kind"),
            "data": False,
            "name": m.group("name"),
            "start": m.start(),
            "decl_end": m.end(),
            "body_start": body_start,
            "body_end": body_end,
            "start_line": line_number(text, m.start()),
            "end_line": line_number(text, body_end),
            "annotations": _annots_before(text, m.start()) + _annots_in(m.group(0)),
        }
    for m in _DATA_CLASS_RE.finditer(text):
        if m.start() in matched_starts:
            continue
        yield {
            "kind": "class",
            "data": True,
            "name": m.group("name"),
            "start": m.start(),
            "decl_end": m.end(),
            "body_start": -1,
            "body_end": m.end(),
            "start_line": line_number(text, m.start()),
            "end_line": line_number(text, m.end()),
            "annotations": _annots_before(text, m.start()) + _annots_in(m.group(0)),
        }


def _annots_before(text: str, decl_start: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in reversed(text[:decl_start].splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("@"):
            break
        out[0:0] = _annots_in(stripped)
    return out


def _annots_in(text: str) -> list[dict[str, str]]:
    return [{"name": m.group("name"), "args": m.group("args") or ""} for m in _ANNOT_RE.finditer(text)]


def _class_route_prefix(attrs: list[dict[str, str]]) -> str:
    for attr in attrs:
        if attr["name"].endswith("RequestMapping"):
            return first_string_literal(attr["args"])
    return ""


def _method_route(attrs: list[dict[str, str]], class_route: str) -> tuple[str, str] | None:
    for attr in attrs:
        short = attr["name"].rsplit(".", 1)[-1]
        if short in _HTTP_ANNOTS:
            return _HTTP_ANNOTS[short], normalize_route_path(class_route, first_string_literal(attr["args"]))
        if short == "RequestMapping":
            return "ANY", normalize_route_path(class_route, first_string_literal(attr["args"]))
    return None


def _add_route(
    symbols: list[ParsedSymbol],
    edges: list[ParsedEdge],
    method: str,
    path: str,
    handler_qname: str,
    line: int,
) -> None:
    route_qname = f"route::{method} {path}"
    if not any(s.qualified_name == route_qname for s in symbols):
        symbols.append(ParsedSymbol(
            kind="route",
            name=f"{method} {path}",
            qualified_name=route_qname,
            start_line=line,
            end_line=line,
            signature=f"{method} {path}",
            parent_qualified_name=handler_qname,
            extras={
                "language": "kotlin",
                "http_method": method,
                "path": path,
                "handler": handler_qname,
            },
        ))
    edges.append(ParsedEdge(
        src_qualified_name=route_qname,
        dst_name=handler_qname,
        dst_qname=handler_qname,
        edge_type="ROUTES_TO",
        confidence=0.9,
        extraction_source="regex",
        line=line,
        reason="kotlin.spring_route",
    ))


def _function_end(text: str, match: re.Match[str]) -> int:
    if match.group("body") == "{":
        return find_matching_brace(text, match.end() - 1)
    line_end = text.find("\n", match.end())
    return len(text) if line_end < 0 else line_end


def _calls_in(body: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _CALL_RE.finditer(body):
        name = m.group(1)
        if name in _KOTLIN_KEYWORDS or name.split(".", 1)[0] in _KOTLIN_KEYWORDS:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _append_test_edges(
    symbols: list[ParsedSymbol],
    edges: list[ParsedEdge],
    functions_by_name: dict[str, str],
) -> None:
    for sym in symbols:
        if sym.kind != "test_block":
            continue
        for edge in [e for e in edges if e.src_qualified_name == sym.qualified_name and e.edge_type == "CALLS"]:
            target_name = edge.dst_name.rsplit(".", 1)[-1]
            target_qname = functions_by_name.get(target_name)
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
                reason="kotlin.test_calls_symbol",
            ))


def _inside_ranges(ranges: list[tuple[int, int]], pos: int) -> bool:
    return any(start <= pos < end for start, end in ranges)


def _qname(package: str, name: str) -> str:
    return f"{package}.{name}" if package else name
