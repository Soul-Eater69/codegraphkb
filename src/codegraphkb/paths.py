"""Path normalization helpers used at eval/report boundaries."""
from __future__ import annotations

import re
from pathlib import Path


_DRIVE_RE = re.compile(r"^[A-Za-z]:/")


def normalize_path(value: str | Path | None, repo_root: str | Path | None = None) -> str:
    """Return a stable repo-relative POSIX-ish path when possible.

    The eval datasets store POSIX relative paths. Runtime paths may be POSIX,
    Windows-relative, absolute Windows paths, or absolute POSIX paths. This
    helper normalizes separators, strips a matching repo root, collapses
    leading ``./`` segments, and lowercases Windows drive letters.
    """
    if value is None:
        return ""
    raw = str(value).strip().replace("\\", "/")
    if not raw:
        return ""
    raw = re.sub(r"/+", "/", raw)
    if _DRIVE_RE.match(raw):
        raw = raw[0].lower() + raw[1:]

    root = ""
    if repo_root is not None:
        root = str(repo_root).strip().replace("\\", "/")
        root = re.sub(r"/+", "/", root).rstrip("/")
        if _DRIVE_RE.match(root):
            root = root[0].lower() + root[1:]
        if root and (raw == root or raw.startswith(root + "/")):
            raw = raw[len(root):].lstrip("/")

    while raw.startswith("./"):
        raw = raw[2:]
    return raw.strip("/")


def file_matches(retrieved_path: str | Path | None, oracle_path: str | Path | None,
                 repo_root: str | Path | None = None) -> bool:
    retrieved = normalize_path(retrieved_path, repo_root)
    oracle = normalize_path(oracle_path, repo_root)
    if not retrieved or not oracle:
        return False
    if retrieved == oracle:
        return True
    if retrieved.endswith("/" + oracle) or oracle.endswith("/" + retrieved):
        return True
    retrieved_name = retrieved.rsplit("/", 1)[-1]
    oracle_name = oracle.rsplit("/", 1)[-1]
    return retrieved_name == oracle_name and (oracle in retrieved or retrieved in oracle)
