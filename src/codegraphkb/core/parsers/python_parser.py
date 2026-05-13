"""Python parser using stdlib `ast`. No external deps."""
from __future__ import annotations

import ast
from typing import Iterable

from codegraphkb.core.graph_schema import PrecisionLevel
from codegraphkb.core.parsers.base import (
    ExtractResult,
    ImportBinding,
    ParsedEdge,
    ParsedParameter,
    ParsedSymbol,
)
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
    imports: list[ImportBinding] = []

    # Module-level imports
    for node in ast.iter_child_nodes(tree):
        _collect_imports(
            node,
            source_qname=module_qname,
            file_path=source.rel_path,
            edges=edges,
            imports=imports,
        )

    visitor = _Visitor(module_qname=module_qname, symbols=symbols, edges=edges, source=source)
    visitor.visit(tree)

    # Module-level constants (UPPER_CASE assignments). PR 13 — closes the gap
    # for tasks that reference data-shape symbols like `SECRET_FILES`.
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and _is_module_constant(target.id):
                    qname = f"{module_qname}.{target.id}"
                    symbols.append(ParsedSymbol(
                        kind="constant",
                        name=target.id,
                        qualified_name=qname,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        signature=f"{target.id} = ...",
                        parent_qualified_name=module_qname,
                    ))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _is_module_constant(node.target.id):
                qname = f"{module_qname}.{node.target.id}"
                symbols.append(ParsedSymbol(
                    kind="constant",
                    name=node.target.id,
                    qualified_name=qname,
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    signature=f"{node.target.id}: ...",
                    parent_qualified_name=module_qname,
                ))

    return ExtractResult(symbols=symbols, edges=edges, imports=imports)


def _is_module_constant(name: str) -> bool:
    if not name or name.startswith("_"):
        return False
    # ALL_CAPS_LIKE_THIS — the standard Python convention for module constants.
    return name == name.upper() and any(ch.isalpha() for ch in name)


def _module_qname(rel_path: str) -> str:
    p = rel_path
    if p.endswith(".py"):
        p = p[:-3]
    return p.replace("/", ".").replace("\\", ".")


def _collect_imports(
    node: ast.AST,
    source_qname: str,
    file_path: str,
    edges: list[ParsedEdge],
    imports: list[ImportBinding],
) -> None:
    """Emit IMPORTS edges and ImportBindings for each module-level import.

    The IMPORTS edge keeps existing behavior (one edge per imported symbol or
    module, dst_name = fully-qualified target). The ImportBinding records the
    *local* alias so the whole-repo resolver can rewrite later edges that use
    that alias as a free name (e.g. ``from x import y as z; z()`` should
    resolve CALLS z → x.y).
    """
    line = getattr(node, "lineno", None)
    if isinstance(node, ast.Import):
        # `import a.b` binds local name `a`. `import a.b as c` binds `c`.
        for alias in node.names:
            edges.append(ParsedEdge(
                src_qualified_name=source_qname,
                dst_name=alias.name,
                edge_type="IMPORTS",
                line=line,
            ))
            local_name = alias.asname or alias.name.split(".")[0]
            imports.append(ImportBinding(
                file_path=file_path,
                local_name=local_name,
                imported_name=alias.name,
                source_module=alias.name,
                import_kind="namespace" if alias.asname is None else "default",
                line=line,
                reason="ast.Import",
            ))
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        level = getattr(node, "level", 0) or 0
        # Relative imports (`from .x import y`): record level via prefix dots
        # in source_module so the resolver can map them to a sibling module.
        rel_prefix = "." * level
        for alias in node.names:
            target = f"{module}.{alias.name}" if module else alias.name
            edges.append(ParsedEdge(
                src_qualified_name=source_qname,
                dst_name=target,
                edge_type="IMPORTS",
                line=line,
            ))
            if alias.name == "*":
                # Star imports don't bind a single local name; skip.
                continue
            imports.append(ImportBinding(
                file_path=file_path,
                local_name=alias.asname or alias.name,
                imported_name=alias.name,
                source_module=f"{rel_prefix}{module}" if module else rel_prefix,
                import_kind="named",
                line=line,
                reason="ast.ImportFrom",
                metadata={"level": level},
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
            return_type=_annotation(node.returns),
            parameters=_parameters_for_function(node, skip_receiver=kind == "method"),
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


def _parameters_for_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    skip_receiver: bool,
) -> list[ParsedParameter]:
    out: list[ParsedParameter] = []

    def add_arg(
        arg: ast.arg,
        *,
        default_node: ast.AST | None = None,
        is_variadic: bool = False,
        param_kind: str = "positional",
    ) -> None:
        if skip_receiver and not out and arg.arg in {"self", "cls"}:
            return
        declared = _annotation(arg.annotation)
        default_value = _safe_unparse(default_node) if default_node is not None else ""
        out.append(ParsedParameter(
            name=arg.arg,
            position=len(out),
            declared_type=declared,
            inferred_type=declared,
            default_value=default_value,
            is_optional=bool(default_value) or _annotation_allows_none(declared),
            is_variadic=is_variadic,
            confidence=0.78 if declared else 0.64,
            precision_level=int(PrecisionLevel.SYNTAX),
            extraction_source="python-ast",
            metadata={"param_kind": param_kind},
        ))

    positional = list(node.args.posonlyargs) + list(node.args.args)
    defaults = list(node.args.defaults)
    default_offset = len(positional) - len(defaults)
    for idx, arg in enumerate(positional):
        default = defaults[idx - default_offset] if idx >= default_offset else None
        add_arg(arg, default_node=default, param_kind="positional")

    if node.args.vararg is not None:
        add_arg(node.args.vararg, is_variadic=True, param_kind="vararg")

    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        add_arg(arg, default_node=default, param_kind="keyword_only")

    if node.args.kwarg is not None:
        add_arg(node.args.kwarg, is_variadic=True, param_kind="kwarg")

    return out


def _annotation(node: ast.AST | None) -> str:
    if node is None:
        return ""
    return _safe_unparse(node)


def _annotation_allows_none(value: str) -> bool:
    cleaned = value.replace(" ", "")
    return (
        "None" in value
        or "Optional[" in value
        or "|None" in cleaned
        or "None|" in cleaned
    )
