"""Framework registry — runs language-specific detectors after structural parse.

Each detector receives the full structural ExtractResult plus the source text and
emits additional symbols/edges. Detectors are pure-Python and need no extra deps.
"""
from __future__ import annotations

from codegraphkb.core.extractors.base import FrameworkExtraction
from codegraphkb.core.parsers.base import ExtractResult
from codegraphkb.core.scanner import SourceFile


def enrich_extraction(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    if source.language == "python":
        return _enrich_python(source, extract)
    if source.language in ("javascript", "typescript"):
        return _enrich_js_ts(source, extract)
    return FrameworkExtraction()


def _enrich_python(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    from codegraphkb.core.extractors.python.fastapi import detect_fastapi
    from codegraphkb.core.extractors.python.flask import detect_flask
    from codegraphkb.core.extractors.python.pytest_extr import detect_pytest
    from codegraphkb.core.extractors.python.sqlalchemy import detect_sqlalchemy
    from codegraphkb.core.extractors.python.pydantic import detect_pydantic
    from codegraphkb.core.extractors.python.envvar import detect_env_vars
    from codegraphkb.core.extractors.python.constant_reads import detect_constant_reads
    from codegraphkb.core.extractors.python.config_reads import detect_config_reads

    out = FrameworkExtraction()
    for detect in (detect_fastapi, detect_flask, detect_pytest,
                   detect_sqlalchemy, detect_pydantic, detect_env_vars,
                   detect_constant_reads, detect_config_reads):
        partial = detect(source, extract)
        out.extra_symbols.extend(partial.extra_symbols)
        out.extra_edges.extend(partial.extra_edges)
        for fw in partial.detected_frameworks:
            if fw not in out.detected_frameworks:
                out.detected_frameworks.append(fw)
    return out


def _enrich_js_ts(source: SourceFile, extract: ExtractResult) -> FrameworkExtraction:
    from codegraphkb.core.extractors.js_ts.express import detect_express
    from codegraphkb.core.extractors.js_ts.fastify import detect_fastify
    from codegraphkb.core.extractors.js_ts.fetch_axios import detect_fetch_axios
    from codegraphkb.core.extractors.js_ts.nextjs import detect_nextjs
    from codegraphkb.core.extractors.js_ts.react_hooks import detect_react_hooks
    from codegraphkb.core.extractors.js_ts.jest_vitest import detect_jest_vitest
    from codegraphkb.core.extractors.js_ts.prisma import detect_prisma
    from codegraphkb.core.extractors.js_ts.envvar import detect_env_vars_js

    out = FrameworkExtraction()
    for detect in (detect_express, detect_fastify, detect_nextjs,
                   detect_react_hooks, detect_jest_vitest, detect_prisma,
                   detect_fetch_axios, detect_env_vars_js):
        partial = detect(source, extract)
        out.extra_symbols.extend(partial.extra_symbols)
        out.extra_edges.extend(partial.extra_edges)
        for fw in partial.detected_frameworks:
            if fw not in out.detected_frameworks:
                out.detected_frameworks.append(fw)
    return out
