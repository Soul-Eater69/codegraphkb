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

from codegraphkb.core.graph_schema import PrecisionLevel
from codegraphkb.core.parsers.base import (
    ExtractResult,
    ImportBinding,
    ParsedEdge,
    ParsedParameter,
    ParsedSymbol,
)
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
# Captures the *binding* portion of an ES import so we can populate
# ImportBinding records. Matches in priority order:
#   import D from 'src'                            -> default
#   import D, { a, b as c } from 'src'             -> default + named
#   import { a, b as c } from 'src'                -> named
#   import * as ns from 'src'                      -> namespace
#   import 'src'                                   -> side effect (no binding)
#   const { a, b: c } = require('src')             -> named via destructure
#   const x = require('src')                       -> default-ish (CommonJS)
_ESM_IMPORT_RE = re.compile(
    r"""(?mx)
    ^\s* import \s+
    (?:
        # default + optional named: D | D, { ... } | D, * as ns
        (?P<default> [A-Za-z_$][\w$]* )
        (?: \s* , \s* \{ \s* (?P<after_default_named> [^}]+ ) \s* \} )?
        (?: \s* , \s* \* \s+ as \s+ (?P<after_default_ns> [A-Za-z_$][\w$]* ) )?
      | \{ \s* (?P<named> [^}]+ ) \s* \}
      | \* \s+ as \s+ (?P<namespace> [A-Za-z_$][\w$]* )
    )
    \s+ from \s+ ["'] (?P<source> [^"']+ ) ["']
    """
)
_CJS_REQUIRE_RE = re.compile(
    r"""(?mx)
    ^\s* (?:const|let|var) \s+
    (?:
        (?P<default> [A-Za-z_$][\w$]* )
      | \{ \s* (?P<named> [^}]+ ) \s* \}
    )
    \s* = \s* require\( \s* ["'] (?P<source> [^"']+ ) ["'] \s* \)
    """
)
_FUNCTION_RE = re.compile(
    r"(?m)^(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*(?::\s*([^{\n]+))?"
)
_ARROW_RE = re.compile(
    r"(?m)^(?:export\s+(?:default\s+)?)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*"
    r"(?::\s*[^=]+)?=\s*(?:async\s*)?\(([^)]*)\)\s*(?::\s*([^=;\n]+?))?\s*=>"
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
    imports: list[ImportBinding] = []

    # Imports (module-level edges)
    for m in _IMPORT_RE.finditer(text):
        target = m.group(1) or m.group(2)
        if target:
            edges.append(ParsedEdge(
                src_qualified_name=module,
                dst_name=target,
                edge_type="IMPORTS",
                line=text[: m.start()].count("\n") + 1,
            ))

    # Structured import bindings — captures the *local* alias for each form.
    for m in _ESM_IMPORT_RE.finditer(text):
        _emit_js_esm_bindings(m, rel, text, imports)
    for m in _CJS_REQUIRE_RE.finditer(text):
        _emit_js_cjs_bindings(m, rel, text, imports)

    # Functions
    for m in _FUNCTION_RE.finditer(text):
        name = m.group(1)
        params = m.group(2).strip()
        return_type = (m.group(3) or "").strip()
        line = text[: m.start()].count("\n") + 1
        end = _approx_block_end(text, m.end(), line)
        kind = _function_kind(name, params)
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=f"{module}.{name}",
            start_line=line,
            end_line=end,
            signature=f"function {name}({params})" + (f": {return_type}" if return_type else ""),
            return_type=return_type,
            parent_qualified_name=module,
            parameters=_parse_parameters_text(params, extraction_source="regex"),
        ))

    # Arrow bindings
    for m in _ARROW_RE.finditer(text):
        name = m.group(1)
        params = m.group(2).strip()
        return_type = (m.group(3) or "").strip()
        line = text[: m.start()].count("\n") + 1
        end = _approx_block_end(text, m.end(), line)
        kind = _function_kind(name, params)
        symbols.append(ParsedSymbol(
            kind=kind,
            name=name,
            qualified_name=f"{module}.{name}",
            start_line=line,
            end_line=end,
            signature=f"const {name} = ({params})" + (f": {return_type}" if return_type else "") + " =>",
            return_type=return_type,
            parent_qualified_name=module,
            parameters=_parse_parameters_text(params, extraction_source="regex"),
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

    return ExtractResult(symbols=symbols, edges=edges, imports=imports)


def _emit_js_esm_bindings(
    m: re.Match, file_path: str, text: str, out: list[ImportBinding],
) -> None:
    """Populate ImportBindings for one ``import ... from "src"`` match."""
    source_mod = m.group("source") or ""
    line = text[: m.start()].count("\n") + 1
    default = m.group("default")
    if default:
        out.append(ImportBinding(
            file_path=file_path,
            local_name=default,
            imported_name="default",
            source_module=source_mod,
            import_kind="default",
            line=line,
            reason="esm.default",
        ))
    after_named = m.group("after_default_named")
    if after_named:
        for binding in _parse_named_specs(after_named):
            local, imported = binding
            out.append(ImportBinding(
                file_path=file_path,
                local_name=local,
                imported_name=imported,
                source_module=source_mod,
                import_kind="named",
                line=line,
                reason="esm.default+named",
            ))
    after_ns = m.group("after_default_ns")
    if after_ns:
        out.append(ImportBinding(
            file_path=file_path,
            local_name=after_ns,
            imported_name="*",
            source_module=source_mod,
            import_kind="namespace",
            line=line,
            reason="esm.default+namespace",
        ))
    named = m.group("named")
    if named:
        for binding in _parse_named_specs(named):
            local, imported = binding
            out.append(ImportBinding(
                file_path=file_path,
                local_name=local,
                imported_name=imported,
                source_module=source_mod,
                import_kind="named",
                line=line,
                reason="esm.named",
            ))
    ns = m.group("namespace")
    if ns:
        out.append(ImportBinding(
            file_path=file_path,
            local_name=ns,
            imported_name="*",
            source_module=source_mod,
            import_kind="namespace",
            line=line,
            reason="esm.namespace",
        ))


def _emit_js_cjs_bindings(
    m: re.Match, file_path: str, text: str, out: list[ImportBinding],
) -> None:
    source_mod = m.group("source") or ""
    line = text[: m.start()].count("\n") + 1
    default = m.group("default")
    if default:
        out.append(ImportBinding(
            file_path=file_path,
            local_name=default,
            imported_name="default",
            source_module=source_mod,
            import_kind="default",
            line=line,
            reason="cjs.require",
        ))
    named = m.group("named")
    if named:
        for binding in _parse_named_specs(named, separator_for_aliased=":"):
            local, imported = binding
            out.append(ImportBinding(
                file_path=file_path,
                local_name=local,
                imported_name=imported,
                source_module=source_mod,
                import_kind="named",
                line=line,
                reason="cjs.destructure",
            ))


def _parse_named_specs(
    body: str, separator_for_aliased: str = " as ",
) -> list[tuple[str, str]]:
    """Parse the inside of ``{ a, b as c }`` (ESM) or ``{ a, b: c }`` (CJS).

    Returns ``[(local_name, imported_name), ...]``. The first form uses
    ``as`` to rename; the second (destructuring in require()) uses ``:``.
    """
    out: list[tuple[str, str]] = []
    for raw in body.split(","):
        spec = raw.strip()
        if not spec:
            continue
        if separator_for_aliased in spec:
            left, _, right = spec.partition(separator_for_aliased)
            imported = left.strip()
            local = right.strip()
        else:
            imported = local = spec
        # Drop trailing type-only markers ("type Foo") rarely seen in named specs.
        if imported.startswith("type "):
            imported = imported[len("type "):].strip()
        if local and imported:
            out.append((local, imported))
    return out


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


def _parse_parameters_text(params: str, *, extraction_source: str) -> list[ParsedParameter]:
    out: list[ParsedParameter] = []
    for raw in _split_params(params):
        text = raw.strip()
        if not text:
            continue
        default_value = ""
        if "=" in text:
            text, default_value = [part.strip() for part in text.split("=", 1)]
        is_variadic = text.startswith("...")
        if is_variadic:
            text = text[3:].strip()
        declared_type = ""
        if ":" in text:
            name_part, declared_type = [part.strip() for part in text.split(":", 1)]
        else:
            name_part = text
        is_optional = name_part.endswith("?") or bool(default_value)
        name = name_part.rstrip("?").strip()
        if not name:
            name = "<anonymous>"
        out.append(ParsedParameter(
            name=name,
            position=len(out),
            declared_type=declared_type,
            inferred_type=declared_type,
            default_value=default_value,
            is_optional=is_optional,
            is_variadic=is_variadic,
            confidence=0.76 if declared_type else 0.58,
            precision_level=int(PrecisionLevel.SYNTAX),
            extraction_source=extraction_source,
            metadata={"raw": raw.strip()},
        ))
    return out


def _split_params(params: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for idx, ch in enumerate(params):
        if quote:
            if ch == quote and (idx == 0 or params[idx - 1] != "\\"):
                quote = None
            continue
        if ch in {"'", '"', "`"}:
            quote = ch
            continue
        if ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            items.append(params[start:idx])
            start = idx + 1
    tail = params[start:]
    if tail.strip():
        items.append(tail)
    return items
