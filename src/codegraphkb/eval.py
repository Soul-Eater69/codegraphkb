"""Retrieval evaluation harness.

Run a YAML dataset of golden tasks (with oracle files / symbols), measure how
well the current retrieval pipeline recovers them inside the token budget.

Designed to be the first Phase-2 module so every subsequent change (tree-sitter,
embeddings, hybrid retrieval) can be A/B'd with `codegraph eval`.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from codegraphkb.api import CodeGraphKB
from codegraphkb.config import DEFAULT_TOKEN_BUDGET
from codegraphkb.core.retrieval import ContextPack
from codegraphkb.paths import file_matches, normalize_path


@dataclass
class GoldenTask:
    id: str
    task: str
    mode: str = "explain"
    budget: int = DEFAULT_TOKEN_BUDGET
    oracle_files: list[str] = field(default_factory=list)
    oracle_symbols: list[str] = field(default_factory=list)
    pinned_files: list[str] = field(default_factory=list)
    intent: str | None = None
    # Phase 2.5 (PR 12): files/symbols that should NOT show up in the pack.
    should_exclude_files: list[str] = field(default_factory=list)
    should_exclude_symbols: list[str] = field(default_factory=list)


@dataclass
class MissedSymbol:
    name: str
    rank: int | None        # rank in full ranked list, or None if never seen
    included: bool
    final_score: float
    bm25: float
    vector: float
    graph: float
    sources: list[str]
    file_path: str | None


@dataclass
class NoiseItem:
    """An item included in the pack that doesn't match the oracle (PR 8)."""
    title: str
    file_path: str | None
    final_score: float
    sources: list[str]
    reason: str


@dataclass
class TaskResult:
    id: str
    task: str
    mode: str
    file_recall_at_8: float
    file_recall_at_k: dict[int, float]
    symbol_recall_at_12: float
    symbol_recall_at_k: dict[int, float]
    irrelevant_ratio: float
    exclusion_violations: int = 0  # PR 12
    budget_utilization: float = 0.0
    estimated_tokens: int = 0
    budget: int = 0
    latency_ms: float = 0.0
    retrieved_files: list[str] = field(default_factory=list)
    retrieved_symbols: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    missing_symbols: list[str] = field(default_factory=list)
    excluded_violations: list[str] = field(default_factory=list)
    # PR 8 — failure-report extras
    missed_symbols_detail: list[MissedSymbol] = field(default_factory=list)
    noise_items: list[NoiseItem] = field(default_factory=list)
    # PR 13 — failure-driven tuning hints
    suggested_tuning_actions: list[str] = field(default_factory=list)
    retrieval_sources_causing_noise: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    dataset: str
    repo_path: str
    retrieval_mode: str
    n_tasks: int
    file_recall_at_8: float
    symbol_recall_at_12: float
    irrelevant_ratio: float
    exclusion_violation_rate: float
    budget_utilization: float
    median_latency_ms: float
    p95_latency_ms: float
    tasks: list[TaskResult]

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def summary_text(self) -> str:
        lines = [
            f"Eval dataset:      {self.dataset}",
            f"Repo:              {self.repo_path}",
            f"Retrieval mode:    {self.retrieval_mode}",
            f"Tasks:             {self.n_tasks}",
            "",
            f"File recall@8:        {self.file_recall_at_8:.2f}",
            f"Symbol recall@12:     {self.symbol_recall_at_12:.2f}",
            f"Irrelevant ratio:     {self.irrelevant_ratio:.2f}",
            f"Exclusion violations: {self.exclusion_violation_rate:.2f}",
            f"Budget utilization:   {self.budget_utilization:.2f}",
            f"Median latency:       {self.median_latency_ms:.0f} ms",
            f"p95 latency:          {self.p95_latency_ms:.0f} ms",
        ]
        return "\n".join(lines)

    def explain_text(self, max_misses: int = 4, max_noise: int = 5) -> str:
        """Per-task failure report (PR 8). Renders rank/scores for missed oracle
        symbols and lists noisy items that crowded them out."""
        out: list[str] = []
        for r in self.tasks:
            if not r.missed_symbols_detail and not r.noise_items and not r.excluded_violations:
                continue
            out.append("")
            out.append(f"### {r.id}  ({r.mode})")
            out.append(f"  task: {r.task}")
            if r.missed_symbols_detail:
                out.append("  missed oracle symbols:")
                for m in r.missed_symbols_detail[:max_misses]:
                    if m.rank is None:
                        out.append(f"    - {m.name}: NOT in ranked candidates")
                    else:
                        included = "included" if m.included else "excluded by budget"
                        out.append(
                            f"    - {m.name}: rank #{m.rank} ({included})  "
                            f"final={m.final_score:.3f}  bm25={m.bm25:.2f}  "
                            f"vector={m.vector:.2f}  graph={m.graph:.2f}  "
                            f"sources={','.join(m.sources) or '∅'}"
                        )
            if r.noise_items:
                out.append("  noisy items in pack:")
                for n in r.noise_items[:max_noise]:
                    loc = f" ({n.file_path})" if n.file_path else ""
                    out.append(
                        f"    - {n.title}{loc}  final={n.final_score:.3f}  "
                        f"sources={','.join(n.sources) or '∅'}"
                    )
            if r.excluded_violations:
                out.append("  exclusion-list violations:")
                for v in r.excluded_violations:
                    out.append(f"    - {v}")
        return "\n".join(out)


