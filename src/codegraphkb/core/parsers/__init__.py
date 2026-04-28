"""Language parsers. Each returns a list of Symbol and Edge records."""
from __future__ import annotations

from codegraphkb.core.parsers.base import ExtractResult, ParsedEdge, ParsedSymbol
from codegraphkb.core.parsers.js_parser import parse_javascript
from codegraphkb.core.parsers.python_parser import parse_python
from codegraphkb.core.scanner import SourceFile


def parse_file(source: SourceFile) -> ExtractResult:
    if source.language == "python":
        return parse_python(source)
    if source.language in ("javascript", "typescript"):
        return parse_javascript(source)
    return ExtractResult(symbols=[], edges=[])


__all__ = ["parse_file", "ParsedSymbol", "ParsedEdge", "ExtractResult"]
