"""Python parser using stdlib `ast`. No external deps."""
from __future__ import annotations

import ast
from typing import Iterable

from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options",
                    "route", "api_route", "websocket"}


def parse_python(source: SourceFile) -> ExtractResult:
    try:
        tree = ast.parse(source.content, filename=source.rel_path)
    except SyntaxError:
        return ExtractResult(symbols=[], edges=[])

    module_qname = _module_qname(source.rel_path)
    symbols: list[ParsedSymbol] = []
    edges: list[ParsedEdge] = []

    # Module-level imports
    for node in ast.iter_child_nodes(tree):
        _collect_imports(node, source_qname=module_qname, edges=edges)

    visitor = _Visitor(module_qname=module_qname, symbols=symbols, edges=edges, source=source)
    visitor.visit(tree)
    return ExtractResult(symbols=symbols, edges=edges)


def _module_qname(rel_path: str) -> str:
    p = rel_path
    if p.endswith(".py"):
        p = p[:-3]
    return p.replace("/", ".").replace("\\", ".")


def _collect_imports(node: ast.AST, source_qname: str, edges: list[ParsedEdge]) -> None:
    if isinstance(node, ast.Import):
        for alias in node.names:
            edges.append(ParsedEdge(
                src_qualified_name=source_qname,
                dst_name=alias.name,
                edge_type="IMPORTS",
                line=getattr(node, "lineno", None),
            ))
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        for alias in node.names:
            target = f"{module}.{alias.name}" if module else alias.name
            edges.append(ParsedEdge(
                src_qualified_name=source_qname,
                dst_name=target,
                edge_type="IMPORTS",
                line=getattr(node, "lineno", None),
            ))


def _signature(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        try:
            args = ast.unparse(node.args)  # type: ignore[attr-defined]
        except Exception:
            args = ""
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({args})"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(_safe_unparse(b) for b in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    return ""


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)  # type: ignore[attr-defined]
    except Exception:
        return getattr(node, "id", "?")


def _decorator_route(decorator: ast.AST) -> tuple[str, str] | None:
    """If decorator looks like a route (e.g. @app.post('/x')), return (method, path)."""
    target = decorator
    args: list[ast.AST] = []
    if isinstance(decorator, ast.Call):
        target = decorator.func
        args = list(decorator.args)
    name = ""
    if isinstance(target, ast.Attribute):
        name = target.attr
    elif isinstance(target, ast.Name):
        name = target.id
    name_lower = name.lower()
    if name_lower not in ROUTE_DECORATORS:
        return None
    path = "?"
    if args and isinstance(args[0], ast.Constant) and isinstance(args[0].value, str):
        path = args[0].value
    method = name_lower.upper() if name_lower != "route" else "ANY"
    return method, path


class _Visitor(ast.NodeVisitor):
    def __init__(self, module_qname: str, symbols: list[ParsedSymbol],
                 edges: list[ParsedEdge], source: SourceFile):
        self.module = module_qname
        self.symbols = symbols
        self.edges = edges
        self.source = source
        self.scope_stack: list[str] = [module_qname]
        self.class_stack: list[str] = []

    def _qname(self, name: str) -> str:
        return ".".join([*self.scope_stack, name])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qname = self._qname(node.name)
        self.symbols.append(ParsedSymbol(
            kind="class",
            name=node.name,
            qualified_name=qname,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=_signature(node),
            docstring=ast.get_docstring(node) or "",
            parent_qualified_name=self.scope_stack[-1] if self.scope_stack else None,
        ))
        for base in node.bases:
            base_name = _safe_unparse(base)
            if base_name and base_name != "?":
                self.edges.append(ParsedEdge(
                    src_qualified_name=qname,
                    dst_name=base_name,
                    edge_type="EXTENDS",
                    line=node.lineno,
                ))
        self.scope_stack.append(node.name)
        self.class_stack.append(qname)
        for child in node.body:
            self.visit(child)
        self.class_stack.pop()
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node)

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qname = self._qname(node.name)
        kind = "method" if self.class_stack else "function"
        self.symbols.append(ParsedSymbol(
            kind=kind,
            name=node.name,
            qualified_name=qname,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=_signature(node),
            docstring=ast.get_docstring(node) or "",
            parent_qualified_name=self.scope_stack[-1] if self.scope_stack else None,
        ))
        # Routes
        for decorator in node.decorator_list:
            route = _decorator_route(decorator)
            if route is not None:
                method, path = route
                route_qname = f"route::{method} {path}"
                self.symbols.append(ParsedSymbol(
                    kind="route",
                    name=f"{method} {path}",
                    qualified_name=route_qname,
                    start_line=getattr(decorator, "lineno", node.lineno),
                    end_line=node.lineno,
                    extras={"http_method": method, "path": path},
                ))
                self.edges.append(ParsedEdge(
                    src_qualified_name=route_qname,
                    dst_name=qname,
                    edge_type="ROUTES_TO",
                    confidence=0.95,
                ))
        # Tests heuristic: pytest-style test functions
        if node.name.startswith("test_") or qname.endswith(".test"):
            for call_target in _calls_in(node):
                self.edges.append(ParsedEdge(
                    src_qualified_name=qname,
                    dst_name=call_target,
                    edge_type="TESTS",
                    confidence=0.5,
                    extraction_source="heuristic:test_calls",
                ))
        # Calls
        self.scope_stack.append(node.name)
        for call_target in _calls_in(node):
            self.edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=call_target,
                edge_type="CALLS",
                confidence=0.7,
            ))
        # Recurse for nested functions/classes
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.visit(child)
        self.scope_stack.pop()


def _calls_in(node: ast.AST) -> Iterable[str]:
    seen = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            target = child.func
            name = None
            if isinstance(target, ast.Name):
                name = target.id
            elif isinstance(target, ast.Attribute):
                name = target.attr
            if name and name not in seen and not name.startswith("_"):
                seen.add(name)
                yield name
