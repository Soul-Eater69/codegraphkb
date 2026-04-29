"""Noise-control and diversity rules (Phase 2.5 PR 10).

Drops the irrelevant-context ratio by:
  - penalizing generic symbols that show up in nearly every retrieval
  - capping how many capsules can come from the same file
  - capping how many low-confidence graph hops are admitted per seed
  - allow/deny patterns per mode
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from codegraphkb.core.store import SymbolRow

# Symbol names that are widely shared boilerplate and rarely the actual answer.
# Penalized unless the user's query explicitly mentions them.
_GENERIC_NAMES = {
    "main", "run", "start", "stop", "init",
    "stats", "status", "health", "ping", "version", "info",
    "config", "settings", "setup", "configure",
    "parse_args", "cli", "command", "exec", "execute",
    "write_report", "render_report", "to_json", "to_dict",
    "from_dict", "as_dict", "loads", "dumps",
    "echo", "log", "print", "debug",
    "register", "load", "build_app", "create_app",
}

# Names that strongly suggest they are *not* implementation logic.
_TEST_INFRA = {
    "fixture", "conftest", "setup_method", "teardown_method", "setUp", "tearDown",
}


@dataclass(frozen=True)
class DiversityCaps:
    max_per_file: int = 4
    max_low_confidence_neighbors: int = 3
    max_pure_graph_hits: int = 6
    max_capsules: int = 14         # PR 10 — absolute cap on capsules, irrelevant-ratio control
    drop_test_files: bool = False  # when True, test capsules are skipped entirely


def default_caps_for_mode(mode: str) -> DiversityCaps:
    """Soft caps. The token budget already enforces a hard limit; these caps
    just stop one file or one seed from dominating the pack and bound noise."""
    if mode in {"impact", "impact_analysis"}:
        return DiversityCaps(max_per_file=8, max_low_confidence_neighbors=6,
                             max_pure_graph_hits=14, max_capsules=16, drop_test_files=False)
    if mode in {"explain", "onboarding", "architecture_explanation"}:
        return DiversityCaps(max_per_file=4, max_low_confidence_neighbors=3,
                             max_pure_graph_hits=6, max_capsules=8, drop_test_files=True)
    if mode in {"api_usage"}:
        return DiversityCaps(max_per_file=4, max_low_confidence_neighbors=3,
                             max_pure_graph_hits=6, max_capsules=10, drop_test_files=True)
    if mode in {"security", "security_review"}:
        # Don't drop tests for security: security tests *are* relevant context.
        return DiversityCaps(max_per_file=5, max_low_confidence_neighbors=3,
                             max_pure_graph_hits=8, max_capsules=12, drop_test_files=False)
    if mode in {"edit", "feature", "feature_implementation", "refactor"}:
        return DiversityCaps(max_per_file=5, max_low_confidence_neighbors=3,
                             max_pure_graph_hits=8, max_capsules=12, drop_test_files=False)
    if mode in {"debug"}:
        return DiversityCaps(max_per_file=5, max_low_confidence_neighbors=3,
                             max_pure_graph_hits=8, max_capsules=12, drop_test_files=False)
    if mode in {"test", "test_generation"}:
        return DiversityCaps(max_per_file=6, max_low_confidence_neighbors=3,
                             max_pure_graph_hits=8, max_capsules=14, drop_test_files=False)
    return DiversityCaps(max_per_file=5, max_low_confidence_neighbors=3,
                         max_pure_graph_hits=8, max_capsules=12, drop_test_files=False)


def is_generic_symbol(sym: SymbolRow, query_terms: set[str]) -> bool:
    """Generic symbols are penalized only when the query doesn't mention them."""
    name = sym.name.lower()
    if name in _GENERIC_NAMES and name not in query_terms:
        return True
    if name in _TEST_INFRA and "test" not in query_terms:
        return True
    return False


def query_terms_from(question: str) -> set[str]:
    return {tok.lower() for tok in re.findall(r"[A-Za-z][A-Za-z0-9_]+", question)}


def generic_penalty(sym: SymbolRow, query_terms: set[str]) -> float:
    """Score reduction (subtracted from the final score) for generic symbols."""
    if is_generic_symbol(sym, query_terms):
        return 0.20
    return 0.0
