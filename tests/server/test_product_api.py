from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # type: ignore  # noqa: E402

from codegraphkb.product.db import initialize_app_db  # noqa: E402
from codegraphkb.product.projects import create_project  # noqa: E402
from codegraphkb.product.settings import load_settings  # noqa: E402
from codegraphkb.server.product_api import build_product_app  # noqa: E402


@pytest.fixture()
def product_client(workspace_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app_dir = workspace_tmp / "app"
    monkeypatch.setenv("CODEGRAPHKB_APP_DIR", str(app_dir))
    monkeypatch.setenv("CODEGRAPHKB_WORKSPACE_DIR", str(app_dir / "workspaces"))
    monkeypatch.setenv("CODEGRAPHKB_APP_DB", f"file:{workspace_tmp.name}_api?mode=memory&cache=shared")
    initialize_app_db(load_settings())
    return TestClient(build_product_app())


def test_product_health(product_client: TestClient) -> None:
    resp = product_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "version": "0.1.0"}


def test_upload_zip_project_queues_index_job(
    product_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("codegraphkb.server.product_api.jobs.run_index_job", lambda *args, **kwargs: None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("repo/app.py", "def hello():\n    return 'hi'\n")
    resp = product_client.post(
        "/projects/upload",
        data={"name": "Uploaded"},
        files={"file": ("repo.zip", buf.getvalue(), "application/zip")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["project_id"]
    assert payload["status"] == "indexing"
    assert payload["job_id"]


def test_create_github_project_queues_index_job(
    product_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("codegraphkb.server.product_api.clone_public_repo", lambda url, dest: None)
    monkeypatch.setattr("codegraphkb.server.product_api.jobs.run_index_job", lambda *args, **kwargs: None)
    resp = product_client.post(
        "/projects/github",
        json={"url": "https://github.com/owner/repo.git", "name": "Repo"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["project_id"]
    assert payload["status"] == "importing"
    assert payload["job_id"]


def test_ask_returns_409_if_project_not_ready(
    product_client: TestClient,
) -> None:
    settings = load_settings()
    repo = settings.workspace_dir / "repo"
    repo.mkdir(parents=True)
    project = create_project(
        source_type="local_path",
        source_ref="fixture",
        workspace_path=repo,
        settings=settings,
    )
    resp = product_client.post(
        f"/projects/{project.id}/ask",
        json={"question": "How does auth work?"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"


def test_prepare_edit_returns_409_if_project_not_ready(
    product_client: TestClient,
) -> None:
    settings = load_settings()
    repo = settings.workspace_dir / "repo2"
    repo.mkdir(parents=True)
    project = create_project(
        source_type="local_path",
        source_ref="fixture",
        workspace_path=repo,
        settings=settings,
    )
    resp = product_client.post(
        f"/projects/{project.id}/prepare-edit",
        json={"task": "Add refresh token rotation"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PROJECT_NOT_READY"
