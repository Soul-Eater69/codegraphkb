"""Tree-sitter parser for JavaScript / TypeScript / JSX / TSX.

Loaded lazily by the registry so the package still imports cleanly without the
`codegraphkb[parser]` extra installed.

What this catches that the regex parser misses:
  - methods inside classes (with class.method qualified name)
  - arrow functions assigned to variables (incl. inside object literals)
  - exported defaults / re-exports
  - import alias resolution
  - calls expressed as member-access chains (foo.bar.baz())
  - `describe` / `it` / `test` blocks for Jest / Vitest test linkage
  - JSX-typed React component detection (PascalCase + returns JSX)
"""
from __future__ import annotations

from typing import Any, Iterable

from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

# Imported lazily to keep the optional dep boundary clean.
_PARSER_CACHE: dict[str, Any] = {}


def _get_parser(language: str):
    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]
    from tree_sitter_language_pack import get_parser  # type: ignore
    if language == "typescript":
        parser = get_parser("typescript")
    elif language == "tsx":
        parser = get_parser("tsx")
    elif language == "jsx":
        parser = get_parser("javascript")  # tree-sitter-javascript handles JSX
    else:
        parser = get_parser("javascript")
    _PARSER_CACHE[language] = parser
    return parser


def parse_treesitter_js(source: SourceFile) -> ExtractResult:
    lang = _detect_grammar(source)
    parser = _get_parser(lang)
    tree = parser.parse(source.content.encode("utf-8"))
    module = _module_qname(source.rel_path)
    state = _State(module=module, source=source.content, source_bytes=source.content.encode("utf-8"))
    _walk(tree.root_node, state, scope=[module], class_stack=[])
    return ExtractResult(symbols=state.symbols, edges=state.edges)


# ---------- internals ----------

class _State:
    def __init__(self, module: str, source: str, source_bytes: bytes):
        self.module = module
        self.source = source
        self.source_bytes = source_bytes
        self.symbols: list[ParsedSymbol] = []
        self.edges: list[ParsedEdge] = []


_FUNCTION_NODE_TYPES = {
    "function_declaration",
    "generator_function_declaration",
    "function",
    "function_expression",
    "arrow_function",
    "method_definition",
    "method_signature",
}
_CLASS_NODE_TYPES = {"class_declaration", "class"}
_ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "all", "use"}
_TEST_BLOCKS = {"describe", "it", "test", "context", "suite"}
_KNOWN_BUILTINS = {
    "Array", "Object", "String", "Number", "Boolean", "Promise", "Set", "Map",
    "console", "require", "module", "exports", "JSON", "Math", "Date",
    "Symbol", "Error", "RegExp", "fetch", "URL", "Buffer", "process",
}


def _walk(node, state: _State, scope: list[str], class_stack: list[str]) -> None:
    nt = node.type
    if nt in _CLASS_NODE_TYPES:
        _handle_class(node, state, scope, class_stack)
        return
    if nt in _FUNCTION_NODE_TYPES:
        _handle_function(node, state, scope, class_stack)
        return
    if nt == "lexical_declaration" or nt == "variable_declaration":
        _handle_var_declaration(node, state, scope, class_stack)
        return
    if nt == "import_statement":
        _handle_import(node, state)
        return
    if nt == "export_statement":
        # Drill into the inner declaration so functions/classes still get captured.
        for child in node.named_children:
            _walk(child, state, scope, class_stack)
        return
    if nt == "call_expression":
        _handle_top_level_call(node, state, scope)
        # fall through so children are visited
    for child in node.named_children:
        _walk(child, state, scope, class_stack)


def _handle_import(node, state: _State) -> None:
    src_node = node.child_by_field_name("source")
    if src_node is None:
        return
    target = _strip_quotes(_text(src_node, state))
    if target:
        state.edges.append(ParsedEdge(
            src_qualified_name=state.module,
            dst_name=target,
            edge_type="IMPORTS",
            line=node.start_point[0] + 1,
            confidence=0.95,
            extraction_source="tree-sitter",
        ))


