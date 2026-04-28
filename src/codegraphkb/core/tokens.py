"""Cheap token estimator. Avoids a dependency on tiktoken/anthropic for a 4-char heuristic."""
from __future__ import annotations

from codegraphkb.config import CHARS_PER_TOKEN


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    if estimate_tokens(text) <= max_tokens:
        return text
    return text[: max_tokens * CHARS_PER_TOKEN].rstrip() + "\n... [truncated]"
