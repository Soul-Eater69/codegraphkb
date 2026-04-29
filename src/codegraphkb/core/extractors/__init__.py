"""Framework-aware extractors. Run after the structural parse to enrich
the graph with semantic objects (Route, Component, TestBlock, Model, EnvVar, ...)
and framework-specific edges (ROUTE_HANDLED_BY, TESTS_SYMBOL, READS_ENV_VAR, ...)."""
from codegraphkb.core.extractors.base import (
    EXTENSION_LANG, FrameworkObjectKind, FrameworkExtraction,
)
from codegraphkb.core.extractors.framework_registry import enrich_extraction

__all__ = [
    "FrameworkObjectKind",
    "FrameworkExtraction",
    "enrich_extraction",
    "EXTENSION_LANG",
]
