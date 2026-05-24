"""Tests for the user-facing artifact generator (PR 5 / Phase 4)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraphkb import CodeGraphKB
from codegraphkb.ux.artifacts import (
    ArtifactPaths,
    build_mcp_config,
    generate_artifacts,
)


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


def test_artifact_paths_under_default(tmp_path: Path) -> None:
    paths = ArtifactPaths.under(tmp_path)
    assert paths.out_dir == tmp_path / ".codegraphkb"
    assert paths.graph_json.name == "graph.json"
    assert paths.graph_html.name == "graph.html"
    assert paths.report.name == "GRAPH_REPORT.md"
    assert paths.mcp_config.name == "mcp.json"
    assert paths.edit_plan_example.name == "edit_plan_example.md"


def test_artifact_paths_custom_out(tmp_path: Path) -> None:
    out = tmp_path / "elsewhere"
    paths = ArtifactPaths.under(tmp_path, out_dir=out)
    assert paths.out_dir == out
    assert paths.graph_json.parent == out


def test_build_mcp_config_contains_absolute_repo_path(tmp_path: Path) -> None:
    config = build_mcp_config(tmp_path)
    server = config["mcpServers"]["codegraphkb"]
    assert server["command"] == "codegraph"
    assert "--repo" in server["args"]
    assert str(tmp_path.resolve()) in server["args"]


def test_generate_artifacts_writes_all_files_after_indexing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    result = generate_artifacts(kb, include_edit_plan_example=False)

    assert result.ok, f"unexpected skips: {result.skipped}"
    assert result.paths.report.exists()
    assert result.paths.graph_json.exists()
    assert result.paths.graph_html.exists()
    assert result.paths.mcp_config.exists()

    payload = json.loads(result.paths.graph_json.read_text(encoding="utf-8"))
    assert "metadata" in payload
    assert "nodes" in payload
    assert "edges" in payload

    html = result.paths.graph_html.read_text(encoding="utf-8")
    assert "vis-network" in html

    mcp = json.loads(result.paths.mcp_config.read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["codegraphkb"]["command"] == "codegraph"
    assert str(repo.resolve()) in mcp["mcpServers"]["codegraphkb"]["args"]

    report = result.paths.report.read_text(encoding="utf-8")
    assert "# Graph Report" in report


def test_generate_artifacts_respects_disable_flags(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)
    # kb.index() writes the report itself; remove so we can prove the flag is honored.
    if (repo / ".codegraphkb" / "GRAPH_REPORT.md").exists():
        (repo / ".codegraphkb" / "GRAPH_REPORT.md").unlink()

    result = generate_artifacts(
        kb,
        include_report=False,
        include_graph_json=True,
        include_graph_html=False,
        include_mcp=False,
        include_edit_plan_example=False,
    )

    assert result.paths.graph_json.exists()
    assert not result.paths.report.exists()
    assert not result.paths.graph_html.exists()
    assert not result.paths.mcp_config.exists()
    assert not result.paths.edit_plan_example.exists()


def test_generate_artifacts_writes_edit_plan_example(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)

    result = generate_artifacts(
        kb,
        include_report=False,
        include_graph_json=False,
        include_graph_html=False,
        include_mcp=False,
        include_edit_plan_example=True,
        edit_plan_task="Add refresh token rotation",
    )

    assert result.paths.edit_plan_example.exists(), result.skipped
    text = result.paths.edit_plan_example.read_text(encoding="utf-8")
    assert "Add refresh token rotation" in text
    assert "## Files likely to edit" in text


def test_generate_artifacts_uses_custom_out_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _build_python_repo(repo)
    kb = CodeGraphKB(repo)
    kb.index(force=True)
    out_dir = tmp_path / "elsewhere"

    result = generate_artifacts(
        kb,
        out_dir=out_dir,
        include_edit_plan_example=False,
    )

    assert out_dir.exists()
    assert (out_dir / "graph.json").exists()
    assert not (repo / ".codegraphkb" / "graph.json").exists()
    _ = result  # silence unused
