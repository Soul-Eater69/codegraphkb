"""Lightweight C# parser for classes, methods, routes, and tests."""
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
    split_type_list,
)
from codegraphkb.core.scanner import SourceFile

CSHARP_PARSER_VERSION = 1

_NAMESPACE_RE = re.compile(r"(?m)^\s*namespace\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*[;{]")
_USING_RE = re.compile(r"(?m)^\s*using\s+(?:static\s+)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;")
_TYPE_RE = re.compile(
    r"""(?mx)
    ^\s*
    (?:\[[^\]]+\]\s*)*
    (?P<visibility>public|private|protected|internal)?\s*
    (?:abstract|sealed|static|partial|\s)*
    (?P<kind>class|interface|record|struct)\s+
    (?P<name>[A-Za-z_]\w*)
    (?:\s*<[^>{]*>)?
    (?:\s*:\s*(?P<bases>[^{]+))?
    \s*\{
    """
)
_METHOD_RE = re.compile(
    r"""(?mx)
    ^[ \t]*
    (?:\[[^\]]+\]\s*)*
    (?P<visibility>public|private|protected|internal)?\s*
    (?:static|virtual|override|async|sealed|abstract|extern|partial|\s)*
    (?:
        (?P<return>[A-Za-z_][\w.<>\[\],?\s]*)\s+(?P<name>[A-Za-z_]\w*)
      |
        (?P<ctor_name>[A-Za-z_]\w*)
    )
    \s*\((?P<params>[^)]*)\)
    \s*(?:where\s+[^{]+)?(?P<body>[{;])
    """
)
_PROPERTY_RE = re.compile(
    r"""(?mx)
    ^[ \t]*(?:\[[^\]]+\]\s*)*
    (?P<visibility>public|private|protected|internal)?\s*
    (?:static|virtual|override|required|init|readonly|\s)*
    (?P<type>[A-Za-z_][\w.<>\[\],?\s]*)\s+
    (?P<name>[A-Za-z_]\w*)\s*\{\s*(?:get|set|init)\b
    """
)
_CONST_RE = re.compile(
    r"(?m)^[ \t]*(?:public|private|protected|internal|\s)*(?:static\s+)?const\s+(?P<type>[A-Za-z_][\w.<>\[\],?\s]*)\s+(?P<name>[A-Za-z_]\w*)\s*="
)
_ATTR_RE = re.compile(r"\[(?P<name>[A-Za-z_]\w*)(?:Attribute)?(?:\((?P<args>[^\]]*)\))?\]")
_CALL_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\(")
_CSHARP_KEYWORDS = frozenset({
    "if", "for", "foreach", "while", "switch", "catch", "using", "lock",
    "return", "throw", "new", "typeof", "nameof", "sizeof", "default",
})
_HTTP_ATTRS = {
    "HttpGet": "GET",
    "HttpPost": "POST",
    "HttpPut": "PUT",
    "HttpPatch": "PATCH",
    "HttpDelete": "DELETE",
    "HttpHead": "HEAD",
    "HttpOptions": "OPTIONS",
}
_TEST_ATTRS = {"Fact", "Theory", "Test", "TestMethod"}


def parse_csharp(source: SourceFile) -> ExtractResult:
    text = source.content
    rel = source.rel_path
    namespace = _detect_namespace(text) or module_from_path(rel, ".cs")
    symbols: list[ParsedSymbol] = []
    edges: list[ParsedEdge] = []
    imports: list[ImportBinding] = []

    for m in _USING_RE.finditer(text):
        fq = m.group(1)
        local = fq.rsplit(".", 1)[-1]
        line = line_number(text, m.start())
        edges.append(ParsedEdge(
            src_qualified_name=namespace,
            dst_name=fq,
            edge_type="IMPORTS",
            line=line,
            extraction_source="regex",
            reason="csharp.using",
        ))
        imports.append(ImportBinding(
            file_path=rel,
            local_name=local,
            imported_name=local,
            source_module=fq.rsplit(".", 1)[0] if "." in fq else "",
            import_kind="using",
            line=line,
            reason="csharp.using",
        ))

    type_spans = list(_collect_type_spans(text))
    method_qnames_by_name: dict[str, str] = {}
    for span in type_spans:
        type_qname = _qname(namespace, span["name"])
        symbols.append(ParsedSymbol(
            kind=span["kind"],
            name=span["name"],
            qualified_name=type_qname,
            start_line=span["start_line"],
            end_line=span["end_line"],
            signature=" ".join(text[span["start"]:span["body_start"]].split()),
            parent_qualified_name=namespace or None,
            visibility=span["visibility"],
            extras={"language": "csharp", "attributes": [a["name"] for a in span["attributes"]]},
        ))
        bases = split_type_list(span["bases"])
        for i, base in enumerate(bases):
            edge_type = "IMPLEMENTS"
            if span["kind"] in {"class", "record"} and i == 0 and not base.rsplit(".", 1)[-1].startswith("I"):
                edge_type = "EXTENDS"
            edges.append(ParsedEdge(
                src_qualified_name=type_qname,
                dst_name=base,
                edge_type=edge_type,
                line=span["start_line"],
                extraction_source="regex",
                reason="csharp.inheritance",
            ))

    for span in type_spans:
        type_qname = _qname(namespace, span["name"])
        body = text[span["body_start"]:span["body_end"]]
        body_offset = span["body_start"]
        class_route = _class_route_prefix(span["attributes"])
        for m in _METHOD_RE.finditer(body):
            attrs = _attrs_before(body, m.start()) + _attrs_in(m.group(0))
            ctor_name = m.group("ctor_name")
            if ctor_name:
                if ctor_name != span["name"]:
                    continue
                name = ctor_name
                return_type = ""
                kind = "constructor"
                qname = f"{type_qname}.<init>"
            else:
                name = m.group("name")
                return_type = (m.group("return") or "").strip()
                kind = "test_block" if any(a["name"] in _TEST_ATTRS for a in attrs) else "method"
                qname = f"{type_qname}.{name}"
            line = line_number(text, body_offset + m.start())
            method_qnames_by_name[name] = qname
            symbols.append(ParsedSymbol(
                kind=kind,
                name=name,
                qualified_name=qname,
                start_line=line,
                end_line=line_number(text, body_offset + _method_end(body, m)),
                signature=f"{return_type} {name}({(m.group('params') or '').strip()})".strip(),
                return_type=return_type,
                parent_qualified_name=type_qname,
                visibility=(m.group("visibility") or ""),
                extras={"language": "csharp", "attributes": [a["name"] for a in attrs]},
            ))
            route = _method_route(attrs, class_route)
            if route:
                method, path = route
                _add_route(symbols, edges, method, path, qname, line, "csharp")
            if m.group("body") == "{":
                body_start = m.end() - 1
                body_end = find_matching_brace(body, body_start)
                for call in _calls_in(body[body_start:body_end]):
                    edges.append(ParsedEdge(
                        src_qualified_name=qname,
                        dst_name=call,
                        edge_type="CALLS",
                        confidence=0.55,
                        extraction_source="regex",
                        line=line,
                        reason="csharp.call",
                    ))

        for m in _PROPERTY_RE.finditer(body):
            name = m.group("name")
            qname = f"{type_qname}.{name}"
            symbols.append(ParsedSymbol(
                kind="property",
                name=name,
                qualified_name=qname,
                start_line=line_number(text, body_offset + m.start()),
                end_line=line_number(text, body_offset + m.start()),
                signature=f"{m.group('type').strip()} {name}",
                declared_type=m.group("type").strip(),
                parent_qualified_name=type_qname,
                visibility=(m.group("visibility") or ""),
                extras={"language": "csharp"},
            ))
        for m in _CONST_RE.finditer(body):
            name = m.group("name")
            qname = f"{type_qname}.{name}"
            symbols.append(ParsedSymbol(
                kind="constant",
                name=name,
                qualified_name=qname,
                start_line=line_number(text, body_offset + m.start()),
                end_line=line_number(text, body_offset + m.start()),
                signature=f"{m.group('type').strip()} {name}",
                declared_type=m.group("type").strip(),
                parent_qualified_name=type_qname,
                extras={"language": "csharp"},
            ))

    _append_test_edges(symbols, edges, method_qnames_by_name)
    return ExtractResult(symbols=symbols, edges=edges, imports=imports)


def _detect_namespace(text: str) -> str:
    match = _NAMESPACE_RE.search(text)
    return match.group(1) if match else ""


def _collect_type_spans(text: str):
    for m in _TYPE_RE.finditer(text):
        open_pos = m.end() - 1
        close_pos = find_matching_brace(text, open_pos)
        yield {
            "kind": m.group("kind"),
            "name": m.group("name"),
            "visibility": m.group("visibility") or "",
            "bases": m.group("bases") or "",
            "start": m.start(),
            "body_start": open_pos,
            "body_end": close_pos,
            "start_line": line_number(text, m.start()),
            "end_line": line_number(text, close_pos),
            "attributes": _attrs_before(text, m.start()) + _attrs_in(m.group(0)),
        }


def _attrs_before(text: str, decl_start: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in reversed(text[:decl_start].splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("["):
            break
        out[0:0] = _attrs_in(stripped)
    return out


def _attrs_in(text: str) -> list[dict[str, str]]:
    return [{"name": m.group("name"), "args": m.group("args") or ""} for m in _ATTR_RE.finditer(text)]


def _class_route_prefix(attrs: list[dict[str, str]]) -> str:
    for attr in attrs:
        if attr["name"] == "Route":
            return first_string_literal(attr["args"])
    return ""


def _method_route(attrs: list[dict[str, str]], class_route: str) -> tuple[str, str] | None:
    for attr in attrs:
        name = attr["name"]
        if name in _HTTP_ATTRS:
            return _HTTP_ATTRS[name], normalize_route_path(class_route, first_string_literal(attr["args"]))
        if name == "Route":
            return "ANY", normalize_route_path(class_route, first_string_literal(attr["args"]))
    return None


def _add_route(
    symbols: list[ParsedSymbol],
    edges: list[ParsedEdge],
    method: str,
    path: str,
    handler_qname: str,
    line: int,
    language: str,
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
                "language": language,
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
        reason="csharp.aspnet_route",
    ))


def _method_end(body: str, match: re.Match[str]) -> int:
    if match.group("body") != "{":
        return match.end()
    return find_matching_brace(body, match.end() - 1)


def _calls_in(body: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _CALL_RE.finditer(body):
        name = m.group(1)
        if name in _CSHARP_KEYWORDS or name.split(".", 1)[0] in _CSHARP_KEYWORDS:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _append_test_edges(
    symbols: list[ParsedSymbol],
    edges: list[ParsedEdge],
    methods_by_name: dict[str, str],
) -> None:
    for sym in symbols:
        if sym.kind != "test_block":
            continue
        for edge in [e for e in edges if e.src_qualified_name == sym.qualified_name and e.edge_type == "CALLS"]:
            target_name = edge.dst_name.rsplit(".", 1)[-1]
            target_qname = methods_by_name.get(target_name)
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
                reason="csharp.test_calls_symbol",
            ))


def _qname(namespace: str, name: str) -> str:
    return f"{namespace}.{name}" if namespace else name
