"""Phase 4 regression reporting.

This module composes the retrieval and edit-workflow eval harnesses into one
machine-readable report for CI. It intentionally keeps gates conservative:
hard failures protect the edit loop that Phase 3 already made useful, while
retrieval quality targets are warnings until Phase 4 closes them.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from codegraphkb import eval as eval_mod
from codegraphkb import eval_edit as eval_edit_mod
from codegraphkb.api import CodeGraphKB
from codegraphkb.diagnostics import (
    collect_doctor_report,
    collect_run_environment,
    compact_index_state,
)


SCHEMA_VERSION = "codegraph_regression_report.v1"


@dataclass
class GateResult:
    metric: str
    actual: float
    threshold: float
    comparator: str
    severity: str
    passed: bool
    message: str


@dataclass
class RegressionReport:
    schema_version: str
    generated_at: str
    repo_path: str
    eval_dataset: str | None
    edit_eval_dataset: str | None
    compare_modes: list[str]
    retrieval_reports: dict[str, dict] = field(default_factory=dict)
    edit_workflow_report: dict | None = None
    run_environment: dict = field(default_factory=dict)
    index_state: dict = field(default_factory=dict)
    dataset_state: dict = field(default_factory=dict)
    workflow_state: dict = field(default_factory=dict)
    gate_profile: str = "release"
    hard_gates: list[GateResult] = field(default_factory=list)
    warnings: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.hard_gates)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def build_regression_report(
    repo_path: str | Path,
    *,
    eval_dataset: Path | None = None,
    edit_eval_dataset: Path | None = None,
    compare_modes: list[str] | None = None,
    gate_profile: str = "release",
) -> RegressionReport:
    modes = compare_modes or ["bm25", "hybrid"]
    retrieval_reports: dict[str, dict] = {}
    repo_label = str(Path(repo_path).resolve())
    kb = CodeGraphKB(repo_path)
    doctor = collect_doctor_report(kb)

    if eval_dataset is not None:
        for mode in modes:
            report = eval_mod.evaluate(repo_path, eval_dataset, retrieval_mode=mode)
            retrieval_reports[mode] = report.to_dict()
            repo_label = report.repo_path

    edit_report_dict = None
    if edit_eval_dataset is not None:
        edit_report = eval_edit_mod.evaluate_edit(repo_path, edit_eval_dataset)
        edit_report_dict = edit_report.to_dict()
        repo_label = edit_report.repo_path

    report = RegressionReport(
        schema_version=SCHEMA_VERSION,
        generated_at=datetime.now(timezone.utc).isoformat(),
        repo_path=repo_label,
        eval_dataset=str(eval_dataset) if eval_dataset else None,
        edit_eval_dataset=str(edit_eval_dataset) if edit_eval_dataset else None,
        compare_modes=modes,
        retrieval_reports=retrieval_reports,
        edit_workflow_report=edit_report_dict,
        run_environment=collect_run_environment(repo_path),
        index_state=compact_index_state(doctor),
        dataset_state=_dataset_state(eval_dataset, edit_eval_dataset),
        workflow_state={
            "mode": "edit",
            "budget": 6000,
            "retrieval": "auto",
            "compare_modes": modes,
            "top_k": 5,
        },
        gate_profile=gate_profile,
    )
    report.hard_gates = _hard_gates(edit_report_dict, gate_profile)
    report.warnings = _warning_gates(retrieval_reports, edit_report_dict, modes, gate_profile)
    return report


def write_report_files(
    report: RegressionReport,
    *,
    json_path: Path | None = None,
    markdown_path: Path | None = None,
) -> None:
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(report.to_json() + "\n", encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")


def render_markdown(report: RegressionReport) -> str:
    lines = [
        "# CodeGraphKB Regression Report",
        "",
        f"- Generated: `{report.generated_at}`",
        f"- Repo: `{report.repo_path}`",
        f"- Status: **{'PASS' if report.passed else 'FAIL'}**",
        f"- Gate profile: `{report.gate_profile}`",
        "",
    ]

    if report.run_environment or report.index_state or report.dataset_state:
        lines.extend([
            "## Baseline Diagnostics",
            "",
            "| Area | Signal | Value |",
            "|---|---|---|",
        ])
        env = report.run_environment
        idx = report.index_state
        data = report.dataset_state
        lines.extend([
            f"| environment | Python | `{env.get('python_version', '')}` |",
            f"| environment | Platform | `{env.get('platform', '')}` |",
            f"| environment | Git SHA | `{env.get('git_sha', '')}` |",
            f"| environment | Dirty worktree | `{env.get('dirty_worktree', False)}` |",
            f"| index | DB | `{idx.get('db_path', '')}` |",
            f"| index | Parser | `{idx.get('parser_backend', '')}` |",
            f"| index | Embedding model | `{idx.get('embedding_model', '')}` |",
            f"| index | Stub embeddings | `{idx.get('embedding_stub_mode', False)}` |",
            f"| index | Files / symbols / edges | `{idx.get('indexed_file_count', 0)} / "
            f"{idx.get('symbol_count', 0)} / {idx.get('edge_count', 0)}` |",
            f"| dataset | Retrieval tasks | `{data.get('retrieval', {}).get('task_count', 0)}` |",
            f"| dataset | Edit tasks | `{data.get('edit', {}).get('task_count', 0)}` |",
        ])
        lines.append("")

    if report.retrieval_reports:
        lines.extend([
            "## Retrieval",
            "",
            "| Mode | File recall@8 | Symbol recall@12 | Irrelevant ratio | Median latency |",
            "|---|---:|---:|---:|---:|",
        ])
        for mode in report.compare_modes:
            r = report.retrieval_reports.get(mode)
            if not r:
                continue
            lines.append(
                f"| `{mode}` | {_fmt(r['file_recall_at_8'])} | "
                f"{_fmt(r['symbol_recall_at_12'])} | {_fmt(r['irrelevant_ratio'])} | "
                f"{r['median_latency_ms']:.0f} ms |"
            )
        lines.append("")

    if report.edit_workflow_report:
        e = report.edit_workflow_report
        lines.extend([
            "## Edit Workflow",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Edit file recall@5 | {_fmt(e['edit_file_recall_at_5'])} |",
            f"| Related test recall@5 | {_fmt(e['related_test_recall_at_5'])} |",
            f"| Symbol recall@8 | {_fmt(e['symbol_recall_at_8'])} |",
            f"| Validation command recall | {_fmt(e['validation_command_recall'])} |",
            f"| Risk keyword recall | {_fmt(e['risk_keyword_recall'])} |",
            f"| Median workflow latency | {e['median_latency_ms']:.0f} ms |",
            "",
        ])
        timing = e.get("timing_summary_ms") or {}
        slowest = timing.get("slowest_stage")
        if slowest:
            lines.extend([
                "## Workflow Timing",
                "",
                f"- Slowest task: `{timing.get('slowest_task_id', '')}`",
                f"- Slowest stage: `{slowest}`",
                "",
                "| Stage | Median ms | P95 ms |",
                "|---|---:|---:|",
            ])
            med = timing.get("median_by_stage", {})
            p95 = timing.get("p95_by_stage", {})
            for stage in sorted(med):
                lines.append(f"| `{stage}` | {med[stage]:.0f} | {p95.get(stage, 0.0):.0f} |")
            lines.append("")

    lines.extend(_gate_section("Hard Gates", report.hard_gates))
    lines.extend(_gate_section("Warnings", report.warnings))
    return "\n".join(lines).rstrip() + "\n"


def summary_text(report: RegressionReport) -> str:
    hard_failed = [g for g in report.hard_gates if not g.passed]
    warning_failed = [g for g in report.warnings if not g.passed]
    status = "PASS" if report.passed else "FAIL"
    return (
        f"CodeGraphKB regression report: {status}\n"
        f"  gate profile:  {report.gate_profile}\n"
        f"  hard failures: {len(hard_failed)}\n"
        f"  warnings:      {len(warning_failed)}"
    )


def _hard_gates(edit_report: dict | None, gate_profile: str = "release") -> list[GateResult]:
    if not edit_report:
        return []
    profile = _gate_profile(gate_profile)
    if not profile["hard_fail"]:
        return []
    return [
        _min_gate(
            "edit_file_recall_at_5",
            edit_report["edit_file_recall_at_5"],
            profile["edit_file_recall_min"],
            "hard",
            "Edit file recall@5 must stay >= 0.80.",
        ),
        _min_gate(
            "related_test_recall_at_5",
            edit_report["related_test_recall_at_5"],
            profile["related_test_recall_min"],
            "hard",
            "Related test recall@5 must stay >= 0.80.",
        ),
        _max_gate(
            "median_workflow_latency_ms",
            edit_report["median_latency_ms"],
            profile["median_workflow_latency_max_ms"],
            "hard",
            "Median edit-workflow latency must stay <= 700 ms.",
        ),
    ]


def _warning_gates(
    retrieval_reports: dict[str, dict],
    edit_report: dict | None,
    compare_modes: list[str],
    gate_profile: str = "release",
) -> list[GateResult]:
    gates: list[GateResult] = []
    profile = _gate_profile(gate_profile)
    retrieval = _primary_retrieval_report(retrieval_reports, compare_modes)
    if retrieval:
        gates.extend([
            _min_gate(
                "file_recall_at_8",
                retrieval["file_recall_at_8"],
                0.90,
                "warning",
                "Retrieval file recall@8 target is >= 0.90.",
            ),
            _min_gate(
                "symbol_recall_at_12",
                retrieval["symbol_recall_at_12"],
                0.70,
                "warning",
                "Retrieval symbol recall@12 target is >= 0.70.",
            ),
            _max_gate(
                "irrelevant_ratio",
                retrieval["irrelevant_ratio"],
                0.35,
                "warning",
                "Retrieval irrelevant ratio target is <= 0.35.",
            ),
        ])
    if edit_report:
        gates.extend([
            _min_gate(
                "symbol_recall_at_8",
                edit_report["symbol_recall_at_8"],
                profile["symbol_recall_min"],
                "warning",
                "Edit symbol recall@8 target is profile-specific.",
            ),
            _min_gate(
                "risk_keyword_recall",
                edit_report["risk_keyword_recall"],
                0.60,
                "warning",
                "Risk keyword recall target is >= 0.60.",
            ),
        ])
    return gates


def _dataset_state(eval_dataset: Path | None, edit_eval_dataset: Path | None) -> dict:
    return {
        "retrieval": _retrieval_dataset_state(eval_dataset) if eval_dataset else {},
        "edit": _edit_dataset_state(edit_eval_dataset) if edit_eval_dataset else {},
    }


def _retrieval_dataset_state(path: Path) -> dict:
    tasks = eval_mod.load_dataset(path)
    return {
        "dataset_path": str(path),
        "task_count": len(tasks),
        "task_ids": [t.id for t in tasks],
        "oracle_file_count": sum(len(t.oracle_files) for t in tasks),
        "oracle_symbol_count": sum(len(t.oracle_symbols) for t in tasks),
    }


def _edit_dataset_state(path: Path) -> dict:
    tasks = eval_edit_mod._load_dataset(path)
    return {
        "dataset_path": str(path),
        "task_count": len(tasks),
        "task_ids": [t.id for t in tasks],
        "oracle_file_count": sum(len(t.oracle_files_likely_to_edit) + len(t.oracle_tests)
                                 for t in tasks),
        "oracle_symbol_count": sum(len(t.oracle_symbols_to_modify) for t in tasks),
    }


def _gate_profile(name: str) -> dict:
    profiles = {
        "advisory": {
            "hard_fail": False,
            "edit_file_recall_min": 0.0,
            "related_test_recall_min": 0.0,
            "symbol_recall_min": 0.0,
            "median_workflow_latency_max_ms": float("inf"),
        },
        "dev": {
            "hard_fail": True,
            "edit_file_recall_min": 0.60,
            "related_test_recall_min": 0.60,
            "symbol_recall_min": 0.50,
            "median_workflow_latency_max_ms": 5000.0,
        },
        "release": {
            "hard_fail": True,
            "edit_file_recall_min": 0.80,
            "related_test_recall_min": 0.80,
            "symbol_recall_min": 0.70,
            "median_workflow_latency_max_ms": 700.0,
        },
    }
    return profiles.get(name, profiles["release"])


def _primary_retrieval_report(
    retrieval_reports: dict[str, dict],
    compare_modes: list[str],
) -> dict | None:
    if "hybrid" in retrieval_reports:
        return retrieval_reports["hybrid"]
    for mode in reversed(compare_modes):
        if mode in retrieval_reports:
            return retrieval_reports[mode]
    return None


def _min_gate(metric: str, actual: float, threshold: float,
              severity: str, message: str) -> GateResult:
    return GateResult(
        metric=metric,
        actual=float(actual),
        threshold=float(threshold),
        comparator=">=",
        severity=severity,
        passed=actual >= threshold,
        message=message,
    )


def _max_gate(metric: str, actual: float, threshold: float,
              severity: str, message: str) -> GateResult:
    return GateResult(
        metric=metric,
        actual=float(actual),
        threshold=float(threshold),
        comparator="<=",
        severity=severity,
        passed=actual <= threshold,
        message=message,
    )


def _gate_section(title: str, gates: list[GateResult]) -> list[str]:
    lines = [f"## {title}", ""]
    if not gates:
        lines.extend(["_(none)_", ""])
        return lines
    lines.extend([
        "| Status | Severity | Metric | Actual | Gate |",
        "|---|---|---|---:|---:|",
    ])
    for g in gates:
        status = "PASS" if g.passed else "FAIL"
        lines.append(
            f"| {status} | {g.severity} | `{g.metric}` | {_fmt(g.actual)} | "
            f"{g.comparator} {_fmt(g.threshold)} |"
        )
    lines.append("")
    return lines


def _fmt(value: float) -> str:
    return f"{value:.2f}"
