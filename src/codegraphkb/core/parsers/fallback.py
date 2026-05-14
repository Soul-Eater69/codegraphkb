"""Fallback parser for code files with no extracted symbols."""
from __future__ import annotations

from codegraphkb.core.parsers.base import ExtractResult, ParsedSymbol
from codegraphkb.core.scanner import SourceFile

FALLBACK_PARSER_VERSION = 1


def file_summary_fallback(source: SourceFile) -> ExtractResult:
    """Return a file-level summary symbol for otherwise-empty extractions."""
    total_lines = max(1, source.content.count("\n") + (0 if source.content.endswith("\n") else 1))
    rel_path = source.rel_path.replace("\\", "/")
    symbol = ParsedSymbol(
        kind="file_summary",
        name=rel_path,
        qualified_name=f"file::{rel_path}",
        start_line=1,
        end_line=total_lines,
        signature=f"file {rel_path}",
        docstring="File-level summary fallback. No functions/classes detected; contains module-level or unsupported code.",
        extras={
            "language": source.language,
            "fallback": True,
            "summary_type": "file_level",
        },
    )
    return ExtractResult(symbols=[symbol], edges=[])
