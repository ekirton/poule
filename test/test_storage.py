"""TDD tests for the storage layer (writer + reader + errors).

Tests are written BEFORE implementation. They will fail with ImportError
until src/wily_rooster/storage/ modules exist.

Spec: specification/storage.md
Architecture: doc/architecture/storage.md
Data model: doc/architecture/data-models/index-entities.md
"""

from __future__ import annotations

import json
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — deferred so tests fail with ImportError, not at collection
# ---------------------------------------------------------------------------

def _import_writer():
    from wily_rooster.storage.writer import IndexWriter
    return IndexWriter


def _import_reader():
    from wily_rooster.storage.reader import IndexReader
    return IndexReader


def _import_errors():
    from wily_rooster.storage.errors import (
        StorageError,
        IndexNotFoundError,
        IndexVersionError,
    )
    return StorageError, IndexNotFoundError, IndexVersionError


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

def _make_declaration(
    name: str,
    module: str = "Coq.Init.Nat",
    kind: str = "Lemma",
    statement: str = "forall n : nat, n + 0 = n",
    type_expr: str | None = "nat -> Prop",
    constr_tree: bytes | None = None,
    node_count: int = 3,
    symbol_set: list[str] | None = None,
) -> dict:
    """Build a declaration dict matching the expected insert_declarations input."""
    if symbol_set is None:
        symbol_set = ["Coq.Init.Nat.add", "Coq.Init.Nat.O"]
    return {
        "name": name,
        "module": module,
        "kind": kind,
        "statement": statement,
        "type_expr": type_expr,
        "constr_tree": constr_tree,
        "node_count": node_count,
        "symbol_set": json.dumps(symbol_set),
    }


def _make_wl_vector(decl_id: int, h: int = 3, histogram: dict | None = None) -> dict:
    """Build a WL vector dict matching the expected insert_wl_vectors input."""
    if histogram is None:
        histogram = {"LConst": 2, "LApp": 1}
    return {
        "decl_id": decl_id,
        "h": h,
        "histogram": json.dumps(histogram),
    }


