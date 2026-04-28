"""LLM gateway. Anthropic optional; falls back to an offline mode that returns
the assembled context pack so the tool is usable without an API key."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a senior software engineer using a structured code knowledge graph.

Rules:
1. Use only the provided context unless you clearly state that something is missing.
2. Prefer graph paths and capsules for architecture reasoning.
3. Use exact source snippets only when the question requires implementation details.
4. Cite files and line ranges (path:line-line) for every code-specific claim.
5. Do not invent files, functions, APIs, or database tables.
6. If context is insufficient, say exactly which file or symbol you would need.
7. For code changes, list the minimal files to edit first.
8. Be concise and implementation-oriented."""


@dataclass
class LLMResponse:
    answer: str
    model: str
    used_llm: bool


def answer_with_context(
    *,
    context_pack_text: str,
    question: str,
    model: str | None = None,
    api_key: str | None = None,
) -> LLMResponse:
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return LLMResponse(
            answer=_offline_answer(context_pack_text, question),
            model="offline",
            used_llm=False,
        )
    try:
        import anthropic  # type: ignore
    except ImportError:
        return LLMResponse(
            answer=_offline_answer(context_pack_text, question)
            + "\n\n[note] Install `codegraphkb[llm]` to enable Claude-backed answers.",
            model="offline",
            used_llm=False,
        )
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model or DEFAULT_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context_pack_text}],
    )
    text = "".join(
        getattr(block, "text", "") for block in message.content if getattr(block, "type", "") == "text"
    )
    return LLMResponse(answer=text.strip(), model=message.model, used_llm=True)


def _offline_answer(context_pack_text: str, question: str) -> str:
    return (
        "[CodeGraphKB offline mode — no ANTHROPIC_API_KEY set]\n\n"
        "Returning the assembled context pack instead of an LLM-generated answer. "
        "Set `ANTHROPIC_API_KEY` and install `codegraphkb[llm]` to get a synthesized response.\n\n"
        "---\n\n" + context_pack_text
    )
