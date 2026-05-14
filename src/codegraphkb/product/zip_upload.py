"""Safe ZIP extraction for uploaded repositories."""
from __future__ import annotations

import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from codegraphkb.product.models import InvalidRequestError, UploadTooLargeError
from codegraphkb.product.workspace import assert_inside_workspace, should_ignore_repo_entry


def extract_zip_safely(zip_file: Path, dest: Path, max_zip_mb: int) -> Path:
    archive = Path(zip_file).resolve()
    destination = Path(dest).resolve()
    max_bytes = max_zip_mb * 1024 * 1024
    if not archive.exists() or not archive.is_file():
        raise InvalidRequestError("Uploaded ZIP file was not found")
    if archive.stat().st_size > max_bytes:
        raise UploadTooLargeError(f"ZIP file is larger than {max_zip_mb} MB")

    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        for info in members:
            safe_name = _safe_zip_name(info)
            if not safe_name or safe_name.endswith("/"):
                continue
            if should_ignore_repo_entry(safe_name):
                continue
            target = (destination / safe_name).resolve()
            assert_inside_workspace(target, destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)

    return _repo_root_for_extraction(destination)


def _safe_zip_name(info: zipfile.ZipInfo) -> str:
    raw = info.filename.replace("\\", "/")
    if not raw or raw.endswith("/"):
        return raw
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if posix.is_absolute() or windows.is_absolute() or raw.startswith(("/", "\\")):
        raise InvalidRequestError("ZIP entries must use relative paths")
    parts = [p for p in posix.parts if p not in {"", "."}]
    if any(p == ".." for p in parts):
        raise InvalidRequestError("ZIP entries must not contain path traversal")
    mode = info.external_attr >> 16
    if stat.S_IFMT(mode) == stat.S_IFLNK:
        raise InvalidRequestError("ZIP symlinks are not allowed")
    return "/".join(parts)


def _repo_root_for_extraction(destination: Path) -> Path:
    entries = [p for p in destination.iterdir() if p.name != "__MACOSX"]
    dirs = [p for p in entries if p.is_dir()]
    files = [p for p in entries if p.is_file()]
    if len(dirs) == 1 and not files:
        return dirs[0].resolve()
    return destination

