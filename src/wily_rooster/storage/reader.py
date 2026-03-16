"""IndexReader: read path for the SQLite search index."""

from __future__ import annotations

import json
import pickle
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wily_rooster.storage.errors import (
    IndexNotFoundError,
    IndexVersionError,
    StorageError,
)
from wily_rooster.models.responses import Module


EXPECTED_SCHEMA_VERSION = "1"


@dataclass
class DeclarationRow:
    """Lightweight row object for declaration query results."""
    id: int
    name: str
    module: str
    kind: str
    statement: str
    type_expr: str | None
    constr_tree: bytes | None
    node_count: int
    symbol_set: str  # JSON string


@dataclass
class DependencyEdge:
    """Row object for dependency query results."""
    src: int
    dst: int
    relation: str
    name: str | None = None  # resolved name


@dataclass
class FtsResult:
    """A search result with BM25 score."""
    id: int
    name: str
    module: str
    kind: str
    statement: str
    type_expr: str | None
    node_count: int
    symbol_set: str
    score: float


def _row_to_decl(row: tuple) -> DeclarationRow:
    return DeclarationRow(
        id=row[0],
        name=row[1],
        module=row[2],
        kind=row[3],
        statement=row[4],
        type_expr=row[5],
        constr_tree=row[6],
        node_count=row[7],
        symbol_set=row[8],
    )


