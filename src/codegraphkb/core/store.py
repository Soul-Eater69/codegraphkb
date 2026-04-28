"""SQLite-backed storage for files, symbols, edges, and capsules.

Single-file persistence under `.codegraphkb/graph.sqlite`. Avoids Neo4j for the MVP
while keeping the schema isomorphic to the architecture doc, so swapping later is mechanical.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL,
    hash TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    indexed_at TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_lang ON files(language);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    parent_qname TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT,
    docstring TEXT,
    capsule TEXT,
    extras TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_symbols_qname ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src_qname TEXT NOT NULL,
    dst_qname TEXT,
    dst_name TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    confidence REAL NOT NULL,
    extraction_source TEXT NOT NULL,
    line INTEGER
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_qname, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_qname, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_dst_name ON edges(dst_name);

-- Inverted index for BM25-style retrieval over capsules + symbol names.
CREATE TABLE IF NOT EXISTS terms (
    term TEXT NOT NULL,
    symbol_id INTEGER NOT NULL REFERENCES symbols(id) ON DELETE CASCADE,
    tf INTEGER NOT NULL,
    PRIMARY KEY (term, symbol_id)
);
CREATE INDEX IF NOT EXISTS idx_terms_term ON terms(term);

CREATE TABLE IF NOT EXISTS doc_lengths (
    symbol_id INTEGER PRIMARY KEY REFERENCES symbols(id) ON DELETE CASCADE,
    length INTEGER NOT NULL
);
"""


@dataclass
class FileRow:
    id: int
    path: str
    language: str
    content: str


@dataclass
class SymbolRow:
    id: int
    file_id: int
    file_path: str
    kind: str
    name: str
    qualified_name: str
    parent_qname: str | None
    start_line: int
    end_line: int
    signature: str
    docstring: str
    capsule: str
    extras: dict


@dataclass
class EdgeRow:
    src_qname: str
    dst_qname: str | None
    dst_name: str
    edge_type: str
    confidence: float
    line: int | None


class GraphStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ---------- low-level ----------
    @contextmanager
    def transaction(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def close(self) -> None:
        self._conn.close()

    def set_meta(self, key: str, value: str) -> None:
        with self.transaction() as cx:
            cx.execute(
                "INSERT INTO meta(key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    # ---------- files ----------
    def get_file_hash(self, path: str) -> str | None:
        row = self._conn.execute("SELECT hash FROM files WHERE path=?", (path,)).fetchone()
        return row["hash"] if row else None

    def upsert_file(self, *, path: str, language: str, content_hash: str,
                    size_bytes: int, content: str, indexed_at: str) -> int:
        with self.transaction() as cx:
            cx.execute("DELETE FROM files WHERE path=?", (path,))
            cur = cx.execute(
                "INSERT INTO files(path, language, hash, size_bytes, indexed_at, content) "
                "VALUES (?,?,?,?,?,?)",
                (path, language, content_hash, size_bytes, indexed_at, content),
            )
            return int(cur.lastrowid)

    def delete_file(self, path: str) -> None:
        with self.transaction() as cx:
            cx.execute("DELETE FROM files WHERE path=?", (path,))

    def known_files(self) -> set[str]:
        rows = self._conn.execute("SELECT path FROM files").fetchall()
        return {r["path"] for r in rows}

    def file_languages(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT language, COUNT(*) AS n FROM files GROUP BY language"
        ).fetchall()
        return {r["language"]: r["n"] for r in rows}

    def file_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"])

    def get_file(self, path: str) -> FileRow | None:
        row = self._conn.execute(
            "SELECT id, path, language, content FROM files WHERE path=?", (path,)
        ).fetchone()
        if not row:
            return None
        return FileRow(id=row["id"], path=row["path"], language=row["language"], content=row["content"])

    # ---------- symbols ----------
    def insert_symbol(self, *, file_id: int, kind: str, name: str, qualified_name: str,
                      parent_qname: str | None, start_line: int, end_line: int,
                      signature: str, docstring: str, capsule: str, extras: dict) -> int:
        with self.transaction() as cx:
            cx.execute("DELETE FROM symbols WHERE qualified_name=?", (qualified_name,))
            cur = cx.execute(
                "INSERT INTO symbols(file_id, kind, name, qualified_name, parent_qname, "
                "start_line, end_line, signature, docstring, capsule, extras) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (file_id, kind, name, qualified_name, parent_qname, start_line, end_line,
                 signature, docstring, capsule, json.dumps(extras or {})),
            )
            return int(cur.lastrowid)

    def delete_symbols_for_file(self, file_id: int) -> None:
        with self.transaction() as cx:
            cx.execute("DELETE FROM symbols WHERE file_id=?", (file_id,))

    def symbol_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM symbols").fetchone()["n"])

    def edge_count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS n FROM edges").fetchone()["n"])

    def find_symbol(self, qualified_name: str) -> SymbolRow | None:
        row = self._conn.execute(
            "SELECT s.*, f.path AS file_path FROM symbols s JOIN files f ON s.file_id = f.id "
            "WHERE s.qualified_name = ?",
            (qualified_name,),
        ).fetchone()
        return _row_to_symbol(row)

    def find_symbols_by_name(self, name: str, limit: int = 25) -> list[SymbolRow]:
        rows = self._conn.execute(
            "SELECT s.*, f.path AS file_path FROM symbols s JOIN files f ON s.file_id = f.id "
            "WHERE s.name = ? OR s.qualified_name LIKE ? "
            "LIMIT ?",
            (name, f"%.{name}", limit),
        ).fetchall()
        return [s for s in (_row_to_symbol(r) for r in rows) if s]

    def symbols_in_file(self, file_path: str) -> list[SymbolRow]:
        rows = self._conn.execute(
            "SELECT s.*, f.path AS file_path FROM symbols s JOIN files f ON s.file_id = f.id "
            "WHERE f.path = ? ORDER BY s.start_line",
            (file_path,),
        ).fetchall()
        return [s for s in (_row_to_symbol(r) for r in rows) if s]

    def all_symbols(self) -> Iterable[SymbolRow]:
        rows = self._conn.execute(
            "SELECT s.*, f.path AS file_path FROM symbols s JOIN files f ON s.file_id = f.id"
        ).fetchall()
        for r in rows:
            sr = _row_to_symbol(r)
            if sr is not None:
                yield sr

    # ---------- edges ----------
    def delete_edges_from_symbols(self, qualified_names: Iterable[str]) -> None:
        qnames = list(qualified_names)
        if not qnames:
            return
        with self.transaction() as cx:
            cx.executemany("DELETE FROM edges WHERE src_qname=?", [(q,) for q in qnames])

    def insert_edges(self, edges: Iterable[tuple]) -> None:
        """Each edge tuple: (src_qname, dst_qname|None, dst_name, edge_type, confidence, source, line)."""
        rows = list(edges)
        if not rows:
            return
        with self.transaction() as cx:
            cx.executemany(
                "INSERT INTO edges(src_qname, dst_qname, dst_name, edge_type, "
                "confidence, extraction_source, line) VALUES (?,?,?,?,?,?,?)",
                rows,
            )

    def resolve_edge_targets(self) -> None:
        """Best-effort: fill dst_qname where dst_name uniquely matches a symbol."""
        with self.transaction() as cx:
            cx.execute("""
                UPDATE edges
                SET dst_qname = (
                    SELECT s.qualified_name FROM symbols s
                    WHERE s.name = edges.dst_name
                    LIMIT 1
                )
                WHERE dst_qname IS NULL
                  AND (
                    SELECT COUNT(*) FROM symbols s2 WHERE s2.name = edges.dst_name
                  ) = 1
            """)

    def outgoing(self, src_qname: str, edge_types: Iterable[str] | None = None) -> list[EdgeRow]:
        if edge_types:
            placeholders = ",".join("?" * len(list(edge_types)))
            edge_types_list = list(edge_types)
            rows = self._conn.execute(
                f"SELECT * FROM edges WHERE src_qname=? AND edge_type IN ({placeholders})",
                (src_qname, *edge_types_list),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE src_qname=?", (src_qname,)
            ).fetchall()
        return [_row_to_edge(r) for r in rows]

    def incoming(self, dst_qname: str, edge_types: Iterable[str] | None = None) -> list[EdgeRow]:
        if edge_types:
            edge_types_list = list(edge_types)
            placeholders = ",".join("?" * len(edge_types_list))
            rows = self._conn.execute(
                f"SELECT * FROM edges WHERE dst_qname=? AND edge_type IN ({placeholders})",
                (dst_qname, *edge_types_list),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM edges WHERE dst_qname=?", (dst_qname,)
            ).fetchall()
        return [_row_to_edge(r) for r in rows]

    # ---------- search index ----------
    def replace_terms_for_symbol(self, symbol_id: int, term_freqs: dict[str, int],
                                  doc_length: int) -> None:
        with self.transaction() as cx:
            cx.execute("DELETE FROM terms WHERE symbol_id=?", (symbol_id,))
            cx.executemany(
                "INSERT INTO terms(term, symbol_id, tf) VALUES (?,?,?)",
                [(t, symbol_id, f) for t, f in term_freqs.items()],
            )
            cx.execute(
                "INSERT INTO doc_lengths(symbol_id, length) VALUES (?,?) "
                "ON CONFLICT(symbol_id) DO UPDATE SET length=excluded.length",
                (symbol_id, doc_length),
            )

    def avg_doc_length(self) -> float:
        row = self._conn.execute("SELECT AVG(length) AS avg FROM doc_lengths").fetchone()
        return float(row["avg"] or 1.0)

    def total_docs(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM doc_lengths").fetchone()
        return int(row["n"] or 0)

    def lookup_terms(self, terms: list[str]) -> list[tuple[str, int, int]]:
        if not terms:
            return []
        placeholders = ",".join("?" * len(terms))
        rows = self._conn.execute(
            f"SELECT term, symbol_id, tf FROM terms WHERE term IN ({placeholders})",
            terms,
        ).fetchall()
        return [(r["term"], r["symbol_id"], r["tf"]) for r in rows]

    def doc_freq(self, terms: list[str]) -> dict[str, int]:
        if not terms:
            return {}
        placeholders = ",".join("?" * len(terms))
        rows = self._conn.execute(
            f"SELECT term, COUNT(DISTINCT symbol_id) AS df FROM terms "
            f"WHERE term IN ({placeholders}) GROUP BY term",
            terms,
        ).fetchall()
        return {r["term"]: r["df"] for r in rows}

    def doc_length(self, symbol_id: int) -> int:
        row = self._conn.execute(
            "SELECT length FROM doc_lengths WHERE symbol_id=?", (symbol_id,)
        ).fetchone()
        return int(row["length"]) if row else 1

    def get_symbol_by_id(self, symbol_id: int) -> SymbolRow | None:
        row = self._conn.execute(
            "SELECT s.*, f.path AS file_path FROM symbols s JOIN files f ON s.file_id = f.id "
            "WHERE s.id = ?",
            (symbol_id,),
        ).fetchone()
        return _row_to_symbol(row)


def _row_to_symbol(row: sqlite3.Row | None) -> SymbolRow | None:
    if row is None:
        return None
    try:
        extras = json.loads(row["extras"]) if row["extras"] else {}
    except (TypeError, json.JSONDecodeError):
        extras = {}
    return SymbolRow(
        id=row["id"],
        file_id=row["file_id"],
        file_path=row["file_path"],
        kind=row["kind"],
        name=row["name"],
        qualified_name=row["qualified_name"],
        parent_qname=row["parent_qname"],
        start_line=row["start_line"],
        end_line=row["end_line"],
        signature=row["signature"] or "",
        docstring=row["docstring"] or "",
        capsule=row["capsule"] or "",
        extras=extras,
    )


def _row_to_edge(row: sqlite3.Row) -> EdgeRow:
    return EdgeRow(
        src_qname=row["src_qname"],
        dst_qname=row["dst_qname"],
        dst_name=row["dst_name"],
        edge_type=row["edge_type"],
        confidence=row["confidence"],
        line=row["line"],
    )