def _make_dependency(src: int, dst: int, relation: str = "uses") -> dict:
    """Build a dependency edge dict."""
    return {"src": src, "dst": dst, "relation": relation}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Return a fresh path for a temporary SQLite database."""
    return tmp_path / "test_index.db"


@pytest.fixture
def writer_cls():
    return _import_writer()


@pytest.fixture
def reader_cls():
    return _import_reader()


@pytest.fixture
def errors():
    StorageError, IndexNotFoundError, IndexVersionError = _import_errors()
    return {
        "StorageError": StorageError,
        "IndexNotFoundError": IndexNotFoundError,
        "IndexVersionError": IndexVersionError,
    }


@pytest.fixture
def created_writer(writer_cls, db_path):
    """Return an IndexWriter that has already called create()."""
    writer = writer_cls.create(db_path)
    yield writer
    # Ensure cleanup even if test forgets to close/finalize
    try:
        writer.finalize()
    except Exception:
        pass


@pytest.fixture
def populated_db(writer_cls, db_path):
    """Build a fully populated database and return its path.

    Contains:
    - 5 declarations across 2 modules
    - WL vectors at h=3 for each declaration
    - Dependency edges (including cross-module)
    - Symbol frequencies
    - All required metadata
    - FTS rebuilt and finalized

    Used by read-path tests.
    """
    writer = writer_cls.create(db_path)

    decls = [
        _make_declaration(
            "Coq.Init.Nat.add",
            module="Coq.Init.Nat",
            kind="Definition",
            statement="fix add (n m : nat) : nat := ...",
            symbol_set=["Coq.Init.Nat.S", "Coq.Init.Nat.O"],
            node_count=5,
        ),
        _make_declaration(
            "Coq.Init.Nat.add_comm",
            module="Coq.Init.Nat",
            kind="Lemma",
            statement="forall n m : nat, n + m = m + n",
            symbol_set=["Coq.Init.Nat.add", "Coq.Init.Logic.eq"],
            node_count=8,
        ),
        _make_declaration(
            "Coq.Init.Nat.mul",
            module="Coq.Init.Nat",
            kind="Definition",
            statement="fix mul (n m : nat) : nat := ...",
            symbol_set=["Coq.Init.Nat.add", "Coq.Init.Nat.O"],
            node_count=6,
        ),
        _make_declaration(
            "Coq.Arith.PeanoNat.Nat.add_assoc",
            module="Coq.Arith.PeanoNat",
            kind="Lemma",
            statement="forall n m p : nat, n + (m + p) = n + m + p",
            symbol_set=["Coq.Init.Nat.add", "Coq.Init.Logic.eq"],
            node_count=12,
        ),
        _make_declaration(
            "Coq.Arith.PeanoNat.Nat.mul_comm",
            module="Coq.Arith.PeanoNat",
            kind="Theorem",
            statement="forall n m : nat, n * m = m * n",
            symbol_set=["Coq.Init.Nat.mul", "Coq.Init.Logic.eq"],
            node_count=10,
        ),
    ]

    name_to_id = writer.insert_declarations(decls)

    # WL vectors at h=3 for all declarations
    wl_vectors = []
    for decl_name, decl_id in name_to_id.items():
        wl_vectors.append(_make_wl_vector(decl_id, h=3, histogram={
            "LConst": decl_id,  # varying histograms
            "LApp": decl_id + 1,
        }))
    writer.insert_wl_vectors(wl_vectors)

    # Dependency edges
    id_add = name_to_id["Coq.Init.Nat.add"]
    id_add_comm = name_to_id["Coq.Init.Nat.add_comm"]
    id_mul = name_to_id["Coq.Init.Nat.mul"]
    id_add_assoc = name_to_id["Coq.Arith.PeanoNat.Nat.add_assoc"]
    id_mul_comm = name_to_id["Coq.Arith.PeanoNat.Nat.mul_comm"]

    deps = [
        _make_dependency(id_add_comm, id_add, "uses"),
        _make_dependency(id_mul, id_add, "uses"),
        _make_dependency(id_add_assoc, id_add, "uses"),
        _make_dependency(id_add_assoc, id_add_comm, "uses"),
        _make_dependency(id_mul_comm, id_mul, "uses"),
        _make_dependency(id_mul_comm, id_add, "instance_of"),
    ]
    writer.insert_dependencies(deps)

    # Symbol frequencies
    writer.insert_symbol_freq({
        "Coq.Init.Nat.add": 3,
        "Coq.Init.Nat.S": 1,
        "Coq.Init.Nat.O": 2,
        "Coq.Init.Nat.mul": 1,
        "Coq.Init.Logic.eq": 3,
    })

    # Metadata
    writer.write_meta("schema_version", "1")
    writer.write_meta("coq_version", "8.19")
    writer.write_meta("mathcomp_version", "none")
    writer.write_meta("created_at", "2026-03-16T12:00:00Z")

    writer.finalize()

    return db_path, name_to_id


# ===================================================================
# 1. IndexWriter.create creates all 6 tables
# ===================================================================

class TestWriterCreate:

    def test_creates_all_six_tables(self, created_writer, db_path):
        """create() produces a SQLite DB with exactly the 6 required tables."""
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view') "
            "ORDER BY name"
        ).fetchall()
        conn.close()

        table_names = {r[0] for r in rows}
        expected = {
            "declarations",
            "dependencies",
            "wl_vectors",
            "symbol_freq",
            "index_meta",
            "declarations_fts",
        }
        # FTS5 may create shadow tables; check that at least the 6 exist
        assert expected.issubset(table_names)

    def test_foreign_keys_enabled(self, created_writer, db_path):
        """create() enables foreign key enforcement."""
        conn = sqlite3.connect(str(db_path))
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.close()
        assert fk == 1

    def test_write_pragmas_set(self, created_writer, db_path):
        """create() sets write-path pragmas: synchronous=OFF, journal_mode=MEMORY."""
        conn = sqlite3.connect(str(db_path))
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        # synchronous OFF = 0
        assert sync == 0
        assert journal.lower() == "memory"


# ===================================================================
# 2–3. insert_declarations round-trip and name→id mapping
# ===================================================================

class TestInsertDeclarations:

    def test_round_trip(self, created_writer, db_path):
        """Inserted declarations can be read back via raw SQL."""
        decls = [
            _make_declaration("Coq.Init.Nat.add"),
            _make_declaration("Coq.Init.Nat.mul", statement="fix mul ..."),
        ]
        created_writer.insert_declarations(decls)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT name FROM declarations ORDER BY name").fetchall()
        conn.close()

        names = [r[0] for r in rows]
        assert names == ["Coq.Init.Nat.add", "Coq.Init.Nat.mul"]

    def test_returns_name_to_id_mapping(self, created_writer):
        """insert_declarations returns a dict mapping name → assigned id."""
        decls = [
            _make_declaration("Coq.Init.Nat.add"),
            _make_declaration("Coq.Init.Nat.mul"),
        ]
        mapping = created_writer.insert_declarations(decls)

        assert isinstance(mapping, dict)
        assert "Coq.Init.Nat.add" in mapping
        assert "Coq.Init.Nat.mul" in mapping
        assert isinstance(mapping["Coq.Init.Nat.add"], int)
        assert mapping["Coq.Init.Nat.add"] != mapping["Coq.Init.Nat.mul"]


# ===================================================================
# 4. insert_wl_vectors stores JSON histograms
# ===================================================================

class TestInsertWlVectors:

    def test_stores_histograms(self, created_writer, db_path):
        """WL vectors store JSON histograms that round-trip correctly."""
        ids = created_writer.insert_declarations([
            _make_declaration("Coq.Init.Nat.add"),
        ])
        decl_id = ids["Coq.Init.Nat.add"]

        histogram = {"LConst": 5, "LApp": 3, "LProd": 1}
        created_writer.insert_wl_vectors([
            _make_wl_vector(decl_id, h=3, histogram=histogram),
        ])

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT histogram FROM wl_vectors WHERE decl_id = ? AND h = ?",
            (decl_id, 3),
        ).fetchone()
        conn.close()

        assert row is not None
        stored = json.loads(row[0])
        assert stored == histogram


# ===================================================================
# 5. insert_dependencies: edges + self-loop rejection
# ===================================================================

class TestInsertDependencies:

    def test_inserts_edges(self, created_writer, db_path):
        """Dependency edges are stored correctly."""
        ids = created_writer.insert_declarations([
            _make_declaration("Coq.Init.Nat.add"),
            _make_declaration("Coq.Init.Nat.mul"),
        ])
        id_add = ids["Coq.Init.Nat.add"]
        id_mul = ids["Coq.Init.Nat.mul"]

        created_writer.insert_dependencies([
            _make_dependency(id_mul, id_add, "uses"),
        ])

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT src, dst, relation FROM dependencies"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0] == (id_mul, id_add, "uses")

    def test_self_loop_raises_value_error(self, created_writer):
        """Self-loop (src == dst) raises ValueError."""
        ids = created_writer.insert_declarations([
            _make_declaration("Coq.Init.Nat.add"),
        ])
        decl_id = ids["Coq.Init.Nat.add"]

        with pytest.raises(ValueError):
            created_writer.insert_dependencies([
                _make_dependency(decl_id, decl_id, "uses"),
            ])


# ===================================================================
# 6. insert_symbol_freq
# ===================================================================

class TestInsertSymbolFreq:

    def test_stores_frequencies(self, created_writer, db_path):
        """Symbol frequencies are stored correctly."""
        created_writer.insert_symbol_freq({
            "Coq.Init.Nat.add": 5,
            "Coq.Init.Nat.O": 3,
        })

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT symbol, freq FROM symbol_freq ORDER BY symbol"
        ).fetchall()
        conn.close()

        assert rows == [("Coq.Init.Nat.O", 3), ("Coq.Init.Nat.add", 5)]


# ===================================================================
# 7. write_meta
# ===================================================================

class TestWriteMeta:

    def test_stores_key_value(self, created_writer, db_path):
        """write_meta stores key-value pairs in index_meta."""
        created_writer.write_meta("schema_version", "1")
        created_writer.write_meta("coq_version", "8.19")

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT key, value FROM index_meta ORDER BY key"
        ).fetchall()
        conn.close()

        meta = dict(rows)
        assert meta["schema_version"] == "1"
        assert meta["coq_version"] == "8.19"


# ===================================================================
# 8. finalize succeeds on valid DB
# ===================================================================

class TestFinalize:

    def test_succeeds_on_valid_db(self, writer_cls, db_path):
        """finalize() completes without error on a properly populated DB."""
        writer = writer_cls.create(db_path)

        writer.insert_declarations([
            _make_declaration("Coq.Init.Nat.add"),
        ])
        writer.write_meta("schema_version", "1")
        writer.write_meta("coq_version", "8.19")
        writer.write_meta("mathcomp_version", "none")
        writer.write_meta("created_at", "2026-03-16T12:00:00Z")

        # Should not raise
        writer.finalize()

        # DB file should still exist after successful finalize
        assert db_path.exists()


# ===================================================================
# 9. IndexReader.open on non-existent path → IndexNotFoundError
# ===================================================================

class TestReaderOpenErrors:

    def test_missing_file_raises_index_not_found(self, reader_cls, errors, tmp_path):
        """Opening a non-existent database raises IndexNotFoundError."""
        missing = tmp_path / "does_not_exist.db"

        with pytest.raises(errors["IndexNotFoundError"]):
            reader_cls.open(missing)

    # ---------------------------------------------------------------
    # 10. Wrong schema_version → IndexVersionError
    # ---------------------------------------------------------------

    def test_wrong_schema_version_raises_index_version_error(
        self, writer_cls, reader_cls, errors, db_path
    ):
        """Opening a DB with wrong schema_version raises IndexVersionError."""
        writer = writer_cls.create(db_path)
        writer.insert_declarations([_make_declaration("Coq.Init.Nat.add")])
        # Write a schema_version that will NOT match the expected one
        writer.write_meta("schema_version", "9999")
        writer.write_meta("coq_version", "8.19")
        writer.write_meta("mathcomp_version", "none")
        writer.write_meta("created_at", "2026-03-16T12:00:00Z")
        writer.finalize()

        with pytest.raises(errors["IndexVersionError"]):
            reader_cls.open(db_path)


# ===================================================================
# 11. IndexReader.open with correct version succeeds
# ===================================================================

class TestReaderOpenSuccess:

    def test_opens_valid_db(self, populated_db, reader_cls):
        """IndexReader.open succeeds on a properly versioned database."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)
        # Should not raise; reader should be usable
        assert reader is not None
        reader.close()


