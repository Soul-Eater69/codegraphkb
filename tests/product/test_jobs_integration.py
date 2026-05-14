from __future__ import annotations

from pathlib import Path

import pytest

from codegraphkb.product.db import initialize_app_db
from codegraphkb.product.jobs import create_index_job, get_index_job, run_index_job
from codegraphkb.product.projects import create_project, get_project
from codegraphkb.product.settings import load_settings


@pytest.fixture()
def product_env(workspace_tmp: Path, monkeypatch: pytest.MonkeyPatch):
    app_dir = workspace_tmp / "app"
    monkeypatch.setenv("CODEGRAPHKB_APP_DIR", str(app_dir))
    monkeypatch.setenv("CODEGRAPHKB_WORKSPACE_DIR", str(app_dir / "workspaces"))
    monkeypatch.setenv("CODEGRAPHKB_APP_DB", f"file:{workspace_tmp.name}_jobs_integration?mode=memory&cache=shared")
    settings = load_settings()
    initialize_app_db(settings)
    return settings


def test_run_index_job_indexes_real_project(product_env) -> None:
    repo = product_env.workspace_dir / "repo"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text(
        "def helper(name: str) -> str:\n"
        "    return name.upper()\n\n"
        "def greet(name: str) -> str:\n"
        "    return helper(name)\n",
        encoding="utf-8",
    )
    project = create_project(
        source_type="local_path",
        source_ref="fixture",
        workspace_path=repo,
        settings=product_env,
    )
    job = create_index_job(project.id, settings=product_env)

    run_index_job(job.id, project.id, force=True, settings=product_env)

    saved = get_index_job(job.id, settings=product_env)
    assert saved.status == "succeeded"
    assert saved.files_indexed >= 1
    assert saved.symbols >= 2
    assert saved.edges >= 1

    saved_project = get_project(project.id, settings=product_env)
    assert saved_project.status == "ready"
    assert saved_project.last_indexed_at
