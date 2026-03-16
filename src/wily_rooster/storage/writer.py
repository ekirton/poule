"""IndexWriter: write path for the SQLite search index."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from wily_rooster.storage.errors import StorageError


_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    module TEXT NOT NULL,
    kind TEXT NOT NULL,
    statement TEXT NOT NULL,
    type_expr TEXT,
    constr_tree BLOB,
    node_count INTEGER NOT NULL,
    symbol_set TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src INTEGER NOT NULL REFERENCES declarations(id),
    dst INTEGER NOT NULL REFERENCES declarations(id),
    relation TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wl_vectors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decl_id INTEGER NOT NULL REFERENCES declarations(id),
    h INTEGER NOT NULL,
    histogram TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbol_freq (
    symbol TEXT PRIMARY KEY,
    freq INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS declarations_fts USING fts5(
    name,
    statement,
    module,
    content=declarations,
    content_rowid=id,
    tokenize='porter unicode61'
);
"""


class IndexWriter:
    """Write path for bulk-loading a search index database."""

    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self._conn = conn
        self._path = path

    @classmethod
    def create(cls, path: str | Path) -> IndexWriter:
        """Create a new index database at *path*."""
        path = Path(path)
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA journal_mode = MEMORY")
        conn.executescript(_SCHEMA_DDL)
        return cls(conn, path)

    def insert_declarations(self, batch: list[dict[str, Any]]) -> dict[str, int]:
        """Insert a batch of declarations. Returns name -> id mapping."""
        cur = self._conn.cursor()
        mapping: dict[str, int] = {}
        for decl in batch:
            cur.execute(
                "INSERT INTO declarations (name, module, kind, statement, type_expr, constr_tree, node_count, symbol_set) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decl["name"],
                    decl["module"],
                    decl["kind"],
                    decl["statement"],
                    decl.get("type_expr"),
                    decl.get("constr_tree"),
                    decl["node_count"],
                    decl["symbol_set"],
                ),
            )
            rowid = cur.lastrowid
            mapping[decl["name"]] = rowid

            # Sync FTS
            cur.execute(
                "INSERT INTO declarations_fts(rowid, name, statement, module) VALUES (?, ?, ?, ?)",
                (rowid, decl["name"], decl["statement"], decl["module"]),
            )
        self._conn.commit()
        return mapping

    def insert_wl_vectors(self, batch: list[dict[str, Any]]) -> None:
        """Insert a batch of WL vectors."""
        self._conn.executemany(
            "INSERT INTO wl_vectors (decl_id, h, histogram) VALUES (?, ?, ?)",
            [(v["decl_id"], v["h"], v["histogram"]) for v in batch],
        )
        self._conn.commit()

    def insert_dependencies(self, batch: list[dict[str, Any]]) -> None:
        """Insert dependency edges. Rejects self-loops."""
        for dep in batch:
            if dep["src"] == dep["dst"]:
                raise ValueError(
                    f"Self-loop rejected: src == dst == {dep['src']}"
                )
        self._conn.executemany(
            "INSERT INTO dependencies (src, dst, relation) VALUES (?, ?, ?)",
            [(d["src"], d["dst"], d["relation"]) for d in batch],
        )
        self._conn.commit()

    def insert_symbol_freq(self, entries: dict[str, int]) -> None:
        """Insert symbol frequency entries."""
        self._conn.executemany(
            "INSERT INTO symbol_freq (symbol, freq) VALUES (?, ?)",
            list(entries.items()),
        )
        self._conn.commit()

    def write_meta(self, key: str, value: str) -> None:
        """Write a metadata key-value pair."""
        self._conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def finalize(self) -> None:
        """Rebuild FTS, run integrity check, close connection."""
        try:
            self._conn.execute(
                "INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild')"
            )
            result = self._conn.execute("PRAGMA integrity_check").fetchone()
            if result[0] != "ok":
                self._conn.close()
                os.unlink(str(self._path))
                raise StorageError(f"Integrity check failed: {result[0]}")
            self._conn.close()
        except StorageError:
            raise
        except Exception as exc:
            try:
                self._conn.close()
            except Exception:
                pass
            try:
                os.unlink(str(self._path))
            except Exception:
                pass
            raise StorageError(f"Finalize failed: {exc}") from exc