# ===================================================================
# 12. load_wl_histograms
# ===================================================================

class TestLoadWlHistograms:

    def test_returns_correct_structure(self, populated_db, reader_cls):
        """load_wl_histograms returns dict[decl_id, {h: histogram}]."""
        db_path, name_to_id = populated_db
        reader = reader_cls.open(db_path)

        histograms = reader.load_wl_histograms()

        # All 5 declarations should have histograms
        assert len(histograms) == 5

        # Check structure: each value should be a dict mapping h → histogram
        for decl_id, h_map in histograms.items():
            assert isinstance(decl_id, int)
            assert isinstance(h_map, dict)
            # We inserted at h=3 only
            assert 3 in h_map
            hist = h_map[3]
            assert isinstance(hist, dict)
            # All histogram values should be ints
            for label, count in hist.items():
                assert isinstance(label, str)
                assert isinstance(count, int)

        reader.close()


# ===================================================================
# 13. load_inverted_index
# ===================================================================

class TestLoadInvertedIndex:

    def test_builds_correct_mapping(self, populated_db, reader_cls):
        """load_inverted_index returns dict[symbol, set[decl_id]]."""
        db_path, name_to_id = populated_db
        reader = reader_cls.open(db_path)

        inv_index = reader.load_inverted_index()

        # "Coq.Init.Nat.add" appears in symbol_set of:
        #   add_comm, mul, add_assoc
        assert "Coq.Init.Nat.add" in inv_index
        expected_ids = {
            name_to_id["Coq.Init.Nat.add_comm"],
            name_to_id["Coq.Init.Nat.mul"],
            name_to_id["Coq.Arith.PeanoNat.Nat.add_assoc"],
        }
        assert inv_index["Coq.Init.Nat.add"] == expected_ids

        # "Coq.Init.Logic.eq" appears in: add_comm, add_assoc, mul_comm
        assert "Coq.Init.Logic.eq" in inv_index
        eq_ids = {
            name_to_id["Coq.Init.Nat.add_comm"],
            name_to_id["Coq.Arith.PeanoNat.Nat.add_assoc"],
            name_to_id["Coq.Arith.PeanoNat.Nat.mul_comm"],
        }
        assert inv_index["Coq.Init.Logic.eq"] == eq_ids

        reader.close()


