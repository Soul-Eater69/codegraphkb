"""Indexing pipeline: scan -> parse -> persist (graph + capsules + search index)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from codegraphkb.config import IndexConfig
from codegraphkb.core.capsules import build_symbol_capsule
from codegraphkb.core.parsers import parse_file
from codegraphkb.core.scanner import scan_repo
from codegraphkb.core.store import GraphStore

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_indexed: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    symbols: int = 0
    edges: int = 0


def index_repository(config: IndexConfig, force: bool = False,
                     progress=None) -> IndexStats:
    """Index a repo into the graph store. Re-indexes only changed files unless `force`.

    progress: optional callable(message: str) for streaming status.
    """
    config.index_dir.mkdir(parents=True, exist_ok=True)
    store = GraphStore(config.db_path)
    try:
        stats = IndexStats()
        seen_paths: set[str] = set()
        previously_known = store.known_files()
        now = datetime.now(timezone.utc).isoformat()

        for src in scan_repo(config.repo_path, languages=config.languages,
                              follow_symlinks=config.follow_symlinks):
            stats.files_scanned += 1
            seen_paths.add(src.rel_path)
            existing_hash = store.get_file_hash(src.rel_path)
            if not force and existing_hash == src.content_hash:
                stats.files_unchanged += 1
                continue
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
            extract = parse_file(src)
            edges_by_src: dict[str, list] = {}
            for edge in extract.edges:
                edges_by_src.setdefault(edge.src_qualified_name, []).append(edge)

            symbol_qnames: list[str] = []
            for sym in extract.symbols:
                capsule = build_symbol_capsule(sym, src.rel_path,
                                               edges_by_src.get(sym.qualified_name, []))
                store.insert_symbol(
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
                )
                stats.symbols += 1
                symbol_qnames.append(sym.qualified_name)

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
                ))
            store.insert_edges(edge_rows)
            stats.edges += len(edge_rows)
            stats.files_indexed += 1

            # Build search-index terms for each symbol added.
            for sym in extract.symbols:
                doc_text = " ".join([
                    sym.qualified_name.replace(".", " "),
                    sym.name,
                    sym.signature,
                    sym.docstring,
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
