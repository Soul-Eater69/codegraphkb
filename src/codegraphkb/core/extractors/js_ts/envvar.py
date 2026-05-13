"""Detect `process.env.X` / `import.meta.env.X` env reads in JS/TS.

Mirrors the Python env extractor: the ``READS_ENV_VAR`` edge's
``src_qualified_name`` is the enclosing function's qname (so impact queries
can ask "what functions read AUTH_TOKEN?"). Reads outside any function fall
back to the module qname so the edge isn't dropped entirely.
"""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_READS_ENV_VAR, FrameworkExtraction, find_enclosing_symbol,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_ENV_RE = re.compile(
    r"(?:process\.env|import\.meta\.env)\.([A-Z][A-Z0-9_]*)"
)


def detect_env_vars_js(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    if "process.env" not in source.content and "import.meta.env" not in source.content:
        return FrameworkExtraction()
    out = FrameworkExtraction()
    text = source.content
    seen: set[str] = set()
    seen_edges: set[tuple[str, str]] = set()
    module_qname = source.rel_path.replace("/", ".").replace("\\", ".")
    for m in _ENV_RE.finditer(text):
        var_name = m.group(1)
        line = text[: m.start()].count("\n") + 1
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
        src_qname = find_enclosing_symbol(extract.symbols, line) or module_qname
        edge_key = (src_qname, qname)
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=src_qname,
            dst_name=qname,
            dst_qname=qname,
            edge_type=EDGE_READS_ENV_VAR,
            confidence=0.85,
            extraction_source="extractor:env_js",
            line=line,
        ))
    if out.extra_symbols:
        out.detected_frameworks.append("env")
    return out
