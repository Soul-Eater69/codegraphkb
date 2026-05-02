"""SQLite-backed storage for files, symbols, edges, and capsules.

Single-file persistence under `.codegraphkb/graph.sqlite`. Avoids Neo4j for the MVP
while keeping the schema isomorphic to the architecture doc, so swapping later is mechanical.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from codegraphkb.core.graph_schema import PrecisionLevel

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
    extras TEXT,
    return_type TEXT NOT NULL DEFAULT '',
    declared_type TEXT NOT NULL DEFAULT '',
    visibility TEXT NOT NULL DEFAULT '',
    is_exported INTEGER NOT NULL DEFAULT 0,
    parser_backend TEXT NOT NULL DEFAULT '',
    parser_version TEXT NOT NULL DEFAULT '',
    semantic_backend TEXT NOT NULL DEFAULT '',
    semantic_version TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
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
    line INTEGER,
    column INTEGER,
    precision_level INTEGER NOT NULL DEFAULT 1,
    reason TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT ''
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

CREATE TABLE IF NOT EXISTS embeddings (
    symbol_id INTEGER PRIMARY KEY REFERENCES symbols(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_embeddings_model ON embeddings(model);

CREATE TABLE IF NOT EXISTS object_roles (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    role TEXT NOT NULL,
    confidence REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    signals_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_object_roles_node ON object_roles(node_id);
CREATE INDEX IF NOT EXISTS idx_object_roles_role ON object_roles(role);
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
    column: int | None = None
    precision_level: int = int(PrecisionLevel.SYNTAX)
    extraction_source: str = ""
    reason: str = ""
    metadata: dict = None  # type: ignore[assignment]


class GraphStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        is_new_db = not db_path.exists()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if is_new_db:
            self._conn.execute("PRAGMA journal_mode = WAL")
        # Always run base schema first; every statement is `IF NOT EXISTS`,
        # so this is idempotent and also safe for partial / very old DBs that
        # are missing tables migrations would otherwise try to ALTER.
        self._conn.executescript(SCHEMA)
        from codegraphkb.core.migrations import migrate_schema
        migrate_schema(self._conn)
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
                      signature: str, docstring: str, capsule: str, extras: dict,
                      return_type: str = "", declared_type: str = "",
                      visibility: str = "", is_exported: bool = False,
                      parser_backend: str = "", parser_version: str = "",
                      semantic_backend: str = "", semantic_version: str = "",
                      content_hash: str = "", metadata_json: dict | None = None) -> int:
        with self.transaction() as cx:
            cx.execute("DELETE FROM symbols WHERE qualified_name=?", (qualified_name,))
            cur = cx.execute(
                "INSERT INTO symbols(file_id, kind, name, qualified_name, parent_qname, "
                "start_line, end_line, signature, docstring, capsule, extras, "
                "return_type, declared_type, visibility, is_exported, parser_backend, "
                "parser_version, semantic_backend, semantic_version, content_hash, metadata_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (file_id, kind, name, qualified_name, parent_qname, start_line, end_line,
                 signature, docstring, capsule, json.dumps(extras or {}),
                 return_type, declared_type, visibility, 1 if is_exported else 0,
                 parser_backend, parser_version, semantic_backend, semantic_version,
                 content_hash, json.dumps(metadata_json or {})),
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

    def symbols_by_kind(self, kind: str) -> list[SymbolRow]:
        rows = self._conn.execute(
            "SELECT s.*, f.path AS file_path FROM symbols s JOIN files f ON s.file_id = f.id "
            "WHERE s.kind = ? ORDER BY s.qualified_name",
            (kind,),
        ).fetchall()
        return [s for s in (_row_to_symbol(r) for r in rows) if s]

    def symbol_qnames_in_file(self, file_path: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT s.qualified_name FROM symbols s JOIN files f ON s.file_id = f.id "
            "WHERE f.path = ?",
            (file_path,),
        ).fetchall()
        return [r["qualified_name"] for r in rows]

    # ---------- edges ----------
    def delete_edges_from_symbols(self, qualified_names: Iterable[str]) -> None:
        qnames = list(qualified_names)
        if not qnames:
            return
        with self.transaction() as cx:
            cx.executemany("DELETE FROM edges WHERE src_qname=?", [(q,) for q in qnames])

    def delete_edges_touching_symbols(self, qualified_names: Iterable[str]) -> None:
        qnames = list(qualified_names)
        if not qnames:
            return
        placeholders = ",".join("?" * len(qnames))
        params = qnames + qnames
        with self.transaction() as cx:
            cx.execute(
                f"DELETE FROM edges "
                f"WHERE src_qname IN ({placeholders}) "
                f"OR dst_qname IN ({placeholders})",
                params,
            )

    def insert_edges(self, edges: Iterable[tuple]) -> None:
        """Insert edge rows, accepting old 7-tuples or schema-v3 12-tuples."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [_normalize_edge_row(row, now) for row in edges]
        if not rows:
            return
        with self.transaction() as cx:
            cx.executemany(
                "INSERT INTO edges(src_qname, dst_qname, dst_name, edge_type, "
                "confidence, extraction_source, line, column, precision_level, reason, "
                "metadata_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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

    # ---------- embeddings ----------
    def get_embedding(self, symbol_id: int, model: str) -> tuple[str, bytes, int] | None:
        row = self._conn.execute(
            "SELECT content_hash, vector, dim FROM embeddings WHERE symbol_id=? AND model=?",
            (symbol_id, model),
        ).fetchone()
        if row is None:
            return None
        return row["content_hash"], bytes(row["vector"]), int(row["dim"])

    def upsert_embedding(self, symbol_id: int, *, model: str, dim: int,
                         content_hash: str, vector: bytes, created_at: str) -> None:
        with self.transaction() as cx:
            cx.execute(
                "INSERT INTO embeddings(symbol_id, model, dim, content_hash, vector, created_at) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(symbol_id) DO UPDATE SET model=excluded.model, dim=excluded.dim, "
                "content_hash=excluded.content_hash, vector=excluded.vector, "
                "created_at=excluded.created_at",
                (symbol_id, model, dim, content_hash, vector, created_at),
            )

    def all_embeddings(self, model: str) -> list[tuple[int, bytes, int]]:
        rows = self._conn.execute(
            "SELECT symbol_id, vector, dim FROM embeddings WHERE model=?",
            (model,),
        ).fetchall()
        return [(r["symbol_id"], bytes(r["vector"]), int(r["dim"])) for r in rows]

    def embedding_count(self, model: str | None = None) -> int:
        if model is None:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM embeddings WHERE model=?", (model,)
            ).fetchone()
        return int(row["n"] or 0)

    def get_symbol_by_id(self, symbol_id: int) -> SymbolRow | None:
        row = self._conn.execute(
            "SELECT s.*, f.path AS file_path FROM symbols s JOIN files f ON s.file_id = f.id "
            "WHERE s.id = ?",
            (symbol_id,),
        ).fetchone()
        return _row_to_symbol(row)

    # ---------- object roles ----------
    def replace_object_roles(self, roles: Iterable[tuple]) -> None:
        """Replace inferred object roles with stable, auditable rows."""
        rows = list(roles)
        with self.transaction() as cx:
            cx.execute("DELETE FROM object_roles")
            if rows:
                cx.executemany(
                    "INSERT INTO object_roles(id, node_id, role, confidence, reason, "
                    "signals_json, created_at) VALUES (?,?,?,?,?,?,?)",
                    rows,
                )

    def roles_for_node(self, node_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT role, confidence, reason, signals_json, created_at "
            "FROM object_roles WHERE node_id=? "
            "ORDER BY confidence DESC, role",
            (node_id,),
        ).fetchall()
        return [_object_role_row_to_dict(r) for r in rows]

    def object_roles_by_node(self) -> dict[str, list[dict]]:
        rows = self._conn.execute(
            "SELECT node_id, role, confidence, reason, signals_json, created_at "
            "FROM object_roles ORDER BY node_id, confidence DESC, role"
        ).fetchall()
        out: dict[str, list[dict]] = {}
        for row in rows:
            out.setdefault(row["node_id"], []).append(_object_role_row_to_dict(row))
        return out

    def object_role_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT role, COUNT(*) AS n FROM object_roles GROUP BY role"
        ).fetchall()
        return {r["role"]: int(r["n"]) for r in rows}


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
    try:
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    except (TypeError, json.JSONDecodeError, KeyError):
        metadata = {}
    return EdgeRow(
        src_qname=row["src_qname"],
        dst_qname=row["dst_qname"],
        dst_name=row["dst_name"],
        edge_type=row["edge_type"],
        confidence=row["confidence"],
        line=row["line"],
        column=row["column"] if "column" in row.keys() else None,
        precision_level=int(row["precision_level"]) if "precision_level" in row.keys() else 1,
        extraction_source=row["extraction_source"] if "extraction_source" in row.keys() else "",
        reason=row["reason"] if "reason" in row.keys() else "",
        metadata=metadata,
    )


