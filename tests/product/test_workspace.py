from __future__ import annotations

from pathlib import Path

import pytest

from codegraphkb.product.models import InvalidRequestError
from codegraphkb.product.settings import ProductSettings
from codegraphkb.product.workspace import (
    assert_inside_workspace,
    count_repo_files,
    create_project_workspace,
    enforce_repo_limits,
)


def _settings(tmp_path: Path) -> ProductSettings:
    return ProductSettings(
        app_dir=tmp_path / "app",
        workspace_dir=tmp_path / "app" / "workspaces",
        app_db_path=tmp_path / "app" / "app.sqlite",
    )


def test_create_project_workspace_stays_under_root(workspace_tmp: Path) -> None:
    settings = _settings(workspace_tmp)
    workspace = create_project_workspace("project-1", settings=settings)
    assert workspace.exists()
    assert settings.workspace_dir.resolve() in workspace.resolve().parents


def test_assert_inside_workspace_rejects_escape(workspace_tmp: Path) -> None:
    root = workspace_tmp / "root"
    root.mkdir()
    with pytest.raises(InvalidRequestError):
        assert_inside_workspace(workspace_tmp / "outside", root)


def test_repo_limits_count_files_and_reject_large_files(workspace_tmp: Path) -> None:
    repo = workspace_tmp / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "ignored.js").write_text("x", encoding="utf-8")
    assert count_repo_files(repo) == 1

    enforce_repo_limits(repo, max_files=1, max_file_mb=1)
    (repo / "big.py").write_bytes(b"x" * 1025)
    with pytest.raises(InvalidRequestError):
        enforce_repo_limits(repo, max_files=5, max_file_mb=0)

    with pytest.raises(InvalidRequestError):
        enforce_repo_limits(repo, max_files=1, max_file_mb=1)
