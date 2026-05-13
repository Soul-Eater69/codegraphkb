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
    CAPSULE_VERSION, SCHEMA_VERSION, actual_parser_signature, parser_signature,
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")
_TS_LANG_NAMES = ("typescript", "javascript")


def _resolve_semantic_selection(
    semantic: str | list[str] | None,
    languages_present: set[str],
) -> set[str]:
    if semantic is None or semantic == "" or semantic == "none":
        return set()
    if isinstance(semantic, str):
        if semantic == "auto":
            chosen: set[str] = set()
            if languages_present & set(_TS_LANG_NAMES):
                chosen.add("typescript")
            return chosen
        return {semantic}
    return {item for item in semantic if item}


def _run_semantic_pass(store, config, semantic, stats, progress) -> None:
    languages = set(store.file_languages().keys())
    selected = _resolve_semantic_selection(semantic, languages)
    if not selected:
        return
    if "typescript" in selected and (languages & set(_TS_LANG_NAMES)):
        _run_typescript_semantic_pass(store, config, stats, progress)


def _run_process_pass(store, stats, progress) -> None:
    from codegraphkb.core.processes import build_processes, replace_processes

    if progress:
        progress("building process maps")
    processes = build_processes(store)
    replace_processes(store, processes)
    stats.processes_built = len(processes)
    by_type: dict[str, int] = {}
    for proc in processes:
        by_type[proc.process_type] = by_type.get(proc.process_type, 0) + 1
    stats.processes_by_type = by_type
    store.set_meta("processes_built", str(len(processes)))
    if progress and processes:
        summary = ", ".join(f"{k}={v}" for k, v in by_type.items())
        progress(f"processes: {summary}")


def _run_role_pass(store, stats, progress) -> None:
    from codegraphkb.core.roles import classify_roles, object_roles_to_rows, role_counts

    if progress:
        progress("classifying object roles")
    roles = classify_roles(store)
    store.replace_object_roles(object_roles_to_rows(roles))
    stats.roles_built = len(roles)
    stats.roles_by_type = role_counts(roles)
    store.set_meta("object_roles_built", str(len(roles)))
    if progress and roles:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(stats.roles_by_type.items()))
        progress(f"roles: {summary}")


def _run_typescript_semantic_pass(store, config, stats, progress) -> None:
    from codegraphkb.core.semantic.adapter_runner import run_semantic_adapter
    from codegraphkb.core.semantic.merge import merge_semantic_result
    from codegraphkb.core.semantic.typescript_adapter import (
        ADAPTER_VERSION,
        TypeScriptSemanticAdapter,
    )

    adapter = TypeScriptSemanticAdapter()
    repo_path = str(config.repo_path)
    files: list[str] = []
    for path in store.known_files():
        row = store.get_file(path)
        if row is not None and row.language in _TS_LANG_NAMES:
            files.append(path)
    if progress:
        progress("running TypeScript semantic adapter")
    run = run_semantic_adapter(adapter, repo_path, files)
    backend_entry: dict = {
        "adapter": adapter.id,
        "language": adapter.language,
        "available": run.available,
        "warnings": list(run.warnings),
        "edges_upgraded": 0,
        "edges_inserted": 0,
        "types_inserted": 0,
        "symbols_enriched": 0,
        "parameters_merged": 0,
    }
    if not run.available or run.result is None:
        stats.semantic_backends["typescript"] = backend_entry
        store.set_meta("semantic_typescript_available", "false")
        store.set_meta(
            "semantic_typescript_reason",
            (run.warnings[0] if run.warnings else "unavailable"),
        )
        return
    merge_stats = merge_semantic_result(
        store, run.result, backend_version=run.result.adapter_version or ADAPTER_VERSION,
    )
    backend_entry.update({
        "edges_upgraded": merge_stats.edges_upgraded,
        "edges_inserted": merge_stats.edges_inserted,
        "types_inserted": merge_stats.types_inserted,
        "symbols_enriched": merge_stats.symbols_enriched,
        "parameters_merged": merge_stats.parameters_merged,
    })
    stats.semantic_backends["typescript"] = backend_entry
    store.set_meta("semantic_typescript_available", "true")
    store.set_meta(
        "semantic_typescript_version",
        run.result.adapter_version or ADAPTER_VERSION,
    )
    if progress:
        progress(
            f"semantic merge: upgraded={merge_stats.edges_upgraded} "
            f"inserted={merge_stats.edges_inserted}"
        )


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_indexed: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    files_reparsed_for_version: int = 0
    symbols: int = 0
    edges: int = 0
    parameters: int = 0
    parser_backends: dict[str, int] = None  # type: ignore[assignment]
    semantic_backends: dict[str, dict] = None  # type: ignore[assignment]
    processes_built: int = 0
    processes_by_type: dict[str, int] = None  # type: ignore[assignment]
    roles_built: int = 0
    roles_by_type: dict[str, int] = None  # type: ignore[assignment]
    alias_bindings_total: int = 0
    alias_bindings_resolved: int = 0
    alias_edges_rewritten: int = 0
    scope_edges_file: int = 0
    scope_edges_class: int = 0

    def __post_init__(self):
        if self.parser_backends is None:
            self.parser_backends = {}
        if self.semantic_backends is None:
            self.semantic_backends = {}
        if self.processes_by_type is None:
            self.processes_by_type = {}
        if self.roles_by_type is None:
            self.roles_by_type = {}


