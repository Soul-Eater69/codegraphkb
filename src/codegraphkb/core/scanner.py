"""Repository scanner: walks files, applies ignore rules, classifies languages."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from codegraphkb.config import MAX_FILE_BYTES, SECRET_FILES
from codegraphkb.core.ignore import IgnoreRules

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".sql": "sql",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
}

TEXT_LIKE = {"python", "javascript", "typescript", "java", "go", "rust", "ruby",
             "php", "csharp", "kotlin", "swift", "sql", "markdown", "json", "yaml", "toml"}


@dataclass
class SourceFile:
    rel_path: str
    abs_path: Path
    language: str
    content: str
    content_hash: str
    size_bytes: int


def detect_language(path: Path) -> str | None:
    return LANGUAGE_BY_EXT.get(path.suffix.lower())


def is_probably_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    # Heuristic: high ratio of non-text bytes
    text_chars = bytes(range(32, 127)) + b"\n\r\t\b"
    nontext = sum(1 for b in sample if b not in text_chars)
    return (nontext / len(sample)) > 0.30


def scan_repo(
    repo_path: Path,
    languages: Iterable[str] | None = None,
    follow_symlinks: bool = False,
) -> Iterator[SourceFile]:
    repo_path = repo_path.resolve()
    ignore = IgnoreRules.from_repo(repo_path)
    wanted = set(languages) if languages else None

    def walk(directory: Path) -> Iterator[Path]:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            try:
                rel = entry.relative_to(repo_path).as_posix()
            except ValueError:
                continue
            if entry.is_symlink() and not follow_symlinks:
                continue
            if entry.is_dir():
                if ignore.matches(rel, is_dir=True):
                    continue
                yield from walk(entry)
            else:
                if ignore.matches(rel, is_dir=False):
                    continue
                yield entry

    for path in walk(repo_path):
        if path.name in SECRET_FILES:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_FILE_BYTES:
            continue
        language = detect_language(path)
        if language is None:
            continue
        if wanted is not None and language not in wanted:
            continue
        try:
            with path.open("rb") as fh:
                head = fh.read(4096)
                if is_probably_binary(head):
                    continue
                rest = fh.read()
            raw = head + rest
            content = raw.decode("utf-8", errors="replace")
        except OSError:
            continue
        rel_path = path.relative_to(repo_path).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        yield SourceFile(
            rel_path=rel_path,
            abs_path=path,
            language=language,
            content=content,
            content_hash=digest,
            size_bytes=size,
        )
