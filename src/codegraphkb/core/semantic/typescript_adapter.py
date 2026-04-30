"""TypeScript semantic adapter — wraps the Node helper at helpers/ts-semantic."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from codegraphkb.core.semantic.protocol import (
    SemanticFileResult,
    SemanticReference,
    SemanticResult,
    SemanticSymbol,
    SemanticTypeFact,
)


ADAPTER_ID = "typescript-compiler-api"
ADAPTER_LANGUAGE = "typescript"
ADAPTER_VERSION = "0.1.0"
DEFAULT_TIMEOUT_S = 120


@dataclass(frozen=True)
class HelperLocation:
    helper_path: Path
    package_dir: Path
    built: bool

    @property
    def reason(self) -> str:
        if not self.package_dir.exists():
            return "helpers/ts-semantic package not present"
        if not self.built:
            return (
                "helper not built; run `npm install && npm run build` "
                "in helpers/ts-semantic"
            )
        return ""


def find_helper(repo_path: str | Path | None = None) -> HelperLocation:
    """Locate the compiled helper.

    Search order:
      1. ``CODEGRAPHKB_TS_SEMANTIC_HELPER`` environment override.
      2. ``<repo>/helpers/ts-semantic/dist/index.js``.
      3. ``<package-root>/helpers/ts-semantic/dist/index.js`` (CodeGraphKB repo).
    """
    override = os.environ.get("CODEGRAPHKB_TS_SEMANTIC_HELPER")
    if override:
        helper = Path(override)
        return HelperLocation(
            helper_path=helper,
            package_dir=helper.parent.parent,
            built=helper.exists(),
        )
    candidates: list[Path] = []
    if repo_path is not None:
        candidates.append(Path(repo_path) / "helpers" / "ts-semantic")
    package_root = _package_root()
    if package_root is not None:
        candidates.append(package_root / "helpers" / "ts-semantic")
    for pkg in candidates:
        helper = pkg / "dist" / "index.js"
        if helper.exists():
            return HelperLocation(helper_path=helper, package_dir=pkg, built=True)
    # Default to the package-root candidate so the reason explains where to install.
    fallback_pkg = (
        candidates[-1]
        if candidates
        else Path.cwd() / "helpers" / "ts-semantic"
    )
    return HelperLocation(
        helper_path=fallback_pkg / "dist" / "index.js",
        package_dir=fallback_pkg,
        built=False,
    )


def _package_root() -> Path | None:
    """Walk up from this file to a directory containing ``helpers/ts-semantic``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "helpers" / "ts-semantic").exists():
            return parent
    return None


class TypeScriptSemanticAdapter:
    id = ADAPTER_ID
    language = ADAPTER_LANGUAGE
    precision_level = 3

    def __init__(self, *, node_bin: str | None = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        self.node_bin = node_bin or os.environ.get("CODEGRAPHKB_NODE_BIN") or "node"
        self.timeout_s = timeout_s

    # ----- discovery -----
    def helper(self, repo_path: str | Path | None = None) -> HelperLocation:
        return find_helper(repo_path)

    def node_available(self) -> bool:
        return shutil.which(self.node_bin) is not None

    def available(self, repo_path: str) -> bool:
        if not self.node_available():
            return False
        loc = self.helper(repo_path)
        return loc.built

    # ----- analysis -----
    def analyze_repo(self, repo_path: str, files: list[str]) -> SemanticResult:
        loc = self.helper(repo_path)
        if not loc.built:
            raise RuntimeError(f"TypeScript semantic helper not available: {loc.reason}")
        cmd = [self.node_bin, str(loc.helper_path), "--repo", str(repo_path), "--json"]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"TypeScript semantic helper timed out after {self.timeout_s}s"
            ) from exc
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip().splitlines()
            tail = "\n".join(stderr[-5:]) if stderr else "(no stderr)"
            raise RuntimeError(
                f"TypeScript semantic helper exited {proc.returncode}: {tail}"
            )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"TypeScript semantic helper produced invalid JSON: {exc}"
            ) from exc
        return _result_from_dict(payload)


def _result_from_dict(data: dict) -> SemanticResult:
    files: list[SemanticFileResult] = []
    for f in data.get("files", []):
        files.append(SemanticFileResult(
            path=f.get("path", ""),
            symbols=[
                SemanticSymbol(
                    id=s.get("id", ""),
                    name=s.get("name", ""),
                    kind=s.get("kind", ""),
                    qualified_name=s.get("qualified_name", ""),
                    signature=s.get("signature", ""),
                    return_type=s.get("return_type", ""),
                    start_line=int(s.get("start_line", 0) or 0),
                    end_line=int(s.get("end_line", 0) or 0),
                )
                for s in f.get("symbols", [])
            ],
            references=[
                SemanticReference(
                    from_symbol=r.get("from_symbol", ""),
                    to_symbol=r.get("to_symbol"),
                    edge_type=r.get("edge_type", ""),
                    receiver_type=r.get("receiver_type"),
                    call_form=r.get("call_form", ""),
                    confidence=float(r.get("confidence", 0.0) or 0.0),
                    precision_level=int(r.get("precision_level", 3) or 3),
                    reason=r.get("reason", ""),
                )
                for r in f.get("references", [])
            ],
            types=[
                SemanticTypeFact(
                    owner_symbol=t.get("owner_symbol", ""),
                    name=t.get("name", ""),
                    kind=t.get("kind", ""),
                    declared_type=t.get("declared_type", ""),
                    inferred_type=t.get("inferred_type", ""),
                )
                for t in f.get("types", [])
            ],
        ))
    return SemanticResult(
        language=data.get("language", ADAPTER_LANGUAGE),
        adapter=data.get("adapter", ADAPTER_ID),
        adapter_version=data.get("adapter_version", ADAPTER_VERSION),
        repo_path=data.get("repo_path", ""),
        files=files,
        diagnostics=data.get("diagnostics", []) or [],
    )
