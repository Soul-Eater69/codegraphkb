"""Language provider protocol."""
from __future__ import annotations

from typing import Protocol

from codegraphkb.core.parsers.base import ExtractResult
from codegraphkb.core.scanner import SourceFile
from codegraphkb.core.languages.common import (
    FrameworkFact,
    ProcessFact,
    ResolutionContext,
    ResolvedCall,
    ResolvedImport,
    SyntaxParseResult,
    TestFact,
    TypeFact,
)


class LanguageProvider(Protocol):
    id: str
    language_id: str
    extensions: tuple[str, ...]

    def detect(self, file_path: str) -> bool:
        ...

    def can_parse(self, path: str) -> bool:
        ...

    def parse_syntax(self, source_file: SourceFile) -> SyntaxParseResult:
        ...

    def extract_symbols(self, source_file: SourceFile,
                        syntax: SyntaxParseResult) -> ExtractResult:
        ...

    def resolve_imports(self, ctx: ResolutionContext) -> list[ResolvedImport]:
        ...

    def resolve_calls(self, ctx: ResolutionContext) -> list[ResolvedCall]:
        ...

    def extract_types(self, ctx: ResolutionContext) -> list[TypeFact]:
        ...

    def extract_framework_facts(self, ctx: ResolutionContext) -> list[FrameworkFact]:
        ...

    def extract_tests(self, ctx: ResolutionContext) -> list[TestFact]:
        ...

    def build_processes(self, ctx: ResolutionContext) -> list[ProcessFact]:
        ...
