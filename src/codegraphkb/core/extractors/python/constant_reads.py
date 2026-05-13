"""Detect functions that read module-level UPPER_CASE constants.

The Python structural parser already emits ``constant`` symbols for
module-level ``ALL_CAPS = ...`` assignments. This extractor wires them into
the graph by emitting ``READS_CONSTANT`` edges from every function body that
references one of those constants by name.

Why this lives in an extractor rather than the parser: it needs the full set
of constants for the file (which the parser produces) and the per-function
qnames (which the parser produces) before it can match references against
defined constants. Running here keeps the structural parser fast and
self-contained.

Scope: same-file only. Cross-file constant tracing would require the
whole-repo import binding table; that lands in a follow-up.
"""
from __future__ import annotations

import ast

from codegraphkb.core.extractors.base import (
    EDGE_READS_CONSTANT, FrameworkExtraction, find_enclosing_symbol,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge
from codegraphkb.core.scanner import SourceFile


def detect_constant_reads(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    out = FrameworkExtraction()

    # Build the per-file constant set from symbols the structural parser
    # already produced. ``qualified_name`` is the resolved target.
    constants_by_name: dict[str, str] = {
        sym.name: sym.qualified_name
        for sym in extract.symbols
        if sym.kind == "constant"
    }
    if not constants_by_name:
        return out

    try:
        tree = ast.parse(source.content)
    except SyntaxError:
        return out

    seen_edges: set[tuple[str, str]] = set()  # (src_qname, dst_qname)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name):
            continue
        if not isinstance(node.ctx, ast.Load):
            continue
        target_qname = constants_by_name.get(node.id)
        if not target_qname:
            continue
        line = getattr(node, "lineno", 0) or 0
        src_qname = find_enclosing_symbol(extract.symbols, line)
        if not src_qname:
            continue
        # Don't emit a self-edge: the assignment statement itself technically
        # contains the Name in Store context, but ast.Load filters those.
        # Still guard against the (rare) case of constant-references inside
        # a different constant's value expression.
        if src_qname == target_qname:
            continue
        key = (src_qname, target_qname)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=src_qname,
            dst_name=node.id,
            dst_qname=target_qname,
            edge_type=EDGE_READS_CONSTANT,
            confidence=0.85,
            extraction_source="extractor:constants",
            line=line or None,
            reason="Function references a module-level UPPER_CASE constant",
        ))
    return out