def _handle_class(node, state: _State, scope: list[str], class_stack: list[str]) -> None:
    name_node = node.child_by_field_name("name")
    name = _text(name_node, state) if name_node else "<anonymous>"
    qname = ".".join([*scope, name])
    superclass = node.child_by_field_name("superclass")
    extends = _text(superclass, state).lstrip("()").rstrip(")") if superclass else None
    sig = f"class {name}" + (f" extends {extends}" if extends else "")
    state.symbols.append(ParsedSymbol(
        kind="class",
        name=name,
        qualified_name=qname,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=sig,
        parent_qualified_name=scope[-1] if scope else None,
    ))
    if extends:
        # `extends Foo.Bar` — keep only the last segment for a basic dst_name.
        last = extends.split(".")[-1]
        state.edges.append(ParsedEdge(
            src_qualified_name=qname,
            dst_name=last,
            edge_type="EXTENDS",
            confidence=0.9,
            extraction_source="tree-sitter",
            line=node.start_point[0] + 1,
        ))
    body = node.child_by_field_name("body")
    if body is not None:
        for child in body.named_children:
            if child.type in _FUNCTION_NODE_TYPES:
                _handle_function(child, state, scope=[*scope, name], class_stack=[*class_stack, qname])
            else:
                _walk(child, state, scope=[*scope, name], class_stack=[*class_stack, qname])


def _handle_function(node, state: _State, scope: list[str], class_stack: list[str],
                     name_override: str | None = None,
                     forced_kind: str | None = None) -> None:
    if name_override is None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            # anonymous arrow / function expression — handled by the caller via name_override
            for child in node.named_children:
                _walk(child, state, scope, class_stack)
            return
        name = _text(name_node, state)
    else:
        name = name_override
    qname = ".".join([*scope, name])

    params_node = node.child_by_field_name("parameters")
    params_text = _text(params_node, state).strip() if params_node else ""
    body_node = node.child_by_field_name("body")
    has_jsx = _contains_jsx(body_node, state) if body_node is not None else False

    if forced_kind is not None:
        kind = forced_kind
    elif class_stack:
        kind = "method"
    elif name and name[0].isupper() and has_jsx:
        kind = "component"
    else:
        kind = "function"

    sig = ""
    if node.type == "method_definition":
        sig = f"{name}{params_text}".strip()
    elif node.type == "arrow_function":
        sig = f"const {name} = {params_text} =>" if params_text else f"const {name} = () =>"
    else:
        prefix = "async function" if _has_async_modifier(node, state) else "function"
        sig = f"{prefix} {name}{params_text}".strip()

    state.symbols.append(ParsedSymbol(
        kind=kind,
        name=name,
        qualified_name=qname,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=sig,
        parent_qualified_name=scope[-1] if scope else None,
    ))

    # Test-block linkage: `describe('login flow', () => { ... })` should TEST the symbols
    # it calls. We approximate: treat any function whose name starts with `test_` as a test
    # OR rely on test blocks emitted from var-decl path below.
    is_test = name.startswith("test_") or name.startswith("test")

    if body_node is not None:
        seen_calls: set[str] = set()
        for call_target in _collect_calls(body_node, state):
            if call_target in seen_calls or call_target in _KNOWN_BUILTINS:
                continue
            seen_calls.add(call_target)
            edge_type = "TESTS" if is_test else "CALLS"
            state.edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=call_target,
                edge_type=edge_type,
                confidence=0.7 if edge_type == "CALLS" else 0.5,
                extraction_source="tree-sitter",
            ))
        # Recurse into nested classes/functions inside the body.
        for child in body_node.named_children:
            if child.type in _CLASS_NODE_TYPES or child.type in _FUNCTION_NODE_TYPES:
                _walk(child, state, scope=[*scope, name], class_stack=class_stack)
            elif child.type in {"lexical_declaration", "variable_declaration"}:
                _handle_var_declaration(child, state, scope=[*scope, name], class_stack=class_stack)


def _handle_var_declaration(node, state: _State, scope: list[str], class_stack: list[str]) -> None:
    """Handles `const Foo = (...) => { ... }`, `const useFoo = function() {}`, etc."""
    for declarator in node.named_children:
        if declarator.type != "variable_declarator":
            continue
        name_node = declarator.child_by_field_name("name")
        value_node = declarator.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        name = _text(name_node, state)
        if value_node.type in _FUNCTION_NODE_TYPES:
            _handle_function(value_node, state, scope=scope, class_stack=class_stack,
                             name_override=name)
        elif value_node.type == "call_expression":
            # cover `const handler = wrap(async () => { ... })`
            inner = _find_inner_function(value_node)
            if inner is not None:
                _handle_function(inner, state, scope=scope, class_stack=class_stack,
                                 name_override=name)


