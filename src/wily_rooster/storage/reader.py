"""IndexReader — read path for the SQLite search index."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .errors import IndexNotFoundError, IndexVersionError, StorageError

EXPECTED_SCHEMA_VERSION = "1"


class IndexReader:
    def __init__(self, conn_or_path: sqlite3.Connection | str | Path):
        if isinstance(conn_or_path, (str, Path)):
            reader = self.open(conn_or_path)
            self._conn = reader._conn
            self._coq_version = reader._coq_version
            self._mathcomp_version = reader._mathcomp_version
            return
        self._conn = conn_or_path
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> IndexReader:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @classmethod
    def open(cls, path) -> IndexReader:
        path = Path(path)
        if not path.exists():
            raise IndexNotFoundError(f"Database not found: {path}")

        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.OperationalError as e:
            raise StorageError(str(e)) from e

        row = conn.execute(
            "SELECT value FROM index_meta WHERE key = 'schema_version'"
        ).fetchone()
        found = row[0] if row else None

        if found != EXPECTED_SCHEMA_VERSION:
            conn.close()
            raise IndexVersionError(
                found=found, expected=EXPECTED_SCHEMA_VERSION
            )

        reader = cls(conn)

        coq_row = conn.execute(
            "SELECT value FROM index_meta WHERE key = 'coq_version'"
        ).fetchone()
        reader._coq_version = coq_row[0] if coq_row else None

        mc_row = conn.execute(
            "SELECT value FROM index_meta WHERE key = 'mathcomp_version'"
        ).fetchone()
        reader._mathcomp_version = mc_row[0] if mc_row else None

        return reader

    @property
    def coq_version(self) -> str | None:
        return self._coq_version

    @property
    def mathcomp_version(self) -> str | None:
        return self._mathcomp_version

    def load_wl_histograms(self) -> dict[int, dict[int, dict[str, int]]]:
        rows = self._conn.execute(
            "SELECT decl_id, h, histogram FROM wl_vectors"
        ).fetchall()
        result: dict[int, dict[int, dict[str, int]]] = {}
        for row in rows:
            decl_id, h, histogram_json = row[0], row[1], row[2]
            result.setdefault(decl_id, {})[h] = json.loads(histogram_json)
        return result

    def load_inverted_index(self) -> dict[str, set[int]]:
        rows = self._conn.execute(
            "SELECT id, symbol_set FROM declarations"
        ).fetchall()
        result: dict[str, set[int]] = {}
        for row in rows:
            decl_id = row[0]
            symbols = json.loads(row[1])
            for symbol in symbols:
                result.setdefault(symbol, set()).add(decl_id)
        return result

    def load_symbol_frequencies(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT symbol, freq FROM symbol_freq"
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    def load_declaration_node_counts(self) -> dict[int, int]:
        rows = self._conn.execute(
            "SELECT id, node_count FROM declarations WHERE node_count IS NOT NULL"
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    def get_declaration(self, name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM declarations WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_declarations_by_ids(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT * FROM declarations WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_constr_trees(self, ids: list[int]) -> dict[int, bytes]:
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT id, constr_tree FROM declarations "
            f"WHERE id IN ({placeholders}) AND constr_tree IS NOT NULL",
            ids,
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    def search_fts(self, query: str, limit: int) -> list[dict]:
        if not query or not query.strip():
            return []
        rows = self._conn.execute(
            "SELECT d.id, d.name, d.module, d.kind, d.statement, "
            "d.type_expr, d.node_count, d.symbol_set, "
            "bm25(declarations_fts, 10.0, 1.0, 5.0) AS rank "
            "FROM declarations_fts "
            "JOIN declarations d ON d.id = declarations_fts.rowid "
            "WHERE declarations_fts MATCH ? "
            "ORDER BY rank "
            "LIMIT ?",
            (query, limit),
        ).fetchall()

        if not rows:
            return []

        raw_scores = [abs(row["rank"]) for row in rows]
        max_score = max(raw_scores)

        results = []
        for row, raw in zip(rows, raw_scores):
            d = dict(row)
            del d["rank"]
            d["score"] = raw / max_score if max_score > 0 else 1.0
            results.append(d)
        return results

    def get_dependencies(
        self, decl_id: int, direction: str, relation: str | None
    ) -> list[dict]:
        if direction == "outgoing":
            col, join_col = "src", "dst"
        else:
            col, join_col = "dst", "src"

        sql = (
            f"SELECT dep.src, dep.dst, dep.relation, d.name AS target_name "
            f"FROM dependencies dep "
            f"JOIN declarations d ON d.id = dep.{join_col} "
            f"WHERE dep.{col} = ?"
        )
        params: list = [decl_id]

        if relation is not None:
            sql += " AND dep.relation = ?"
            params.append(relation)

        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_declarations_by_module(
        self, module: str, exclude_id: int | None
    ) -> list[dict]:
        if exclude_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM declarations WHERE module = ? AND id != ?",
                (module, exclude_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM declarations WHERE module = ?", (module,)
            ).fetchall()
        return [dict(r) for r in rows]

    def list_modules(self, prefix: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT module, COUNT(*) AS count FROM declarations "
            "WHERE module LIKE ? GROUP BY module",
            (prefix + "%",),
        ).fetchall()
        return [{"module": r[0], "count": r[1]} for r in rows]
