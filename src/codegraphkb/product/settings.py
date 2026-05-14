"""Runtime settings for local-first product services."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProductSettings:
    app_dir: Path
    workspace_dir: Path
    app_db_path: Path | str
    max_zip_mb: int = 50
    max_repo_files: int = 10000
    max_file_mb: int = 2
    allow_private_github: bool = False


def load_settings() -> ProductSettings:
    app_dir = Path(os.getenv("CODEGRAPHKB_APP_DIR", ".codegraphkb_app")).resolve()
    workspace_dir = Path(
        os.getenv("CODEGRAPHKB_WORKSPACE_DIR", str(app_dir / "workspaces"))
    ).resolve()
    raw_db_path = os.getenv("CODEGRAPHKB_APP_DB")
    if raw_db_path and (raw_db_path == ":memory:" or raw_db_path.startswith("file:")):
        app_db_path: Path | str = raw_db_path
    else:
        app_db_path = Path(raw_db_path or str(app_dir / "app.sqlite")).resolve()
    return ProductSettings(
        app_dir=app_dir,
        workspace_dir=workspace_dir,
        app_db_path=app_db_path,
        max_zip_mb=int(os.getenv("CODEGRAPHKB_MAX_ZIP_MB", "50")),
        max_repo_files=int(os.getenv("CODEGRAPHKB_MAX_REPO_FILES", "10000")),
        max_file_mb=int(os.getenv("CODEGRAPHKB_MAX_FILE_MB", "2")),
        allow_private_github=os.getenv("CODEGRAPHKB_ALLOW_PRIVATE_GITHUB", "false").lower()
        == "true",
    )
