"""Java production provider, backed by the regex Java parser.

A tree-sitter or JDT-backed semantic adapter can plug in later — the
provider interface already exposes ``resolve_imports`` / ``resolve_calls``
hooks for that.
"""
from __future__ import annotations

from codegraphkb.core.languages.common import ResolutionContext, SyntaxParseResult
from codegraphkb.core.parsers.base import ExtractResult
from codegraphkb.core.parsers.java_parser import JAVA_PARSER_VERSION, parse_java
from codegraphkb.core.scanner import SourceFile


class JavaLanguageProvider:
    id = "java"
    language_id = "java"
    extensions = (".java",)

    def detect(self, file_path: str) -> bool:
        return file_path.endswith(self.extensions)

    def can_parse(self, path: str) -> bool:
        return self.detect(path)

    def parse_syntax(self, source_file: SourceFile) -> SyntaxParseResult:
        return SyntaxParseResult(
            language=self.id,
            backend="regex",
            backend_version=str(JAVA_PARSER_VERSION),
            source_file=source_file,
        )

    def extract_symbols(self, source_file: SourceFile,
                        syntax: SyntaxParseResult) -> ExtractResult:
        return parse_java(source_file)

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
