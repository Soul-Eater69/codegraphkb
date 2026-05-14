"""Go provider backed by the lightweight regex parser."""
from __future__ import annotations

from codegraphkb.core.languages.common import ResolutionContext, SyntaxParseResult
from codegraphkb.core.parsers.base import ExtractResult
from codegraphkb.core.parsers.go_parser import GO_PARSER_VERSION, parse_go
from codegraphkb.core.scanner import SourceFile


class GoLanguageProvider:
    id = "go"
    language_id = "go"
    extensions = (".go",)

    def detect(self, file_path: str) -> bool:
        return file_path.endswith(self.extensions)

    def can_parse(self, path: str) -> bool:
        return self.detect(path)

    def parse_syntax(self, source_file: SourceFile) -> SyntaxParseResult:
        return SyntaxParseResult(
            language=self.id,
            backend="regex",
            backend_version=str(GO_PARSER_VERSION),
            source_file=source_file,
        )

    def extract_symbols(self, source_file: SourceFile,
                        syntax: SyntaxParseResult) -> ExtractResult:
        return parse_go(source_file)

    def resolve_imports(self, ctx: ResolutionContext) -> list:
        return []

    def resolve_calls(self, ctx: ResolutionContext) -> list:
        return []

    def extract_types(self, ctx: ResolutionContext) -> list:
        return []

    def extract_framework_facts(self, ctx: ResolutionContext) -> list:
        return []

    def extract_tests(self, ctx: ResolutionContext) -> list:
        return []

    def build_processes(self, ctx: ResolutionContext) -> list:
        return []
