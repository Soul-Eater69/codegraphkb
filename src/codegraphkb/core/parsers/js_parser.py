"""Regex-based JavaScript/TypeScript extractor.

Not a real parser — but good enough for MVP graph extraction. Captures:
  - imports
  - top-level functions / arrow-function bindings
  - class declarations + extends
  - React-component-shaped functions (PascalCase)
  - Express/Fastify-style route registration: app.get('/x', handler)
  - calls inside top-level function bodies (best-effort)
"""
from __future__ import annotations

import re

from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_IMPORT_RE = re.compile(
    r"""(?mx)
    ^\s*
    (?:
        import \s+ (?: [^"'\n]+? \s+ from \s+ )? ["']([^"']+)["']
      | (?:const|let|var) \s+ [^=]+ = \s* require\( \s* ["']([^"']+)["'] \s*\)
    )
    """
)
_FUNCTION_RE = re.compile(
    r"(?m)^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"
)
_ARROW_RE = re.compile(
    r"(?m)^(?:export\s+(?:default\s+)?)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
    r"(?::\s*[^=]+)?=\s*(?:async\s*)?\(([^)]*)\)\s*=>"
)
_CLASS_RE = re.compile(
    r"(?m)^(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)(?:\s+extends\s+([A-Za-z_$][\w$.]*))?"
)
_ROUTE_RE = re.compile(
    r"""(?x)
    \b(?:app|router|fastify|server)
    \.(get|post|put|patch|delete|options|head|use|all)\s*\(
    \s*["']([^"']+)["']
    """,
    re.IGNORECASE,
)
_CALL_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")


def parse_javascript(source: SourceFile) -> ExtractResult:
    text = source.content
    rel = source.rel_path
    module = _module_qname(rel)
    symbols: list[ParsedSymbol] = []
    edges: list[ParsedEdge] = []

    # Imports
    for m in _IMPORT_RE.finditer(text):
        target = m.group(1) or m.group(2)
        if target:
            edges.append(ParsedEdge(
                src_qualified_name=module,
                dst_name=target,
                edge_type="IMPORTS",
                line=text[: m.start()].count("\n") + 1,
            ))

    # Functions
    for m in _FUNCTION_RE.finditer(text):
        name = m.group(1)
        params = m.group(2).strip()
        line = text[: m.start()].count("\n") + 1
        end = _approx_block_end(text, m.end(), line)
        kind = _function_kind(name, params)
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=f"{module}.{name}",
            start_line=line,
            end_line=end,
            signature=f"function {name}({params})",
            parent_qualified_name=module,
        ))

    # Arrow bindings
    for m in _ARROW_RE.finditer(text):
        name = m.group(1)
        params = m.group(2).strip()
        line = text[: m.start()].count("\n") + 1
        end = _approx_block_end(text, m.end(), line)
        kind = _function_kind(name, params)
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=f"{module}.{name}",
            start_line=line,
            end_line=end,
            signature=f"const {name} = ({params}) =>",
            parent_qualified_name=module,
        ))

    # Classes
    for m in _CLASS_RE.finditer(text):
        name = m.group(1)
        base = m.group(2)
        line = text[: m.start()].count("\n") + 1
        qname = f"{module}.{name}"
        symbols.append(ParsedSymbol(
            kind="class",
            name=name,
            qualified_name=qname,
            start_line=line,
            end_line=line,
            signature=f"class {name}" + (f" extends {base}" if base else ""),
            parent_qualified_name=module,
        ))
        if base:
            edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=base,
                edge_type="EXTENDS",
                line=line,
            ))

    # Routes
    for m in _ROUTE_RE.finditer(text):
        method = m.group(1).upper()
        path = m.group(2)
        line = text[: m.start()].count("\n") + 1
        route_qname = f"route::{method} {path}"
        symbols.append(ParsedSymbol(
            kind="route",
            name=f"{method} {path}",
            qualified_name=route_qname,
            start_line=line,
            end_line=line,
            extras={"http_method": method, "path": path},
        ))
        # Best-effort: link route to the next identifier after the path arg
        tail = text[m.end(): m.end() + 200]
        tm = re.search(r",\s*([A-Za-z_$][\w$.]*)", tail)
        if tm:
            handler = tm.group(1).split(".")[-1]
            edges.append(ParsedEdge(
                src_qualified_name=route_qname,
                dst_name=handler,
                edge_type="ROUTES_TO",
                confidence=0.7,
                extraction_source="regex",
                line=line,
            ))

    # Calls — best effort within each function body
    for sym in symbols:
        if sym.kind not in ("function", "method", "component"):
            continue
        block = _slice_block(text, sym.start_line)
        seen = set()
        for cm in _CALL_RE.finditer(block):
            name = cm.group(1)
            if name in _JS_KEYWORDS or name in seen:
                continue
            seen.add(name)
            edges.append(ParsedEdge(
                src_qualified_name=sym.qualified_name,
                dst_name=name,
                edge_type="CALLS",
                confidence=0.5,
                extraction_source="regex",
            ))

    return ExtractResult(symbols=symbols, edges=edges)


def _module_qname(rel_path: str) -> str:
    p = rel_path
    for ext in (".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs"):
        if p.endswith(ext):
            p = p[: -len(ext)]
            break
    return p.replace("/", ".").replace("\\", ".")


def _function_kind(name: str, params: str) -> str:
    # PascalCase + JSX-like params often indicates a React component.
    if name and name[0].isupper():
        return "component"
    return "function"


def _approx_block_end(text: str, body_start_pos: int, start_line: int) -> int:
    """Walk braces forward to estimate function body end line."""
    depth = 0
    started = False
    line = start_line
    for ch in text[body_start_pos: body_start_pos + 20000]:
        if ch == "\n":
            line += 1
        if ch == "{":
            depth += 1
            started = True
        elif ch == "}":
            depth -= 1
            if started and depth <= 0:
                return line
    return start_line


def _slice_block(text: str, start_line: int, max_lines: int = 200) -> str:
    lines = text.splitlines()
    end = min(len(lines), start_line - 1 + max_lines)
    return "\n".join(lines[start_line - 1: end])


_JS_KEYWORDS = {
    "if", "else", "for", "while", "do", "switch", "case", "return", "function",
    "var", "let", "const", "new", "typeof", "instanceof", "in", "of", "void",
    "throw", "try", "catch", "finally", "yield", "await", "async", "class",
    "extends", "super", "this", "true", "false", "null", "undefined", "import",
    "export", "from", "as", "default", "delete", "break", "continue", "with",
    "Array", "Object", "String", "Number", "Boolean", "Promise", "Set", "Map",
    "console", "require", "module", "exports", "JSON", "Math", "Date",
    "Symbol", "Error", "RegExp",
}
