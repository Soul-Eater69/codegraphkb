"""Python production provider, currently backed by the existing AST parser."""
from __future__ import annotations

from codegraphkb.core.languages.common import ResolutionContext, SyntaxParseResult
from codegraphkb.core.parsers.base import ExtractResult
from codegraphkb.core.parsers.registry import PYTHON_AST_VERSION
from codegraphkb.core.parsers.python_parser import parse_python
from codegraphkb.core.scanner import SourceFile


class PythonLanguageProvider:
    id = "python"
    language_id = "python"
    extensions = (".py", ".pyi")

    def detect(self, file_path: str) -> bool:
        return file_path.endswith(self.extensions)

    def can_parse(self, path: str) -> bool:
        return self.detect(path)

    def parse_syntax(self, source_file: SourceFile) -> SyntaxParseResult:
        return SyntaxParseResult(
            language=self.id,
            backend="ast",
            backend_version=str(PYTHON_AST_VERSION),
            source_file=source_file,
        )

    def extract_symbols(self, source_file: SourceFile,
                        syntax: SyntaxParseResult) -> ExtractResult:
        return parse_python(source_file)

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
