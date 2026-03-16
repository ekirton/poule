"""TDD tests for SQLite storage layer (specification/storage.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/wily_rooster/storage/.

Covers: schema creation, IndexWriter (write path), IndexReader (read path),
error hierarchy, version validation, batch transaction protocol, and FTS5
configuration.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Imports from production code (TDD — will fail until implemented)
# ---------------------------------------------------------------------------

from wily_rooster.storage import IndexWriter, IndexReader
from wily_rooster.storage.errors import (
    StorageError,
    IndexNotFoundError,
    IndexVersionError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_declaration(
    name="Coq.Init.Nat.add",
    module="Coq.Init.Nat",
    kind="definition",
    statement="forall n m : nat, n + m = m + n",
    type_expr="Prop",
    constr_tree=None,
    node_count=5,
    symbol_set=None,
):
    """Return a dict representing a single declaration row."""
    return {
        "name": name,
        "module": module,
        "kind": kind,
        "statement": statement,
        "type_expr": type_expr,
        "constr_tree": constr_tree,
        "node_count": node_count,
        "symbol_set": symbol_set or ["Coq.Init.Nat.add", "Coq.Init.Logic.eq"],
    }


def _populate_minimal_db(writer):
    """Insert a minimal dataset (2 declarations, 1 dependency, WL vectors,
    symbol freq, metadata) via IndexWriter and finalize."""
    decl_a = _sample_declaration(
        name="Coq.Init.Nat.add",
        module="Coq.Init.Nat",
        kind="definition",
        symbol_set=["Coq.Init.Nat.add"],
    )
    decl_b = _sample_declaration(
        name="Coq.Init.Nat.mul",
        module="Coq.Init.Nat",
        kind="definition",
        symbol_set=["Coq.Init.Nat.mul", "Coq.Init.Nat.add"],
    )
    ids = writer.insert_declarations([decl_a, decl_b])

    id_a = ids["Coq.Init.Nat.add"]
    id_b = ids["Coq.Init.Nat.mul"]

    writer.insert_wl_vectors([
        {"decl_id": id_a, "h": 1, "histogram": {"LConst": 2, "LApp": 1}},
        {"decl_id": id_a, "h": 3, "histogram": {"LConst": 3}},
        {"decl_id": id_a, "h": 5, "histogram": {"LConst": 4}},
        {"decl_id": id_b, "h": 1, "histogram": {"LConst": 1}},
        {"decl_id": id_b, "h": 3, "histogram": {"LConst": 2}},
        {"decl_id": id_b, "h": 5, "histogram": {"LConst": 3}},
    ])

    writer.insert_dependencies([
        {"src": id_b, "dst": id_a, "relation": "uses"},
    ])

    writer.insert_symbol_freq({"Coq.Init.Nat.add": 2, "Coq.Init.Nat.mul": 1})

    writer.write_meta("schema_version", "1")
    writer.write_meta("coq_version", "8.19")
    writer.write_meta("mathcomp_version", "2.2.0")
    writer.write_meta("created_at", "2026-03-16T12:00:00Z")

    writer.finalize()
    return ids


# ═══════════════════════════════════════════════════════════════════════════
# 1. Schema
# ═══════════════════════════════════════════════════════════════════════════


class TestSchemaCreation:
    """IndexWriter.create produces a database with all 6 required tables."""

    def test_all_six_tables_exist(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        conn.close()
        writer.finalize()

        expected = {
            "declarations",
            "dependencies",
            "wl_vectors",
            "symbol_freq",
            "index_meta",
            "declarations_fts",
        }
        assert expected.issubset(tables)

    def test_declarations_fts_is_fts5_virtual_table(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'declarations_fts'"
        ).fetchone()
        conn.close()
        writer.finalize()

        assert row is not None
        ddl = row[0].lower()
        assert "fts5" in ddl

    def test_fts5_tokenizer_porter_wraps_unicode61(self, tmp_db_path):
        """The stemming tokenizer shall wrap the base tokenizer:
        tokenize='porter unicode61' (Section 4.1)."""
        writer = IndexWriter.create(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'declarations_fts'"
        ).fetchone()
        conn.close()
        writer.finalize()

        ddl = row[0]
        # Porter must appear before unicode61 in the tokenize clause,
        # indicating porter wraps unicode61.
        lower = ddl.lower()
        assert "porter" in lower
        assert "unicode61" in lower
        porter_pos = lower.index("porter")
        unicode_pos = lower.index("unicode61")
        assert porter_pos < unicode_pos, (
            f"Porter must wrap unicode61 (appear first in tokenize clause). "
            f"Got: {ddl}"
        )

    def test_fts5_content_synced_with_declarations(self, tmp_db_path):
        """FTS5 table uses content=declarations, content_rowid=id."""
        writer = IndexWriter.create(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'declarations_fts'"
        ).fetchone()
        conn.close()
        writer.finalize()

        ddl = row[0].lower()
        assert "content=declarations" in ddl or "content='declarations'" in ddl

    def test_foreign_keys_enabled(self, tmp_db_path):
        """FK enforcement is active on the writer's connection (Section 4.2)."""
        writer = IndexWriter.create(tmp_db_path)
        # Attempt to insert a dependency referencing a non-existent declaration.
        # If foreign keys are enabled, this must raise an IntegrityError.
        with pytest.raises(sqlite3.IntegrityError):
            writer._conn.execute(
                "INSERT INTO dependencies (src, dst, relation) VALUES (?, ?, ?)",
                (99999, 99998, "uses"),
            )
        writer.finalize()