# ===================================================================
# 14. load_symbol_frequencies
# ===================================================================

class TestLoadSymbolFrequencies:

    def test_returns_correct_mapping(self, populated_db, reader_cls):
        """load_symbol_frequencies returns dict[symbol, freq]."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        freqs = reader.load_symbol_frequencies()

        assert freqs["Coq.Init.Nat.add"] == 3
        assert freqs["Coq.Init.Nat.S"] == 1
        assert freqs["Coq.Init.Nat.O"] == 2
        assert freqs["Coq.Init.Nat.mul"] == 1
        assert freqs["Coq.Init.Logic.eq"] == 3

        reader.close()


# ===================================================================
# 15. get_declaration found vs not found
# ===================================================================

class TestGetDeclaration:

    def test_found(self, populated_db, reader_cls):
        """get_declaration returns row for existing name."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        result = reader.get_declaration("Coq.Init.Nat.add")

        assert result is not None
        assert result.name == "Coq.Init.Nat.add"
        assert result.module == "Coq.Init.Nat"
        assert result.kind == "Definition"

        reader.close()

    def test_not_found(self, populated_db, reader_cls):
        """get_declaration returns None for missing name."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        result = reader.get_declaration("Nonexistent.Name")

        assert result is None

        reader.close()


# ===================================================================
# 16. get_declarations_by_ids with mix of valid/invalid IDs
# ===================================================================

class TestGetDeclarationsByIds:

    def test_returns_found_only(self, populated_db, reader_cls):
        """get_declarations_by_ids returns rows for valid IDs, omits invalid."""
        db_path, name_to_id = populated_db
        reader = reader_cls.open(db_path)

        valid_id = name_to_id["Coq.Init.Nat.add"]
        invalid_id = 99999

        results = reader.get_declarations_by_ids([valid_id, invalid_id])

        assert len(results) == 1
        assert results[0].name == "Coq.Init.Nat.add"

        reader.close()

    def test_empty_input(self, populated_db, reader_cls):
        """get_declarations_by_ids with empty list returns empty list."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        results = reader.get_declarations_by_ids([])

        assert results == []

        reader.close()