def index_repository(config: IndexConfig, force: bool = False,
                     progress=None,
                     parser_backend: ParserBackend = ParserBackend.AUTO,
                     embedder=None,
                     semantic: str | list[str] | None = None) -> IndexStats:
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
            # Capture old symbol qnames before upsert deletes them (cascade),
            # so we can purge edges that touch removed symbols afterwards.
            old_qnames = store.symbol_qnames_in_file(src.rel_path)
            store.delete_parameters_for_symbols(old_qnames)
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
            actual_sig = actual_parser_signature(
                src.language, choice.parser_backend, choice.parser_version,
            )
            store.set_meta(f"file_provider:{src.rel_path}", choice.provider_id)
            # `file_parser` carries the actual signature that ran, so it stays
            # comparable against `target_parser_sig` for cache invalidation.
            store.set_meta(f"file_parser:{src.rel_path}", target_parser_sig)
            store.set_meta(f"file_parser_preferred:{src.rel_path}", choice.preferred_backend)
            store.set_meta(f"file_parser_actual:{src.rel_path}", choice.parser_backend)
            store.set_meta(f"file_parser_signature:{src.rel_path}", actual_sig)
            store.set_meta(
                f"file_parser_fallback:{src.rel_path}",
                "true" if choice.fallback_used else "false",
            )
            if choice.warning:
                store.set_meta(f"file_parser_warning:{src.rel_path}", choice.warning)

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
                store.replace_parameters_for_symbol(sym.qualified_name, sym.parameters)
                stats.parameters += len(sym.parameters)
                symbol_qnames.append(sym.qualified_name)
                new_or_updated_symbol_ids.append(sym_id)

            # Stale-edge cleanup: remove every edge that touches an old symbol
            # of this file (incoming or outgoing) so edges from removed/renamed
            # symbols don't survive the reindex. Also covers the new-qnames set
            # for clean replacement.
            new_qnames_set = set(symbol_qnames)
            stale_qnames = [q for q in old_qnames if q not in new_qnames_set]
            if stale_qnames:
                store.delete_edges_touching_symbols(stale_qnames)
            store.delete_edges_from_symbols(symbol_qnames)
            edge_rows = []
            for edge in extract.edges:
                # Producers may pre-resolve dst_qname (semantic adapters,
                # alias resolvers); fall back to None and let the
                # whole-repo resolution pass fill it.
                pre_resolved = getattr(edge, "dst_qname", None)
                edge_rows.append((
                    edge.src_qualified_name,
                    pre_resolved,
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

            # Phase 4.2 — persist this file's import bindings. We clear the
            # file's existing rows first so renames / removed imports don't
            # leave stale bindings behind across re-indexes.
            store.clear_import_bindings_for_file(src.rel_path)
            if extract.imports:
                store.insert_import_bindings(extract.imports)

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
            stale_qnames = store.symbol_qnames_in_file(stale)
            if stale_qnames:
                store.delete_edges_touching_symbols(stale_qnames)
                store.delete_parameters_for_symbols(stale_qnames)
            store.delete_file(stale)
            stats.files_removed += 1
            if progress:
                progress(f"removed {stale}")

        # Phase 4.2 — alias-driven resolution. This runs before the broad
        # unique-name resolver so the alias rewrites get the precise edges
        # first; the unique-name pass then cleans up what's left.
        from codegraphkb.core.import_resolver import (
            resolve_imports_and_rewrite_edges,
        )
        alias_stats = resolve_imports_and_rewrite_edges(store)
        stats.alias_bindings_total = alias_stats.bindings_total
        stats.alias_bindings_resolved = alias_stats.bindings_resolved
        stats.alias_edges_rewritten = alias_stats.edges_rewritten
        if progress and alias_stats.edges_rewritten:
            progress(
                f"alias resolver rewrote {alias_stats.edges_rewritten} edges "
                f"({alias_stats.bindings_resolved}/{alias_stats.bindings_total} "
                f"bindings resolved)"
            )

        # Phase 4.4 — scope-aware rewrites (same-file then same-class).
        # Runs after the alias pass (which is the most authoritative) but
        # before the broad unique-name fallback so precise scope hits win
        # over noisy unique-name matches.
        from codegraphkb.core.edge_resolver import resolve_edges_by_scope
        scope_stats = resolve_edges_by_scope(store)
        stats.scope_edges_file = scope_stats.file_scope_rewritten
        stats.scope_edges_class = scope_stats.class_scope_rewritten
        if progress and scope_stats.total_rewritten:
            progress(
                f"scope resolver rewrote {scope_stats.total_rewritten} edges "
                f"(file={scope_stats.file_scope_rewritten} "
                f"class={scope_stats.class_scope_rewritten})"
            )

        # Resolve edge targets where unambiguous (catches anything earlier
        # passes couldn't handle — true globals, framework conventions, etc.)
        store.resolve_edge_targets()

        # Phase 3.1 — semantic enrichment pass.
        _run_semantic_pass(store, config, semantic, stats, progress)

        # Phase 3.3 — process map build.
        _run_process_pass(store, stats, progress)

        # Schema v4 — auditable object roles above raw syntax kinds.
        _run_role_pass(store, stats, progress)

        store.prune_orphan_parameters()
        stats.parameters = store.parameter_count()

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
