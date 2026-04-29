"""Semantic adapter runner with fallback policy."""
from __future__ import annotations

from dataclasses import dataclass, field

from codegraphkb.core.semantic.protocol import SemanticAdapter, SemanticResult


@dataclass
class SemanticRun:
    adapter_id: str
    language: str
    available: bool
    result: SemanticResult | None = None
    warnings: list[str] = field(default_factory=list)


def run_semantic_adapter(adapter: SemanticAdapter, repo_path: str,
                         files: list[str]) -> SemanticRun:
    if not adapter.available(repo_path):
        return SemanticRun(
            adapter_id=adapter.id,
            language=adapter.language,
            available=False,
            warnings=[f"Semantic adapter `{adapter.id}` unavailable; using syntax fallback."],
        )
    try:
        result = adapter.analyze_repo(repo_path, files)
    except Exception as exc:
        return SemanticRun(
            adapter_id=adapter.id,
            language=adapter.language,
            available=False,
            warnings=[f"Semantic adapter `{adapter.id}` failed: {exc}"],
        )
    return SemanticRun(
        adapter_id=adapter.id,
        language=adapter.language,
        available=True,
        result=result,
    )
