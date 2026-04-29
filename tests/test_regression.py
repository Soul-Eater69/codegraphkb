"""Regression-report tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from click.testing import CliRunner

from codegraphkb import CodeGraphKB
from codegraphkb.cli import cli
from codegraphkb.regression import (
    SCHEMA_VERSION,
    build_regression_report,
    render_markdown,
    write_report_files,
)


FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_regression_report_writes_json_and_markdown(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    CodeGraphKB(repo).index()

    dataset = tmp_path / "tasks.yaml"
    dataset.write_text(
        "- id: retrieval_smoke\n"
        "  task: \"How does idea card upload work?\"\n"
        "  mode: explain\n"
        "  budget: 3000\n"
        "  oracle_files:\n"
        "    - services.py\n"
        "  oracle_symbols:\n"
        "    - process_upload\n"
        "- id: edit_smoke\n"
        "  task: \"Update process_upload behavior\"\n"
        "  mode: edit\n"
        "  budget: 3000\n"
        "  oracle_files_likely_to_edit:\n"
        "    - services.py\n"
        "  oracle_symbols_to_modify:\n"
        "    - process_upload\n",
        encoding="utf-8",
    )

    report = build_regression_report(
        repo,
        eval_dataset=dataset,
        edit_eval_dataset=dataset,
        compare_modes=["bm25"],
    )

    assert report.schema_version == SCHEMA_VERSION
    assert "bm25" in report.retrieval_reports
    assert report.edit_workflow_report is not None
    assert report.run_environment["repo_root"]
    assert report.index_state["indexed_file_count"] >= 2
    assert report.dataset_state["retrieval"]["task_ids"] == ["retrieval_smoke"]
    assert report.workflow_state["mode"] == "edit"
    assert report.passed
    assert render_markdown(report).startswith("# CodeGraphKB Regression Report")

    json_path = tmp_path / "reports" / "latest.json"
    md_path = tmp_path / "reports" / "latest.md"
    write_report_files(report, json_path=json_path, markdown_path=md_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["passed"] is True
    assert "Edit Workflow" in md_path.read_text(encoding="utf-8")


def test_doctor_json_cli_reports_index_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    CodeGraphKB(repo).index()

    result = CliRunner().invoke(cli, ["doctor", str(repo), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["repo_root"]
    assert payload["indexed_file_count"] >= 2
    assert "embedding_load_state" in payload