def _normalize_edge_row(row: tuple, created_at: str) -> tuple:
    if len(row) == 7:
        src, dst_qname, dst_name, edge_type, confidence, source, line = row
        return (
            src, dst_qname, dst_name, edge_type, confidence, source, line,
            None, int(PrecisionLevel.SYNTAX), "Extracted from legacy parser edge",
            "{}", created_at,
        )
    if len(row) == 12:
        src, dst_qname, dst_name, edge_type, confidence, source, line, column, precision, reason, metadata, at = row
        return (
            src, dst_qname, dst_name, edge_type, confidence, source, line, column,
            int(precision or PrecisionLevel.SYNTAX), reason or "",
            json.dumps(metadata or {}) if not isinstance(metadata, str) else metadata,
            at or created_at,
        )
    raise ValueError(f"Expected edge row with 7 or 12 fields, got {len(row)}")


def _object_role_row_to_dict(row: sqlite3.Row) -> dict:
    try:
        signals = json.loads(row["signals_json"]) if row["signals_json"] else []
    except (TypeError, json.JSONDecodeError, KeyError):
        signals = []
    return {
        "role": row["role"],
        "confidence": float(row["confidence"] or 0.0),
        "reason": row["reason"] or "",
        "signals": signals,
        "created_at": row["created_at"] or "",
    }
