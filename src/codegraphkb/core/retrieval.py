"""Hybrid retrieval orchestrator + token-budget governor (Phase 2).

Pipeline:
  1. classify intent / mode
  2. seed generation:
       - BM25 hits
       - vector hits (when an embedder is supplied)
       - identifier mentions
       - path mentions
       - pinned files
  3. seed fusion via Reciprocal Rank Fusion
  4. mode-aware graph expansion (CALLS, ROUTES_TO, TESTS, IMPORTS, EXTENDS)
  5. final score = weighted blend of RRF + graph proximity + intent-match
  6. token-budget governor with mode-specific tier allocation
  7. each emitted ContextItem carries audit metadata (PR6):
       - retrieval_sources: which signals produced it
       - score components (bm25 / vector / graph / final)
       - graph_path: how we reached it from a seed
       - reason: human-readable explanation
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from codegraphkb.config import DEFAULT_TOKEN_BUDGET
from codegraphkb.core.noise import (
    DiversityCaps, default_caps_for_mode, generic_penalty, is_generic_symbol,
    query_terms_from,
)
from codegraphkb.core.search import SearchHit, search_symbols
from codegraphkb.core.store import EdgeRow, GraphStore, SymbolRow
from codegraphkb.core.tokens import estimate_tokens, truncate_to_tokens

RRF_K = 60


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


class Mode(str, Enum):
    EXPLAIN = "explain"
    EDIT = "edit"
    DEBUG = "debug"
    REFACTOR = "refactor"
    TEST = "test"
    IMPACT = "impact"
    SECURITY = "security"
    ONBOARDING = "onboarding"
    FEATURE = "feature"


_INTENT_TO_MODE: dict[Intent, Mode] = {
    Intent.ARCHITECTURE: Mode.EXPLAIN,
    Intent.BUG_FIX: Mode.DEBUG,
    Intent.FEATURE: Mode.FEATURE,
    Intent.REFACTOR: Mode.REFACTOR,
    Intent.IMPACT: Mode.IMPACT,
    Intent.TEST: Mode.TEST,
    Intent.SECURITY: Mode.SECURITY,
    Intent.API_USAGE: Mode.EXPLAIN,
    Intent.ONBOARDING: Mode.ONBOARDING,
    Intent.EXPLAIN: Mode.EXPLAIN,
}

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


def classify_intent(question: str) -> Intent:
    q = question.lower()
    for intent, needles in _INTENT_PATTERNS:
        if any(n in q for n in needles):
            return intent
    return Intent.EXPLAIN


def coerce_mode(value: Mode | str | None, intent: Intent) -> Mode:
    if isinstance(value, Mode):
        return value
    if isinstance(value, str):
        try:
            return Mode(value)
        except ValueError:
            pass
    return _INTENT_TO_MODE[intent]


# ---------- output dataclasses ----------

@dataclass
class ScoreBreakdown:
    bm25: float = 0.0
    vector: float = 0.0
    graph: float = 0.0
    intent_match: float = 0.0
    centrality: float = 0.0
    # Phase 2.5 (PR 11) — new structured channels.
    identifier_overlap: float = 0.0
    mode_fit: float = 0.0
    test_proximity: float = 0.0
    generic_penalty: float = 0.0
    final: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "bm25": round(self.bm25, 4),
            "vector": round(self.vector, 4),
            "graph": round(self.graph, 4),
            "intent_match": round(self.intent_match, 4),
            "centrality": round(self.centrality, 4),
            "identifier_overlap": round(self.identifier_overlap, 4),
            "mode_fit": round(self.mode_fit, 4),
            "test_proximity": round(self.test_proximity, 4),
            "generic_penalty": round(self.generic_penalty, 4),
            "final": round(self.final, 4),
        }


@dataclass
class ContextItem:
    kind: str  # capsule, snippet, summary
    title: str
    body: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    score: float = 0.0
    tokens: int = 0
    # Audit metadata (PR6)
    retrieval_sources: list[str] = field(default_factory=list)
    score_breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    graph_path: list[str] = field(default_factory=list)
    confidence: float = 0.7
    reason: str = ""


@dataclass
class RankedCandidate:
    """Lightweight summary of every candidate considered, included or not.

    Used by the eval `--explain` mode to show *why* an oracle symbol was missed
    (rank N but excluded by budget vs. never seen).
    """
    qualified_name: str
    file_path: str
    kind: str
    rank: int  # 1-indexed position in the final ranking
    included: bool
    score_breakdown: ScoreBreakdown
    retrieval_sources: list[str]
    distance: int  # 0 = seed, 1 = 1-hop, ...
    graph_path: list[str]


@dataclass
class ContextPack:
    question: str
    intent: Intent
    mode: Mode
    items: list[ContextItem]
    estimated_tokens: int
    repo_map: str = ""
    graph_paths: list[str] = field(default_factory=list)
    files_likely_to_edit: list[str] = field(default_factory=list)
    related_tests: list[str] = field(default_factory=list)
    retrieval_mode: str = "default"
    audit: dict[str, Any] = field(default_factory=dict)
    ranked_candidates: list[RankedCandidate] = field(default_factory=list)

    def to_prompt(self) -> str:
        parts = [
            "# CodeGraphKB Context Pack",
            "",
            f"## User Task\n{self.question}",
            "",
            f"## Retrieval Intent\n{self.intent.value}",
            f"## Mode\n{self.mode.value}",
        ]
        if self.repo_map:
            parts.extend(["", "## Repo Map", self.repo_map])
        if self.graph_paths:
            parts.extend(["", "## Relevant Graph Paths"])
            parts.extend(f"- {p}" for p in self.graph_paths)
        if self.files_likely_to_edit:
            parts.extend(["", "## Files Likely To Edit"])
            parts.extend(f"- `{p}`" for p in self.files_likely_to_edit)
        if self.related_tests:
            parts.extend(["", "## Related Tests"])
            parts.extend(f"- `{p}`" for p in self.related_tests)
        for item in self.items:
            header = f"## {item.title}"
            if item.file_path:
                loc = f"`{item.file_path}"
                if item.start_line is not None and item.end_line is not None:
                    loc += f":{item.start_line}-{item.end_line}"
                loc += "`"
                header += f" — {loc}"
            parts.extend(["", header, item.body])
            if item.reason:
                parts.append(f"_{item.reason}_")
        return "\n".join(parts)


# ---------- public entry ----------

def retrieve_context(
    store: GraphStore,
    question: str,
    *,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    intent: Intent | None = None,
    mode: Mode | str | None = None,
    pinned_files: list[str] | None = None,
    embedder=None,
    retrieval_mode: str = "default",
) -> ContextPack:
    intent = intent or classify_intent(question)
    resolved_mode = coerce_mode(mode, intent)
    pinned = pinned_files or []

    # ---- 1. seed generation ----
    bm25_hits = search_symbols(store, question, limit=25)
    vector_hits: list = []
    if embedder is not None:
        from codegraphkb.core.embeddings import vector_search
        try:
            vector_hits = vector_search(store, embedder, question, limit=25)
        except Exception:
            vector_hits = []
    identifier_hits = _identifier_hits(store, question)
    path_hits = _path_hits(store, question)
    pinned_hits = _pinned_hits(store, pinned)

    # ---- 2. fuse seeds via RRF ----
    seeds = _fuse_seeds(
        store,
        bm25=bm25_hits,
        vector=vector_hits,
        identifiers=identifier_hits,
        paths=path_hits,
        pinned=pinned_hits,
    )

    # ---- 3. graph expansion ----
    expanded, paths_visited = _expand_graph(store, seeds, intent, resolved_mode)

    # ---- 3.5 reranker channels + noise penalty (PR 10 + PR 11) ----
    q_terms = query_terms_from(question)
    _apply_extra_signals(expanded, question, q_terms, resolved_mode)

    # ---- 3.6 file co-location boost (PR 13) ----
    # When a seed scores highly in file F, promote other candidates from F.
    if pinned:  # only apply when user signal is explicit; otherwise too noisy
        _apply_co_location_boost(store, expanded)

    # ---- 4. assemble pack ----
    repo_map = _build_repo_map(store)
    pack = _assemble_pack(
        store=store,
        question=question,
        intent=intent,
        mode=resolved_mode,
        retrieval_mode=retrieval_mode,
        repo_map=repo_map,
        ranked_candidates=expanded,
        graph_paths=paths_visited,
        token_budget=token_budget,
    )
    pack.audit = {
        "seeds": {
            "bm25": len(bm25_hits),
            "vector": len(vector_hits),
            "identifier": len(identifier_hits),
            "path": len(path_hits),
            "pinned": len(pinned_hits),
            "fused": len(seeds),
        },
        "expanded_candidates": len(expanded),
        "graph_paths": len(paths_visited),
    }
    return pack


# ---------- seed generation ----------

@dataclass
class _Seed:
    symbol: SymbolRow
    rrf_score: float
    sources: list[str]
    bm25_score: float = 0.0
    vector_score: float = 0.0
    pinned: bool = False
    is_identifier_match: bool = False


def _identifier_hits(store: GraphStore, question: str) -> list[SymbolRow]:
    out: list[SymbolRow] = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", question):
        for sym in store.find_symbols_by_name(token, limit=3):
            out.append(sym)
    return out


def _path_hits(store: GraphStore, question: str) -> list[SymbolRow]:
    out: list[SymbolRow] = []
    for token in re.findall(r"[\w./\-]+\.[a-zA-Z]{1,5}", question):
        out.extend(store.symbols_in_file(token.strip()))
    return out


def _pinned_hits(store: GraphStore, pinned: list[str]) -> list[SymbolRow]:
    out: list[SymbolRow] = []
    for path in pinned:
        out.extend(store.symbols_in_file(path))
    return out


def _fuse_seeds(
    store: GraphStore,
    *,
    bm25: list[SearchHit],
    vector: list,
    identifiers: list[SymbolRow],
    paths: list[SymbolRow],
    pinned: list[SymbolRow],
) -> list[_Seed]:
    """Reciprocal Rank Fusion across heterogeneous signals."""
    fused: dict[str, _Seed] = {}

    def boost(qname: str, sym: SymbolRow, source: str, rank: int,
              raw_score: float = 0.0, pinned_flag: bool = False,
              identifier_match: bool = False) -> None:
        contribution = 1.0 / (RRF_K + rank)
        seed = fused.get(qname)
        if seed is None:
            seed = _Seed(symbol=sym, rrf_score=0.0, sources=[])
            fused[qname] = seed
        seed.rrf_score += contribution
        if source not in seed.sources:
            seed.sources.append(source)
        if source == "bm25":
            seed.bm25_score = max(seed.bm25_score, raw_score)
        elif source == "vector":
            seed.vector_score = max(seed.vector_score, raw_score)
        if pinned_flag:
            seed.pinned = True
        if identifier_match:
            seed.is_identifier_match = True

    for rank, hit in enumerate(bm25):
        boost(hit.symbol.qualified_name, hit.symbol, "bm25", rank, raw_score=hit.score)

    for rank, hit in enumerate(vector):
        sym = store.get_symbol_by_id(hit.symbol_id)
        if sym is not None:
            boost(sym.qualified_name, sym, "vector", rank, raw_score=hit.score)

    for rank, sym in enumerate(_dedupe(identifiers)):
        boost(sym.qualified_name, sym, "identifier", rank, identifier_match=True)

    for rank, sym in enumerate(_dedupe(paths)):
        boost(sym.qualified_name, sym, "path", rank)

    for rank, sym in enumerate(_dedupe(pinned)):
        boost(sym.qualified_name, sym, "pinned", rank, pinned_flag=True)

    seeds = list(fused.values())
    # Pinned seeds always float to the top.
    seeds.sort(key=lambda s: (s.pinned, s.rrf_score), reverse=True)
    return seeds[:30]


def _dedupe(items: list[SymbolRow]) -> list[SymbolRow]:
    seen: set[str] = set()
    out: list[SymbolRow] = []
    for sym in items:
        if sym.qualified_name in seen:
            continue
        seen.add(sym.qualified_name)
        out.append(sym)
    return out


# ---------- graph expansion ----------

@dataclass
class _Candidate:
    symbol: SymbolRow
    score: ScoreBreakdown
    sources: list[str]
    graph_path: list[str]
    confidence: float
    distance: int  # 0 = seed


def _expand_graph(
    store: GraphStore,
    seeds: list[_Seed],
    intent: Intent,
    mode: Mode,
) -> tuple[list[_Candidate], list[str]]:
    forward_edges, reverse_edges = _mode_edge_filters(mode, intent)
    visited: dict[str, _Candidate] = {}
    paths_visited: list[str] = []

    # Normalize RRF scores so seed signal lives on a 0..1 scale comparable to graph.
    max_rrf = max((s.rrf_score for s in seeds), default=1.0) or 1.0
    for seed in seeds:
        norm_seed = seed.rrf_score / max_rrf
        breakdown = ScoreBreakdown(
            bm25=norm_seed if "bm25" in seed.sources else 0.0,
            vector=norm_seed if "vector" in seed.sources else 0.0,
            graph=0.0,
            intent_match=_intent_match_score(seed.symbol, intent, mode),
            centrality=0.0,
            final=norm_seed,
        )
        visited[seed.symbol.qualified_name] = _Candidate(
            symbol=seed.symbol,
            score=breakdown,
            sources=list(seed.sources),
            graph_path=[seed.symbol.qualified_name],
            confidence=0.9 if seed.pinned else 0.8,
            distance=0,
        )

    # Depth-2 walks add infrastructure context (e.g. callees of callees) that
    # editing/feature/impact tasks need. Strict explain/test stay shallow to
    # keep recall focused.
    depth = 2 if mode in {Mode.IMPACT, Mode.FEATURE, Mode.EDIT, Mode.REFACTOR} else 1
    decay = 0.55
    frontier = list(visited.values())
    for level in range(depth):
        next_frontier: list[_Candidate] = []
        for cand in frontier:
            sym = cand.symbol
            for edge in store.outgoing(sym.qualified_name, forward_edges):
                target = _resolve_edge_symbol(store, edge)
                if target is None:
                    continue
                _absorb_neighbor(
                    visited=visited,
                    next_frontier=next_frontier,
                    paths=paths_visited,
                    parent=cand,
                    target=target,
                    edge=edge,
                    direction="out",
                    decay=decay,
                    intent=intent,
                    mode=mode,
                )
            for edge in store.incoming(sym.qualified_name, reverse_edges):
                src = store.find_symbol(edge.src_qname)
                if src is None:
                    continue
                _absorb_neighbor(
                    visited=visited,
                    next_frontier=next_frontier,
                    paths=paths_visited,
                    parent=cand,
                    target=src,
                    edge=edge,
                    direction="in",
                    decay=decay,
                    intent=intent,
                    mode=mode,
                )
        if not next_frontier:
            break
        frontier = next_frontier

    # Graph score: clip to [0, 1] (don't normalize against itself).
    for cand in visited.values():
        cand.score.graph = min(1.0, cand.score.graph)

    # Final weighted blend is applied later by `_apply_extra_signals`, after
    # PR 11 channels are computed. Just rank by what we have for now.
    ranked = sorted(visited.values(), key=lambda c: max(c.score.bm25, c.score.vector, c.score.graph),
                    reverse=True)
    return ranked, paths_visited


def _apply_extra_signals(candidates: list, question: str, q_terms: set,
                          mode: Mode) -> None:
    """PR 11 — fill identifier_overlap / mode_fit / test_proximity / generic_penalty,
    then compute the final weighted score (replacing the placeholder ranking)."""
    weights = _scoring_weights(mode)
    for cand in candidates:
        sym = cand.symbol
        cand.score.identifier_overlap = _identifier_overlap(sym, q_terms)
        cand.score.mode_fit = _mode_fit(sym, mode)
        cand.score.test_proximity = _test_proximity(sym, mode)
        cand.score.generic_penalty = generic_penalty(sym, q_terms)
        seed_signal = max(cand.score.bm25, cand.score.vector)
        cand.score.final = (
            weights["bm25"] * cand.score.bm25
            + weights["vector"] * cand.score.vector
            + weights["graph"] * cand.score.graph
            + weights["identifier"] * cand.score.identifier_overlap
            + weights["mode_fit"] * cand.score.mode_fit
            + weights["test"] * cand.score.test_proximity
            + weights["intent"] * cand.score.intent_match
            + weights["centrality"] * cand.score.centrality
            - weights["generic"] * cand.score.generic_penalty
        )
        # Stronger seed signal when bm25 and vector both fired together.
        if cand.score.bm25 > 0 and cand.score.vector > 0:
            cand.score.final += 0.05
        if cand.distance == 0 and "identifier" in cand.sources:
            cand.score.final += 0.05
        if cand.distance == 0 and "pinned" in cand.sources:
            cand.score.final += 0.10
    candidates.sort(key=lambda c: c.score.final, reverse=True)


def _apply_co_location_boost(store: GraphStore, candidates: list) -> None:
    """PR 13 — When file F has high-scoring seed candidates, surface other symbols
    from F as candidates too. Closes the gap for tasks like
    `security_secret_handling` where `scan_repo` is found but `IgnoreRules`,
    living in the related file, was never seeded.
    """
    if not candidates:
        return
    # Aggregate the strongest seed score per file (only for distance-0 hits).
    file_strength: dict[str, float] = {}
    seen_qnames: set[str] = {c.symbol.qualified_name for c in candidates}
    for cand in candidates:
        if cand.distance > 0:
            continue
        if cand.symbol.kind == "test":
            continue
        seed_signal = max(cand.score.bm25, cand.score.vector, cand.score.identifier_overlap)
        if seed_signal <= 0:
            continue
        cur = file_strength.get(cand.symbol.file_path, 0.0)
        if seed_signal > cur:
            file_strength[cand.symbol.file_path] = seed_signal

    if not file_strength:
        return

    # Only boost existing candidates that share a file with strong seeds.
    # Pulling fresh same-file siblings turned out to displace true seeds from
    # other files; the existing-candidate boost is enough to recover oracle
    # symbols that the graph already reached.
    for cand in candidates:
        strength = file_strength.get(cand.symbol.file_path)
        if not strength:
            continue
        if cand.distance == 0:
            continue
        boost = 0.20 * strength
        if boost > 0:
            cand.score.final += boost
            if "co_location" not in cand.sources:
                cand.sources.append("co_location")

    candidates.sort(key=lambda c: c.score.final, reverse=True)


def _identifier_overlap(sym: SymbolRow, q_terms: set) -> float:
    sym_tokens = set(_split_identifier_tokens(sym.qualified_name))
    if not sym_tokens or not q_terms:
        return 0.0
    overlap = sym_tokens & q_terms
    if not overlap:
        return 0.0
    return min(1.0, len(overlap) / 3.0)


def _split_identifier_tokens(name: str) -> list[str]:
    out: list[str] = []
    for chunk in re.split(r"[._\-]+", name):
        for m in re.finditer(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", chunk):
            tok = m.group(0).lower()
            if len(tok) > 1:
                out.append(tok)
    return out


def _mode_fit(sym: SymbolRow, mode: Mode) -> float:
    score = 0.0
    if mode in {Mode.EDIT, Mode.FEATURE, Mode.REFACTOR, Mode.DEBUG}:
        if sym.kind in {"function", "method", "component", "route"}:
            score += 1.0
        if sym.kind == "class":
            score += 0.5
    if mode == Mode.IMPACT:
        if sym.kind in {"function", "method", "class", "route"}:
            score += 1.0
    if mode == Mode.SECURITY:
        for kw in ("auth", "login", "session", "token", "secret", "permission"):
            if kw in sym.qualified_name.lower():
                score += 0.6
                break
    if mode in {Mode.EXPLAIN, Mode.ONBOARDING}:
        if sym.kind in {"class", "module", "route"}:
            score += 0.6
    return min(1.0, score)


def _test_proximity(sym: SymbolRow, mode: Mode) -> float:
    is_test = sym.kind == "test" or sym.name.startswith(("test_", "test"))
    in_test_file = "test" in sym.file_path.lower()
    if mode == Mode.TEST:
        if is_test or in_test_file:
            return 1.0
    if mode in {Mode.EDIT, Mode.FEATURE, Mode.REFACTOR, Mode.DEBUG}:
        # Tests are useful but not the focus.
        return 0.4 if is_test or in_test_file else 0.0
    if mode in {Mode.EXPLAIN, Mode.ONBOARDING, Mode.IMPACT}:
        # Don't reward test files — they distract.
        return -0.3 if is_test or in_test_file else 0.0
    return 0.0


def _absorb_neighbor(*, visited: dict, next_frontier: list, paths: list[str],
                     parent: _Candidate, target: SymbolRow, edge: EdgeRow,
                     direction: str, decay: float, intent: Intent, mode: Mode) -> None:
    contribution = (parent.score.final * decay * edge.confidence) or (
        decay * edge.confidence
    )
    qname = target.qualified_name
    cur = visited.get(qname)
    arrow = "-->" if direction == "out" else "<--"
    if direction == "out":
        path_str = f"{parent.symbol.qualified_name} --{edge.edge_type}--> {qname}"
    else:
        path_str = f"{qname} --{edge.edge_type}--> {parent.symbol.qualified_name}"
    if cur is None:
        breakdown = ScoreBreakdown(
            graph=contribution,
            intent_match=_intent_match_score(target, intent, mode),
        )
        cand = _Candidate(
            symbol=target,
            score=breakdown,
            sources=[f"graph:{edge.edge_type.lower()}"],
            graph_path=parent.graph_path + [qname],
            confidence=edge.confidence,
            distance=parent.distance + 1,
        )
        visited[qname] = cand
        next_frontier.append(cand)
        paths.append(path_str)
    else:
        cur.score.graph = max(cur.score.graph, contribution)
        if f"graph:{edge.edge_type.lower()}" not in cur.sources:
            cur.sources.append(f"graph:{edge.edge_type.lower()}")
        if len(cur.graph_path) > parent.distance + 2:
            cur.graph_path = parent.graph_path + [qname]
        paths.append(path_str)


def _mode_edge_filters(mode: Mode, intent: Intent) -> tuple[list[str], list[str]]:
    if mode == Mode.IMPACT or intent == Intent.IMPACT:
        return ["CALLS", "ROUTES_TO"], ["CALLS", "TESTS", "ROUTES_TO", "EXTENDS"]
    if mode == Mode.FEATURE:
        return ["CALLS", "IMPORTS", "ROUTES_TO"], ["CALLS", "ROUTES_TO", "TESTS"]
    if mode == Mode.EDIT:
        return ["CALLS", "IMPORTS"], ["CALLS", "TESTS", "ROUTES_TO"]
    if mode == Mode.DEBUG:
        return ["CALLS", "IMPORTS"], ["CALLS", "TESTS"]
    if mode == Mode.TEST:
        return ["CALLS"], ["TESTS"]
    if mode == Mode.SECURITY:
        return ["CALLS", "IMPORTS", "ROUTES_TO"], ["ROUTES_TO", "CALLS"]
    if mode == Mode.REFACTOR:
        return ["CALLS", "IMPORTS", "EXTENDS"], ["CALLS", "EXTENDS", "TESTS"]
    if mode == Mode.ONBOARDING:
        return ["CALLS", "IMPORTS", "ROUTES_TO"], ["CALLS", "ROUTES_TO"]
    return ["CALLS", "IMPORTS", "EXTENDS", "ROUTES_TO"], ["CALLS", "ROUTES_TO", "TESTS"]


def _scoring_weights(mode: Mode) -> dict[str, float]:
    """Weights for the final score blend (PR 11).

    Strategy: keep the seed signal (bm25 + vector) dominant — it carries 70-80% of
    the ordering. Use identifier_overlap / mode_fit / test_proximity as additive
    refinements (small weights). The generic-symbol penalty is *subtracted*.
    """
    base = {
        "bm25": 0.40, "vector": 0.40, "graph": 0.10, "identifier": 0.08,
        "mode_fit": 0.05, "test": 0.03, "intent": 0.04, "centrality": 0.00,
        "generic": 0.30,
    }
    if mode in {Mode.EXPLAIN, Mode.ONBOARDING}:
        return {
            "bm25": 0.32, "vector": 0.42, "graph": 0.14, "identifier": 0.06,
            "mode_fit": 0.05, "test": 0.03, "intent": 0.04, "centrality": 0.00,
            "generic": 0.30,
        }
    if mode in {Mode.EDIT, Mode.FEATURE, Mode.DEBUG, Mode.REFACTOR}:
        return {
            "bm25": 0.40, "vector": 0.36, "graph": 0.10, "identifier": 0.10,
            "mode_fit": 0.06, "test": 0.04, "intent": 0.04, "centrality": 0.00,
            "generic": 0.25,
        }
    if mode == Mode.IMPACT:
        return {
            "bm25": 0.20, "vector": 0.18, "graph": 0.40, "identifier": 0.06,
            "mode_fit": 0.08, "test": 0.04, "intent": 0.04, "centrality": 0.00,
            "generic": 0.20,
        }
    if mode == Mode.TEST:
        return {
            "bm25": 0.25, "vector": 0.22, "graph": 0.22, "identifier": 0.06,
            "mode_fit": 0.05, "test": 0.15, "intent": 0.05, "centrality": 0.00,
            "generic": 0.18,
        }
    return base


def _intent_match_score(sym: SymbolRow, intent: Intent, mode: Mode) -> float:
    score = 0.0
    if mode == Mode.TEST and (sym.kind == "test" or sym.name.startswith(("test_", "test"))
                              or "test" in sym.file_path.lower()):
        score += 1.0
    if mode == Mode.IMPACT and sym.kind in {"function", "method", "class", "route"}:
        score += 0.5
    if mode in {Mode.EDIT, Mode.FEATURE} and sym.kind in {"function", "method", "component", "route"}:
        score += 0.4
    if mode == Mode.SECURITY and any(kw in sym.qualified_name.lower()
                                     for kw in ("auth", "login", "session", "token", "secret")):
        score += 0.6
    return score


def _resolve_edge_symbol(store: GraphStore, edge: EdgeRow) -> SymbolRow | None:
    if edge.dst_qname:
        sym = store.find_symbol(edge.dst_qname)
        if sym:
            return sym
    by_name = store.find_symbols_by_name(edge.dst_name, limit=1)
    return by_name[0] if by_name else None


# ---------- pack assembly ----------

def _assemble_pack(*, store: GraphStore, question: str, intent: Intent, mode: Mode,
                   retrieval_mode: str, repo_map: str,
                   ranked_candidates: list[_Candidate],
                   graph_paths: list[str], token_budget: int) -> ContextPack:
    map_share, capsule_share, snippet_share = _tier_shares(mode)
    map_budget = max(300, int(token_budget * map_share))
    capsule_budget = max(800, int(token_budget * capsule_share))
    snippet_budget = max(0, int(token_budget * snippet_share))

    if estimate_tokens(repo_map) > map_budget:
        repo_map = truncate_to_tokens(repo_map, map_budget)
    spent = estimate_tokens(repo_map)
    items: list[ContextItem] = []
    files_to_edit: list[str] = []
    related_tests: list[str] = []
    capsule_spent = 0
    snippet_spent = 0

    needs_source = mode in {Mode.EDIT, Mode.FEATURE, Mode.DEBUG, Mode.REFACTOR, Mode.TEST,
                            Mode.IMPACT, Mode.EXPLAIN, Mode.ONBOARDING}
    # Limit how many snippets we'll emit — explain/onboarding only get the top
    # 2 to keep snippets focused, while edit modes get the wider top-8.
    max_snippets = 8 if mode in {Mode.EDIT, Mode.FEATURE, Mode.DEBUG, Mode.REFACTOR,
                                  Mode.TEST, Mode.IMPACT} else 2

    # PR 10 — diversity caps
    caps = default_caps_for_mode(mode.value)
    q_terms = query_terms_from(question)
    per_file_count: dict[str, int] = {}
    pure_graph_admitted = 0

    seen_qnames: set[str] = set()
    capsules_admitted = 0
    for cand in ranked_candidates:
        sym = cand.symbol
        if sym.qualified_name in seen_qnames:
            continue
        seen_qnames.add(sym.qualified_name)

        # PR 10/13 — drop test/fixture capsules entirely in modes where they distract.
        is_pinned_file = "pinned" in cand.sources
        path_l = sym.file_path.lower()
        looks_like_test = (
            sym.kind == "test"
            or sym.name.startswith(("test_", "test"))
            or "/tests/" in "/" + path_l + "/"
            or path_l.startswith("tests/")
            or "/test/" in "/" + path_l + "/"
            or "/__tests__/" in "/" + path_l + "/"
            or "fixture" in path_l
        )
        if caps.drop_test_files and looks_like_test and not is_pinned_file:
            continue

        # Hard cap on number of capsules — strongest lever for irrelevant_ratio.
        if capsules_admitted >= caps.max_capsules:
            continue

        # Diversity: cap how many capsules can come from the same file.
        if not is_pinned_file:
            count = per_file_count.get(sym.file_path, 0)
            if count >= caps.max_per_file:
                continue

        seed_sourced = any(s in cand.sources for s in ("bm25", "vector", "identifier", "pinned"))
        if not seed_sourced:
            if pure_graph_admitted >= caps.max_pure_graph_hits:
                continue
            pure_graph_admitted += 1

        capsule_text = sym.capsule or _fallback_capsule(sym)
        ctok = estimate_tokens(capsule_text)
        if capsule_spent + ctok > capsule_budget:
            continue
        per_file_count[sym.file_path] = per_file_count.get(sym.file_path, 0) + 1
        capsules_admitted += 1
        items.append(ContextItem(
            kind="capsule",
            title=f"Capsule: {sym.qualified_name}",
            body=capsule_text,
            file_path=sym.file_path,
            start_line=sym.start_line,
            end_line=sym.end_line,
            score=cand.score.final,
            tokens=ctok,
            retrieval_sources=list(cand.sources),
            score_breakdown=cand.score,
            graph_path=list(cand.graph_path),
            confidence=cand.confidence,
            reason=_explain_inclusion(cand, mode),
        ))
        capsule_spent += ctok
        spent += ctok
        if needs_source and sym.file_path not in files_to_edit:
            files_to_edit.append(sym.file_path)
        if sym.kind == "test" or sym.name.startswith("test_"):
            related_tests.append(sym.file_path)

    if needs_source and snippet_budget > 0:
        snippets_admitted = 0
        for cand in ranked_candidates[:8]:
            if snippets_admitted >= max_snippets:
                break
            snippet = _extract_snippet(store, cand.symbol)
            if not snippet:
                continue
            snippets_admitted += 1
            stok = estimate_tokens(snippet)
            if snippet_spent + stok > snippet_budget:
                snippet = truncate_to_tokens(snippet, max(200, snippet_budget - snippet_spent))
                stok = estimate_tokens(snippet)
                if stok <= 0:
                    continue
            items.append(ContextItem(
                kind="snippet",
                title=f"Source: {cand.symbol.qualified_name}",
                body=f"```\n{snippet}\n```",
                file_path=cand.symbol.file_path,
                start_line=cand.symbol.start_line,
                end_line=cand.symbol.end_line,
                score=cand.score.final,
                tokens=stok,
                retrieval_sources=list(cand.sources) + ["source-extract"],
                score_breakdown=cand.score,
                graph_path=list(cand.graph_path),
                confidence=cand.confidence,
                reason=f"Mode `{mode.value}` requires implementation detail.",
            ))
            snippet_spent += stok
            spent += stok
            if snippet_spent >= snippet_budget:
                break

    included_qnames = {
        _qname_from_title(it.title) for it in items if it.kind in {"capsule", "snippet"}
    }
    ranked_candidates_summary: list[RankedCandidate] = []
    for rank, cand in enumerate(ranked_candidates, start=1):
        ranked_candidates_summary.append(RankedCandidate(
            qualified_name=cand.symbol.qualified_name,
            file_path=cand.symbol.file_path,
            kind=cand.symbol.kind,
            rank=rank,
            included=cand.symbol.qualified_name in included_qnames,
            score_breakdown=cand.score,
            retrieval_sources=list(cand.sources),
            distance=cand.distance,
            graph_path=list(cand.graph_path),
        ))

    return ContextPack(
        question=question,
        intent=intent,
        mode=mode,
        items=items,
        estimated_tokens=spent,
        repo_map=repo_map,
        graph_paths=_dedupe_paths(graph_paths)[:14],
        files_likely_to_edit=files_to_edit[:8],
        related_tests=_dedupe_strings(related_tests)[:6],
        retrieval_mode=retrieval_mode,
        ranked_candidates=ranked_candidates_summary,
    )


def _qname_from_title(title: str) -> str:
    parts = title.split(":", 1)
    if len(parts) != 2:
        return ""
    return parts[1].strip()


def _tier_shares(mode: Mode) -> tuple[float, float, float]:
    """Return (repo_map, capsules, snippets) budget shares — should sum ≤ 1.0."""
    if mode in {Mode.EDIT, Mode.FEATURE, Mode.DEBUG, Mode.REFACTOR}:
        return 0.08, 0.40, 0.50
    if mode == Mode.TEST:
        return 0.08, 0.42, 0.48
    if mode == Mode.IMPACT:
        return 0.10, 0.50, 0.40
    if mode in {Mode.EXPLAIN, Mode.ONBOARDING}:
        return 0.10, 0.50, 0.40
    return 0.10, 0.45, 0.45


def _explain_inclusion(cand: _Candidate, mode: Mode) -> str:
    parts: list[str] = []
    src = ", ".join(cand.sources) or "graph"
    if cand.distance == 0:
        parts.append(f"Seed match via {src}")
    else:
        path = " → ".join(cand.graph_path)
        parts.append(f"{cand.distance}-hop neighbor: {path}")
    parts.append(f"score={cand.score.final:.3f}")
    parts.append(f"mode={mode.value}")
    return "  ·  ".join(parts)


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
    for path in store.known_files():
        top = path.split("/", 1)[0] if "/" in path else "(root)"
        counts[top] = counts.get(top, 0) + 1
    if not counts:
        return ""
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:max_dirs]
    return "\n".join(f"- `{name}/` — {n} files" for name, n in ranked)


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out