# ---------- public API ----------

def load_dataset(path: Path) -> list[GoldenTask]:
    text = path.read_text(encoding="utf-8")
    raw = _parse_yaml(text)
    if not isinstance(raw, list):
        raise ValueError(f"{path}: dataset must be a top-level list of tasks.")
    tasks: list[GoldenTask] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: each task must be a mapping, got {type(entry)}.")
        # Skip edit-workflow-only entries (consumed by `codegraph eval-edit`).
        if not entry.get("oracle_files") and not entry.get("oracle_symbols"):
            continue
        tasks.append(GoldenTask(
            id=str(entry.get("id") or entry.get("task") or "task"),
            task=str(entry["task"]),
            mode=str(entry.get("mode") or "explain"),
            budget=int(entry.get("budget") or DEFAULT_TOKEN_BUDGET),
            oracle_files=[str(p) for p in entry.get("oracle_files", []) or []],
            oracle_symbols=[str(s) for s in entry.get("oracle_symbols", []) or []],
            pinned_files=[str(p) for p in entry.get("pinned_files", []) or []],
            intent=entry.get("intent"),
            should_exclude_files=[str(p) for p in entry.get("should_exclude_files", [])
                                  or entry.get("should_exclude", []) or []],
            should_exclude_symbols=[str(s) for s in entry.get("should_exclude_symbols", []) or []],
        ))
    return tasks


def evaluate(
    repo_path: str | Path,
    dataset_path: Path,
    *,
    retrieval_mode: str = "default",
) -> EvalReport:
    kb = CodeGraphKB(repo_path)
    tasks = load_dataset(dataset_path)
    results: list[TaskResult] = []
    for task in tasks:
        results.append(_run_task(kb, task, retrieval_mode))
    return _aggregate(
        dataset=str(dataset_path),
        repo_path=str(kb.config.repo_path),
        retrieval_mode=retrieval_mode,
        results=results,
    )


# ---------- internals ----------

_K_FILES = (1, 3, 5, 8, 12)
_K_SYMBOLS = (3, 5, 8, 12, 20)


