"""Lightweight Rust parser for modules, types, functions, impl methods, and tests."""
from __future__ import annotations

import re

from codegraphkb.core.parsers.base import (
    ExtractResult,
    ImportBinding,
    ParsedEdge,
    ParsedSymbol,
)
from codegraphkb.core.parsers.regex_utils import find_matching_brace, line_number, module_from_path
from codegraphkb.core.scanner import SourceFile

RUST_PARSER_VERSION = 1

_USE_RE = re.compile(r"(?m)^\s*use\s+([^;]+);")
_MOD_RE = re.compile(r"(?m)^\s*(?:pub\s+)?mod\s+([A-Za-z_]\w*)\s*[;{]")
_TYPE_RE = re.compile(
    r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?(?P<kind>struct|enum|trait)\s+(?P<name>[A-Za-z_]\w*)[^{;]*(?P<body>[{;])"
)
_CONST_RE = re.compile(
    r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?const\s+(?P<name>[A-Za-z_]\w*)\s*:\s*(?P<type>[^=;]+)="
)
_IMPL_RE = re.compile(
    r"(?m)^\s*impl(?:\s*<[^>]+>)?\s+(?:(?P<trait>[A-Za-z_][\w:]*)\s+for\s+)?(?P<type>[A-Za-z_][\w:]*)[^{]*\{"
)
_FN_RE = re.compile(
    r"""(?mx)
    ^\s*
    (?:\#\[[^\]]+\]\s*)*
    (?:pub(?:\([^)]*\))?\s+)?
    (?:async\s+)?
    fn\s+(?P<name>[A-Za-z_]\w*)\s*
    \((?P<params>[^)]*)\)\s*
    (?P<return>->\s*[^{\n]+)?\{
    """
)
_CALL_RE = re.compile(r"(?<![\w:])([A-Za-z_]\w*(?:::[A-Za-z_]\w*)?)!?\s*\(")
_RUST_KEYWORDS = frozenset({
    "if", "while", "for", "loop", "match", "return", "break", "continue",
    "let", "fn", "impl", "Some", "Ok", "Err", "None",
})


def parse_rust(source: SourceFile) -> ExtractResult:
    text = source.content
    rel = source.rel_path
    module = module_from_path(rel, ".rs", sep="::") or "crate"
    if module.startswith("src::"):
        module = module[len("src::"):]
    if module in {"main", "lib"}:
        module = "crate"
    symbols: list[ParsedSymbol] = []
    edges: list[ParsedEdge] = []
    imports: list[ImportBinding] = []

    for m in _USE_RE.finditer(text):
        raw = " ".join(m.group(1).split())
        local = _local_from_use(raw)
        line = line_number(text, m.start())
        edges.append(ParsedEdge(
            src_qualified_name=module,
            dst_name=raw,
            edge_type="IMPORTS",
            line=line,
            extraction_source="regex",
            reason="rust.use",
        ))
        if local:
            imports.append(ImportBinding(
                file_path=rel,
                local_name=local,
                imported_name=local,
                source_module=raw.rsplit("::", 1)[0] if "::" in raw else raw,
                import_kind="use",
                line=line,
                reason="rust.use",
            ))

    for m in _MOD_RE.finditer(text):
        name = m.group(1)
        qname = f"{module}::{name}"
        symbols.append(ParsedSymbol(
            kind="module",
            name=name,
            qualified_name=qname,
            start_line=line_number(text, m.start()),
            end_line=line_number(text, m.start()),
            signature=f"mod {name}",
            parent_qualified_name=module,
            extras={"language": "rust"},
        ))

    for m in _TYPE_RE.finditer(text):
        name = m.group("name")
        kind = m.group("kind")
        close_pos = find_matching_brace(text, m.end() - 1) if m.group("body") == "{" else m.end()
        qname = f"{module}::{name}"
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=qname,
            start_line=line_number(text, m.start()),
            end_line=line_number(text, close_pos),
            signature=" ".join(text[m.start():m.end()].split()),
            parent_qualified_name=module,
            is_exported=text[m.start():m.end()].lstrip().startswith("pub "),
            extras={"language": "rust"},
        ))

    impl_spans = list(_collect_impl_spans(text))
    impl_ranges = [(s["body_start"], s["body_end"]) for s in impl_spans]
    function_symbols: dict[str, str] = {}

    for span in impl_spans:
        owner = f"{module}::{span['type'].rsplit('::', 1)[-1]}"
        if span["trait"]:
            edges.append(ParsedEdge(
                src_qualified_name=owner,
                dst_name=span["trait"],
                edge_type="IMPLEMENTS",
                line=span["start_line"],
                extraction_source="regex",
                reason="rust.impl_trait",
            ))
        body = text[span["body_start"]:span["body_end"]]
        for m in _FN_RE.finditer(body):
            name = m.group("name")
            qname = f"{owner}.{name}"
            function_symbols[name] = qname
            line = line_number(text, span["body_start"] + m.start())
            end = find_matching_brace(body, m.end() - 1)
            symbols.append(ParsedSymbol(
                kind="method",
                name=name,
                qualified_name=qname,
                start_line=line,
                end_line=line_number(text, span["body_start"] + end),
                signature=f"fn {name}({(m.group('params') or '').strip()}) {(m.group('return') or '').strip()}".strip(),
                return_type=(m.group("return") or "").replace("->", "").strip(),
                parent_qualified_name=owner,
                is_exported=body[m.start():m.end()].lstrip().startswith("pub "),
                extras={"language": "rust", "impl": span["type"], "trait": span["trait"]},
            ))
            for call in _calls_in(body[m.end():end]):
                edges.append(ParsedEdge(
                    src_qualified_name=qname,
                    dst_name=call,
                    edge_type="CALLS",
                    confidence=0.55,
                    extraction_source="regex",
                    line=line,
                    reason="rust.call",
                ))

    for m in _FN_RE.finditer(text):
        if _inside_ranges(impl_ranges, m.start()):
            continue
        name = m.group("name")
        attrs = _attrs_before(text, m.start()) + _attrs_in(m.group(0))
        kind = "test_block" if "test" in attrs else "function"
        qname = f"{module}::{name}"
        function_symbols[name] = qname
        close_pos = find_matching_brace(text, m.end() - 1)
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=qname,
            start_line=line_number(text, m.start()),
            end_line=line_number(text, close_pos),
            signature=f"fn {name}({(m.group('params') or '').strip()}) {(m.group('return') or '').strip()}".strip(),
            return_type=(m.group("return") or "").replace("->", "").strip(),
            parent_qualified_name=module,
            is_exported=text[m.start():m.end()].lstrip().startswith("pub "),
            extras={"language": "rust", "attributes": attrs},
        ))
        for call in _calls_in(text[m.end():close_pos]):
            edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=call,
                edge_type="CALLS",
                confidence=0.55,
                extraction_source="regex",
                line=line_number(text, m.start()),
                reason="rust.call",
            ))

    for m in _CONST_RE.finditer(text):
        name = m.group("name")
        qname = f"{module}::{name}"
        symbols.append(ParsedSymbol(
            kind="constant",
            name=name,
            qualified_name=qname,
            start_line=line_number(text, m.start()),
            end_line=line_number(text, m.start()),
            signature=f"const {name}: {m.group('type').strip()}",
            declared_type=m.group("type").strip(),
            parent_qualified_name=module,
            extras={"language": "rust"},
        ))

    _append_test_edges(symbols, edges, function_symbols)
    return ExtractResult(symbols=symbols, edges=edges, imports=imports)