# ===================================================================
# 17. search_fts returns ranked results, scores in [0, 1]
# ===================================================================

class TestSearchFts:

    def test_returns_ranked_results(self, populated_db, reader_cls):
        """search_fts returns results for a matching query."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        results = reader.search_fts("add", limit=10)

        assert len(results) > 0
        # Results should contain declarations with "add" in name/statement
        reader.close()

    def test_scores_normalized_zero_to_one(self, populated_db, reader_cls):
        """search_fts scores are normalized to [0, 1]."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        results = reader.search_fts("add", limit=10)

        for result in results:
            # Results should have a score attribute or be tuples with score
            if hasattr(result, "score"):
                assert 0.0 <= result.score <= 1.0
            else:
                # If returned as (row, score) or similar structure
                score = result[-1] if isinstance(result, tuple) else result.score
                assert 0.0 <= score <= 1.0

        reader.close()

    def test_respects_limit(self, populated_db, reader_cls):
        """search_fts returns at most `limit` results."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        results = reader.search_fts("nat", limit=2)

        assert len(results) <= 2

        reader.close()

    def test_no_matches_returns_empty(self, populated_db, reader_cls):
        """search_fts returns empty list for non-matching query."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        results = reader.search_fts("zzzznonexistent", limit=10)

        assert results == []

        reader.close()


# ===================================================================
# 18. get_dependencies outgoing/incoming
# ===================================================================

