"""Detect `os.environ['X']` / `os.getenv('X')` / `Settings(env=...)` env reads."""
from __future__ import annotations

import ast

from codegraphkb.core.extractors.base import (
    EDGE_READS_ENV_VAR, FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile


def detect_env_vars(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    if "os.environ" not in source.content and "getenv" not in source.content:
        return FrameworkExtraction()
    try:
        tree = ast.parse(source.content)
    except SyntaxError:
        return FrameworkExtraction()
    out = FrameworkExtraction()
    seen: set[str] = set()

    # Walk; for each os.environ['X'] or os.getenv('X', ...) under a function,
    # emit an EnvVar symbol + READS_ENV_VAR edge from the enclosing function.
    parent_map = _build_parent_map(tree)
    for node in ast.walk(tree):
        var_name = _env_name_from(node)
        if not var_name or var_name in seen:
            continue
        seen.add(var_name)
        qname = f"env::{var_name}"
        out.extra_symbols.append(ParsedSymbol(
            kind="env_var",
            name=var_name,
            qualified_name=qname,
            start_line=getattr(node, "lineno", 0),
            end_line=getattr(node, "lineno", 0),
            signature=f"env var {var_name}",
            extras={"framework": "env"},
        ))
        enclosing = _enclosing_function(node, parent_map)
        if enclosing is not None:
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=enclosing,
                dst_name=qname,
                edge_type=EDGE_READS_ENV_VAR,
                confidence=0.9,
                extraction_source="extractor:env",
                line=getattr(node, "lineno", None),
            ))
    if out.extra_symbols:
        out.detected_frameworks.append("env")
    return out


def _build_parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


def _enclosing_function(node: ast.AST, parents: dict[int, ast.AST]) -> str | None:
    cur = node
    while id(cur) in parents:
        cur = parents[id(cur)]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
    return None


def _env_name_from(node: ast.AST) -> str | None:
    # os.getenv('X', ...) -> first string arg
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "getenv":
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return node.args[0].value
    # os.environ['X'] / os.environ.get('X')
    if isinstance(node, ast.Subscript):
        v = node.value
        if isinstance(v, ast.Attribute) and v.attr == "environ":
            slc = node.slice
            if isinstance(slc, ast.Constant) and isinstance(slc.value, str):
                return slc.value
    if isinstance(node, ast.Call):
        fn = node.func
        if (isinstance(fn, ast.Attribute) and fn.attr == "get"
                and isinstance(fn.value, ast.Attribute) and fn.value.attr == "environ"):
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                return node.args[0].value
    return None