def _collect_impl_spans(text: str):
    for m in _IMPL_RE.finditer(text):
        open_pos = m.end() - 1
        close_pos = find_matching_brace(text, open_pos)
        yield {
            "trait": m.group("trait") or "",
            "type": m.group("type"),
            "body_start": open_pos,
            "body_end": close_pos,
            "start_line": line_number(text, m.start()),
        }


def _attrs_before(text: str, decl_start: int) -> list[str]:
    out: list[str] = []
    for line in reversed(text[:decl_start].splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("#["):
            break
        out[0:0] = _attrs_in(stripped)
    return out


def _attrs_in(text: str) -> list[str]:
    return re.findall(r"#\[\s*([A-Za-z_]\w*)", text)


def _calls_in(body: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _CALL_RE.finditer(body):
        name = m.group(1)
        base = name.rsplit("::", 1)[-1]
        if base in _RUST_KEYWORDS or name in _RUST_KEYWORDS:
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
            target_name = edge.dst_name.rsplit("::", 1)[-1]
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
                reason="rust.test_calls_symbol",
            ))


def _inside_ranges(ranges: list[tuple[int, int]], pos: int) -> bool:
    return any(start <= pos < end for start, end in ranges)


def _local_from_use(raw: str) -> str:
    cleaned = raw.strip()
    if " as " in cleaned:
        return cleaned.rsplit(" as ", 1)[-1].strip()
    cleaned = cleaned.rstrip("}")
    if "::{" in cleaned:
        cleaned = cleaned.split("::{", 1)[0]
    return cleaned.rsplit("::", 1)[-1].strip("{}* ")
