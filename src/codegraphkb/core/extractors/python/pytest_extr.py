"""Pytest detector — fixtures + test functions linked to symbols they call."""
from __future__ import annotations

import ast

from codegraphkb.core.extractors.base import (
    EDGE_TESTS_SYMBOL, FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile


def detect_pytest(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    rel = source.rel_path.lower()
    if not (rel.startswith("tests/") or "/tests/" in "/" + rel + "/"
            or rel.startswith("test_") or "/test_" in rel
            or rel.endswith("_test.py") or "conftest.py" in rel):
        return FrameworkExtraction()

    try:
        tree = ast.parse(source.content)
    except SyntaxError:
        return FrameworkExtraction()

    out = FrameworkExtraction()
    detected = False
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_test = node.name.startswith("test_") or node.name.startswith("test")
        is_fixture = any(_is_fixture_decorator(d) for d in node.decorator_list)
        if not (is_test or is_fixture):
            continue
        kind = "fixture" if is_fixture else "test_block"
        qname_prefix = "pytest::"
        qname = f"{qname_prefix}{source.rel_path}::{node.name}"
        out.extra_symbols.append(ParsedSymbol(
            kind=kind,
            name=node.name,
            qualified_name=qname,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=f"{kind} {node.name}",
            extras={"framework": "pytest"},
        ))
        detected = True
        if is_test:
            for call in _collect_call_names(node):
                out.extra_edges.append(ParsedEdge(
                    src_qualified_name=qname,
                    dst_name=call,
                    edge_type=EDGE_TESTS_SYMBOL,
                    confidence=0.5,
                    extraction_source="extractor:pytest",
                    line=node.lineno,
                ))
    if detected:
        out.detected_frameworks.append("pytest")
    return out


def _is_fixture_decorator(decorator: ast.AST) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr == "fixture"
    if isinstance(target, ast.Name):
        return target.id == "fixture"
    return False


def _collect_call_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            target = child.func
            name = None
            if isinstance(target, ast.Name):
                name = target.id
            elif isinstance(target, ast.Attribute):
                name = target.attr
            if name and not name.startswith("_") and not name.startswith("assert"):
                out.add(name)
    return out
