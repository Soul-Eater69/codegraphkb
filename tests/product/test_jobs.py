from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from codegraphkb.product.db import initialize_app_db
from codegraphkb.product.jobs import create_index_job, get_index_job, latest_job_for_project, run_index_job
from codegraphkb.product.projects import create_project, get_project
from codegraphkb.product.settings import load_settings


@pytest.fixture()
def product_env(workspace_tmp: Path, monkeypatch: pytest.MonkeyPatch):
    app_dir = workspace_tmp / "app"
    monkeypatch.setenv("CODEGRAPHKB_APP_DIR", str(app_dir))
    monkeypatch.setenv("CODEGRAPHKB_WORKSPACE_DIR", str(app_dir / "workspaces"))
    monkeypatch.setenv("CODEGRAPHKB_APP_DB", f"file:{workspace_tmp.name}_jobs?mode=memory&cache=shared")
    settings = load_settings()
    initialize_app_db(settings)
    return settings


@dataclass
class _Stats:
    files_scanned: int = 2
    files_indexed: int = 1
    symbols: int = 3
    edges: int = 4


def test_run_index_job_marks_success(product_env, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = product_env.workspace_dir / "repo"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    project = create_project(
        source_type="local_path",
        source_ref="fixture",
        workspace_path=repo,
        settings=product_env,
    )
    job = create_index_job(project.id, settings=product_env)

    class DummyKB:
        def __init__(self, workspace):
            self.workspace = workspace

        def index(self, **kwargs):
            kwargs["progress"]("halfway")
            return _Stats()

    monkeypatch.setattr("codegraphkb.product.jobs.CodeGraphKB", DummyKB)
    run_index_job(job.id, project.id, force=True, settings=product_env)

    saved = get_index_job(job.id, settings=product_env)
    assert saved.status == "succeeded"
    assert saved.files_scanned == 2
    assert latest_job_for_project(project.id, settings=product_env).id == job.id
    assert get_project(project.id, settings=product_env).status == "ready"


def test_run_index_job_captures_failure(product_env, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = product_env.workspace_dir / "repo"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
    project = create_project(
        source_type="local_path",
        source_ref="fixture",
        workspace_path=repo,
        settings=product_env,
    )
    job = create_index_job(project.id, settings=product_env)

    class FailingKB:
        def __init__(self, workspace):
            self.workspace = workspace

        def index(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr("codegraphkb.product.jobs.CodeGraphKB", FailingKB)
    run_index_job(job.id, project.id, settings=product_env)

    saved = get_index_job(job.id, settings=product_env)
    assert saved.status == "failed"
    assert "boom" in saved.error_message
    assert get_project(project.id, settings=product_env).status == "failed"