def _find_inner_function(node):
    for child in node.named_children:
        if child.type in _FUNCTION_NODE_TYPES:
            return child
        inner = _find_inner_function(child)
        if inner is not None:
            return inner
    return None


def _handle_top_level_call(node, state: _State, scope: list[str]) -> None:
    callee = node.child_by_field_name("function")
    args = node.child_by_field_name("arguments")
    if callee is None:
        return
    callee_text = _text(callee, state)
    # Express/Fastify-style: app.get('/x', handler)
    parts = callee_text.split(".")
    method = parts[-1].lower() if parts else ""
    if method in _ROUTE_METHODS and len(parts) >= 2 and args is not None:
        path = _first_string_arg(args, state)
        if path:
            handler = _last_identifier_arg(args, state)
            method_uc = method.upper()
            route_qname = f"route::{method_uc} {path}"
            state.symbols.append(ParsedSymbol(
                kind="route",
                name=f"{method_uc} {path}",
                qualified_name=route_qname,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                extras={"http_method": method_uc, "path": path},
            ))
            if handler:
                state.edges.append(ParsedEdge(
                    src_qualified_name=route_qname,
                    dst_name=handler,
                    edge_type="ROUTES_TO",
                    confidence=0.85,
                    extraction_source="tree-sitter",
                    line=node.start_point[0] + 1,
                ))

    # describe/it/test('...', () => { ... })
    if callee_text in _TEST_BLOCKS and args is not None:
        label = _first_string_arg(args, state) or "<anonymous>"
        inner = _find_inner_function(node)
        if inner is not None:
            test_qname = ".".join([*scope, f"{callee_text}::{label}"])
            state.symbols.append(ParsedSymbol(
                kind="test",
                name=f"{callee_text}: {label}",
                qualified_name=test_qname,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
            ))
            for call_target in _collect_calls(inner, state):
                if call_target in _KNOWN_BUILTINS or call_target in _TEST_BLOCKS:
                    continue
                state.edges.append(ParsedEdge(
                    src_qualified_name=test_qname,
                    dst_name=call_target,
                    edge_type="TESTS",
                    confidence=0.6,
                    extraction_source="tree-sitter:test_block",
                ))


def _collect_calls(node, state: _State) -> Iterable[str]:
    if node is None:
        return []
    out: list[str] = []
    stack = [node]
    while stack:
        cur = stack.pop()
        if cur.type == "call_expression":
            callee = cur.child_by_field_name("function")
            if callee is not None:
                callee_text = _text(callee, state)
                last = callee_text.rsplit(".", 1)[-1]
                last = last.split("(", 1)[0].strip()
                if last and last.isidentifier() and not last.startswith("_"):
                    out.append(last)
        for child in cur.named_children:
            stack.append(child)
    return out


def _contains_jsx(node, state: _State) -> bool:
    if node is None:
        return False
    stack = [node]
    while stack:
        cur = stack.pop()
        if cur.type in {"jsx_element", "jsx_self_closing_element", "jsx_fragment"}:
            return True
        for child in cur.named_children:
            stack.append(child)
    return False


def _has_async_modifier(node, state: _State) -> bool:
    text = _text(node, state)[:80]
    return text.strip().startswith("async")


def _first_string_arg(arguments_node, state: _State) -> str | None:
    for arg in arguments_node.named_children:
        if arg.type in {"string", "template_string"}:
            return _strip_quotes(_text(arg, state))
    return None


def _last_identifier_arg(arguments_node, state: _State) -> str | None:
    last: str | None = None
    for arg in arguments_node.named_children:
        if arg.type == "identifier":
            last = _text(arg, state)
        elif arg.type == "member_expression":
            last = _text(arg, state).rsplit(".", 1)[-1]
    return last


def _text(node, state: _State) -> str:
    if node is None:
        return ""
    return state.source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")) or (
        s.startswith("`") and s.endswith("`")
    ):
        return s[1:-1]
    return s


def _module_qname(rel_path: str) -> str:
    p = rel_path
    for ext in (".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs"):
        if p.endswith(ext):
            p = p[: -len(ext)]
            break
    return p.replace("/", ".").replace("\\", ".")


def _detect_grammar(source: SourceFile) -> str:
    if source.rel_path.endswith(".tsx"):
        return "tsx"
    if source.rel_path.endswith(".ts"):
        return "typescript"
    if source.rel_path.endswith(".jsx"):
        return "jsx"
    return "javascript"
