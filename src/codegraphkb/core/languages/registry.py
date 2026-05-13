"""Production language-provider registry with graceful fallback."""
from __future__ import annotations

from dataclasses import dataclass

from codegraphkb.core.languages.java import JavaLanguageProvider
from codegraphkb.core.languages.provider import LanguageProvider
from codegraphkb.core.languages.python import PythonLanguageProvider
from codegraphkb.core.languages.typescript import TypeScriptLanguageProvider
from codegraphkb.core.parsers.registry import ParserBackend, is_treesitter_available
from codegraphkb.core.scanner import SourceFile


@dataclass(frozen=True)
class ProviderChoice:
    provider_id: str
    parser_backend: str        # actual backend that ran (e.g. "ast", "tree-sitter", "regex")
    parser_version: str
    preferred_backend: str = "auto"  # what was requested ("auto" | "tree-sitter" | "regex" | "ast")
    fallback_used: bool = False
    warning: str = ""

    @property
    def signature(self) -> str:
        return f"{self.provider_id}:{self.parser_backend}:{self.parser_version}"


class LanguageProviderRegistry:
    def __init__(self, providers: list[LanguageProvider],
                 parser_backend: ParserBackend = ParserBackend.AUTO):
        self.providers = providers
        self.parser_backend = parser_backend

    @classmethod
    def default(cls, parser_backend: ParserBackend = ParserBackend.AUTO) -> "LanguageProviderRegistry":
        return cls(
            [
                PythonLanguageProvider(),
                TypeScriptLanguageProvider(backend=parser_backend),
                JavaLanguageProvider(),
            ],
            parser_backend=parser_backend,
        )

    def provider_for_source(self, source: SourceFile) -> LanguageProvider | None:
        for provider in self.providers:
            if source.language == provider.id or provider.detect(source.rel_path):
                return provider
        return None

    def diagnostics(self) -> dict:
        """Return per-provider status for doctor reports."""
        out: dict = {}
        for provider in self.providers:
            entry = {
                "syntax_provider": provider.id,
                "parser_backend": _expected_parser_backend(provider.id, self.parser_backend),
                "semantic_backend": _semantic_backend_id(provider.id),
                "semantic_available": False,
                "status": "syntax-only",
            }
            out[provider.id] = entry
        return out

    def parse_and_extract(self, source: SourceFile) -> tuple:
        provider = self.provider_for_source(source)
        if provider is None:
            from codegraphkb.core.parsers.base import ExtractResult
            return ExtractResult(symbols=[], edges=[]), ProviderChoice(
                provider_id="none",
                parser_backend="none",
                parser_version="1",
                preferred_backend=self.parser_backend.value,
                fallback_used=True,
                warning=f"No provider for language `{source.language}`.",
            )
        syntax = provider.parse_syntax(source)
        extraction = provider.extract_symbols(source, syntax)

        preferred = self.parser_backend.value
        actual_backend = syntax.backend
        fallback_used = False
        warning = ""
        if source.language in ("javascript", "typescript"):
            if self.parser_backend == ParserBackend.AUTO and actual_backend == "regex":
                # AUTO preferred tree-sitter; fell back to regex.
                fallback_used = True
                warning = "tree-sitter unavailable; used regex fallback"
        return extraction, ProviderChoice(
            provider_id=provider.id,
            parser_backend=actual_backend,
            parser_version=syntax.backend_version,
            preferred_backend=preferred,
            fallback_used=fallback_used,
            warning=warning,
        )


def _expected_parser_backend(provider_id: str, backend: ParserBackend) -> str:
    if provider_id == "python":
        return "ast"
    if provider_id == "java":
        return "regex"
    if backend == ParserBackend.REGEX:
        return "regex"
    if backend == ParserBackend.TREESITTER:
        return "tree-sitter"
    return "tree-sitter" if is_treesitter_available() else "regex"


def _semantic_backend_id(provider_id: str) -> str:
    return {
        "typescript": "typescript-compiler-api",
        "python": "pyright/basedpyright",
    }.get(provider_id, "")
