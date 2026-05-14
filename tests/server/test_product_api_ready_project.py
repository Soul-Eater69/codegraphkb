from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # type: ignore  # noqa: E402

from codegraphkb.product import jobs  # noqa: E402
from codegraphkb.product.db import initialize_app_db  # noqa: E402
from codegraphkb.product.projects import create_project, get_project  # noqa: E402
from codegraphkb.product.settings import load_settings  # noqa: E402
from codegraphkb.server.product_api import build_product_app  # noqa: E402


@pytest.fixture()
def product_client(workspace_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app_dir = workspace_tmp / "app"
    monkeypatch.setenv("CODEGRAPHKB_APP_DIR", str(app_dir))
    monkeypatch.setenv("CODEGRAPHKB_WORKSPACE_DIR", str(app_dir / "workspaces"))
    monkeypatch.setenv("CODEGRAPHKB_APP_DB", f"file:{workspace_tmp.name}_ready?mode=memory&cache=shared")
    initialize_app_db(load_settings())
    return TestClient(build_product_app())


def _build_ready_project() -> str:
    settings = load_settings()
    repo = settings.workspace_dir / "ready-python-repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "app.py").write_text(
        "def normalize_user(email: str) -> str:\n"
        "    return email.strip().lower()\n\n"
        "def create_user(email: str) -> dict:\n"
        "    normalized = normalize_user(email)\n"
        "    return {\"email\": normalized, \"active\": True}\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_app.py").write_text(
        "from app import create_user\n\n"
        "def test_create_user_normalizes_email():\n"
        "    user = create_user('A@EXAMPLE.COM')\n"
        "    assert user['email'] == 'a@example.com'\n",
        encoding="utf-8",
    )
    project = create_project(
        source_type="local_path",
        source_ref="fixture",
        workspace_path=repo,
        settings=settings,
    )
    job = jobs.create_index_job(project.id, settings=settings)
    jobs.run_index_job(job.id, project.id, force=True, settings=settings)
    assert get_project(project.id, settings=settings).status == "ready"
    return project.id


def test_ready_project_files_symbols_stats_and_graph_summary(
    product_client: TestClient,
) -> None:
    project_id = _build_ready_project()

    stats = product_client.get(f"/projects/{project_id}/stats")
    assert stats.status_code == 200
    stats_payload = stats.json()
    assert stats_payload["files"] >= 2
    assert stats_payload["symbols"] >= 3
    assert stats_payload["edges"] >= 1

    files = product_client.get(f"/projects/{project_id}/files")
    assert files.status_code == 200
    assert any(row["path"] == "app.py" for row in files.json()["files"])

    symbols = product_client.get(f"/projects/{project_id}/symbols")
    assert symbols.status_code == 200
    qnames = {row["qualified_name"] for row in symbols.json()["symbols"]}
    assert "app.create_user" in qnames
    assert "app.normalize_user" in qnames

    graph = product_client.get(f"/projects/{project_id}/graph/summary")
    assert graph.status_code == 200
    assert graph.json()["node_count"] > 0
    assert graph.json()["edge_count"] > 0


def test_ready_project_ask_context_only_and_prepare_edit(
    product_client: TestClient,
) -> None:
    project_id = _build_ready_project()

    ask = product_client.post(
        f"/projects/{project_id}/ask",
        json={"question": "How does create_user normalize email?", "context_only": True},
    )
    assert ask.status_code == 200
    ask_payload = ask.json()
    assert ask_payload["items"]
    assert any("create_user" in item["title"] for item in ask_payload["items"])

    prepare = product_client.post(
        f"/projects/{project_id}/prepare-edit",
        json={"task": "Update create_user to include an id field"},
    )
    assert prepare.status_code == 200
    prepare_payload = prepare.json()
    assert prepare_payload["context_pack"]
    assert prepare_payload["files_likely_to_edit"] or prepare_payload["warnings"]
