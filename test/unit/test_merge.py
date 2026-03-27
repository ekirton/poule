"""Tests for per-library index merging.

Spec: specification/prebuilt-distribution.md §4.8

Import paths under test:
  poule.cli.merge.merge_indexes  (or poule.storage.merge.merge_indexes)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from Poule.storage import IndexWriter, IndexReader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_per_library_db(path: Path, library_name: str, declarations: list[dict],
                           dependencies: list[tuple[str, str]] | None = None,
                           coq_version: str = "8.19.2",
                           schema_version: str = "1",
                           library_version: str = "1.0.0") -> Path:
    """Create a per-library index database with the given declarations.

    Each declaration dict must have: name, module, kind, statement, type_expr,
    node_count, symbol_set. constr_tree defaults to None.
    """
    writer = IndexWriter.create(path)
    ids = writer.insert_declarations(declarations)

    # Insert WL vectors (minimal: empty histograms)
    wl_rows = []
    for name, decl_id in ids.items():
        wl_rows.append({"decl_id": decl_id, "h": 3, "histogram": {}})
    writer.insert_wl_vectors(wl_rows)

    # Insert dependencies if provided (as name pairs)
    if dependencies:
        dep_rows = []
        for src_name, dst_name in dependencies:
            if src_name in ids and dst_name in ids:
                dep_rows.append({
                    "src": ids[src_name],
                    "dst": ids[dst_name],
                    "relation": "uses",
                })
        if dep_rows:
            writer.insert_dependencies(dep_rows)

    # Compute symbol frequencies
    freq: dict[str, int] = {}
    for d in declarations:
        for sym in d.get("symbol_set", []):
            freq[sym] = freq.get(sym, 0) + 1
    writer.insert_symbol_freq(freq)

    # Write metadata
    writer.write_meta("schema_version", schema_version)
    writer.write_meta("coq_version", coq_version)
    writer.write_meta("libraries", json.dumps([library_name]))
    writer.write_meta("library_versions", json.dumps({library_name: library_version}))
    writer.write_meta("created_at", "2026-03-18T00:00:00Z")

    writer.finalize()
    return path


def _stdlib_declarations():
    """Return sample stdlib declarations."""
    return [
        {
            "name": "Stdlib.Init.Nat.add",
            "module": "Stdlib.Init.Nat",
            "kind": "definition",
            "statement": "fix add (n m : nat) : nat",
            "type_expr": "nat -> nat -> nat",
            "constr_tree": None,
            "node_count": 5,
            "symbol_set": ["Stdlib.Init.Nat.add", "Stdlib.Init.Datatypes.nat"],
        },
        {
            "name": "Stdlib.Init.Nat.mul",
            "module": "Stdlib.Init.Nat",
            "kind": "definition",
            "statement": "fix mul (n m : nat) : nat",
            "type_expr": "nat -> nat -> nat",
            "constr_tree": None,
            "node_count": 6,
            "symbol_set": ["Stdlib.Init.Nat.mul", "Stdlib.Init.Nat.add", "Stdlib.Init.Datatypes.nat"],
        },
    ]


def _declarations_with_proof_body():
    """Return declarations with has_proof_body annotations."""
    return [
        {
            "name": "Lib.lemma1",
            "module": "Lib",
            "kind": "lemma",
            "statement": "forall n, n = n",
            "type_expr": "forall n : nat, n = n",
            "constr_tree": None,
            "node_count": 3,
            "symbol_set": [],
            "has_proof_body": 1,
        },
        {
            "name": "Lib.def1",
            "module": "Lib",
            "kind": "definition",
            "statement": "Definition def1 := 42",
            "type_expr": "nat",
            "constr_tree": None,
            "node_count": 1,
            "symbol_set": [],
            "has_proof_body": 0,
        },
    ]


def _mathcomp_declarations():
    """Return sample mathcomp declarations that reference stdlib."""
    return [
        {
            "name": "mathcomp.ssreflect.ssrbool.negb",
            "module": "mathcomp.ssreflect.ssrbool",
            "kind": "definition",
            "statement": "fun b : bool => if b then false else true",
            "type_expr": "bool -> bool",
            "constr_tree": None,
            "node_count": 4,
            "symbol_set": ["Stdlib.Init.Datatypes.bool"],
        },
    ]


# ---------------------------------------------------------------------------
# We need to import merge_indexes — try both possible locations per spec §9
# ---------------------------------------------------------------------------

try:
    from Poule.cli.merge import merge_indexes
except ImportError:
    try:
        from Poule.storage.merge import merge_indexes
    except ImportError:
        # TDD: will fail until implemented
        merge_indexes = None


pytestmark = pytest.mark.skipif(
    merge_indexes is None,
    reason="merge_indexes not yet implemented"
)


# ===========================================================================
# 1. Basic merge behavior
# ===========================================================================


class TestMergeBasic:
    """merge_indexes combines per-library databases into one."""

    def test_merge_single_library(self, tmp_path):
        """§4.8: Merging a single library produces a valid index."""
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", _stdlib_declarations(),
            library_version="8.19.2",
        )
        dest = tmp_path / "index.db"
        result = merge_indexes([("stdlib", stdlib_path)], dest)
        assert result["total_declarations"] == 2
        assert result["libraries"] == ["stdlib"]
        assert dest.exists()

    def test_merge_two_libraries(self, tmp_path):
        """§4.8: Given stdlib (2 decls) and mathcomp (1 decl), merged has 3."""
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", _stdlib_declarations(),
            library_version="8.19.2",
        )
        mc_path = _create_per_library_db(
            tmp_path / "index-mathcomp.db", "mathcomp", _mathcomp_declarations(),
            library_version="2.2.0",
        )
        dest = tmp_path / "index.db"
        result = merge_indexes([("stdlib", stdlib_path), ("mathcomp", mc_path)], dest)
        assert result["total_declarations"] == 3
        assert set(result["libraries"]) == {"stdlib", "mathcomp"}

    def test_merged_db_readable_by_index_reader(self, tmp_path):
        """§4.8: Merged DB must be a valid index usable by IndexReader."""
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", _stdlib_declarations(),
            library_version="8.19.2",
        )
        dest = tmp_path / "index.db"
        merge_indexes([("stdlib", stdlib_path)], dest)
        reader = IndexReader.open(dest)
        # Should be able to read declarations
        decl = reader.get_declaration("Stdlib.Init.Nat.add")
        assert decl is not None

    def test_deletes_existing_dest(self, tmp_path):
        """§4.8: If dest exists, it is deleted before merge."""
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", _stdlib_declarations(),
            library_version="8.19.2",
        )
        dest = tmp_path / "index.db"
        dest.write_text("old garbage")
        result = merge_indexes([("stdlib", stdlib_path)], dest)
        assert result["total_declarations"] == 2

    def test_has_proof_body_preserved(self, tmp_path):
        """§4.8: has_proof_body annotation survives merge."""
        decls = _declarations_with_proof_body()
        src_path = _create_per_library_db(
            tmp_path / "index-lib.db", "lib", decls,
            library_version="1.0.0",
        )
        dest = tmp_path / "index.db"
        merge_indexes([("lib", src_path)], dest)

        conn = sqlite3.connect(str(dest))
        rows = conn.execute(
            "SELECT name, has_proof_body FROM declarations ORDER BY name"
        ).fetchall()
        conn.close()

        by_name = {name: hpb for name, hpb in rows}
        assert by_name["Lib.lemma1"] == 1, "lemma should keep has_proof_body=1"
        assert by_name["Lib.def1"] == 0, "definition should keep has_proof_body=0"


# ===========================================================================
# 2. Dependency resolution
# ===========================================================================


class TestMergeDependencies:
    """Dependency edges are remapped during merge."""

    def test_intra_library_dependencies_preserved(self, tmp_path):
        """§4.8: Dependencies within a single library are preserved."""
        decls = _stdlib_declarations()
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", decls,
            dependencies=[("Stdlib.Init.Nat.mul", "Stdlib.Init.Nat.add")],
            library_version="8.19.2",
        )
        dest = tmp_path / "index.db"
        result = merge_indexes([("stdlib", stdlib_path)], dest)
        assert result["total_dependencies"] >= 1
        assert result["dropped_dependencies"] == 0

    def test_cross_library_dependencies_dropped_when_target_missing(self, tmp_path):
        """§4.8: Deps referencing declarations not in any source are dropped."""
        # mathcomp alone — its deps on stdlib decls can't be resolved
        mc_decls = _mathcomp_declarations()
        # Add a fake dependency that references a stdlib name not in this DB
        mc_path = _create_per_library_db(
            tmp_path / "index-mathcomp.db", "mathcomp", mc_decls,
            library_version="2.2.0",
        )
        # Manually add a dependency row referencing a non-existent name
        conn = sqlite3.connect(str(mc_path))
        # Get the only declaration's ID
        row = conn.execute("SELECT id FROM declarations LIMIT 1").fetchone()
        decl_id = row[0]
        # Insert a dep where dst doesn't exist in merged DB
        conn.execute(
            "INSERT INTO dependencies (src, dst, relation) VALUES (?, ?, ?)",
            (decl_id, 99999, "uses"),
        )
        conn.commit()
        conn.close()

        dest = tmp_path / "index.db"
        result = merge_indexes([("mathcomp", mc_path)], dest)
        assert result["dropped_dependencies"] >= 1

    def test_cross_library_deps_from_symbol_set_exact_fqn(self, tmp_path):
        """§4.8: Cross-library edges created from symbol_set exact FQN match."""
        # mathcomp's negb has symbol_set=["Stdlib.Init.Datatypes.bool"]
        # which exactly matches stdlib's Coq.Init.Datatypes.bool (if it existed)
        stdlib_decls = _stdlib_declarations() + [{
            "name": "Stdlib.Init.Datatypes.bool",
            "module": "Stdlib.Init.Datatypes",
            "kind": "inductive",
            "statement": "Inductive bool : Set := true | false",
            "type_expr": "Set",
            "constr_tree": None,
            "node_count": 1,
            "symbol_set": [],
        }]
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", stdlib_decls,
            library_version="8.19.2",
        )
        mc_path = _create_per_library_db(
            tmp_path / "index-mathcomp.db", "mathcomp", _mathcomp_declarations(),
            library_version="2.2.0",
        )
        dest = tmp_path / "index.db"
        result = merge_indexes([("stdlib", stdlib_path), ("mathcomp", mc_path)], dest)

        # negb → bool cross-library edge should exist
        conn = sqlite3.connect(str(dest))
        edge = conn.execute(
            "SELECT d1.name, d2.name FROM dependencies dep "
            "JOIN declarations d1 ON d1.id = dep.src "
            "JOIN declarations d2 ON d2.id = dep.dst "
            "WHERE d1.name = 'mathcomp.ssreflect.ssrbool.negb' "
            "AND d2.name = 'Stdlib.Init.Datatypes.bool'"
        ).fetchone()
        conn.close()
        assert edge is not None, "Cross-library edge negb→bool should exist"

    def test_cross_library_deps_suffix_resolution(self, tmp_path):
        """§4.8: Cross-library edges created via suffix match on short names."""
        # A declaration with symbol_set containing a short name "Nat.add"
        # should resolve to Stdlib.Init.Nat.add via suffix matching
        other_decls = [{
            "name": "Other.Lib.uses_add",
            "module": "Other.Lib",
            "kind": "definition",
            "statement": "forall n : nat, n + 0 = n",
            "type_expr": "forall n : nat, n + 0 = n",
            "constr_tree": None,
            "node_count": 5,
            "symbol_set": ["Nat.add"],  # short name, not FQN
        }]
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", _stdlib_declarations(),
            library_version="8.19.2",
        )
        other_path = _create_per_library_db(
            tmp_path / "index-other.db", "other", other_decls,
            library_version="1.0.0",
        )
        dest = tmp_path / "index.db"
        merge_indexes([("stdlib", stdlib_path), ("other", other_path)], dest)

        conn = sqlite3.connect(str(dest))
        edge = conn.execute(
            "SELECT d1.name, d2.name FROM dependencies dep "
            "JOIN declarations d1 ON d1.id = dep.src "
            "JOIN declarations d2 ON d2.id = dep.dst "
            "WHERE d1.name = 'Other.Lib.uses_add' "
            "AND d2.name = 'Stdlib.Init.Nat.add'"
        ).fetchone()
        conn.close()
        assert edge is not None, "Short name 'Nat.add' should resolve via suffix"

    def test_cross_library_deps_skip_self_references(self, tmp_path):
        """§4.8: Symbol-set resolution skips self-references."""
        decls = [{
            "name": "Stdlib.Init.Nat.add",
            "module": "Stdlib.Init.Nat",
            "kind": "definition",
            "statement": "fix add (n m : nat) : nat",
            "type_expr": "nat -> nat -> nat",
            "constr_tree": None,
            "node_count": 5,
            "symbol_set": ["Stdlib.Init.Nat.add"],  # self-reference
        }]
        db_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", decls,
            library_version="8.19.2",
        )
        dest = tmp_path / "index.db"
        result = merge_indexes([("stdlib", db_path)], dest)

        conn = sqlite3.connect(str(dest))
        edges = conn.execute("SELECT COUNT(*) FROM dependencies").fetchone()[0]
        conn.close()
        assert edges == 0, "Self-referencing symbol_set should not create edges"

    def test_cross_library_deps_skip_ambiguous_suffix(self, tmp_path):
        """§4.8: Ambiguous suffix matches are skipped."""
        decls = [
            {
                "name": "Lib.A.add",
                "module": "Lib.A",
                "kind": "definition",
                "statement": "Definition add := 1",
                "type_expr": "nat",
                "constr_tree": None,
                "node_count": 1,
                "symbol_set": [],
            },
            {
                "name": "Lib.B.add",
                "module": "Lib.B",
                "kind": "definition",
                "statement": "Definition add := 2",
                "type_expr": "nat",
                "constr_tree": None,
                "node_count": 1,
                "symbol_set": [],
            },
            {
                "name": "Lib.C.user",
                "module": "Lib.C",
                "kind": "definition",
                "statement": "Definition user := add",
                "type_expr": "nat",
                "constr_tree": None,
                "node_count": 1,
                "symbol_set": ["add"],  # ambiguous — matches both A.add and B.add
            },
        ]
        db_path = _create_per_library_db(
            tmp_path / "index-lib.db", "lib", decls,
            library_version="1.0.0",
        )
        dest = tmp_path / "index.db"
        merge_indexes([("lib", db_path)], dest)

        conn = sqlite3.connect(str(dest))
        edges = conn.execute(
            "SELECT COUNT(*) FROM dependencies WHERE src = "
            "(SELECT id FROM declarations WHERE name = 'Lib.C.user')"
        ).fetchone()[0]
        conn.close()
        assert edges == 0, "Ambiguous suffix 'add' should not create edges"


# ===========================================================================
# 3. Metadata
# ===========================================================================


class TestMergeMetadata:
    """Merged index_meta records library provenance."""

    def test_libraries_metadata(self, tmp_path):
        """§4.8: index_meta contains libraries JSON array."""
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", _stdlib_declarations(),
            library_version="8.19.2",
        )
        mc_path = _create_per_library_db(
            tmp_path / "index-mathcomp.db", "mathcomp", _mathcomp_declarations(),
            library_version="2.2.0",
        )
        dest = tmp_path / "index.db"
        merge_indexes([("stdlib", stdlib_path), ("mathcomp", mc_path)], dest)

        conn = sqlite3.connect(str(dest))
        libs = json.loads(
            conn.execute("SELECT value FROM index_meta WHERE key = 'libraries'").fetchone()[0]
        )
        assert set(libs) == {"stdlib", "mathcomp"}

        versions = json.loads(
            conn.execute("SELECT value FROM index_meta WHERE key = 'library_versions'").fetchone()[0]
        )
        assert versions["stdlib"] == "8.19.2"
        assert versions["mathcomp"] == "2.2.0"
        conn.close()

    def test_schema_version_preserved(self, tmp_path):
        """§4.8: schema_version from sources is preserved."""
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", _stdlib_declarations(),
            schema_version="1", library_version="8.19.2",
        )
        dest = tmp_path / "index.db"
        merge_indexes([("stdlib", stdlib_path)], dest)

        conn = sqlite3.connect(str(dest))
        sv = conn.execute("SELECT value FROM index_meta WHERE key = 'schema_version'").fetchone()[0]
        assert sv == "1"
        conn.close()


# ===========================================================================
# 4. Error cases
# ===========================================================================


class TestMergeErrors:
    """merge_indexes error handling."""

    def test_schema_version_mismatch_raises(self, tmp_path):
        """§4.8: Different schema_version raises error."""
        db1 = _create_per_library_db(
            tmp_path / "db1.db", "stdlib", _stdlib_declarations(),
            schema_version="1", library_version="8.19.2",
        )
        db2 = _create_per_library_db(
            tmp_path / "db2.db", "mathcomp", _mathcomp_declarations(),
            schema_version="2", library_version="2.2.0",
        )
        dest = tmp_path / "index.db"
        with pytest.raises(Exception, match="Schema version mismatch"):
            merge_indexes([("stdlib", db1), ("mathcomp", db2)], dest)

    def test_coq_version_mismatch_raises(self, tmp_path):
        """§4.8: Different coq_version raises error."""
        db1 = _create_per_library_db(
            tmp_path / "db1.db", "stdlib", _stdlib_declarations(),
            coq_version="8.19.2", library_version="8.19.2",
        )
        db2 = _create_per_library_db(
            tmp_path / "db2.db", "mathcomp", _mathcomp_declarations(),
            coq_version="8.20.0", library_version="2.2.0",
        )
        dest = tmp_path / "index.db"
        with pytest.raises(Exception, match="Coq version mismatch"):
            merge_indexes([("stdlib", db1), ("mathcomp", db2)], dest)


# ===========================================================================
# 5. FTS5 and symbol frequencies
# ===========================================================================


class TestMergeFTS:
    """FTS5 index and symbol frequencies are rebuilt during merge."""

    def test_fts_covers_all_merged_declarations(self, tmp_path):
        """§4.8: FTS5 index covers all merged declarations."""
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", _stdlib_declarations(),
            library_version="8.19.2",
        )
        mc_path = _create_per_library_db(
            tmp_path / "index-mathcomp.db", "mathcomp", _mathcomp_declarations(),
            library_version="2.2.0",
        )
        dest = tmp_path / "index.db"
        merge_indexes([("stdlib", stdlib_path), ("mathcomp", mc_path)], dest)

        conn = sqlite3.connect(str(dest))
        # FTS search for a stdlib declaration
        rows = conn.execute(
            "SELECT name FROM declarations_fts WHERE declarations_fts MATCH 'Nat'",
        ).fetchall()
        names = [r[0] for r in rows]
        assert any("Nat.add" in n for n in names)

        # FTS search for a mathcomp declaration
        rows = conn.execute(
            "SELECT name FROM declarations_fts WHERE declarations_fts MATCH 'negb'",
        ).fetchall()
        names = [r[0] for r in rows]
        assert any("negb" in n for n in names)
        conn.close()

    def test_symbol_frequencies_recomputed(self, tmp_path):
        """§4.8: Symbol frequencies are recomputed across merged set."""
        stdlib_path = _create_per_library_db(
            tmp_path / "index-stdlib.db", "stdlib", _stdlib_declarations(),
            library_version="8.19.2",
        )
        mc_path = _create_per_library_db(
            tmp_path / "index-mathcomp.db", "mathcomp", _mathcomp_declarations(),
            library_version="2.2.0",
        )
        dest = tmp_path / "index.db"
        merge_indexes([("stdlib", stdlib_path), ("mathcomp", mc_path)], dest)

        conn = sqlite3.connect(str(dest))
        # Stdlib.Init.Datatypes.nat appears in stdlib decls; bool in mathcomp
        nat_freq = conn.execute(
            "SELECT freq FROM symbol_freq WHERE symbol = 'Stdlib.Init.Datatypes.nat'",
        ).fetchone()
        assert nat_freq is not None
        assert nat_freq[0] >= 2  # appears in both stdlib declarations

        bool_freq = conn.execute(
            "SELECT freq FROM symbol_freq WHERE symbol = 'Stdlib.Init.Datatypes.bool'",
        ).fetchone()
        assert bool_freq is not None
        assert bool_freq[0] >= 1  # appears in mathcomp declaration
        conn.close()