class TestWritePathPragmas:
    """Write-path pragmas are set for bulk loading throughput (Section 6)."""

    def test_synchronous_off(self, tmp_db_path):
        """Writer's connection uses synchronous=OFF (Section 6)."""
        writer = IndexWriter.create(tmp_db_path)
        val = writer._conn.execute("PRAGMA synchronous").fetchone()[0]
        writer.finalize()

        assert val == 0  # OFF

    def test_journal_mode_memory(self, tmp_db_path):
        """Writer's connection uses journal_mode=MEMORY (Section 6)."""
        writer = IndexWriter.create(tmp_db_path)
        val = writer._conn.execute("PRAGMA journal_mode").fetchone()[0]
        writer.finalize()

        assert val.lower() == "memory"


# ═══════════════════════════════════════════════════════════════════════════
# 2. IndexWriter
# ═══════════════════════════════════════════════════════════════════════════


class TestIndexWriterCreate:
    """IndexWriter.create creates a new database at the given path."""

    def test_creates_database_file(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        writer.finalize()
        assert tmp_db_path.exists()


class TestInsertDeclarations:
    """insert_declarations inserts batch and returns name→id mapping."""

    def test_returns_name_to_id_mapping(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        decl = _sample_declaration()
        ids = writer.insert_declarations([decl])
        writer.finalize()

        assert "Coq.Init.Nat.add" in ids
        assert isinstance(ids["Coq.Init.Nat.add"], int)

    def test_multiple_declarations_in_batch(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        decls = [
            _sample_declaration(name=f"Decl.n{i}", module="Decl")
            for i in range(10)
        ]
        ids = writer.insert_declarations(decls)
        writer.finalize()

        assert len(ids) == 10
        assert all(isinstance(v, int) for v in ids.values())

    def test_fts_entries_synced_on_insert(self, tmp_db_path):
        """Inserting declarations also populates declarations_fts."""
        writer = IndexWriter.create(tmp_db_path)
        decl = _sample_declaration()
        writer.insert_declarations([decl])

        conn = sqlite3.connect(tmp_db_path)
        rows = conn.execute(
            "SELECT * FROM declarations_fts WHERE declarations_fts MATCH 'Nat'"
        ).fetchall()
        conn.close()
        writer.finalize()

        assert len(rows) >= 1


class TestInsertWlVectors:
    """insert_wl_vectors inserts WL histogram rows."""

    def test_vectors_inserted(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        ids = writer.insert_declarations([_sample_declaration()])
        decl_id = ids["Coq.Init.Nat.add"]

        writer.insert_wl_vectors([
            {"decl_id": decl_id, "h": 1, "histogram": {"LConst": 2}},
            {"decl_id": decl_id, "h": 3, "histogram": {"LConst": 3}},
            {"decl_id": decl_id, "h": 5, "histogram": {"LConst": 4}},
        ])
        writer.finalize()

        conn = sqlite3.connect(tmp_db_path)
        rows = conn.execute(
            "SELECT h, histogram FROM wl_vectors WHERE decl_id = ?",
            (decl_id,),
        ).fetchall()
        conn.close()

        assert len(rows) == 3
        h_values = {row[0] for row in rows}
        assert h_values == {1, 3, 5}


class TestInsertDependencies:
    """insert_dependencies inserts directed edges; rejects self-loops."""

    def test_edge_inserted(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        ids = writer.insert_declarations([
            _sample_declaration(name="A.src", module="A"),
            _sample_declaration(name="A.dst", module="A"),
        ])

        writer.insert_dependencies([
            {"src": ids["A.src"], "dst": ids["A.dst"], "relation": "uses"},
        ])
        writer.finalize()

        conn = sqlite3.connect(tmp_db_path)
        rows = conn.execute("SELECT src, dst, relation FROM dependencies").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0] == (ids["A.src"], ids["A.dst"], "uses")

    def test_self_loop_rejected(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        ids = writer.insert_declarations([_sample_declaration()])
        decl_id = ids["Coq.Init.Nat.add"]

        with pytest.raises(ValueError):
            writer.insert_dependencies([
                {"src": decl_id, "dst": decl_id, "relation": "uses"},
            ])
        writer.finalize()


class TestInsertSymbolFreq:
    """insert_symbol_freq inserts symbol→frequency entries."""

    def test_entries_inserted(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        writer.insert_symbol_freq({"Coq.Init.Nat.add": 5, "Coq.Init.Logic.eq": 3})
        writer.finalize()

        conn = sqlite3.connect(tmp_db_path)
        rows = conn.execute("SELECT symbol, freq FROM symbol_freq").fetchall()
        conn.close()

        freq_map = dict(rows)
        assert freq_map["Coq.Init.Nat.add"] == 5
        assert freq_map["Coq.Init.Logic.eq"] == 3


class TestWriteMeta:
    """write_meta inserts key-value pairs into index_meta."""

    def test_metadata_written(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        writer.write_meta("schema_version", "1")
        writer.write_meta("coq_version", "8.19")
        writer.finalize()

        conn = sqlite3.connect(tmp_db_path)
        rows = conn.execute("SELECT key, value FROM index_meta").fetchall()
        conn.close()

        meta = dict(rows)
        assert meta["schema_version"] == "1"
        assert meta["coq_version"] == "8.19"


class TestFinalize:
    """finalize runs FTS5 rebuild, integrity check, and closes connection."""

    def test_finalize_succeeds_on_valid_db(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        writer.insert_declarations([_sample_declaration()])
        writer.write_meta("schema_version", "1")
        writer.finalize()

        # Database should be readable after finalize
        conn = sqlite3.connect(tmp_db_path)
        result = conn.execute("PRAGMA integrity_check").fetchone()
        conn.close()
        assert result[0] == "ok"


class TestBatchTransactionProtocol:
    """Pass 1 co-inserts declarations and WL vectors; Pass 2 inserts
    dependency edges. This ordering guarantees FK targets exist before
    edges reference them."""

    def test_declarations_and_wl_vectors_coinserted(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        ids = writer.insert_declarations([_sample_declaration()])
        decl_id = ids["Coq.Init.Nat.add"]

        writer.insert_wl_vectors([
            {"decl_id": decl_id, "h": 3, "histogram": {"LConst": 1}},
        ])

        # Both declaration and vector should be visible in the same transaction
        conn = sqlite3.connect(tmp_db_path)
        decl_count = conn.execute("SELECT COUNT(*) FROM declarations").fetchone()[0]
        vec_count = conn.execute("SELECT COUNT(*) FROM wl_vectors").fetchone()[0]
        conn.close()
        writer.finalize()

        assert decl_count == 1
        assert vec_count == 1


# ═══════════════════════════════════════════════════════════════════════════
# 3. IndexReader
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def populated_db(tmp_db_path):
    """Create and populate a complete database, return (path, ids)."""
    writer = IndexWriter.create(tmp_db_path)
    ids = _populate_minimal_db(writer)
    return tmp_db_path, ids


@pytest.fixture
def reader(populated_db):
    """Open an IndexReader on the populated database; close on teardown."""
    db_path, ids = populated_db
    r = IndexReader.open(db_path)
    r._ids = ids  # attach for test access
    yield r
    r.close()


class TestIndexReaderOpen:
    """IndexReader.open validates schema_version and opens read-only."""

    def test_opens_valid_database(self, reader):
        assert reader is not None

    def test_raises_index_not_found_for_missing_file(self, tmp_path):
        with pytest.raises(IndexNotFoundError):
            IndexReader.open(tmp_path / "nonexistent.db")

    def test_raises_index_version_error_on_mismatch(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        writer.write_meta("schema_version", "999")
        writer.write_meta("coq_version", "8.19")
        writer.write_meta("mathcomp_version", "none")
        writer.write_meta("created_at", "2026-03-16T00:00:00Z")
        writer.finalize()

        with pytest.raises(IndexVersionError):
            IndexReader.open(tmp_db_path)

    def test_exposes_library_versions(self, reader):
        assert reader.coq_version == "8.19"
        assert reader.mathcomp_version == "2.2.0"


class TestLoadWlHistograms:
    """load_wl_histograms returns decl_id → {h → histogram} map."""

    def test_returns_all_histograms(self, reader):
        ids = reader._ids
        histograms = reader.load_wl_histograms()

        id_a = ids["Coq.Init.Nat.add"]
        assert id_a in histograms
        assert set(histograms[id_a].keys()) == {1, 3, 5}
        assert isinstance(histograms[id_a][3], dict)

    def test_histograms_deserialized_from_json(self, reader):
        ids = reader._ids
        histograms = reader.load_wl_histograms()

        id_a = ids["Coq.Init.Nat.add"]
        assert histograms[id_a][1] == {"LConst": 2, "LApp": 1}


class TestLoadInvertedIndex:
    """load_inverted_index returns symbol → set[decl_id]."""

    def test_returns_inverted_index(self, reader):
        ids = reader._ids
        inv = reader.load_inverted_index()

        # "Coq.Init.Nat.add" appears in both declarations' symbol_set
        assert "Coq.Init.Nat.add" in inv
        assert ids["Coq.Init.Nat.add"] in inv["Coq.Init.Nat.add"]
        assert ids["Coq.Init.Nat.mul"] in inv["Coq.Init.Nat.add"]

    def test_unique_symbol_maps_to_single_decl(self, reader):
        ids = reader._ids
        inv = reader.load_inverted_index()

        # "Coq.Init.Nat.mul" only in mul's symbol_set
        assert "Coq.Init.Nat.mul" in inv
        assert inv["Coq.Init.Nat.mul"] == {ids["Coq.Init.Nat.mul"]}


class TestLoadSymbolFrequencies:
    """load_symbol_frequencies returns symbol → freq map."""

    def test_returns_frequencies(self, reader):
        freqs = reader.load_symbol_frequencies()

        assert freqs["Coq.Init.Nat.add"] == 2
        assert freqs["Coq.Init.Nat.mul"] == 1


class TestGetDeclaration:
    """get_declaration returns a single row by name, or None."""

    def test_returns_existing_declaration(self, reader):
        decl = reader.get_declaration("Coq.Init.Nat.add")

        assert decl is not None
        assert decl["name"] == "Coq.Init.Nat.add"
        assert decl["module"] == "Coq.Init.Nat"
        assert decl["kind"] == "definition"

    def test_returns_none_for_missing(self, reader):
        assert reader.get_declaration("Nonexistent.decl") is None


class TestGetDeclarationsByIds:
    """get_declarations_by_ids returns rows for found IDs; omits missing."""

    def test_returns_found_ids(self, reader):
        ids = reader._ids
        all_ids = list(ids.values())
        results = reader.get_declarations_by_ids(all_ids)

        assert len(results) == 2

    def test_missing_ids_silently_omitted(self, reader):
        ids = reader._ids
        results = reader.get_declarations_by_ids([ids["Coq.Init.Nat.add"], 99999])

        assert len(results) == 1


class TestSearchFts:
    """search_fts returns declaration rows ranked by BM25, scores in [0, 1]."""

    def test_returns_matching_results(self, reader):
        results = reader.search_fts("add", limit=10)

        assert len(results) >= 1
        assert any(r["name"] == "Coq.Init.Nat.add" for r in results)

    def test_scores_normalized_zero_to_one(self, reader):
        results = reader.search_fts("Nat", limit=10)

        for r in results:
            assert 0.0 <= r["score"] <= 1.0

    def test_respects_limit(self, reader):
        results = reader.search_fts("Nat", limit=1)

        assert len(results) <= 1

    def test_fts5_stemming_matches_stemmed_forms(self, reader):
        """Porter stemming should allow 'adds' to match 'add'."""
        results = reader.search_fts("adds", limit=10)

        # Porter stemmer reduces "adds" → "add", which should match
        assert len(results) >= 1


class TestGetDependencies:
    """get_dependencies returns edges filtered by direction and relation."""

    def test_outgoing_dependencies(self, reader):
        ids = reader._ids

        # mul depends on add (outgoing from mul)
        deps = reader.get_dependencies(
            ids["Coq.Init.Nat.mul"], direction="outgoing", relation=None
        )
        assert len(deps) == 1

    def test_incoming_dependencies(self, reader):
        ids = reader._ids

        # add is depended on by mul (incoming to add)
        deps = reader.get_dependencies(
            ids["Coq.Init.Nat.add"], direction="incoming", relation=None
        )
        assert len(deps) == 1

    def test_filter_by_relation(self, reader):
        ids = reader._ids

        deps = reader.get_dependencies(
            ids["Coq.Init.Nat.mul"], direction="outgoing", relation="uses"
        )
        assert len(deps) == 1

        deps = reader.get_dependencies(
            ids["Coq.Init.Nat.mul"], direction="outgoing", relation="instance_of"
        )
        assert len(deps) == 0


class TestGetDeclarationsByModule:
    """get_declarations_by_module returns all declarations in a module."""

    def test_returns_module_declarations(self, reader):
        results = reader.get_declarations_by_module("Coq.Init.Nat", exclude_id=None)

        assert len(results) == 2

    def test_excludes_specified_id(self, reader):
        ids = reader._ids
        results = reader.get_declarations_by_module(
            "Coq.Init.Nat", exclude_id=ids["Coq.Init.Nat.add"]
        )

        assert len(results) == 1
        assert results[0]["name"] == "Coq.Init.Nat.mul"


class TestListModules:
    """list_modules returns Module entries with declaration counts."""

    def test_returns_modules_with_counts(self, reader):
        modules = reader.list_modules("")

        assert len(modules) >= 1
        mod = next(m for m in modules if m["module"] == "Coq.Init.Nat")
        assert mod["count"] == 2

    def test_filters_by_prefix(self, reader):
        results = reader.list_modules("Coq.Init")
        assert len(results) >= 1

        results = reader.list_modules("Nonexistent")
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════════════
# 4. Error Hierarchy
# ═══════════════════════════════════════════════════════════════════════════


class TestErrorHierarchy:
    """StorageError is the base; IndexNotFoundError and IndexVersionError
    are subclasses."""

    def test_storage_error_is_exception(self):
        assert issubclass(StorageError, Exception)

    def test_index_not_found_is_storage_error(self):
        assert issubclass(IndexNotFoundError, StorageError)

    def test_index_version_error_is_storage_error(self):
        assert issubclass(IndexVersionError, StorageError)

    def test_index_version_error_carries_versions(self):
        err = IndexVersionError(found="1", expected="2")
        assert err.found == "1"
        assert err.expected == "2"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Integrity Check Failure
# ═══════════════════════════════════════════════════════════════════════════


class TestIntegrityCheckFailure:
    """On integrity check failure: close connection, delete DB, raise
    StorageError."""

    def test_failed_integrity_deletes_database(self, tmp_db_path, monkeypatch):
        writer = IndexWriter.create(tmp_db_path)
        writer.insert_declarations([_sample_declaration()])

        # Corrupt the database before finalize to trigger integrity failure.
        # We monkeypatch the integrity check to simulate failure.
        original_finalize = type(writer).finalize

        def _corrupt_finalize(self):
            # Force the integrity check to detect corruption
            conn = sqlite3.connect(tmp_db_path)
            # Overwrite a page to simulate corruption
            conn.close()
            with open(tmp_db_path, "r+b") as f:
                f.seek(2000)
                f.write(b"\x00" * 100)
            original_finalize(self)

        monkeypatch.setattr(type(writer), "finalize", _corrupt_finalize)

        with pytest.raises(StorageError):
            writer.finalize()

        assert not tmp_db_path.exists()


# ═══════════════════════════════════════════════════════════════════════════
# 6. GetConstrTrees
# ═══════════════════════════════════════════════════════════════════════════


class TestGetConstrTrees:
    """get_constr_trees returns id → deserialized ExprTree for non-null
    constr_tree fields."""

    def test_returns_trees_for_non_null(self, tmp_db_path):
        writer = IndexWriter.create(tmp_db_path)
        # One declaration with a constr_tree, one without
        decl_with = _sample_declaration(
            name="A.with_tree",
            module="A",
            constr_tree=b"serialized_tree_data",
        )
        decl_without = _sample_declaration(
            name="A.without_tree",
            module="A",
            constr_tree=None,
        )
        ids = writer.insert_declarations([decl_with, decl_without])
        writer.write_meta("schema_version", "1")
        writer.write_meta("coq_version", "8.19")
        writer.write_meta("mathcomp_version", "none")
        writer.write_meta("created_at", "2026-03-16T00:00:00Z")
        writer.finalize()

        with IndexReader.open(tmp_db_path) as r:
            trees = r.get_constr_trees(list(ids.values()))

        assert ids["A.with_tree"] in trees
        assert ids["A.without_tree"] not in trees

    def test_empty_ids_returns_empty(self, reader):
        trees = reader.get_constr_trees([])

        assert trees == {}
