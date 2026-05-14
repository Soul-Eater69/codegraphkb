"""Public GitHub clone support for product projects."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from codegraphkb.product.models import InvalidRequestError

_GITHUB_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def validate_public_github_url(url: str) -> str:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise InvalidRequestError("Only HTTPS GitHub URLs are supported")
    if parsed.netloc.lower() != "github.com":
        raise InvalidRequestError("Only github.com repositories are supported")
    if parsed.username or parsed.password or parsed.params or parsed.query or parsed.fragment:
        raise InvalidRequestError("GitHub URL must not include credentials, query, or fragment")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2:
        raise InvalidRequestError("GitHub URL must be https://github.com/owner/repo")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo or not _GITHUB_NAME_RE.match(owner) or not _GITHUB_NAME_RE.match(repo):
        raise InvalidRequestError("GitHub owner or repo name is malformed")
    return f"https://github.com/{owner}/{repo}"


def clone_public_repo(url: str, dest: Path, *, timeout: int = 120) -> None:
    clean_url = validate_public_github_url(url)
    destination = Path(dest).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", clean_url, str(destination)],
            check=True,
            timeout=timeout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise InvalidRequestError("GitHub clone timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise InvalidRequestError(f"GitHub clone failed: {detail[:500]}") from exc

