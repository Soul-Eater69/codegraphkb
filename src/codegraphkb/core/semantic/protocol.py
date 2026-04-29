"""Semantic adapter protocol and JSON result contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SemanticSymbol:
    id: str
    name: str
    kind: str
    qualified_name: str
    signature: str = ""
    return_type: str = ""
    start_line: int = 0
    end_line: int = 0


@dataclass
class SemanticReference:
    from_symbol: str
    to_symbol: str | None
    edge_type: str
    receiver_type: str | None = None
    call_form: str = ""
    confidence: float = 0.0
    precision_level: int = 3
    reason: str = ""


@dataclass
class SemanticTypeFact:
    owner_symbol: str
    name: str
    kind: str
    declared_type: str = ""
    inferred_type: str = ""


@dataclass
class SemanticFileResult:
    path: str
    symbols: list[SemanticSymbol] = field(default_factory=list)
    references: list[SemanticReference] = field(default_factory=list)
    types: list[SemanticTypeFact] = field(default_factory=list)


@dataclass
class SemanticResult:
    language: str
    adapter: str
    adapter_version: str
    repo_path: str
    files: list[SemanticFileResult] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "repo_path": self.repo_path,
            "files": [
                {
                    "path": f.path,
                    "symbols": [vars(s) for s in f.symbols],
                    "references": [vars(r) for r in f.references],
                    "types": [vars(t) for t in f.types],
                }
                for f in self.files
            ],
            "diagnostics": self.diagnostics,
        }


class SemanticAdapter(Protocol):
    id: str
    language: str
    precision_level: int

    def available(self, repo_path: str) -> bool:
        ...

    def analyze_repo(self, repo_path: str, files: list[str]) -> SemanticResult:
        ...
