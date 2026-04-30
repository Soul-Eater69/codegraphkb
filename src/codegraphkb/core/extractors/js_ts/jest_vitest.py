"""Jest / Vitest detector.

For each ``describe`` / ``it`` / ``test`` block we emit a ``test_block`` symbol
with line bounds based on brace-matching, and emit ``TESTS`` edges from the
block to every distinct identifier called inside it (filtered against framework
boilerplate). The legacy ``TESTS_SYMBOL`` edges are kept for back-compat.
"""
from __future__ import annotations

import re

from codegraphkb.core.extractors.base import (
    EDGE_TESTS,
    EDGE_TESTS_SYMBOL,
    FrameworkExtraction,
)
from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

_BLOCK_RE = re.compile(
    r"\b(describe|it|test|context|suite)(?:\.(?:only|skip|each))?\s*"
    r"\(\s*['\"`]([^'\"`]+)['\"`]"
)
_CALL_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")


def detect_jest_vitest(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    rel = source.rel_path.lower().replace("\\", "/")
    in_test_path = (
        ".test." in rel or ".spec." in rel
        or rel.startswith("tests/") or "/tests/" in "/" + rel
        or rel.startswith("test/") or "/test/" in "/" + rel
        or "/__tests__/" in "/" + rel
    )
    if not in_test_path:
        return FrameworkExtraction()
    text = source.content
    if not any(needle in text for needle in ("describe(", "it(", "test(", "expect(",
                                              "describe.", "test.", "it.")):
        return FrameworkExtraction()

    out = FrameworkExtraction()
    for m in _BLOCK_RE.finditer(text):
        kind_word = m.group(1)
        label = m.group(2)
        block_start = text[: m.start()].count("\n") + 1
        body_start, body_end = _block_body_span(text, m.end())
        if body_start is None:
            continue
        body_text = text[body_start:body_end]
        end_line = block_start + body_text.count("\n")
        qname = f"jest::{source.rel_path}::{label}"[:200]
        out.extra_symbols.append(ParsedSymbol(
            kind="test_block",
            name=label,
            qualified_name=qname,
            start_line=block_start,
            end_line=end_line,
            signature=f"{kind_word}('{label}')",
            extras={"framework": "jest_vitest", "block_kind": kind_word},
        ))
        seen: set[str] = set()
        for cm in _CALL_RE.finditer(body_text):
            name = cm.group(1)
            if name in seen or name in _NOISE:
                continue
            seen.add(name)
            for edge_type, conf in (
                (EDGE_TESTS, 0.6),
                (EDGE_TESTS_SYMBOL, 0.55),
            ):
                out.extra_edges.append(ParsedEdge(
                    src_qualified_name=qname,
                    dst_name=name,
                    edge_type=edge_type,
                    confidence=conf,
                    extraction_source="extractor:jest_vitest",
                    line=block_start,
                    metadata={
                        "block_kind": kind_word,
                        "block_label": label,
                    },
                ))
    if out.extra_symbols:
        out.detected_frameworks.append("jest_vitest")
    return out


def _block_body_span(text: str, start_pos: int) -> tuple[int | None, int | None]:
    """Return ``(body_start, body_end)`` for a block whose ``(`` argument list
    began before ``start_pos``.

    We're already *inside* the outer ``(`` of the ``describe(...)`` /
    ``it(...)`` call (the regex consumed the opening paren plus the label),
    so paren depth starts at 1. We walk until the matching close-paren brings
    depth back to 0; the slice ``text[start_pos:close)`` is the block body —
    arguments, arrow function, braces and all.
    """
    depth = 1
    i = start_pos
    while i < len(text):
        ch = text[i]
        if ch in ("'", '"', "`"):
            i = _skip_string(text, i, ch)
            continue
        if ch == "/" and i + 1 < len(text) and text[i + 1] in ("/", "*"):
            i = _skip_comment(text, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return start_pos, i
        i += 1
    return None, None


def _skip_string(text: str, i: int, quote: str) -> int:
    j = i + 1
    while j < len(text):
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == quote:
            return j + 1
        j += 1
    return j


def _skip_comment(text: str, i: int) -> int:
    if text[i + 1] == "/":
        j = text.find("\n", i + 2)
        return j + 1 if j != -1 else len(text)
    j = text.find("*/", i + 2)
    return j + 2 if j != -1 else len(text)


_NOISE = {
    "describe", "it", "test", "context", "suite", "expect", "beforeAll",
    "afterAll", "beforeEach", "afterEach", "vi", "jest", "console", "Promise",
    "Array", "Object", "Math", "JSON", "require", "Symbol",
    "if", "for", "while", "return", "function", "async", "await", "throw",
    "try", "catch", "finally", "switch", "case", "default", "break", "continue",
    "new", "typeof", "instanceof", "in", "of", "void",
    "Number", "String", "Boolean", "Date", "Error", "RegExp", "Map", "Set",
}
