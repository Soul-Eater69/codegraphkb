from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from codegraphkb.product.models import InvalidRequestError, UploadTooLargeError
from codegraphkb.product.zip_upload import extract_zip_safely


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return path


def test_normal_zip_extracts_and_returns_single_top_level_folder(workspace_tmp: Path) -> None:
    archive = _zip(workspace_tmp / "repo.zip", {"repo/src/app.py": b"print('ok')\n"})
    dest = workspace_tmp / "workspace"
    repo_root = extract_zip_safely(archive, dest, max_zip_mb=1)
    assert repo_root == (dest / "repo").resolve()
    assert (repo_root / "src" / "app.py").exists()


def test_zip_path_traversal_is_rejected(workspace_tmp: Path) -> None:
    archive = _zip(workspace_tmp / "evil.zip", {"../evil.py": b"bad"})
    with pytest.raises(InvalidRequestError):
        extract_zip_safely(archive, workspace_tmp / "workspace", max_zip_mb=1)


def test_zip_absolute_path_is_rejected(workspace_tmp: Path) -> None:
    archive = _zip(workspace_tmp / "evil.zip", {"/abs/evil.py": b"bad"})
    with pytest.raises(InvalidRequestError):
        extract_zip_safely(archive, workspace_tmp / "workspace", max_zip_mb=1)


def test_zip_over_size_limit_is_rejected(workspace_tmp: Path) -> None:
    archive = _zip(workspace_tmp / "large.zip", {"repo/a.py": b"x" * 2048})
    with pytest.raises(UploadTooLargeError):
        extract_zip_safely(archive, workspace_tmp / "workspace", max_zip_mb=0)


def test_zip_symlink_is_rejected(workspace_tmp: Path) -> None:
    archive = workspace_tmp / "link.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("repo/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "target")
    with pytest.raises(InvalidRequestError):
        extract_zip_safely(archive, workspace_tmp / "workspace", max_zip_mb=1)
