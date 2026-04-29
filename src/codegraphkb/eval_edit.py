"""Edit-workflow evaluation (Phase 3 PR 19).

Loads golden tasks with edit-specific oracles:
  - oracle_files_likely_to_edit
  - oracle_files_read_only
  - oracle_tests
  - oracle_symbols_to_modify
  - expected_validation_types
  - risk_keywords

Runs `prepare_edit_context` for each task and reports:
  - edit_file_recall@5
  - read_only_file_precision@5
  - related_test_recall@5
  - symbol_to_modify_recall@8
  - validation_command_recall
  - risk_keyword_recall
  - workflow_latency_ms
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from codegraphkb.api import CodeGraphKB
from codegraphkb.eval import _any_file_match, _parse_yaml, _symbol_match
from codegraphkb.paths import normalize_path
from codegraphkb.workflow import prepare_edit_context


@dataclass
class EditTask:
    id: str
    task: str
    mode: str = "edit"
    budget: int = 6000
    oracle_files_likely_to_edit: list[str] = field(default_factory=list)
    oracle_files_read_only: list[str] = field(default_factory=list)
    oracle_tests: list[str] = field(default_factory=list)
    oracle_symbols_to_modify: list[str] = field(default_factory=list)
    expected_validation_types: list[str] = field(default_factory=list)
    risk_keywords: list[str] = field(default_factory=list)


@dataclass
class EditTaskResult:
    id: str
    task: str
    mode: str
    edit_file_recall_at_5: float
    read_only_file_precision_at_5: float
    related_test_recall_at_5: float
    symbol_recall_at_8: float
    validation_command_recall: float
    risk_keyword_recall: float
    workflow_latency_ms: float
    budget_utilization: float
    retrieved_edit_files: list[str] = field(default_factory=list)
    retrieved_tests: list[str] = field(default_factory=list)
    retrieved_symbols: list[str] = field(default_factory=list)
    missing_edit_files: list[str] = field(default_factory=list)
    missing_symbols: list[str] = field(default_factory=list)
    missing_validation_types: list[str] = field(default_factory=list)
    timing_ms: dict[str, float] = field(default_factory=dict)


@dataclass
class EditEvalReport:
    dataset: str
    repo_path: str
    n_tasks: int
    edit_file_recall_at_5: float
    related_test_recall_at_5: float
    symbol_recall_at_8: float
    validation_command_recall: float
    risk_keyword_recall: float
    median_latency_ms: float
    tasks: list[EditTaskResult]
    timing_summary_ms: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary_text(self) -> str:
        return "\n".join([
            f"Dataset:                 {self.dataset}",
            f"Repo:                    {self.repo_path}",
            f"Tasks:                   {self.n_tasks}",
            "",
            f"Edit file recall@5:      {self.edit_file_recall_at_5:.2f}",
            f"Related test recall@5:   {self.related_test_recall_at_5:.2f}",
            f"Symbol recall@8:         {self.symbol_recall_at_8:.2f}",
            f"Validation cmd recall:   {self.validation_command_recall:.2f}",
            f"Risk keyword recall:     {self.risk_keyword_recall:.2f}",
            f"Median latency:          {self.median_latency_ms:.0f} ms",
        ])


def evaluate_edit(repo_path: str | Path, dataset_path: Path) -> EditEvalReport:
    kb = CodeGraphKB(repo_path)
    tasks = _load_dataset(dataset_path)
    if not tasks:
        return EditEvalReport(
            dataset=str(dataset_path), repo_path=str(kb.config.repo_path),
            n_tasks=0,
            edit_file_recall_at_5=0.0, related_test_recall_at_5=0.0,
            symbol_recall_at_8=0.0, validation_command_recall=0.0,
            risk_keyword_recall=0.0, median_latency_ms=0.0, tasks=[],
            timing_summary_ms={},
        )
    results: list[EditTaskResult] = []
    for task in tasks:
        results.append(_run_task(kb, task))
    return _aggregate(str(dataset_path), str(kb.config.repo_path), results)


def _load_dataset(path: Path) -> list[EditTask]:
    raw = _parse_yaml(path.read_text(encoding="utf-8"))
    tasks: list[EditTask] = []
    for entry in raw:
        # Only consume entries that have edit-specific oracles.
        if not any(k in entry for k in ("oracle_files_likely_to_edit",
                                         "oracle_symbols_to_modify",
                                         "oracle_tests")):
            continue
        tasks.append(EditTask(
            id=str(entry.get("id") or "task"),
            task=str(entry["task"]),
            mode=str(entry.get("mode") or "edit"),
            budget=int(entry.get("budget") or 6000),
            oracle_files_likely_to_edit=list(entry.get("oracle_files_likely_to_edit", []) or []),
            oracle_files_read_only=list(entry.get("oracle_files_read_only", []) or []),
            oracle_tests=list(entry.get("oracle_tests", []) or []),
            oracle_symbols_to_modify=list(entry.get("oracle_symbols_to_modify", []) or []),
            expected_validation_types=list(entry.get("expected_validation_types", []) or []),
            risk_keywords=list(entry.get("risk_keywords", []) or []),
        ))
    return tasks


def _run_task(kb: CodeGraphKB, task: EditTask) -> EditTaskResult:
    started = time.perf_counter()
    pack = prepare_edit_context(kb, task.task, token_budget=task.budget)
    latency_ms = (time.perf_counter() - started) * 1000.0

    repo_root = kb.config.repo_path
    edit_files = [normalize_path(fe.file, repo_root) for fe in pack.files_likely_to_edit]
    read_files = [normalize_path(fe.file, repo_root) for fe in pack.files_to_read_only]
    tests = [normalize_path(te.file, repo_root) for te in pack.related_tests]
    syms = [se.symbol for se in pack.symbols_to_modify]
    oracle_edit_files = [normalize_path(p, repo_root) for p in task.oracle_files_likely_to_edit]
    oracle_read_files = [normalize_path(p, repo_root) for p in task.oracle_files_read_only]
    oracle_tests = [normalize_path(p, repo_root) for p in task.oracle_tests]

    edit_at_5 = _file_recall(edit_files, oracle_edit_files, 5, repo_root)
    read_prec_5 = _file_precision(read_files, oracle_read_files, 5, repo_root)
    test_at_5 = _file_recall(tests, oracle_tests, 5, repo_root)
    sym_at_8 = _symbol_recall(syms, task.oracle_symbols_to_modify, 8)

    val_types_returned = {c.type for c in pack.validation_commands}
    if task.expected_validation_types:
        hit = sum(1 for t in task.expected_validation_types if t in val_types_returned)
        val_recall = hit / len(task.expected_validation_types)
    else:
        val_recall = 1.0

    risk_text = " ".join(r.title + " " + r.reason for r in pack.risks).lower()
    if task.risk_keywords:
        hit = sum(1 for kw in task.risk_keywords if kw.lower() in risk_text)
        risk_recall = hit / len(task.risk_keywords)
    else:
        risk_recall = 1.0

    util = pack.audit.get("estimated_tokens", 0) / max(1, task.budget)

    missing_edit_files = [
        f for f in oracle_edit_files
        if not _any_file_match(edit_files, f, repo_root)
    ]
    missing_symbols = [
        s for s in task.oracle_symbols_to_modify
        if not any(_symbol_match(s, q) for q in syms)
    ]
    missing_validation = [
        t for t in task.expected_validation_types if t not in val_types_returned
    ]

    return EditTaskResult(
        id=task.id, task=task.task, mode=task.mode,
        edit_file_recall_at_5=edit_at_5,
        read_only_file_precision_at_5=read_prec_5,
        related_test_recall_at_5=test_at_5,
        symbol_recall_at_8=sym_at_8,
        validation_command_recall=val_recall,
        risk_keyword_recall=risk_recall,
        workflow_latency_ms=latency_ms,
        budget_utilization=util,
        retrieved_edit_files=edit_files[:10],
        retrieved_tests=tests[:10],
        retrieved_symbols=syms[:10],
        missing_edit_files=missing_edit_files,
        missing_symbols=missing_symbols,
        missing_validation_types=missing_validation,
        timing_ms=dict(pack.audit.get("timing_ms", {})),
    )


def _file_recall(retrieved: list[str], oracle: list[str], k: int,
                 repo_root: str | Path | None = None) -> float:
    if not oracle:
        return 1.0
    top = retrieved[:k]
    hits = sum(1 for o in oracle if _any_file_match(top, o, repo_root))
    return hits / len(oracle)


def _file_precision(retrieved: list[str], oracle: list[str], k: int,
                    repo_root: str | Path | None = None) -> float:
    if not retrieved:
        return 1.0
    top = retrieved[:k]
    if not top:
        return 1.0
    hits = sum(1 for r in top if any(_any_file_match([r], o, repo_root) for o in oracle))
    return hits / len(top)


def _symbol_recall(retrieved: list[str], oracle: list[str], k: int) -> float:
    if not oracle:
        return 1.0
    top = retrieved[:k]
    hits = sum(1 for o in oracle if any(_symbol_match(o, q) for q in top))
    return hits / len(oracle)


def _aggregate(dataset: str, repo_path: str,
               results: list[EditTaskResult]) -> EditEvalReport:
    if not results:
        return EditEvalReport(
            dataset=dataset, repo_path=repo_path, n_tasks=0,
            edit_file_recall_at_5=0.0, related_test_recall_at_5=0.0,
            symbol_recall_at_8=0.0, validation_command_recall=0.0,
            risk_keyword_recall=0.0, median_latency_ms=0.0, tasks=[],
            timing_summary_ms={},
        )
    return EditEvalReport(
        dataset=dataset, repo_path=repo_path, n_tasks=len(results),
        edit_file_recall_at_5=statistics.fmean(r.edit_file_recall_at_5 for r in results),
        related_test_recall_at_5=statistics.fmean(r.related_test_recall_at_5 for r in results),
        symbol_recall_at_8=statistics.fmean(r.symbol_recall_at_8 for r in results),
        validation_command_recall=statistics.fmean(r.validation_command_recall for r in results),
        risk_keyword_recall=statistics.fmean(r.risk_keyword_recall for r in results),
        median_latency_ms=statistics.median(r.workflow_latency_ms for r in results),
        tasks=results,
        timing_summary_ms=_timing_summary(results),
    )


def _timing_summary(results: list[EditTaskResult]) -> dict:
    stages: dict[str, list[float]] = {}
    slowest_task_id = ""
    slowest_task_ms = -1.0
    for result in results:
        total = float(result.timing_ms.get("total") or result.workflow_latency_ms)
        if total > slowest_task_ms:
            slowest_task_ms = total
            slowest_task_id = result.id
        for stage, value in result.timing_ms.items():
            stages.setdefault(stage, []).append(float(value))
    median_by_stage = {stage: statistics.median(values) for stage, values in stages.items()}
    p95_by_stage = {
        stage: sorted(values)[max(0, int(len(values) * 0.95) - 1)]
        for stage, values in stages.items()
    }
    slowest_stage = ""
    if median_by_stage:
        slowest_stage = max(
            (stage for stage in median_by_stage if stage != "total"),
            key=lambda stage: median_by_stage[stage],
            default="",
        )
    return {
        "slowest_task_id": slowest_task_id,
        "slowest_task_ms": slowest_task_ms,
        "slowest_stage": slowest_stage,
        "median_by_stage": median_by_stage,
        "p95_by_stage": p95_by_stage,
    }
