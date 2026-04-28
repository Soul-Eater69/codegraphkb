"""Configuration constants and defaults for CodeGraphKB."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

INDEX_DIR_NAME = ".codegraphkb"
DB_FILE = "graph.sqlite"
REPORT_FILE = "GRAPH_REPORT.md"
CONFIG_FILE = "config.json"

DEFAULT_TOKEN_BUDGET = 8000

# Roughly 4 chars per token — same heuristic Anthropic publishes for English.
CHARS_PER_TOKEN = 4

DEFAULT_IGNORE = [
    ".git/",
    ".hg/",
    ".svn/",
    "node_modules/",
    "__pycache__/",
    ".venv/",
    "venv/",
    "env/",
    "dist/",
    "build/",
    ".next/",
    ".cache/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "target/",
    "*.min.js",
    "*.min.css",
    "*.lock",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    INDEX_DIR_NAME + "/",
]

# Files larger than this are skipped (likely generated / not useful for graph).
MAX_FILE_BYTES = 1_000_000

# Secret patterns — refuse to index files matching these names verbatim.
SECRET_FILES = {".env", ".env.local", ".env.production", "credentials.json", "secrets.json"}


@dataclass
class IndexConfig:
    repo_path: Path
    index_dir: Path
    languages: list[str] = field(default_factory=lambda: ["python", "javascript", "typescript"])
    follow_symlinks: bool = False

    @classmethod
    def for_repo(cls, repo_path: str | Path) -> "IndexConfig":
        repo = Path(repo_path).resolve()
        return cls(repo_path=repo, index_dir=repo / INDEX_DIR_NAME)

    @property
    def db_path(self) -> Path:
        return self.index_dir / DB_FILE

    @property
    def report_path(self) -> Path:
        return self.index_dir / REPORT_FILE
