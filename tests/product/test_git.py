from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codegraphkb.product.git import clone_public_repo, validate_public_github_url
from codegraphkb.product.models import InvalidRequestError


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/owner/repo", "https://github.com/owner/repo"),
        ("https://github.com/owner/repo.git", "https://github.com/owner/repo"),
    ],
)
def test_validate_public_github_url_accepts_https_repo(url: str, expected: str) -> None:
    assert validate_public_github_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:owner/repo.git",
        "ssh://github.com/owner/repo",
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com/owner/repo/tree/main",
    ],
)
def test_validate_public_github_url_rejects_unsupported_urls(url: str) -> None:
    with pytest.raises(InvalidRequestError):
        validate_public_github_url(url)


def test_clone_public_repo_uses_shallow_clone_without_shell(
    workspace_tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    dest = workspace_tmp / "repo"
    clone_public_repo("https://github.com/owner/repo.git", dest)

    cmd, kwargs = calls[0]
    assert cmd == ["git", "clone", "--depth", "1", "https://github.com/owner/repo", str(dest.resolve())]
    assert kwargs["check"] is True
    assert kwargs["timeout"] == 120
    assert "shell" not in kwargs
