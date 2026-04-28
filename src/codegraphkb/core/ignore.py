"""gitignore-style path matching. Supports a small subset enough for repo scans."""
from __future__ import annotations

import fnmatch
from pathlib import Path

from codegraphkb.config import DEFAULT_IGNORE


class IgnoreRules:
    def __init__(self, patterns: list[str]):
        self.patterns = [p.strip() for p in patterns if p.strip() and not p.startswith("#")]

    @classmethod
    def from_repo(cls, repo_path: Path, extra: list[str] | None = None) -> "IgnoreRules":
        patterns = list(DEFAULT_IGNORE)
        gitignore = repo_path / ".gitignore"
        if gitignore.exists():
            try:
                patterns.extend(gitignore.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError:
                pass
        cgkb_ignore = repo_path / ".codegraphkbignore"
        if cgkb_ignore.exists():
            try:
                patterns.extend(cgkb_ignore.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError:
                pass
        if extra:
            patterns.extend(extra)
        return cls(patterns)

    def matches(self, rel_path: str, is_dir: bool = False) -> bool:
        rel = rel_path.replace("\\", "/")
        for raw in self.patterns:
            pat = raw.lstrip("/").rstrip()
            if not pat:
                continue
            negate = pat.startswith("!")
            if negate:
                continue  # negations not supported in MVP
            dir_only = pat.endswith("/")
            if dir_only:
                pat = pat.rstrip("/")
                if is_dir and (fnmatch.fnmatch(rel, pat) or _segment_match(rel, pat)):
                    return True
                if _segment_match(rel, pat):
                    return True
            else:
                if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(Path(rel).name, pat):
                    return True
                if _segment_match(rel, pat):
                    return True
        return False


def _segment_match(rel: str, pat: str) -> bool:
    """Match if any path segment equals the pattern (e.g., 'node_modules')."""
    if "/" in pat or "*" in pat or "?" in pat:
        return False
    parts = rel.split("/")
    return pat in parts
