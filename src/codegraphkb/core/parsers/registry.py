"""Parser registry — chooses a parser backend per language with graceful fallback.

  ParserBackend.AUTO          tree-sitter if installed, else regex/ast
  ParserBackend.TREESITTER    force tree-sitter, error if unavailable
  ParserBackend.REGEX         force regex (or stdlib ast for Python)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from codegraphkb.core.parsers.base import ExtractResult
from codegraphkb.core.parsers.csharp_parser import (
    CSHARP_PARSER_VERSION,
    parse_csharp as _regex_csharp_parse,
)
from codegraphkb.core.parsers.go_parser import (
    GO_PARSER_VERSION,
    parse_go as _regex_go_parse,
)
from codegraphkb.core.parsers.java_parser import (
    JAVA_PARSER_VERSION,
    parse_java as _regex_java_parse,
)
from codegraphkb.core.parsers.js_parser import parse_javascript as _regex_js_parse
from codegraphkb.core.parsers.kotlin_parser import (
    KOTLIN_PARSER_VERSION,
    parse_kotlin as _regex_kotlin_parse,
)
from codegraphkb.core.parsers.python_parser import parse_python as _ast_python_parse
from codegraphkb.core.parsers.rust_parser import (
    RUST_PARSER_VERSION,
    parse_rust as _regex_rust_parse,
)
from codegraphkb.core.scanner import SourceFile


class ParserBackend(str, Enum):
    AUTO = "auto"
    TREESITTER = "tree-sitter"
    REGEX = "regex"


@dataclass(frozen=True)
class ParserChoice:
    backend: str        # the actual backend that ran (e.g. "tree-sitter", "ast", "regex")
    version: int        # bumps whenever the parser semantics change for cache invalidation


# Bumped in Phase 2.5 (PR 9) — alias-expansion changed BM25 doc construction.
# Bumped in Phase 2.6 (PR 13) — Python parser now extracts module-level constants.
# Bumped in Phase 2.6 (PR 14) — framework-aware extractors enrich the symbol table.
PYTHON_AST_VERSION = 4
REGEX_JS_VERSION = 3
TREESITTER_JS_VERSION = 3


def parse(
    source: SourceFile,
    backend: ParserBackend = ParserBackend.AUTO,
) -> tuple[ExtractResult, ParserChoice]:
    if source.language == "python":
        return _ast_python_parse(source), ParserChoice("ast", PYTHON_AST_VERSION)

    if source.language == "java":
        return _regex_java_parse(source), ParserChoice("regex", JAVA_PARSER_VERSION)

    if source.language == "go":
        return _regex_go_parse(source), ParserChoice("regex", GO_PARSER_VERSION)

    if source.language == "csharp":
        return _regex_csharp_parse(source), ParserChoice("regex", CSHARP_PARSER_VERSION)

    if source.language == "rust":
        return _regex_rust_parse(source), ParserChoice("regex", RUST_PARSER_VERSION)

    if source.language == "kotlin":
        return _regex_kotlin_parse(source), ParserChoice("regex", KOTLIN_PARSER_VERSION)

    if source.language in ("javascript", "typescript"):
        if backend == ParserBackend.REGEX:
            return _regex_js_parse(source), ParserChoice("regex", REGEX_JS_VERSION)
        ts_parser = _try_load_treesitter()
        if ts_parser is not None:
            try:
                return ts_parser(source), ParserChoice("tree-sitter", TREESITTER_JS_VERSION)
            except Exception:
                if backend == ParserBackend.TREESITTER:
                    raise
                return _regex_js_parse(source), ParserChoice("regex", REGEX_JS_VERSION)
        if backend == ParserBackend.TREESITTER:
            raise RuntimeError(
                "tree-sitter backend requested but `codegraphkb[parser]` is not installed."
            )
        return _regex_js_parse(source), ParserChoice("regex", REGEX_JS_VERSION)

    return ExtractResult(symbols=[], edges=[]), ParserChoice("none", 1)


def is_treesitter_available() -> bool:
    return _try_load_treesitter() is not None


def _try_load_treesitter() -> Callable[[SourceFile], ExtractResult] | None:
    """Lazy-load and cache the tree-sitter JS/TS parser callable."""
    global _CACHED_TS_PARSER, _TS_LOAD_TRIED
    if _TS_LOAD_TRIED:
        return _CACHED_TS_PARSER
    _TS_LOAD_TRIED = True
    try:
        from codegraphkb.core.parsers.treesitter_js_parser import parse_treesitter_js
    except Exception:
        _CACHED_TS_PARSER = None
        return None
    _CACHED_TS_PARSER = parse_treesitter_js
    return _CACHED_TS_PARSER


_CACHED_TS_PARSER: Callable[[SourceFile], ExtractResult] | None = None
_TS_LOAD_TRIED: bool = False
