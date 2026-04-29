"""Canonical production pipeline phase names."""
from __future__ import annotations

PHASES = (
    "scan",
    "structure",
    "syntax_parse",
    "symbol_extract",
    "semantic_extract",
    "import_resolution",
    "call_resolution",
    "type_merge",
    "framework_extract",
    "test_extract",
    "process_build",
    "community_build",
    "capsule_build",
    "search_index",
    "eval_snapshot",
)