class TestGetDependencies:

    def test_outgoing(self, populated_db, reader_cls):
        """get_dependencies with direction='outgoing' returns dst edges."""
        db_path, name_to_id = populated_db
        reader = reader_cls.open(db_path)

        id_add_assoc = name_to_id["Coq.Arith.PeanoNat.Nat.add_assoc"]
        edges = reader.get_dependencies(id_add_assoc, direction="outgoing")

        # add_assoc depends on: add (uses), add_comm (uses)
        dst_ids = {e["dst"] if isinstance(e, dict) else e.dst for e in edges}
        assert name_to_id["Coq.Init.Nat.add"] in dst_ids
        assert name_to_id["Coq.Init.Nat.add_comm"] in dst_ids

        reader.close()

    def test_incoming(self, populated_db, reader_cls):
        """get_dependencies with direction='incoming' returns src edges."""
        db_path, name_to_id = populated_db
        reader = reader_cls.open(db_path)

        id_add = name_to_id["Coq.Init.Nat.add"]
        edges = reader.get_dependencies(id_add, direction="incoming")

        # add is used by: add_comm, mul, add_assoc, mul_comm(instance_of)
        src_ids = {e["src"] if isinstance(e, dict) else e.src for e in edges}
        assert name_to_id["Coq.Init.Nat.add_comm"] in src_ids
        assert name_to_id["Coq.Init.Nat.mul"] in src_ids
        assert name_to_id["Coq.Arith.PeanoNat.Nat.add_assoc"] in src_ids

        reader.close()

    def test_with_relation_filter(self, populated_db, reader_cls):
        """get_dependencies with relation filter returns only matching edges."""
        db_path, name_to_id = populated_db
        reader = reader_cls.open(db_path)

        id_add = name_to_id["Coq.Init.Nat.add"]
        edges = reader.get_dependencies(
            id_add, direction="incoming", relation="instance_of"
        )

        # Only mul_comm has instance_of relation to add
        assert len(edges) == 1
        src_id = edges[0]["src"] if isinstance(edges[0], dict) else edges[0].src
        assert src_id == name_to_id["Coq.Arith.PeanoNat.Nat.mul_comm"]

        reader.close()


# ===================================================================
# 19. get_declarations_by_module with/without exclude
# ===================================================================

class TestGetDeclarationsByModule:

    def test_returns_module_declarations(self, populated_db, reader_cls):
        """get_declarations_by_module returns all declarations in module."""
        db_path, name_to_id = populated_db
        reader = reader_cls.open(db_path)

        results = reader.get_declarations_by_module("Coq.Init.Nat")

        names = {r.name for r in results}
        assert names == {
            "Coq.Init.Nat.add",
            "Coq.Init.Nat.add_comm",
            "Coq.Init.Nat.mul",
        }

        reader.close()

    def test_with_exclude_id(self, populated_db, reader_cls):
        """get_declarations_by_module with exclude_id omits that declaration."""
        db_path, name_to_id = populated_db
        reader = reader_cls.open(db_path)

        exclude = name_to_id["Coq.Init.Nat.add"]
        results = reader.get_declarations_by_module(
            "Coq.Init.Nat", exclude_id=exclude
        )

        names = {r.name for r in results}
        assert "Coq.Init.Nat.add" not in names
        assert "Coq.Init.Nat.add_comm" in names
        assert "Coq.Init.Nat.mul" in names

        reader.close()

    def test_empty_module(self, populated_db, reader_cls):
        """get_declarations_by_module returns empty list for unknown module."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        results = reader.get_declarations_by_module("Nonexistent.Module")

        assert results == []

        reader.close()


# ===================================================================
# 20. list_modules with empty and specific prefix
# ===================================================================

class TestListModules:

    def test_empty_prefix_lists_all(self, populated_db, reader_cls):
        """list_modules('') returns all modules with counts."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        modules = reader.list_modules("")

        # Should have 2 modules
        module_names = {m.name if hasattr(m, "name") else m["name"] for m in modules}
        assert "Coq.Init.Nat" in module_names
        assert "Coq.Arith.PeanoNat" in module_names

        reader.close()

    def test_specific_prefix(self, populated_db, reader_cls):
        """list_modules with prefix filters to matching modules."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        modules = reader.list_modules("Coq.Arith")

        module_names = {m.name if hasattr(m, "name") else m["name"] for m in modules}
        assert "Coq.Arith.PeanoNat" in module_names
        assert "Coq.Init.Nat" not in module_names

        reader.close()

    def test_module_counts(self, populated_db, reader_cls):
        """list_modules entries include declaration counts."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        modules = reader.list_modules("Coq.Init.Nat")

        assert len(modules) == 1
        mod = modules[0]
        count = mod.count if hasattr(mod, "count") else mod["count"]
        assert count == 3  # add, add_comm, mul

        reader.close()


