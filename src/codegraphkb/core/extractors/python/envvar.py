"""Detect `os.environ['X']` / `os.getenv('X')` / `Settings(env=...)` env reads.

For each detected read, emits:
    * a synthetic ``env_var`` symbol (qname = ``env::<NAME>``), de-duplicated
      across the file
    * a ``READS_ENV_VAR`` edge from the *enclosing function's qualified name*
      to that synthetic symbol — so callers / impact analysis can find every
      symbol that touches ``ANTHROPIC_API_KEY``.
"""
from __future__ import annotations

import ast

from codegraphkb.core.extractors.base import (
    EDGE_READS_ENV_VAR, FrameworkExtraction, find_enclosing_symbol,
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

    for node in ast.walk(tree):
        var_name = _env_name_from(node)
        if not var_name:
            continue
        line = getattr(node, "lineno", 0)
        qname = f"env::{var_name}"
        if var_name not in seen:
            seen.add(var_name)
            out.extra_symbols.append(ParsedSymbol(
                kind="env_var",
                name=var_name,
                qualified_name=qname,
                start_line=line,
                end_line=line,
                signature=f"env var {var_name}",
                extras={"framework": "env"},
            ))
        # Resolve the enclosing function via the structural symbol list so the
        # edge's ``src_qualified_name`` is the real qname (``pkg.mod.func``),
        # not a bare function name. Without this the edge can't be joined back
        # to a symbol row and impact queries miss the env read.
        src_qname = find_enclosing_symbol(extract.symbols, line)
        if src_qname is not None:
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=src_qname,
                dst_name=qname,
                dst_qname=qname,
                edge_type=EDGE_READS_ENV_VAR,
                confidence=0.9,
                extraction_source="extractor:env",
                line=line or None,
            ))
    if out.extra_symbols:
        out.detected_frameworks.append("env")
    return out


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
