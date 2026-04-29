"""Pydantic schema / model detector."""
from __future__ import annotations

import ast

from codegraphkb.core.extractors.base import FrameworkExtraction
from codegraphkb.core.parsers.base import ExtractResult, ParsedSymbol
from codegraphkb.core.scanner import SourceFile


def detect_pydantic(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    text = source.content
    if "BaseModel" not in text and "pydantic" not in text:
        return FrameworkExtraction()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return FrameworkExtraction()
    out = FrameworkExtraction()
    detected = False
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not _has_basemodel_base(node):
            continue
        qname = f"schema::{node.name}"
        out.extra_symbols.append(ParsedSymbol(
            kind="schema",
            name=node.name,
            qualified_name=qname,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=f"Pydantic schema {node.name}",
            extras={"framework": "pydantic"},
        ))
        detected = True
    if detected:
        out.detected_frameworks.append("pydantic")
    return out


def _has_basemodel_base(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        text = _safe(base)
        if "BaseModel" in text:
            return True
    return False


def _safe(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""
