"""Indexing pipeline: scan -> parse -> persist (graph + capsules + search index)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from codegraphkb.config import IndexConfig
from codegraphkb.core.aliases import build_alias_text
from codegraphkb.core.capsules import build_symbol_capsule
from codegraphkb.core.extractors import enrich_extraction
from codegraphkb.core.graph_schema import PrecisionLevel
from codegraphkb.core.languages import LanguageProviderRegistry
from codegraphkb.core.parsers import ParserBackend, parse
from codegraphkb.core.scanner import scan_repo
from codegraphkb.core.store import GraphStore
from codegraphkb.versioning import (
    CAPSULE_VERSION, SCHEMA_VERSION, parser_signature,
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_indexed: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    files_reparsed_for_version: int = 0
    symbols: int = 0
    edges: int = 0
    parser_backends: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.parser_backends is None:
            self.parser_backends = {}


def index_repository(config: IndexConfig, force: bool = False,
                     progress=None,
                     parser_backend: ParserBackend = ParserBackend.AUTO,
                     embedder=None) -> IndexStats:
    """Index a repo into the graph store.

    Re-indexes a file when:
      - its content hash changed, OR
      - the parser version recorded for it differs from the current one, OR
      - `force` is True.

    `embedder` is optional: when provided, capsules are also embedded after the
    structural pass (PR4).
    """
    config.index_dir.mkdir(parents=True, exist_ok=True)
    store = GraphStore(config.db_path)
    try:
        stats = IndexStats()
        seen_paths: set[str] = set()
        previously_known = store.known_files()
        now = datetime.now(timezone.utc).isoformat()
        store.set_meta("schema_version", str(SCHEMA_VERSION))
        store.set_meta("capsule_version", str(CAPSULE_VERSION))
        store.set_meta("parser_backend_pref", parser_backend.value)
        store.set_meta("provider_registry", "production-foundation-v1")
        new_or_updated_symbol_ids: list[int] = []
        providers = LanguageProviderRegistry.default(parser_backend=parser_backend)

        for src in scan_repo(config.repo_path, languages=config.languages,
                              follow_symlinks=config.follow_symlinks):
            stats.files_scanned += 1
            seen_paths.add(src.rel_path)
            existing_hash = store.get_file_hash(src.rel_path)
            existing_parser_sig = store.get_meta(f"file_parser:{src.rel_path}")
            target_parser_sig = parser_signature(src.language, parser_backend)
            content_unchanged = existing_hash == src.content_hash
            parser_unchanged = existing_parser_sig == target_parser_sig
            if not force and content_unchanged and parser_unchanged:
                stats.files_unchanged += 1
                continue
            if content_unchanged and not parser_unchanged:
                stats.files_reparsed_for_version += 1
            if progress:
                progress(f"indexing {src.rel_path}")
            file_id = store.upsert_file(
                path=src.rel_path,
                language=src.language,
                content_hash=src.content_hash,
                size_bytes=src.size_bytes,
                content=src.content,
                indexed_at=now,
            )
            extract, choice = providers.parse_and_extract(src)
            stats.parser_backends[choice.parser_backend] = stats.parser_backends.get(choice.parser_backend, 0) + 1
            store.set_meta(f"file_provider:{src.rel_path}", choice.provider_id)
            store.set_meta(f"file_parser:{src.rel_path}", target_parser_sig)

            # PR 14 — framework-aware enrichment.
            framework_out = enrich_extraction(src, extract)
            if framework_out.extra_symbols or framework_out.extra_edges:
                # Drop duplicate symbols (same qualified_name) before merging.
                existing_qnames = {s.qualified_name for s in extract.symbols}
                for sym in framework_out.extra_symbols:
                    if sym.qualified_name not in existing_qnames:
                        extract.symbols.append(sym)
                        existing_qnames.add(sym.qualified_name)
                extract.edges.extend(framework_out.extra_edges)
            for fw in framework_out.detected_frameworks:
                store.set_meta(f"framework:{src.rel_path}:{fw}", "1")
            edges_by_src: dict[str, list] = {}
            for edge in extract.edges:
                edges_by_src.setdefault(edge.src_qualified_name, []).append(edge)

            symbol_qnames: list[str] = []
            for sym in extract.symbols:
                capsule = build_symbol_capsule(sym, src.rel_path,
                                               edges_by_src.get(sym.qualified_name, []))
                sym_id = store.insert_symbol(
                    file_id=file_id,
                    kind=sym.kind,
                    name=sym.name,
                    qualified_name=sym.qualified_name,
                    parent_qname=sym.parent_qualified_name,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    signature=sym.signature,
                    docstring=sym.docstring,
                    capsule=capsule,
                    extras=sym.extras,
                    return_type=sym.return_type,
                    declared_type=sym.declared_type,
                    visibility=sym.visibility,
                    is_exported=sym.is_exported,
                    parser_backend=choice.parser_backend,
                    parser_version=choice.parser_version,
                    semantic_backend=sym.semantic_backend,
                    semantic_version=sym.semantic_version,
                    content_hash=src.content_hash,
                    metadata_json=sym.extras,
                )
                stats.symbols += 1
                symbol_qnames.append(sym.qualified_name)
                new_or_updated_symbol_ids.append(sym_id)

            # Replace edges keyed by these source symbol qnames
            store.delete_edges_from_symbols(symbol_qnames)
            edge_rows = []
            for edge in extract.edges:
                edge_rows.append((
                    edge.src_qualified_name,
                    None,  # dst_qname resolved later
                    edge.dst_name,
                    edge.edge_type,
                    edge.confidence,
                    edge.extraction_source,
                    edge.line,
                    edge.column,
                    edge.precision_level or int(PrecisionLevel.SYNTAX),
                    edge.reason,
                    edge.metadata,
                    now,
                ))
            store.insert_edges(edge_rows)
            stats.edges += len(edge_rows)
            stats.files_indexed += 1

            # Build search-index terms for each symbol added.
            # Phase 2.5 (PR 9): include alias/concept text so natural-language
            # queries can connect to function names that don't share surface tokens.
            for sym in extract.symbols:
                alias_text = build_alias_text(
                    sym, src.rel_path, edges_by_src.get(sym.qualified_name, [])
                )
                doc_text = " ".join([
                    sym.qualified_name.replace(".", " "),
                    sym.name,
                    sym.signature,
                    sym.docstring,
                    alias_text,
                ])
                terms, length = _tokenize(doc_text)
                row = store.find_symbol(sym.qualified_name)
                if row is not None:
                    store.replace_terms_for_symbol(row.id, terms, length)

        # Remove files no longer present in the repo
        for stale in previously_known - seen_paths:
            store.delete_file(stale)
            stats.files_removed += 1
            if progress:
                progress(f"removed {stale}")

        # Resolve edge targets where unambiguous
        store.resolve_edge_targets()
        store.set_meta("last_indexed_at", now)
        store.set_meta("repo_path", str(config.repo_path))

        if embedder is not None and new_or_updated_symbol_ids:
            from codegraphkb.core.embeddings import embed_symbols
            embedded = embed_symbols(store, new_or_updated_symbol_ids, embedder,
                                     progress=progress)
            store.set_meta("embedding_model", embedder.model_id)
            store.set_meta("embedding_dim", str(embedder.dimension))
            stats.parser_backends[f"embedded:{embedded}"] = embedded

        return stats
    finally:
        store.close()


def _tokenize(text: str) -> tuple[dict[str, int], int]:
    freqs: dict[str, int] = {}
    length = 0
    for match in _TOKEN_RE.finditer(text or ""):
        tok = match.group(0).lower()
        if len(tok) <= 1 or tok in _STOP:
            continue
        freqs[tok] = freqs.get(tok, 0) + 1
        length += 1
        # split CamelCase / snake_case sub-tokens too
        for sub in _split_identifier(tok):
            if sub != tok and len(sub) > 1 and sub not in _STOP:
                freqs[sub] = freqs.get(sub, 0) + 1
    return freqs, max(length, 1)


def _split_identifier(tok: str) -> list[str]:
    parts = re.split(r"[_]+", tok)
    out: list[str] = []
    camel_re = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+")
    for part in parts:
        out.extend(m.group(0).lower() for m in camel_re.finditer(part) if m.group(0))
    return out


_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "into", "onto", "self",
    "true", "false", "none", "null", "return", "import", "export", "function",
    "class", "const", "let", "var", "def", "type", "interface", "extends",
    "implements", "public", "private", "protected", "static", "async", "await",
    "yield", "new", "delete", "typeof", "instanceof", "in", "of", "void",
    "throw", "try", "catch", "finally", "if", "else", "elif", "while", "do",
    "switch", "case", "break", "continue", "pass", "raise", "as",
}
