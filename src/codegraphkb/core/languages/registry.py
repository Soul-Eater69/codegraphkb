"""Production language-provider registry with graceful fallback."""
from __future__ import annotations

from dataclasses import dataclass

from codegraphkb.core.languages.provider import LanguageProvider
from codegraphkb.core.languages.python import PythonLanguageProvider
from codegraphkb.core.languages.typescript import TypeScriptLanguageProvider
from codegraphkb.core.parsers.registry import ParserBackend
from codegraphkb.core.scanner import SourceFile


@dataclass(frozen=True)
class ProviderChoice:
    provider_id: str
    parser_backend: str
    parser_version: str
    fallback_used: bool = False
    warning: str = ""


class LanguageProviderRegistry:
    def __init__(self, providers: list[LanguageProvider]):
        self.providers = providers

    @classmethod
    def default(cls, parser_backend: ParserBackend = ParserBackend.AUTO) -> "LanguageProviderRegistry":
        return cls([
            PythonLanguageProvider(),
            TypeScriptLanguageProvider(backend=parser_backend),
        ])

    def provider_for_source(self, source: SourceFile) -> LanguageProvider | None:
        for provider in self.providers:
            if source.language == provider.id or provider.detect(source.rel_path):
                return provider
        return None

    def parse_and_extract(self, source: SourceFile) -> tuple:
        provider = self.provider_for_source(source)
        if provider is None:
            from codegraphkb.core.parsers.base import ExtractResult
            return ExtractResult(symbols=[], edges=[]), ProviderChoice(
                provider_id="none",
                parser_backend="none",
                parser_version="1",
                fallback_used=True,
                warning=f"No provider for language `{source.language}`.",
            )
        syntax = provider.parse_syntax(source)
        extraction = provider.extract_symbols(source, syntax)
        return extraction, ProviderChoice(
            provider_id=provider.id,
            parser_backend=syntax.backend,
            parser_version=syntax.backend_version,
        )
