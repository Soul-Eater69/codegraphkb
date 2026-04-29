"""Prisma model usage: `prisma.<model>.<op>(...)` and `Prisma.<Model>` references.

We don't parse `schema.prisma` here — only TS/JS usage of generated client types.
"""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_MODEL_USED_BY, FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_USAGE_RE = re.compile(r"\b(?:prisma|db|client)\.([a-z][\w]*)\.(findMany|findUnique|"
                       r"findFirst|create|createMany|update|updateMany|upsert|"
                       r"delete|deleteMany|count|aggregate|groupBy)\s*\(")


def detect_prisma(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    if "prisma" not in source.content.lower():
        return FrameworkExtraction()
    out = FrameworkExtraction()
    seen: set[str] = set()
    for m in _USAGE_RE.finditer(source.content):
        model_name = m.group(1)[:1].upper() + m.group(1)[1:]  # `users` -> `Users`
        if model_name in seen:
            continue
        seen.add(model_name)
        line = source.content[: m.start()].count("\n") + 1
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
        # Edge from the using file (module) to the model.
        module_qname = source.rel_path.replace("/", ".").replace("\\", ".")
        out.extra_edges.append(ParsedEdge(
            src_qualified_name=qname,
            dst_name=module_qname,
            edge_type=EDGE_MODEL_USED_BY,
            confidence=0.7,
            extraction_source="extractor:prisma",
            line=line,
        ))
    if out.extra_symbols:
        out.detected_frameworks.append("prisma")
    return out
