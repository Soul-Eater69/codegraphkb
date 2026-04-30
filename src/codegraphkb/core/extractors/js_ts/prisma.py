"""Prisma model usage detector.

For every call shaped like ``prisma.<model>.<op>(...)`` we emit:

* a ``Model`` symbol (one per distinct model name, deduped per file)
* a ``QUERIES`` edge from the *enclosing function/method* of the call to the
  Model (so that process maps can attribute DB access to handlers/services).
* the legacy ``MODEL_USED_BY`` edge ``Model → file_module`` for back-compat.

We don't parse ``schema.prisma``; only client usage is captured.
"""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_MODEL_USED_BY,
    EDGE_QUERIES,
    FrameworkExtraction,
    find_enclosing_symbol,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_USAGE_RE = re.compile(
    r"\b(?P<recv>prisma|db|client)\.(?P<model>[a-z][\w]*)\.(?P<op>findMany|findUnique|"
    r"findFirst|create|createMany|update|updateMany|upsert|delete|deleteMany|"
    r"count|aggregate|groupBy)\s*\("
)


def detect_prisma(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    if "prisma" not in source.content.lower():
        return FrameworkExtraction()
    out = FrameworkExtraction()
    text = source.content
    module_qname = source.rel_path.replace("/", ".").replace("\\", ".")
    seen_models: dict[str, int] = {}

    for m in _USAGE_RE.finditer(text):
        model_name = m.group("model")[:1].upper() + m.group("model")[1:]
        op = m.group("op")
        line = text[: m.start()].count("\n") + 1
        if model_name not in seen_models:
            seen_models[model_name] = line
            qname = f"prisma::{model_name}"
            out.extra_symbols.append(ParsedSymbol(
                kind="model",
                name=model_name,
                qualified_name=qname,
                start_line=line,
                end_line=line,
                signature=f"Prisma model {model_name}",
                extras={"framework": "prisma"},
            ))
            # Legacy edge: Model -> module
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=module_qname,
                edge_type=EDGE_MODEL_USED_BY,
                confidence=0.7,
                extraction_source="extractor:prisma",
                line=line,
            ))
        # Caller -> Model (QUERIES) per-call.
        caller = find_enclosing_symbol(extract.symbols, line) or module_qname
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=caller,
            dst_name=model_name,
            edge_type=EDGE_QUERIES,
            confidence=0.85,
            extraction_source="extractor:prisma",
            line=line,
            metadata={
                "framework": "prisma",
                "operation": op,
                "model_qname": f"prisma::{model_name}",
            },
        ))

    if out.extra_symbols or any(e.edge_type == EDGE_QUERIES for e in out.extra_edges):
        out.detected_frameworks.append("prisma")
    return out