class IndexReader:
    """Read path for querying the search index database."""

    def __init__(self, conn: sqlite3.Connection, path: Path) -> None:
        self._conn = conn
        self._path = path

    @classmethod
    def open(cls, path: str | Path) -> IndexReader:
        """Open an existing index database, validating schema version."""
        path = Path(path)
        if not path.exists():
            raise IndexNotFoundError(f"Database not found: {path}")

        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA foreign_keys = ON")

        # Validate schema version
        try:
            row = conn.execute(
                "SELECT value FROM index_meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.OperationalError as exc:
            conn.close()
            raise StorageError(f"Cannot read schema version: {exc}") from exc

        if row is None:
            conn.close()
            raise IndexVersionError(found="<missing>", expected=EXPECTED_SCHEMA_VERSION)

        found_version = row[0]
        if found_version != EXPECTED_SCHEMA_VERSION:
            conn.close()
            raise IndexVersionError(found=found_version, expected=EXPECTED_SCHEMA_VERSION)

        return cls(conn, path)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def load_wl_histograms(self) -> dict[int, dict[int, dict[str, int]]]:
        """Load all WL histograms: decl_id -> {h -> histogram}."""
        rows = self._conn.execute(
            "SELECT decl_id, h, histogram FROM wl_vectors"
        ).fetchall()

        result: dict[int, dict[int, dict[str, int]]] = {}
        for decl_id, h, histogram_json in rows:
            if decl_id not in result:
                result[decl_id] = {}
            result[decl_id][h] = json.loads(histogram_json)
        return result

    def load_inverted_index(self) -> dict[str, set[int]]:
        """Build inverted index: symbol -> set[decl_id]."""
        rows = self._conn.execute(
            "SELECT id, symbol_set FROM declarations"
        ).fetchall()

        inv: dict[str, set[int]] = {}
        for decl_id, symbol_set_json in rows:
            symbols = json.loads(symbol_set_json)
            for sym in symbols:
                if sym not in inv:
                    inv[sym] = set()
                inv[sym].add(decl_id)
        return inv

    def load_symbol_frequencies(self) -> dict[str, int]:
        """Load symbol -> freq mapping."""
        rows = self._conn.execute(
            "SELECT symbol, freq FROM symbol_freq"
        ).fetchall()
        return dict(rows)

    def get_declaration(self, name: str) -> DeclarationRow | None:
        """Get a declaration by fully qualified name."""
        row = self._conn.execute(
            "SELECT id, name, module, kind, statement, type_expr, constr_tree, node_count, symbol_set "
            "FROM declarations WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_decl(row)

    def get_declarations_by_ids(self, ids: list[int]) -> list[DeclarationRow]:
        """Get declarations by a list of IDs. Missing IDs are silently omitted."""
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT id, name, module, kind, statement, type_expr, constr_tree, node_count, symbol_set "
            f"FROM declarations WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        return [_row_to_decl(r) for r in rows]

    def get_constr_trees(self, ids: list[int]) -> dict[int, Any]:
        """Get deserialized constr_trees for given IDs (non-null only)."""
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT id, constr_tree FROM declarations "
            f"WHERE id IN ({placeholders}) AND constr_tree IS NOT NULL",
            ids,
        ).fetchall()
        result: dict[int, Any] = {}
        for decl_id, blob in rows:
            try:
                result[decl_id] = pickle.loads(blob)
            except Exception:
                # If pickle fails, store raw bytes
                result[decl_id] = blob
        return result

    def search_fts(self, query: str, limit: int = 10) -> list[FtsResult]:
        """Full-text search with BM25 scoring, normalized to [0, 1]."""
        rows = self._conn.execute(
            "SELECT d.id, d.name, d.module, d.kind, d.statement, d.type_expr, "
            "d.node_count, d.symbol_set, "
            "bm25(declarations_fts, 10.0, 1.0, 5.0) AS rank "
            "FROM declarations_fts fts "
            "JOIN declarations d ON d.id = fts.rowid "
            "WHERE declarations_fts MATCH ? "
            "ORDER BY rank "
            "LIMIT ?",
            (query, limit),
        ).fetchall()

        if not rows:
            return []

        # BM25 returns negative scores (more negative = better match).
        # Normalize to [0, 1] where 1 is the best match.
        raw_scores = [r[8] for r in rows]
        min_score = min(raw_scores)  # most negative = best
        max_score = max(raw_scores)  # least negative = worst

        results = []
        for r in rows:
            raw = r[8]
            if min_score == max_score:
                normalized = 1.0
            else:
                # Map: min_score -> 1.0, max_score -> 0.0
                normalized = (max_score - raw) / (max_score - min_score)
            results.append(FtsResult(
                id=r[0],
                name=r[1],
                module=r[2],
                kind=r[3],
                statement=r[4],
                type_expr=r[5],
                node_count=r[6],
                symbol_set=r[7],
                score=normalized,
            ))
        return results

    def get_dependencies(
        self,
        decl_id: int,
        direction: str = "outgoing",
        relation: str | None = None,
    ) -> list[DependencyEdge]:
        """Get dependency edges for a declaration."""
        if direction == "outgoing":
            sql = "SELECT src, dst, relation FROM dependencies WHERE src = ?"
        else:
            sql = "SELECT src, dst, relation FROM dependencies WHERE dst = ?"

        params: list[Any] = [decl_id]
        if relation is not None:
            sql += " AND relation = ?"
            params.append(relation)

        rows = self._conn.execute(sql, params).fetchall()
        return [DependencyEdge(src=r[0], dst=r[1], relation=r[2]) for r in rows]

    def get_declarations_by_module(
        self, module: str, exclude_id: int | None = None
    ) -> list[DeclarationRow]:
        """Get all declarations in a module, optionally excluding one."""
        if exclude_id is not None:
            rows = self._conn.execute(
                "SELECT id, name, module, kind, statement, type_expr, constr_tree, node_count, symbol_set "
                "FROM declarations WHERE module = ? AND id != ?",
                (module, exclude_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, name, module, kind, statement, type_expr, constr_tree, node_count, symbol_set "
                "FROM declarations WHERE module = ?",
                (module,),
            ).fetchall()
        return [_row_to_decl(r) for r in rows]

    def list_modules(self, prefix: str = "") -> list[Module]:
        """List modules matching prefix with declaration counts."""
        if prefix:
            rows = self._conn.execute(
                "SELECT module, COUNT(*) FROM declarations "
                "WHERE module LIKE ? GROUP BY module ORDER BY module",
                (prefix + "%",),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT module, COUNT(*) FROM declarations "
                "GROUP BY module ORDER BY module"
            ).fetchall()
        return [Module(name=r[0], decl_count=r[1]) for r in rows]
