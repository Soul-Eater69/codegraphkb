"""Common production language-provider contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codegraphkb.core.parsers.base import ExtractResult
from codegraphkb.core.scanner import SourceFile


@dataclass(frozen=True)
class LanguageId:
    id: str
    extensions: tuple[str, ...]


@dataclass
class SyntaxParseResult:
    language: str
    backend: str
    backend_version: str
    source_file: SourceFile
    tree: Any = None
    extraction: ExtractResult | None = None
    diagnostics: list[dict] = field(default_factory=list)


@dataclass
class ResolutionContext:
    repo_path: str
    source_file: SourceFile
    syntax: SyntaxParseResult
    extraction: ExtractResult
    files: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedImport:
    source_symbol: str
    imported_name: str
    target_symbol: str | None
    confidence: float
    precision_level: int
    reason: str


@dataclass
class ResolvedCall:
    from_symbol: str
    to_symbol: str | None
    dst_name: str
    confidence: float
    precision_level: int
    reason: str


@dataclass
class TypeFact:
    owner_symbol: str
    name: str
    kind: str
    declared_type: str = ""
    inferred_type: str = ""
    confidence: float = 0.0
    precision_level: int = 1


@dataclass
class FrameworkFact:
    owner_symbol: str
    kind: str
    name: str
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class TestFact:
    test_symbol: str
    target_symbol: str | None
    confidence: float
    reason: str


@dataclass
class ProcessFact:
    id: str
    label: str
    process_type: str
    steps: list[str]
    confidence: float
