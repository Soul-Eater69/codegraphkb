"""Jest / Vitest test-block detector. Captures the human-readable label for each
`describe()` / `it()` / `test()` block and links calls inside the block to the
symbols-under-test via TESTS_SYMBOL edges."""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_TESTS_SYMBOL, FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_BLOCK_RE = re.compile(
    r"\b(describe|it|test|context|suite)\s*\(\s*['\"`]([^'\"`]+)['\"`]"
)
_CALL_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")


def detect_jest_vitest(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    rel = source.rel_path.lower()
    if not (".test." in rel or ".spec." in rel or "/tests/" in "/" + rel + "/"
            or "/test/" in "/" + rel + "/" or "/__tests__/" in "/" + rel + "/"):
        return FrameworkExtraction()
    text = source.content
    if not any(needle in text for needle in ("describe(", "it(", "test(", "expect(")):
        return FrameworkExtraction()

    out = FrameworkExtraction()
    block_matches = list(_BLOCK_RE.finditer(text))
    for i, m in enumerate(block_matches):
        kind_word = m.group(1)
        label = m.group(2)
        line = text[: m.start()].count("\n") + 1
        # Slice from this block-start to the next (rough but cheap).
        end_pos = block_matches[i + 1].start() if i + 1 < len(block_matches) else len(text)
        block_text = text[m.end(): end_pos]
        qname = f"jest::{source.rel_path}::{label}"[:200]
        out.extra_symbols.append(ParsedSymbol(
            kind="test_block",
            name=label,
            qualified_name=qname,
            start_line=line,
            end_line=line + block_text.count("\n"),
            signature=f"{kind_word}('{label}')",
            extras={"framework": "jest_vitest", "block_kind": kind_word},
        ))
        # Collect calls inside the block; emit TESTS_SYMBOL edges.
        seen: set[str] = set()
        for cm in _CALL_RE.finditer(block_text):
            name = cm.group(1)
            if name in seen or name in _NOISE:
                continue
            seen.add(name)
            out.extra_edges.append(ParsedEdge(
                src_qualified_name=qname,
                dst_name=name,
                edge_type=EDGE_TESTS_SYMBOL,
                confidence=0.55,
                extraction_source="extractor:jest_vitest",
                line=line,
            ))
    if out.extra_symbols:
        out.detected_frameworks.append("jest_vitest")
    return out


_NOISE = {
    "describe", "it", "test", "context", "suite", "expect", "beforeAll",
    "afterAll", "beforeEach", "afterEach", "vi", "jest", "console", "Promise",
    "Array", "Object", "Math", "JSON", "require", "Symbol",
    "if", "for", "while", "return", "function",
}
