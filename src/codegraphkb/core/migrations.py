"""SQLite migration helpers for graph schema evolution."""
from __future__ import annotations

import sqlite3

from codegraphkb.core.graph_schema import GRAPH_SCHEMA_VERSION


def migrate_schema(conn) -> None:
    _ensure_column(conn, "edges", "precision_level", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "edges", "reason", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "edges", "column", "INTEGER")
    _ensure_column(conn, "edges", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    _ensure_column(conn, "edges", "created_at", "TEXT NOT NULL DEFAULT ''")

    _ensure_column(conn, "symbols", "return_type", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "symbols", "declared_type", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "symbols", "visibility", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "symbols", "is_exported", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "symbols", "parser_backend", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "symbols", "parser_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "symbols", "semantic_backend", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "symbols", "semantic_version", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "symbols", "content_hash", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "symbols", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL UNIQUE
    );
    CREATE TABLE IF NOT EXISTS types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_qname TEXT NOT NULL,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        declared_type TEXT,
        inferred_type TEXT,
        confidence REAL NOT NULL DEFAULT 0.0,
        precision_level INTEGER NOT NULL DEFAULT 1,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS callsites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        caller_qname TEXT NOT NULL,
        callee_qname TEXT,
        callee_name TEXT NOT NULL,
        line INTEGER,
        column INTEGER,
        confidence REAL NOT NULL DEFAULT 0.0,
        precision_level INTEGER NOT NULL DEFAULT 1,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL,
        imported_name TEXT NOT NULL,
        target_qname TEXT,
        confidence REAL NOT NULL DEFAULT 0.0,
        precision_level INTEGER NOT NULL DEFAULT 1,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS processes (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        process_type TEXT NOT NULL,
        entrypoint_id TEXT,
        terminal_id TEXT,
        step_count INTEGER NOT NULL DEFAULT 0,
        confidence REAL NOT NULL DEFAULT 0.0,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS process_steps (
        process_id TEXT NOT NULL,
        step INTEGER NOT NULL,
        src_qname TEXT NOT NULL,
        dst_qname TEXT,
        confidence REAL NOT NULL DEFAULT 0.0,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (process_id, step, src_qname)
    );
    CREATE TABLE IF NOT EXISTS communities (
        id TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        keywords TEXT NOT NULL DEFAULT '[]',
        symbol_count INTEGER NOT NULL DEFAULT 0,
        cohesion REAL NOT NULL DEFAULT 0.0,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS capsules (
        symbol_id INTEGER PRIMARY KEY,
        capsule TEXT NOT NULL,
        capsule_version TEXT NOT NULL,
        token_count INTEGER NOT NULL DEFAULT 0,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS eval_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        dataset TEXT NOT NULL,
        mode TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS eval_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        task_id TEXT NOT NULL,
        metrics_json TEXT NOT NULL
    );
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
    """)
    _set_meta(conn, "graph_schema_version", str(GRAPH_SCHEMA_VERSION))


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if any(row["name"] == column for row in rows):
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc).lower():
            raise


def _set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
