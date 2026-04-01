"""IndexWriter — write path for the SQLite search index."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path

from .errors import StorageError

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """\
CREATE TABLE declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    module TEXT NOT NULL,
    kind TEXT NOT NULL,
    statement TEXT NOT NULL,
    type_expr TEXT,
    constr_tree BLOB,
    node_count INTEGER NOT NULL CHECK(node_count > 0),
    symbol_set TEXT NOT NULL,
    has_proof_body INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE dependencies (
    src INTEGER NOT NULL REFERENCES declarations(id) ON DELETE CASCADE,
    dst INTEGER NOT NULL REFERENCES declarations(id) ON DELETE CASCADE,
    relation TEXT NOT NULL,
    PRIMARY KEY (src, dst, relation)
);

CREATE TABLE wl_vectors (
    decl_id INTEGER NOT NULL REFERENCES declarations(id) ON DELETE CASCADE,
    h INTEGER NOT NULL,
    histogram TEXT NOT NULL,
    PRIMARY KEY (decl_id, h)
);

CREATE TABLE symbol_freq (
    symbol TEXT PRIMARY KEY,
    freq INTEGER NOT NULL CHECK(freq > 0)
);

CREATE TABLE re_export_aliases (
    alias_fqn TEXT PRIMARY KEY,
    canonical_fqn TEXT NOT NULL
);

CREATE TABLE index_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE embeddings (
    decl_id INTEGER PRIMARY KEY REFERENCES declarations(id) ON DELETE CASCADE,
    vector BLOB NOT NULL
);

CREATE VIRTUAL TABLE declarations_fts USING fts5(
    name, statement, module,
    content=declarations, content_rowid=id,
    tokenize='porter unicode61'
);
"""


class IndexWriter:
    def __init__(self, conn: sqlite3.Connection, db_path: Path):
        self._conn = conn
        self._db_path = db_path

    @classmethod
    def create(cls, path) -> IndexWriter:
        path = Path(path)
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA journal_mode = MEMORY")
        conn.executescript(_SCHEMA_SQL)
        return cls(conn, path)

    def insert_declarations(self, batch: list[dict]) -> dict[str, int]:
        name_to_id: dict[str, int] = {}
        for decl in batch:
            symbol_set_json = json.dumps(decl["symbol_set"])
            cursor = self._conn.execute(
                "INSERT INTO declarations "
                "(name, module, kind, statement, type_expr, constr_tree, "
                "node_count, symbol_set, has_proof_body) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decl["name"],
                    decl["module"],
                    decl["kind"],
                    decl["statement"],
                    decl.get("type_expr"),
                    decl.get("constr_tree"),
                    decl["node_count"],
                    symbol_set_json,
                    decl.get("has_proof_body", 0),
                ),
            )
            row_id = cursor.lastrowid
            name_to_id[decl["name"]] = row_id
            self._conn.execute(
                "INSERT INTO declarations_fts(rowid, name, statement, module) "
                "VALUES (?, ?, ?, ?)",
                (row_id, decl["name"], decl["statement"], decl["module"]),
            )
        self._conn.commit()
        return name_to_id

    def insert_wl_vectors(self, batch: list[dict]) -> None:
        self._conn.executemany(
            "INSERT INTO wl_vectors (decl_id, h, histogram) VALUES (?, ?, ?)",
            [(v["decl_id"], v["h"], json.dumps(v["histogram"])) for v in batch],
        )
        self._conn.commit()

    def insert_dependencies(self, batch: list[dict]) -> None:
        for edge in batch:
            if edge["src"] == edge["dst"]:
                raise ValueError(
                    f"Self-loop detected: src == dst == {edge['src']}"
                )
        self._conn.executemany(
            "INSERT INTO dependencies (src, dst, relation) VALUES (?, ?, ?)",
            [(e["src"], e["dst"], e["relation"]) for e in batch],
        )
        self._conn.commit()

    def insert_re_export_aliases(self, aliases: dict[str, str]) -> None:
        if not aliases:
            return
        self._conn.executemany(
            "INSERT OR IGNORE INTO re_export_aliases (alias_fqn, canonical_fqn) "
            "VALUES (?, ?)",
            list(aliases.items()),
        )
        self._conn.commit()

    def insert_symbol_freq(self, entries: dict[str, int]) -> None:
        self._conn.executemany(
            "INSERT INTO symbol_freq (symbol, freq) VALUES (?, ?)",
            list(entries.items()),
        )
        self._conn.commit()

    def write_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    def finalize(self) -> None:
        self._conn.commit()
        self._conn.close()

        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                "INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild')"
            )
            conn.commit()
            result = conn.execute("PRAGMA integrity_check").fetchone()
        except Exception as e:
            conn.close()
            if self._db_path.exists():
                os.remove(self._db_path)
            raise StorageError(str(e)) from e
        conn.close()

        if result[0] != "ok":
            if self._db_path.exists():
                os.remove(self._db_path)
            raise StorageError(f"Integrity check failed: {result[0]}")

