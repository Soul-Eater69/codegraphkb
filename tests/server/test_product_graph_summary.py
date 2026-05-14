from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # type: ignore  # noqa: E402

from codegraphkb import CodeGraphKB  # noqa: E402
from codegraphkb.product.db import initialize_app_db  # noqa: E402
from codegraphkb.product.projects import create_project  # noqa: E402
from codegraphkb.product.settings import load_settings  # noqa: E402
from codegraphkb.server.product_api import build_product_app  # noqa: E402


@pytest.fixture()
def product_client(workspace_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app_dir = workspace_tmp / "app"
    monkeypatch.setenv("CODEGRAPHKB_APP_DIR", str(app_dir))
    monkeypatch.setenv("CODEGRAPHKB_WORKSPACE_DIR", str(app_dir / "workspaces"))
    monkeypatch.setenv("CODEGRAPHKB_APP_DB", f"file:{workspace_tmp.name}_graph?mode=memory&cache=shared")
    initialize_app_db(load_settings())
    return TestClient(build_product_app())


def test_product_graph_summary_works_for_ready_indexed_project(
    product_client: TestClient,
) -> None:
    settings = load_settings()
    repo = settings.workspace_dir / "ready-repo"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text(
        "def helper():\n"
        "    return 'hi'\n\n"
        "def hello():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    CodeGraphKB(repo).index(force=True)
    project = create_project(
        source_type="local_path",
        source_ref="fixture",
        workspace_path=repo,
        status="ready",
        settings=settings,
    )

    resp = product_client.get(f"/projects/{project.id}/graph/summary")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["metadata"]["view"] == "full"
    assert payload["node_count"] > 0
    assert payload["edge_count"] > 0
