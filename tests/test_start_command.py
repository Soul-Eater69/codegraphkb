"""Tests for `codegraph start` and start_local_experience (PR 3 / Phase 2)."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from codegraphkb.cli import cli
from codegraphkb.ux.start import start_local_experience


def _build_python_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "app.py").write_text(
        "def authenticate_user(email: str, password: str) -> bool:\n"
        "    return email == 'demo@example.com' and password == 'secret'\n\n"
        "def login(email: str, password: str) -> str:\n"
        "    if authenticate_user(email, password):\n"
        "        return 'token'\n"
        "    raise ValueError('invalid')\n",
        encoding="utf-8",
    )


def test_start_local_experience_indexes_and_generates_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)

    messages: list[str] = []
    result = start_local_experience(
        repo,
        host="127.0.0.1",
        port=9999,
        open_browser=False,
        start_server=False,
        register_project=False,
        on_message=messages.append,
    )

    assert result.server_started is False
    assert result.repo == repo.resolve()
    assert result.host == "127.0.0.1"
    assert result.port == 9999
    assert result.index_stats is not None
    assert result.index_stats["symbols"] > 0

    assert result.artifact_paths.graph_json.exists()
    assert result.artifact_paths.graph_html.exists()
    assert result.artifact_paths.report.exists()
    assert result.artifact_paths.mcp_config.exists()

    summary_text = "\n".join(result.lines)
    assert "CodeGraphKB ready." in summary_text
    assert "http://127.0.0.1:9999" in summary_text
    assert "Try:" in summary_text


def test_start_local_experience_no_index_skips_indexing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)
    # Pre-index so artifacts can still generate.
    from codegraphkb import CodeGraphKB

    CodeGraphKB(repo).index(force=True)

    result = start_local_experience(
        repo,
        no_index=True,
        open_browser=False,
        start_server=False,
        register_project=False,
    )

    assert result.index_stats is None
    assert result.artifact_paths.graph_json.exists()


def test_start_local_experience_rejects_missing_repo(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        start_local_experience(
            tmp_path / "does-not-exist",
            open_browser=False,
            start_server=False,
            register_project=False,
        )


def test_start_cli_no_serve_runs_to_completion(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["start", str(repo), "--no-serve", "--no-browser", "--semantic", "none"],
    )

    assert result.exit_code == 0, result.output
    assert "CodeGraphKB ready." in result.output
    assert (repo / ".codegraphkb" / "graph.json").exists()
    assert (repo / ".codegraphkb" / "mcp.json").exists()