# ===================================================================
# 21. Batch co-insertion: declarations + WL vectors in same transaction
# ===================================================================

class TestBatchCoInsertion:

    def test_declarations_and_wl_vectors_co_insert(self, writer_cls, db_path):
        """Declarations and their WL vectors can be co-inserted correctly."""
        writer = writer_cls.create(db_path)

        decls = [
            _make_declaration(f"Coq.Test.decl_{i}") for i in range(10)
        ]
        ids = writer.insert_declarations(decls)

        wl_vecs = [
            _make_wl_vector(ids[f"Coq.Test.decl_{i}"], h=3)
            for i in range(10)
        ]
        writer.insert_wl_vectors(wl_vecs)

        # Verify both tables populated
        conn = sqlite3.connect(str(db_path))
        decl_count = conn.execute("SELECT COUNT(*) FROM declarations").fetchone()[0]
        wl_count = conn.execute("SELECT COUNT(*) FROM wl_vectors").fetchone()[0]
        conn.close()

        assert decl_count == 10
        assert wl_count == 10

        try:
            writer.write_meta("schema_version", "1")
            writer.write_meta("coq_version", "8.19")
            writer.write_meta("mathcomp_version", "none")
            writer.write_meta("created_at", "2026-03-16T12:00:00Z")
            writer.finalize()
        except Exception:
            pass


# ===================================================================
# Error hierarchy tests
# ===================================================================

class TestErrorHierarchy:

    def test_index_not_found_is_storage_error(self, errors):
        """IndexNotFoundError is a subclass of StorageError."""
        assert issubclass(
            errors["IndexNotFoundError"], errors["StorageError"]
        )

    def test_index_version_error_is_storage_error(self, errors):
        """IndexVersionError is a subclass of StorageError."""
        assert issubclass(
            errors["IndexVersionError"], errors["StorageError"]
        )

    def test_index_version_error_carries_versions(self, errors):
        """IndexVersionError carries found and expected version info."""
        err = errors["IndexVersionError"](found="9999", expected="1")
        assert err.found == "9999"
        assert err.expected == "1"


# ===================================================================
# get_constr_trees (batched, non-null only)
# ===================================================================

class TestGetConstrTrees:

    def test_returns_trees_for_non_null(self, writer_cls, reader_cls, db_path):
        """get_constr_trees returns deserialized trees for non-null entries."""
        writer = writer_cls.create(db_path)

        # One declaration with constr_tree, one without
        decl_with_tree = _make_declaration(
            "Coq.Init.Nat.add",
            constr_tree=b"\x80\x05\x95\x05\x00\x00\x00\x00\x00\x00\x00test_blob",
        )
        decl_without = _make_declaration(
            "Coq.Init.Nat.mul",
            constr_tree=None,
        )
        ids = writer.insert_declarations([decl_with_tree, decl_without])
        writer.write_meta("schema_version", "1")
        writer.write_meta("coq_version", "8.19")
        writer.write_meta("mathcomp_version", "none")
        writer.write_meta("created_at", "2026-03-16T12:00:00Z")
        writer.finalize()

        reader = reader_cls.open(db_path)
        id_add = ids["Coq.Init.Nat.add"]
        id_mul = ids["Coq.Init.Nat.mul"]

        trees = reader.get_constr_trees([id_add, id_mul])

        # Only the non-null entry should be present
        assert id_add in trees
        assert id_mul not in trees

        reader.close()

    def test_empty_ids_returns_empty(self, populated_db, reader_cls):
        """get_constr_trees with empty list returns empty dict."""
        db_path, _ = populated_db
        reader = reader_cls.open(db_path)

        trees = reader.get_constr_trees([])

        assert trees == {}

        reader.close()
