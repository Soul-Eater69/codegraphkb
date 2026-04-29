"""Language parsers. Use `registry.parse(source, backend)` for the public path."""
from __future__ import annotations

from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.parsers.registry import ParserBackend, ParserChoice, parse, is_treesitter_available
from codegraphkb.core.scanner import SourceFile


def parse_file(source: SourceFile, backend: ParserBackend = ParserBackend.AUTO) -> ExtractResult:
    """Backwards-compatible parse helper used by older callers."""
    result, _ = parse(source, backend=backend)
    return result


__all__ = [
    "parse",
    "parse_file",
    "ParserBackend",
    "ParserChoice",
    "ParsedSymbol",
    "ParsedEdge",
    "ExtractResult",
    "is_treesitter_available",
]
