"""TypeScript/JavaScript provider backed by current tree-sitter/regex parsers."""
from __future__ import annotations

from codegraphkb.core.languages.common import ResolutionContext, SyntaxParseResult
from codegraphkb.core.parsers.base import ExtractResult
from codegraphkb.core.parsers.registry import (
    REGEX_JS_VERSION,
    TREESITTER_JS_VERSION,
    ParserBackend,
    parse,
)
from codegraphkb.core.scanner import SourceFile


class TypeScriptLanguageProvider:
    id = "typescript"
    extensions = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

    def __init__(self, backend: ParserBackend = ParserBackend.AUTO):
        self.backend = backend

    def detect(self, file_path: str) -> bool:
        return file_path.endswith(self.extensions)

    def parse_syntax(self, source_file: SourceFile) -> SyntaxParseResult:
        extraction, choice = parse(source_file, backend=self.backend)
        version = TREESITTER_JS_VERSION if choice.backend == "tree-sitter" else REGEX_JS_VERSION
        return SyntaxParseResult(
            language=source_file.language,
            backend=choice.backend,
            backend_version=str(version),
            source_file=source_file,
            extraction=extraction,
        )

    def extract_symbols(self, source_file: SourceFile,
                        syntax: SyntaxParseResult) -> ExtractResult:
        if syntax.extraction is not None:
            return syntax.extraction
        extraction, _ = parse(source_file, backend=self.backend)
        return extraction

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