def _run_task(kb: CodeGraphKB, task: GoldenTask, retrieval_mode: str = "default") -> TaskResult:
    started = time.perf_counter()
    pack = kb.retrieve_context(
        task.task,
        token_budget=task.budget,
        intent=task.intent or task.mode,
        mode=task.mode,
        pinned_files=task.pinned_files,
        retrieval=_retrieval_for_mode(retrieval_mode),
    )
    latency_ms = (time.perf_counter() - started) * 1000.0

    repo_root = kb.config.repo_path
    retrieved_files = _ordered_unique([
        normalize_path(item.file_path, repo_root) for item in pack.items if item.file_path
    ])
    retrieved_symbols = _ordered_unique([
        _qname_from_title(item.title) for item in pack.items
        if item.kind in {"capsule", "snippet"}
    ])

    oracle_files = [normalize_path(p, repo_root) for p in task.oracle_files]
    should_exclude_files = [normalize_path(p, repo_root) for p in task.should_exclude_files]

    file_recall_at_k = {k: _recall_at_k(retrieved_files, oracle_files, k) for k in _K_FILES}
    symbol_recall_at_k = {
        k: _symbol_recall_at_k(retrieved_symbols, task.oracle_symbols, k)
        for k in _K_SYMBOLS
    }

    irrelevant = _irrelevant_ratio(pack, task)
    utilization = pack.estimated_tokens / max(1, task.budget)

    missing_files = [f for f in oracle_files if not _any_file_match(retrieved_files, f, repo_root)]
    missing_symbols = [
        s for s in task.oracle_symbols
        if not any(_symbol_match(s, q) for q in retrieved_symbols)
    ]

    # PR 8 — explain why each missing oracle symbol was missed.
    missed_detail: list[MissedSymbol] = []
    for oracle in missing_symbols:
        match = _find_in_ranked(pack.ranked_candidates, oracle)
        if match is None:
            missed_detail.append(MissedSymbol(
                name=oracle, rank=None, included=False,
                final_score=0.0, bm25=0.0, vector=0.0, graph=0.0,
                sources=[], file_path=None,
            ))
        else:
            missed_detail.append(MissedSymbol(
                name=oracle, rank=match.rank, included=match.included,
                final_score=match.score_breakdown.final,
                bm25=match.score_breakdown.bm25,
                vector=match.score_breakdown.vector,
                graph=match.score_breakdown.graph,
                sources=list(match.retrieval_sources),
                file_path=match.file_path,
            ))

    # PR 8 — surface noisy items: included symbols that don't match the oracle.
    noise_items: list[NoiseItem] = []
    for item in pack.items:
        if item.kind not in {"capsule", "snippet"}:
            continue
        qname = _qname_from_title(item.title)
        if any(_symbol_match(o, qname) for o in task.oracle_symbols):
            continue
        if item.file_path and any(_any_file_match([item.file_path], o, repo_root) for o in oracle_files):
            continue
        noise_items.append(NoiseItem(
            title=item.title,
            file_path=item.file_path,
            final_score=item.score_breakdown.final,
            sources=list(item.retrieval_sources),
            reason=item.reason or "ranked above the budget cutoff",
        ))

    # PR 12 — exclusion violations
    exclusion_violations: list[str] = []
    for f in should_exclude_files:
        if any(_any_file_match([rf], f, repo_root) for rf in retrieved_files):
            exclusion_violations.append(f"file:{f}")
    for s in task.should_exclude_symbols:
        if any(_symbol_match(s, q) for q in retrieved_symbols):
            exclusion_violations.append(f"symbol:{s}")

    suggested = _suggest_tuning_actions(missed_detail, noise_items, task)
    sources_noise = _summarize_noise_sources(noise_items)

    return TaskResult(
        id=task.id,
        task=task.task,
        mode=task.mode,
        file_recall_at_8=file_recall_at_k[8],
        file_recall_at_k=file_recall_at_k,
        symbol_recall_at_12=symbol_recall_at_k[12],
        symbol_recall_at_k=symbol_recall_at_k,
        irrelevant_ratio=irrelevant,
        exclusion_violations=len(exclusion_violations),
        budget_utilization=utilization,
        estimated_tokens=pack.estimated_tokens,
        budget=task.budget,
        latency_ms=latency_ms,
        retrieved_files=retrieved_files[:20],
        retrieved_symbols=retrieved_symbols[:20],
        missing_files=missing_files,
        missing_symbols=missing_symbols,
        excluded_violations=exclusion_violations,
        missed_symbols_detail=missed_detail,
        noise_items=noise_items[:8],
        suggested_tuning_actions=suggested,
        retrieval_sources_causing_noise=sources_noise,
    )


