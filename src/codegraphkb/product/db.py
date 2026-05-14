"""SQLite metadata database for product projects and index jobs."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from codegraphkb.product.settings import ProductSettings, load_settings


APP_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_indexed_at TEXT
);

CREATE TABLE IF NOT EXISTS index_jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL,
    progress_message TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    files_scanned INTEGER NOT NULL DEFAULT 0,
    files_indexed INTEGER NOT NULL DEFAULT 0,
    symbols INTEGER NOT NULL DEFAULT 0,
    edges INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_index_jobs_project_created ON index_jobs(project_id, created_at);
"""

_MEMORY_KEEPERS: dict[str, sqlite3.Connection] = {}


def initialize_app_db(settings: ProductSettings | None = None) -> None:
    settings = settings or load_settings()
    settings.app_dir.mkdir(parents=True, exist_ok=True)
    settings.workspace_dir.mkdir(parents=True, exist_ok=True)
    with connect(settings) as conn:
        conn.executescript(APP_SCHEMA)
        conn.commit()


def connect(settings: ProductSettings | None = None) -> sqlite3.Connection:
    settings = settings or load_settings()
    target = str(settings.app_db_path)
    uri = target.startswith("file:")
    if uri and "mode=memory" in target:
        _ensure_memory_keeper(target)
    elif target != ":memory:":
        path = settings.app_db_path
        if not isinstance(path, str):
            path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, uri=uri)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def app_db(settings: ProductSettings | None = None) -> Iterator[sqlite3.Connection]:
    initialize_app_db(settings)
    conn = connect(settings)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_memory_keeper(target: str) -> None:
    if target in _MEMORY_KEEPERS:
        return
    keeper = sqlite3.connect(target, uri=True)
    keeper.row_factory = sqlite3.Row
    keeper.execute("PRAGMA foreign_keys = ON")
    _MEMORY_KEEPERS[target] = keeper
