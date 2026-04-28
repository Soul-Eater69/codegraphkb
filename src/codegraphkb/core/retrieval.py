"""Retrieval orchestrator + token-budget governor.

Pipeline (per architecture doc §9):
  1. classify intent
  2. seed nodes (BM25 + filename / qualified-name match)
  3. graph expansion by intent
  4. rank
  5. fit into token budget -> ContextPack
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from codegraphkb.config import DEFAULT_TOKEN_BUDGET
from codegraphkb.core.search import SearchHit, search_symbols
from codegraphkb.core.store import EdgeRow, GraphStore, SymbolRow
from codegraphkb.core.tokens import estimate_tokens, truncate_to_tokens


class Intent(str, Enum):
    ARCHITECTURE = "architecture_explanation"
    BUG_FIX = "bug_fix"
    FEATURE = "feature_implementation"
    REFACTOR = "refactor"
    IMPACT = "impact_analysis"
    TEST = "test_generation"
    SECURITY = "security_review"
    API_USAGE = "api_usage"
    ONBOARDING = "onboarding"
    EXPLAIN = "explain"


_INTENT_PATTERNS: list[tuple[Intent, list[str]]] = [
    (Intent.IMPACT, ["impact", "what breaks", "if i change", "if i modify", "affected", "blast radius"]),
    (Intent.BUG_FIX, ["bug", "fix", "broken", "error", "crash", "fails"]),
    (Intent.FEATURE, ["add ", "implement", "build", "create new", "feature"]),
    (Intent.REFACTOR, ["refactor", "rename", "clean up", "extract", "simplify"]),
    (Intent.TEST, ["test", "spec", "coverage"]),
    (Intent.SECURITY, ["security", "auth", "vulnerab", "leak", "secret", "permission"]),
    (Intent.API_USAGE, ["how do i call", "usage of", "api for"]),
    (Intent.ONBOARDING, ["onboard", "overview", "what is this", "tour", "where do i start"]),
    (Intent.ARCHITECTURE, ["architecture", "how does", "how it works", "explain the", "flow"]),
]


@dataclass
class ContextItem:
    kind: str  # "capsule", "snippet", "graph_path", "summary"
    title: str
    body: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    score: float = 0.0
    tokens: int = 0


@dataclass
class ContextPack:
    question: str
    intent: Intent
    items: list[ContextItem]
    estimated_tokens: int
    repo_map: str = ""
    graph_paths: list[str] = field(default_factory=list)
    files_likely_to_edit: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        parts = [
            "# CodeGraphKB Context Pack",
            "",
            f"## User Task\n{self.question}",
            "",
            f"## Retrieval Intent\n{self.intent.value}",
        ]
        if self.repo_map:
            parts.extend(["", "## Repo Map", self.repo_map])
        if self.graph_paths:
            parts.extend(["", "## Relevant Graph Paths"])
            parts.extend(f"- {p}" for p in self.graph_paths)
        if self.files_likely_to_edit:
            parts.extend(["", "## Files Likely To Edit"])
            parts.extend(f"- `{p}`" for p in self.files_likely_to_edit)
        for item in self.items:
            header = f"## {item.title}"
            if item.file_path:
                loc = f"`{item.file_path}"
                if item.start_line is not None and item.end_line is not None:
                    loc += f":{item.start_line}-{item.end_line}"
                loc += "`"
                header += f" — {loc}"
            parts.extend(["", header, item.body])
        return "\n".join(parts)


def classify_intent(question: str) -> Intent:
    q = question.lower()
    for intent, needles in _INTENT_PATTERNS:
        if any(n in q for n in needles):
            return intent
    return Intent.EXPLAIN


def retrieve_context(
    store: GraphStore,
    question: str,
    *,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    intent: Intent | None = None,
    pinned_files: list[str] | None = None,
) -> ContextPack:
    intent = intent or classify_intent(question)
    pinned = pinned_files or []

    seeds = _seed_nodes(store, question, pinned)
    expanded, paths = _expand_graph(store, seeds, intent)

    repo_map = _build_repo_map(store)
    repo_map_tokens = estimate_tokens(repo_map)

    items: list[ContextItem] = []
    used_qnames: set[str] = set()
    files_to_edit: list[str] = []

    # Tier allocation (rough, doc §19 token tiers)
    capsule_budget = max(1000, int(token_budget * 0.45))
    snippet_budget = max(800, int(token_budget * 0.35))
    map_budget = max(400, int(token_budget * 0.10))
    if repo_map_tokens > map_budget:
        repo_map = truncate_to_tokens(repo_map, map_budget)
        repo_map_tokens = estimate_tokens(repo_map)

    spent_tokens = repo_map_tokens
    capsule_spent = 0
    snippet_spent = 0
    needs_source = intent in {Intent.BUG_FIX, Intent.FEATURE, Intent.REFACTOR, Intent.TEST}

    for sym, score in expanded:
        if sym.qualified_name in used_qnames:
            continue
        used_qnames.add(sym.qualified_name)
        capsule = sym.capsule or _fallback_capsule(sym)
        ctok = estimate_tokens(capsule)
        if capsule_spent + ctok <= capsule_budget:
            items.append(ContextItem(
                kind="capsule",
                title=f"Capsule: {sym.qualified_name}",
                body=capsule,
                file_path=sym.file_path,
                start_line=sym.start_line,
                end_line=sym.end_line,
                score=score,
                tokens=ctok,
            ))
            capsule_spent += ctok
            spent_tokens += ctok
            if needs_source and sym.file_path not in files_to_edit:
                files_to_edit.append(sym.file_path)

    # Exact snippets only for top symbols if intent calls for editing.
    if needs_source:
        for sym, score in expanded[: 6]:
            snippet = _extract_snippet(store, sym)
            if not snippet:
                continue
            stok = estimate_tokens(snippet)
            if snippet_spent + stok > snippet_budget:
                snippet = truncate_to_tokens(snippet, max(200, snippet_budget - snippet_spent))
                stok = estimate_tokens(snippet)
                if stok <= 0:
                    continue
            items.append(ContextItem(
                kind="snippet",
                title=f"Source: {sym.qualified_name}",
                body=f"```\n{snippet}\n```",
                file_path=sym.file_path,
                start_line=sym.start_line,
                end_line=sym.end_line,
                score=score,
                tokens=stok,
            ))
            snippet_spent += stok
            spent_tokens += stok
            if snippet_spent >= snippet_budget:
                break

    return ContextPack(
        question=question,
        intent=intent,
        items=items,
        estimated_tokens=spent_tokens,
        repo_map=repo_map,
        graph_paths=paths[:12],
        files_likely_to_edit=files_to_edit[:8],
    )


# ---------- helpers ----------

def _seed_nodes(store: GraphStore, question: str, pinned: list[str]) -> list[tuple[SymbolRow, float]]:
    seeds: dict[str, tuple[SymbolRow, float]] = {}

    # Pinned files first
    for path in pinned:
        for sym in store.symbols_in_file(path):
            seeds.setdefault(sym.qualified_name, (sym, 5.0))

    # Path mentions
    for token in re.findall(r"[\w./\-]+\.[a-zA-Z]{1,5}", question):
        for sym in store.symbols_in_file(token.strip()):
            seeds.setdefault(sym.qualified_name, (sym, 4.0))

    # Identifier mentions
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", question):
        for sym in store.find_symbols_by_name(token, limit=3):
            cur = seeds.get(sym.qualified_name)
            if cur is None or cur[1] < 3.0:
                seeds[sym.qualified_name] = (sym, 3.0)

    # BM25 hits
    for hit in search_symbols(store, question, limit=20):
        cur = seeds.get(hit.symbol.qualified_name)
        score = max(cur[1] if cur else 0.0, hit.score)
        seeds[hit.symbol.qualified_name] = (hit.symbol, score)

    ranked = sorted(seeds.values(), key=lambda kv: kv[1], reverse=True)
    return ranked[:25]


def _expand_graph(
    store: GraphStore,
    seeds: list[tuple[SymbolRow, float]],
    intent: Intent,
) -> tuple[list[tuple[SymbolRow, float]], list[str]]:
    forward_edges, reverse_edges = _intent_edge_filters(intent)
    visited: dict[str, tuple[SymbolRow, float]] = {}
    paths: list[str] = []

    for sym, score in seeds:
        visited[sym.qualified_name] = (sym, score)

    frontier = list(seeds)
    depth = 2 if intent in {Intent.IMPACT, Intent.ARCHITECTURE, Intent.FEATURE} else 1
    decay = 0.6
    for _ in range(depth):
        next_frontier: list[tuple[SymbolRow, float]] = []
        for sym, score in frontier:
            # forward
            for edge in store.outgoing(sym.qualified_name, forward_edges):
                target = _resolve_edge_symbol(store, edge)
                if target is None:
                    continue
                new_score = score * decay * edge.confidence
                cur = visited.get(target.qualified_name)
                if cur is None or cur[1] < new_score:
                    visited[target.qualified_name] = (target, new_score)
                    next_frontier.append((target, new_score))
                    paths.append(f"{sym.qualified_name} --{edge.edge_type}--> {target.qualified_name}")
            # reverse (callers, tests, routes)
            for edge in store.incoming(sym.qualified_name, reverse_edges):
                src = store.find_symbol(edge.src_qname)
                if src is None:
                    continue
                new_score = score * decay * edge.confidence
                cur = visited.get(src.qualified_name)
                if cur is None or cur[1] < new_score:
                    visited[src.qualified_name] = (src, new_score)
                    next_frontier.append((src, new_score))
                    paths.append(f"{src.qualified_name} --{edge.edge_type}--> {sym.qualified_name}")
        frontier = next_frontier
        if not frontier:
            break

    ranked = sorted(visited.values(), key=lambda kv: kv[1], reverse=True)
    return ranked, paths


def _intent_edge_filters(intent: Intent) -> tuple[list[str], list[str]]:
    if intent == Intent.IMPACT:
        return ["CALLS", "ROUTES_TO"], ["CALLS", "TESTS", "ROUTES_TO", "EXTENDS"]
    if intent == Intent.FEATURE:
        return ["CALLS", "IMPORTS", "ROUTES_TO"], ["CALLS", "ROUTES_TO", "TESTS"]
    if intent == Intent.BUG_FIX:
        return ["CALLS", "IMPORTS"], ["CALLS", "TESTS"]
    if intent == Intent.TEST:
        return ["CALLS"], ["TESTS"]
    if intent == Intent.SECURITY:
        return ["CALLS", "IMPORTS", "ROUTES_TO"], ["ROUTES_TO", "CALLS"]
    return ["CALLS", "IMPORTS", "EXTENDS", "ROUTES_TO"], ["CALLS", "ROUTES_TO", "TESTS"]


def _resolve_edge_symbol(store: GraphStore, edge: EdgeRow) -> SymbolRow | None:
    if edge.dst_qname:
        sym = store.find_symbol(edge.dst_qname)
        if sym:
            return sym
    by_name = store.find_symbols_by_name(edge.dst_name, limit=1)
    return by_name[0] if by_name else None


def _fallback_capsule(sym: SymbolRow) -> str:
    return (
        f"### {sym.kind.title()}: {sym.qualified_name}\n"
        f"- File: `{sym.file_path}:{sym.start_line}-{sym.end_line}`\n"
        + (f"- Signature: `{sym.signature}`\n" if sym.signature else "")
    )


def _extract_snippet(store: GraphStore, sym: SymbolRow, max_lines: int = 60) -> str:
    file = store.get_file(sym.file_path)
    if not file:
        return ""
    lines = file.content.splitlines()
    start = max(0, sym.start_line - 1)
    end = min(len(lines), max(sym.end_line, start + 1))
    if end - start > max_lines:
        end = start + max_lines
    snippet_lines = lines[start:end]
    width = len(str(end))
    return "\n".join(f"{str(start + i + 1).rjust(width)}  {ln}" for i, ln in enumerate(snippet_lines))


def _build_repo_map(store: GraphStore, max_dirs: int = 12) -> str:
    counts: dict[str, int] = {}
    langs: dict[str, set[str]] = {}
    for path in store.known_files():
        top = path.split("/", 1)[0] if "/" in path else "(root)"
        counts[top] = counts.get(top, 0) + 1
        # Best-effort language fetch is omitted to avoid extra queries
    if not counts:
        return ""
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:max_dirs]
    lines = [f"- `{name}/` — {n} files" for name, n in ranked]
    return "\n".join(lines)
