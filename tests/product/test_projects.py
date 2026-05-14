from __future__ import annotations

import pytest

from codegraphkb.product.db import initialize_app_db
from codegraphkb.product.models import ProjectNotFoundError
from codegraphkb.product.projects import (
    create_project,
    get_project,
    list_projects,
    update_project_status,
)
from codegraphkb.product.settings import load_settings


@pytest.fixture()
def product_env(workspace_tmp, monkeypatch: pytest.MonkeyPatch):
    app_dir = workspace_tmp / "app"
    monkeypatch.setenv("CODEGRAPHKB_APP_DIR", str(app_dir))
    monkeypatch.setenv("CODEGRAPHKB_WORKSPACE_DIR", str(app_dir / "workspaces"))
    monkeypatch.setenv("CODEGRAPHKB_APP_DB", f"file:{workspace_tmp.name}_app?mode=memory&cache=shared")
    settings = load_settings()
    initialize_app_db(settings)
    return settings


def test_project_records_can_be_created_listed_fetched_and_updated(product_env) -> None:
    workspace = product_env.workspace_dir / "repo-1"
    workspace.mkdir(parents=True)
    project = create_project(
        source_type="local_path",
        source_ref="fixture",
        workspace_path=workspace,
        name="Fixture",
        settings=product_env,
    )

    assert project.id
    fetched = get_project(project.id, settings=product_env)
    assert fetched.name == "Fixture"
    assert fetched.status == "created"
    assert list_projects(settings=product_env)[0].id == project.id

    update_project_status(project.id, "ready", settings=product_env)
    assert get_project(project.id, settings=product_env).status == "ready"


def test_get_project_rejects_unknown_id(product_env) -> None:
    with pytest.raises(ProjectNotFoundError):
        get_project("missing", settings=product_env)