def _suggest_tuning_actions(missed: list[MissedSymbol], noise: list[NoiseItem],
                            task: GoldenTask) -> list[str]:
    """PR 13 — heuristic suggestions extracted from each task's failure shape."""
    actions: list[str] = []
    # Excluded-by-budget misses → suggest raising rank for these
    for m in missed:
        if m.rank is None:
            actions.append(
                f"oracle `{m.name}` never reached the candidate set — consider alias "
                f"expansion or a same-file co-location boost"
            )
        elif not m.included:
            if m.bm25 == 0.0 and m.vector == 0.0:
                actions.append(
                    f"oracle `{m.name}` is reachable only via graph (rank #{m.rank}) — "
                    f"strengthen identifier_overlap or alias text on this symbol"
                )
            else:
                actions.append(
                    f"oracle `{m.name}` ranked #{m.rank} (excluded by budget) — "
                    f"raise max_capsules for mode `{task.mode}` or reduce noise above it"
                )
    # Noise items repeating the same file → suggest tighter per-file cap
    file_counts: dict[str, int] = {}
    for n in noise:
        if n.file_path:
            file_counts[n.file_path] = file_counts.get(n.file_path, 0) + 1
    for path, count in file_counts.items():
        if count >= 3:
            actions.append(
                f"file `{path}` contributed {count} noise items — tighten max_per_file "
                f"or add a path-prior penalty"
            )
    # Test files leaking into non-test modes
    if task.mode not in {"test", "test_generation"}:
        test_noise = [n for n in noise if n.file_path and "test" in n.file_path.lower()]
        if test_noise:
            actions.append(
                f"{len(test_noise)} test capsules leaked into mode `{task.mode}` — "
                f"set drop_test_files=True for this mode"
            )
    return actions


def _summarize_noise_sources(noise: list[NoiseItem]) -> list[str]:
    counts: dict[str, int] = {}
    for n in noise:
        for s in n.sources:
            counts[s] = counts.get(s, 0) + 1
    return [f"{src}:{count}" for src, count in
            sorted(counts.items(), key=lambda kv: kv[1], reverse=True)]


def _retrieval_for_mode(retrieval_mode: str) -> str:
    """Map an eval-level mode label to the kb.retrieve_context retrieval flag."""
    if retrieval_mode in ("hybrid", "vector"):
        return retrieval_mode
    if retrieval_mode == "bm25":
        return "bm25"
    return "auto"


def _find_in_ranked(candidates, oracle: str):
    for cand in candidates:
        if _symbol_match(oracle, cand.qualified_name):
            return cand
    return None


def _qname_from_title(title: str) -> str:
    parts = title.split(":", 1)
    if len(parts) != 2:
        return ""
    return parts[1].strip()


def _aggregate(*, dataset: str, repo_path: str, retrieval_mode: str,
               results: list[TaskResult]) -> EvalReport:
    if not results:
        return EvalReport(
            dataset=dataset, repo_path=repo_path, retrieval_mode=retrieval_mode,
            n_tasks=0, file_recall_at_8=0.0, symbol_recall_at_12=0.0,
            irrelevant_ratio=0.0, exclusion_violation_rate=0.0,
            budget_utilization=0.0,
            median_latency_ms=0.0, p95_latency_ms=0.0, tasks=[],
        )
    file_r = statistics.fmean(r.file_recall_at_8 for r in results)
    sym_r = statistics.fmean(r.symbol_recall_at_12 for r in results)
    irr = statistics.fmean(r.irrelevant_ratio for r in results)
    excl = statistics.fmean(1.0 if r.exclusion_violations else 0.0 for r in results)
    util = statistics.fmean(r.budget_utilization for r in results)
    latencies = sorted(r.latency_ms for r in results)
    median = statistics.median(latencies)
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0.0
    return EvalReport(
        dataset=dataset,
        repo_path=repo_path,
        retrieval_mode=retrieval_mode,
        n_tasks=len(results),
        file_recall_at_8=file_r,
        symbol_recall_at_12=sym_r,
        irrelevant_ratio=irr,
        exclusion_violation_rate=excl,
        budget_utilization=util,
        median_latency_ms=median,
        p95_latency_ms=p95,
        tasks=results,
    )


