"""Version constants for the schema, capsules, and parser backends.

Bumping these forces re-indexing of affected files even if their content hash
hasn't changed.
"""
from __future__ import annotations

from codegraphkb.core.parsers.registry import (
    PYTHON_AST_VERSION,
    REGEX_JS_VERSION,
    TREESITTER_JS_VERSION,
    ParserBackend,
)

SCHEMA_VERSION = 4          # bumped when sqlite tables change shape
CAPSULE_VERSION = 1         # bumped when capsule layout changes
RETRIEVAL_VERSION = 2       # bumped when ranking / RRF / modes change


def parser_signature(language: str, backend: ParserBackend) -> str:
    """Stable identifier of (language, backend, parser_version) for cache keys."""
    if language == "python":
        return f"python:ast:{PYTHON_AST_VERSION}"
    if language in ("javascript", "typescript"):
        if backend == ParserBackend.REGEX:
            return f"jsts:regex:{REGEX_JS_VERSION}"
        if backend == ParserBackend.TREESITTER:
            return f"jsts:tree-sitter:{TREESITTER_JS_VERSION}"
        return f"jsts:auto:rt{REGEX_JS_VERSION}-ts{TREESITTER_JS_VERSION}"
    return f"{language}:none:1"


def actual_parser_signature(language: str, actual_backend: str, version: str | int) -> str:
    """Signature describing the *actual* parser that ran (not the preference).

    ``actual_backend`` is the concrete backend name produced by the parser
    registry (e.g. ``"ast"``, ``"tree-sitter"``, ``"regex"``).
    """
    base_lang = language
    if language in ("javascript", "typescript"):
        base_lang = language
    return f"{base_lang}:{actual_backend}:{version}"
