"""Safe workspace helpers for cloned and uploaded repositories."""
from __future__ import annotations

from pathlib import Path

from codegraphkb.product.models import InvalidRequestError
from codegraphkb.product.settings import ProductSettings, load_settings


IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "target",
}

IGNORED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "secrets.json",
}

IGNORED_EXTENSIONS = {
    ".pem",
    ".key",
    ".crt",
    ".cert",
    ".p12",
    ".pfx",
}


def create_project_workspace(
    project_id: str,
    *,
    settings: ProductSettings | None = None,
) -> Path:
    settings = settings or load_settings()
    root = settings.workspace_dir.resolve()
    workspace = (root / project_id).resolve()
    assert_inside_workspace(workspace, root)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def assert_inside_workspace(path: Path, workspace_root: Path) -> None:
    root = workspace_root.resolve()
    candidate = Path(path).resolve()
    if candidate != root and root not in candidate.parents:
        raise InvalidRequestError(f"Path `{candidate}` is outside workspace root")


def count_repo_files(path: Path) -> int:
    root = Path(path).resolve()
    if not root.exists():
        return 0
    count = 0
    for child in root.rglob("*"):
        if _is_ignored_path(child, root):
            continue
        if child.is_file():
            count += 1
    return count


def enforce_repo_limits(path: Path, max_files: int, max_file_mb: int) -> None:
    root = Path(path).resolve()
    if not root.exists() or not root.is_dir():
        raise InvalidRequestError(f"Repository workspace `{root}` does not exist")
    max_bytes = max_file_mb * 1024 * 1024
    file_count = 0
    for child in root.rglob("*"):
        if _is_ignored_path(child, root):
            continue
        if child.is_symlink():
            raise InvalidRequestError(f"Symlinks are not allowed in workspaces: {child.name}")
        if not child.is_file():
            continue
        file_count += 1
        if file_count > max_files:
            raise InvalidRequestError(f"Repository has more than {max_files} files")
        if child.stat().st_size > max_bytes:
            raise InvalidRequestError(
                f"File `{_safe_rel(child, root)}` is larger than {max_file_mb} MB"
            )


def should_ignore_repo_entry(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/")
    if not normalized:
        return False
    parts = [p for p in normalized.split("/") if p]
    if any(p in IGNORED_DIR_NAMES for p in parts[:-1]):
        return True
    name = parts[-1]
    lower_name = name.lower()
    if lower_name in IGNORED_FILE_NAMES:
        return True
    return Path(lower_name).suffix in IGNORED_EXTENSIONS


def _is_ignored_path(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    parts = rel.parts
    if any(p in IGNORED_DIR_NAMES for p in parts):
        return True
    if not parts:
        return False
    name = parts[-1].lower()
    if name in IGNORED_FILE_NAMES:
        return True
    return Path(name).suffix in IGNORED_EXTENSIONS


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name