def _recall_at_k(retrieved: list[str], oracle: list[str], k: int) -> float:
    if not oracle:
        return 1.0
    top = retrieved[:k]
    hits = sum(1 for o in oracle if _any_file_match(top, o))
    return hits / len(oracle)


def _symbol_recall_at_k(retrieved: list[str], oracle: list[str], k: int) -> float:
    if not oracle:
        return 1.0
    top = retrieved[:k]
    hits = sum(1 for o in oracle if any(_symbol_match(o, q) for q in top))
    return hits / len(oracle)


def _any_file_match(retrieved: Iterable[str], oracle_path: str,
                    repo_root: str | Path | None = None) -> bool:
    for r in retrieved:
        if file_matches(r, oracle_path, repo_root):
            return True
    return False


def _symbol_match(oracle: str, qname: str) -> bool:
    if not qname:
        return False
    if oracle == qname:
        return True
    if qname.endswith("." + oracle):
        return True
    last = qname.rsplit(".", 1)[-1]
    return last == oracle


def _irrelevant_ratio(pack: ContextPack, task: GoldenTask) -> float:
    if not pack.items:
        return 0.0
    total_tokens = sum(item.tokens for item in pack.items) or 1
    relevant_tokens = 0
    for item in pack.items:
        if item.file_path and _any_file_match([item.file_path], task.oracle_files[0] if task.oracle_files else ""):
            pass
        if item.file_path and any(
            _any_file_match([item.file_path], o) for o in task.oracle_files
        ):
            relevant_tokens += item.tokens
            continue
        qname = _qname_from_title(item.title)
        if qname and any(_symbol_match(o, qname) for o in task.oracle_symbols):
            relevant_tokens += item.tokens
    return 1.0 - (relevant_tokens / total_tokens)


def _qname_from_title(title: str) -> str:
    # Titles look like "Capsule: foo.bar.Baz" or "Source: foo.bar.Baz".
    parts = title.split(":", 1)
    if len(parts) != 2:
        return ""
    return parts[1].strip()


def _ordered_unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


# ---------- tiny YAML reader ----------
# We intentionally avoid a PyYAML dep — the dataset format is a list of mappings
# with string / list / int values. This handles that subset and nothing more.

def _parse_yaml(text: str) -> list[dict]:
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    docs: list[dict] = []
    current: dict | None = None
    current_key: str | None = None
    pending_list: list | None = None
    for raw_line in lines:
        stripped = raw_line.lstrip()
        indent = len(raw_line) - len(stripped)
        if stripped.startswith("- "):
            # New task or list item
            content = stripped[2:].strip()
            if indent == 0:
                if current is not None:
                    docs.append(current)
                current = {}
                pending_list = None
                if ":" in content:
                    key, _, value = content.partition(":")
                    current[key.strip()] = _coerce_scalar(value.strip())
                    current_key = key.strip()
            else:
                if pending_list is None:
                    raise ValueError(f"Unexpected list item: {raw_line!r}")
                pending_list.append(_coerce_scalar(content))
        elif current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "":
                current[key] = []
                pending_list = current[key]
                current_key = key
            else:
                current[key] = _coerce_scalar(value)
                pending_list = None
                current_key = key
        else:
            raise ValueError(f"Unsupported line: {raw_line!r}")
    if current is not None:
        docs.append(current)
    return docs


def _coerce_scalar(value: str):
    v = value.strip()
    if not v:
        return ""
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if v.lower() in {"true", "false"}:
        return v.lower() == "true"
    if v.lower() == "null":
        return None
    return v


def report_to_json(report: EvalReport, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent)
