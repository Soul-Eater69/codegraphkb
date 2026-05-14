"""Small public language-provider contract.

The production providers in this package expose a richer set of hooks, but
new language MVPs only need the stable parse result shape below. Keeping this
contract tiny makes it straightforward to add one provider file plus tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from codegraphkb.core.parsers.base import ExtractResult
from codegraphkb.core.scanner import SourceFile


@dataclass
class LanguageProviderResult:
    extract: ExtractResult
    parser_backend: str
    parser_version: str
    warnings: list[str] = field(default_factory=list)


class BasicLanguageProvider(Protocol):
    language_id: str
    extensions: set[str]

    def can_parse(self, path: str) -> bool:
        ...

    def parse(self, source: SourceFile) -> LanguageProviderResult:
        ...
