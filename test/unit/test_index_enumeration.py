"""TDD tests for index-based declaration enumeration.

Tests for replacing regex-based theorem enumeration with SQLite index queries
(specification/extraction-campaign.md §4.1).

Covers: _enumerate_from_index, module_to_source_file, PROOF_NOT_FOUND → no_proof_body
mapping, build_campaign_plan with index_db_path, removal of _THEOREM_RE and
_enumerate_theorems, get_provable_declarations query, summary statistics with
no_proof_body.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _create_test_index_db(db_path: Path, declarations: list[dict] | None = None) -> None:
    """Create a minimal index.db with declarations for testing.

    Each declaration dict should have keys: name, module, kind.
    Optional keys: id, statement, type_expr, node_count, symbol_set, has_proof_body.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE declarations ("
        "  id INTEGER PRIMARY KEY,"
        "  name TEXT UNIQUE NOT NULL,"
        "  module TEXT NOT NULL,"
        "  kind TEXT NOT NULL,"
        "  statement TEXT DEFAULT '',"
        "  type_expr TEXT,"
        "  constr_tree BLOB,"
        "  node_count INTEGER DEFAULT 1,"
        "  symbol_set TEXT DEFAULT '[]',"
        "  has_proof_body INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute(
        "CREATE TABLE dependencies (src INTEGER, dst INTEGER, relation TEXT)"
    )
    conn.execute("CREATE TABLE index_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO index_meta (key, value) VALUES ('schema_version', '1')"
    )
    conn.execute(
        "INSERT INTO index_meta (key, value) VALUES ('coq_version', '9.1.1')"
    )
    conn.execute(
        "INSERT INTO index_meta (key, value) VALUES ('created_at', '2026-03-22T00:00:00Z')"
    )

    if declarations:
        for i, decl in enumerate(declarations, start=1):
            conn.execute(
                "INSERT INTO declarations (id, name, module, kind, statement, has_proof_body) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    decl.get("id", i),
                    decl["name"],
                    decl["module"],
                    decl["kind"],
                    decl.get("statement", f"Statement of {decl['name']}"),
                    decl.get("has_proof_body", 0),
                ),
            )

    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# 1. module_to_source_file (§4.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestModuleToSourceFile:
    """module_to_source_file maps dot-separated module paths to relative file paths."""

    def test_stdlib_prefix(self):
        from Poule.extraction.campaign import module_to_source_file

        result = module_to_source_file("Stdlib.Reals.Ranalysis1", "Stdlib.")
        assert result == "Reals/Ranalysis1.v"

    def test_mathcomp_prefix(self):
        from Poule.extraction.campaign import module_to_source_file

        result = module_to_source_file("mathcomp.algebra.ring", "mathcomp.")
        assert result == "algebra/ring.v"

    def test_stdpp_prefix(self):
        from Poule.extraction.campaign import module_to_source_file

        result = module_to_source_file("stdpp.fin_maps", "stdpp.")
        assert result == "fin_maps.v"

    def test_flocq_prefix(self):
        from Poule.extraction.campaign import module_to_source_file

        result = module_to_source_file("Flocq.Core.Raux", "Flocq.")
        assert result == "Core/Raux.v"

    def test_coquelicot_prefix(self):
        from Poule.extraction.campaign import module_to_source_file

        result = module_to_source_file("Coquelicot.Derive", "Coquelicot.")
        assert result == "Derive.v"

    def test_interval_prefix(self):
        from Poule.extraction.campaign import module_to_source_file

        result = module_to_source_file("Interval.Tactic", "Interval.")
        assert result == "Tactic.v"

    def test_corelib_alias_for_stdlib(self):
        """Rocq 9.x uses Corelib. as an alias for Coq. (§4.1)."""
        from Poule.extraction.campaign import module_to_source_file

        result = module_to_source_file("Corelib.Init.Logic", "Stdlib.")
        assert result == "Init/Logic.v"

    def test_deeply_nested_module(self):
        from Poule.extraction.campaign import module_to_source_file

        result = module_to_source_file(
            "Stdlib.Arith.PeanoNat", "Stdlib."
        )
        assert result == "Arith/PeanoNat.v"


# ═══════════════════════════════════════════════════════════════════════════
# 2. _enumerate_from_index (§4.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestEnumerateFromIndex:
    """_enumerate_from_index queries the index DB for provable declarations."""

    def test_returns_declarations_from_index(self, tmp_path):
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Stdlib.Init.Logic.eq_refl", "module": "Stdlib.Init.Logic", "kind": "lemma"},
            {"name": "Stdlib.Arith.PeanoNat.Nat.add_comm", "module": "Stdlib.Arith.PeanoNat", "kind": "theorem"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Stdlib.")
        assert len(targets) == 2

    def test_includes_instances(self, tmp_path):
        """Instance declarations are included (previously missed by regex)."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Stdlib.Classes.Morphisms.eq_Reflexive", "module": "Stdlib.Classes.Morphisms", "kind": "instance"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Stdlib.")
        assert len(targets) == 1
        assert targets[0][3] == "instance"  # decl_kind

    def test_includes_definitions(self, tmp_path):
        """Definition declarations are included."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Stdlib.Init.Datatypes.andb", "module": "Stdlib.Init.Datatypes", "kind": "definition"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Stdlib.")
        assert len(targets) == 1
        assert targets[0][3] == "definition"

    def test_excludes_inductives_and_constructors(self, tmp_path):
        """Inductive and constructor kinds are not provable — exclude them."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Stdlib.Init.Datatypes.nat", "module": "Stdlib.Init.Datatypes", "kind": "inductive"},
            {"name": "Stdlib.Init.Datatypes.O", "module": "Stdlib.Init.Datatypes", "kind": "constructor"},
            {"name": "Stdlib.Init.Logic.eq_refl", "module": "Stdlib.Init.Logic", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Stdlib.")
        assert len(targets) == 1
        names = [t[2] for t in targets]
        assert "Stdlib.Init.Logic.eq_refl" in names

    def test_excludes_axioms(self, tmp_path):
        """Axioms have no proof body — exclude them."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Stdlib.Logic.ClassicalFacts.prop_degen", "module": "Stdlib.Logic.ClassicalFacts", "kind": "axiom"},
            {"name": "Stdlib.Init.Logic.eq_refl", "module": "Stdlib.Init.Logic", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Stdlib.")
        assert len(targets) == 1

    def test_targets_contain_fqn(self, tmp_path):
        """Theorem names are fully qualified from the index, not short names."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Stdlib.Arith.PeanoNat.Nat.add_comm", "module": "Stdlib.Arith.PeanoNat", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Stdlib.")
        assert targets[0][2] == "Stdlib.Arith.PeanoNat.Nat.add_comm"

    def test_targets_contain_source_file(self, tmp_path):
        """Source file is derived from module path."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Stdlib.Arith.PeanoNat.Nat.add_comm", "module": "Stdlib.Arith.PeanoNat", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Stdlib.")
        assert targets[0][1] == "Arith/PeanoNat.v"

    def test_targets_ordered_by_module_then_name(self, tmp_path):
        """Targets are ordered by (module, name) — deterministic ordering."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Stdlib.Arith.PeanoNat.Nat.mul_comm", "module": "Stdlib.Arith.PeanoNat", "kind": "lemma"},
            {"name": "Stdlib.Init.Logic.eq_refl", "module": "Stdlib.Init.Logic", "kind": "lemma"},
            {"name": "Stdlib.Arith.PeanoNat.Nat.add_comm", "module": "Stdlib.Arith.PeanoNat", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Stdlib.")
        names = [t[2] for t in targets]
        # Within Coq.Arith.PeanoNat, add_comm before mul_comm (alphabetical)
        # Coq.Arith before Coq.Init
        assert names.index("Stdlib.Arith.PeanoNat.Nat.add_comm") < names.index("Stdlib.Arith.PeanoNat.Nat.mul_comm")
        assert names.index("Stdlib.Arith.PeanoNat.Nat.mul_comm") < names.index("Stdlib.Init.Logic.eq_refl")


# ═══════════════════════════════════════════════════════════════════════════
# 3. get_provable_declarations (IndexReader)
# ═══════════════════════════════════════════════════════════════════════════


class TestGetProvableDeclarations:
    """IndexReader.get_provable_declarations returns declarations suitable for extraction."""

    def test_returns_lemmas_theorems_instances_definitions(self, tmp_path):
        from Poule.storage.reader import IndexReader

        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "A.lemma1", "module": "A", "kind": "lemma"},
            {"name": "A.thm1", "module": "A", "kind": "theorem"},
            {"name": "A.inst1", "module": "A", "kind": "instance"},
            {"name": "A.def1", "module": "A", "kind": "definition"},
            {"name": "A.ind1", "module": "A", "kind": "inductive"},
            {"name": "A.ctr1", "module": "A", "kind": "constructor"},
            {"name": "A.ax1", "module": "A", "kind": "axiom"},
        ])

        reader = IndexReader.open(db_path)
        decls = reader.get_provable_declarations()
        reader.close()

        kinds = {d["kind"] for d in decls}
        assert kinds == {"lemma", "theorem", "instance", "definition"}
        assert len(decls) == 4

    def test_filters_by_module_prefix(self, tmp_path):
        from Poule.storage.reader import IndexReader

        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "Stdlib.Init.Logic.eq_refl", "module": "Stdlib.Init.Logic", "kind": "lemma"},
            {"name": "mathcomp.algebra.ring.mulrC", "module": "mathcomp.algebra.ring", "kind": "lemma"},
        ])

        reader = IndexReader.open(db_path)
        decls = reader.get_provable_declarations(module_prefix="Stdlib.")
        reader.close()

        assert len(decls) == 1
        assert decls[0]["name"] == "Stdlib.Init.Logic.eq_refl"

    def test_ordered_by_module_then_name(self, tmp_path):
        from Poule.storage.reader import IndexReader

        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "B.z", "module": "B", "kind": "lemma"},
            {"name": "A.b", "module": "A", "kind": "lemma"},
            {"name": "A.a", "module": "A", "kind": "lemma"},
        ])

        reader = IndexReader.open(db_path)
        decls = reader.get_provable_declarations()
        reader.close()

        names = [d["name"] for d in decls]
        assert names == ["A.a", "A.b", "B.z"]


# ═══════════════════════════════════════════════════════════════════════════
# 3b. has_proof_body filtering (specification/storage.md, extraction-campaign.md)
# ═══════════════════════════════════════════════════════════════════════════


class TestHasProofBodyFiltering:
    """get_provable_declarations filters on has_proof_body when requested."""

    def test_filters_to_only_proof_body_declarations(self, tmp_path):
        from Poule.storage.reader import IndexReader

        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "A.with_proof", "module": "A", "kind": "lemma", "has_proof_body": 1},
            {"name": "A.no_proof", "module": "A", "kind": "definition", "has_proof_body": 0},
            {"name": "A.included", "module": "A", "kind": "theorem", "has_proof_body": 0},
        ])

        reader = IndexReader.open(db_path)
        decls = reader.get_provable_declarations(has_proof_body=True)
        reader.close()

        assert len(decls) == 1
        assert decls[0]["name"] == "A.with_proof"

    def test_no_filter_returns_all(self, tmp_path):
        from Poule.storage.reader import IndexReader

        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "A.with_proof", "module": "A", "kind": "lemma", "has_proof_body": 1},
            {"name": "A.no_proof", "module": "A", "kind": "definition", "has_proof_body": 0},
        ])

        reader = IndexReader.open(db_path)
        decls = reader.get_provable_declarations()
        reader.close()

        assert len(decls) == 2

    def test_has_proof_body_field_in_result(self, tmp_path):
        from Poule.storage.reader import IndexReader

        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "A.thm", "module": "A", "kind": "theorem", "has_proof_body": 1},
        ])

        reader = IndexReader.open(db_path)
        decls = reader.get_provable_declarations()
        reader.close()

        assert "has_proof_body" in decls[0]
        assert decls[0]["has_proof_body"] == 1

    def test_combined_with_module_prefix(self, tmp_path):
        from Poule.storage.reader import IndexReader

        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "Stdlib.A.thm1", "module": "Stdlib.A", "kind": "lemma", "has_proof_body": 1},
            {"name": "Stdlib.A.def1", "module": "Stdlib.A", "kind": "definition", "has_proof_body": 0},
            {"name": "mc.B.thm1", "module": "mc.B", "kind": "lemma", "has_proof_body": 1},
        ])

        reader = IndexReader.open(db_path)
        decls = reader.get_provable_declarations(module_prefix="Stdlib.", has_proof_body=True)
        reader.close()

        assert len(decls) == 1
        assert decls[0]["name"] == "Stdlib.A.thm1"


class TestCampaignPlanFiltersOnProofBody:
    """build_campaign_plan uses has_proof_body to filter targets."""

    def test_plan_excludes_no_proof_body_declarations(self, tmp_path):
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "stdlib"
        proj.mkdir()
        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "Stdlib.A.thm1", "module": "Stdlib.A", "kind": "lemma", "has_proof_body": 1},
            {"name": "Stdlib.A.def1", "module": "Stdlib.A", "kind": "definition", "has_proof_body": 0},
            {"name": "Stdlib.A.included", "module": "Stdlib.A", "kind": "theorem", "has_proof_body": 0},
        ])

        plan = build_campaign_plan(
            [str(proj)], index_db_path=str(db_path), module_prefix="Stdlib."
        )
        assert len(plan.targets) == 1
        assert plan.targets[0][2] == "Stdlib.A.thm1"

    def test_plan_fallback_when_all_zero(self, tmp_path):
        """Backward compat: if all has_proof_body=0, fall back to unfiltered."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "stdlib"
        proj.mkdir()
        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "Stdlib.A.thm1", "module": "Stdlib.A", "kind": "lemma", "has_proof_body": 0},
            {"name": "Stdlib.A.thm2", "module": "Stdlib.A", "kind": "theorem", "has_proof_body": 0},
        ])

        plan = build_campaign_plan(
            [str(proj)], index_db_path=str(db_path), module_prefix="Stdlib."
        )
        # Fallback: returns all provable declarations
        assert len(plan.targets) == 2


# ═══════════════════════════════════════════════════════════════════════════
# 4. NO_PROOF_BODY error kind mapping (§4.2)
# ═══════════════════════════════════════════════════════════════════════════


class TestNoProofBodyErrorKind:
    """PROOF_NOT_FOUND SessionError maps to no_proof_body error kind."""

    def test_proof_not_found_maps_to_no_proof_body(self):
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionError
        from Poule.session.errors import PROOF_NOT_FOUND, SessionError

        sm = AsyncMock()
        sm.create_session = AsyncMock(
            side_effect=SessionError(PROOF_NOT_FOUND, "No proof body found")
        )
        sm.close_session = AsyncMock()

        result = asyncio.run(extract_single_proof(
            sm, "proj", "Init/Datatypes.v", "Stdlib.Init.Datatypes.andb",
        ))

        assert isinstance(result, ExtractionError)
        assert result.error_kind == "no_proof_body"

    def test_no_proof_body_in_error_kind_enum(self):
        from Poule.extraction.types import ErrorKind

        assert hasattr(ErrorKind, "NO_PROOF_BODY")
        assert ErrorKind.NO_PROOF_BODY.value == "no_proof_body"


# ═══════════════════════════════════════════════════════════════════════════
# 5. build_campaign_plan with index_db_path (§4.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildCampaignPlanWithIndex:
    """build_campaign_plan accepts index_db_path and uses index for enumeration."""

    def test_requires_index_db_path(self, tmp_path):
        """build_campaign_plan requires index_db_path parameter."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "stdlib"
        proj.mkdir()
        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "Stdlib.Init.Logic.eq_refl", "module": "Stdlib.Init.Logic", "kind": "lemma"},
        ])

        # Should work with index_db_path
        plan = build_campaign_plan(
            [str(proj)], index_db_path=str(db_path), module_prefix="Stdlib."
        )
        assert len(plan.targets) >= 1

    def test_missing_index_raises_error(self, tmp_path):
        """Missing index_db_path raises an error."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "stdlib"
        proj.mkdir()

        with pytest.raises(Exception):
            build_campaign_plan(
                [str(proj)], index_db_path=str(tmp_path / "missing.db"),
                module_prefix="Stdlib."
            )

    def test_targets_use_fqn_from_index(self, tmp_path):
        """Campaign targets use fully qualified names from the index."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "stdlib"
        proj.mkdir()
        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "Stdlib.Arith.PeanoNat.Nat.add_comm", "module": "Stdlib.Arith.PeanoNat", "kind": "lemma"},
        ])

        plan = build_campaign_plan(
            [str(proj)], index_db_path=str(db_path), module_prefix="Stdlib."
        )
        # Targets are now 4-tuples: (project_id, source_file, fqn, decl_kind)
        assert plan.targets[0][2] == "Stdlib.Arith.PeanoNat.Nat.add_comm"

    def test_targets_include_decl_kind(self, tmp_path):
        """Campaign targets include declaration kind as fourth element."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "stdlib"
        proj.mkdir()
        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "Stdlib.Init.Logic.eq_refl", "module": "Stdlib.Init.Logic", "kind": "lemma"},
            {"name": "Stdlib.Classes.Morphisms.eq_Reflexive", "module": "Stdlib.Classes.Morphisms", "kind": "instance"},
        ])

        plan = build_campaign_plan(
            [str(proj)], index_db_path=str(db_path), module_prefix="Stdlib."
        )
        kinds = {t[3] for t in plan.targets}
        assert "lemma" in kinds
        assert "instance" in kinds


# ═══════════════════════════════════════════════════════════════════════════
# 5b. FQN-to-proof-name conversion (§4.2)
# ═══════════════════════════════════════════════════════════════════════════


class TestFqnToProofName:
    """fqn_to_proof_name strips module prefix from FQN to get the
    document-internal name that Petanque can resolve (§4.2 line 129)."""

    def test_strips_module_prefix_from_fqn(self):
        """Stdlib.Arith.PeanoNat.Nat.add_comm with source Arith/PeanoNat.v → Nat.add_comm"""
        from Poule.extraction.campaign import fqn_to_proof_name

        result = fqn_to_proof_name(
            "Stdlib.Arith.PeanoNat.Nat.add_comm", "Arith/PeanoNat.v"
        )
        assert result == "Nat.add_comm"

    def test_top_level_name_in_module(self):
        """Stdlib.Init.Logic.eq_refl with source Init/Logic.v → eq_refl"""
        from Poule.extraction.campaign import fqn_to_proof_name

        result = fqn_to_proof_name(
            "Stdlib.Init.Logic.eq_refl", "Init/Logic.v"
        )
        assert result == "eq_refl"

    def test_mathcomp_nested_module(self):
        """mathcomp.algebra.ring.Ring.sort with source algebra/ring.v → Ring.sort"""
        from Poule.extraction.campaign import fqn_to_proof_name

        result = fqn_to_proof_name(
            "mathcomp.algebra.ring.Ring.sort", "algebra/ring.v"
        )
        assert result == "Ring.sort"

    def test_single_level_source_file(self):
        """Coquelicot.Derive.some_thm with source Derive.v → some_thm"""
        from Poule.extraction.campaign import fqn_to_proof_name

        result = fqn_to_proof_name(
            "Coquelicot.Derive.some_thm", "Derive.v"
        )
        assert result == "some_thm"

    def test_no_match_falls_back_to_short_name(self):
        """When module suffix is not found in FQN, fall back to last component."""
        from Poule.extraction.campaign import fqn_to_proof_name

        result = fqn_to_proof_name(
            "Some.Other.Module.thm_name", "Unrelated/File.v"
        )
        assert result == "thm_name"

    def test_short_name_unchanged(self):
        """A short name without dots passes through unchanged."""
        from Poule.extraction.campaign import fqn_to_proof_name

        result = fqn_to_proof_name("eq_refl", "Logic.v")
        assert result == "eq_refl"


class TestDoExtractionUsesProofName:
    """_do_extraction converts FQN to document-internal name before
    calling create_session, while keeping FQN in ExtractionRecord (§4.2)."""

    def test_create_session_receives_internal_name(self):
        """create_session should receive the document-internal name,
        not the full FQN from the index."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionRecord

        sm = AsyncMock()
        sm.create_session = AsyncMock(return_value=("session-1", Mock()))
        sm.extract_trace = AsyncMock(return_value=Mock(
            total_steps=0, steps=[], partial=False,
        ))
        sm.get_premises = AsyncMock(return_value=[])
        sm.close_session = AsyncMock()

        asyncio.run(extract_single_proof(
            sm, "stdlib", "Arith/PeanoNat.v",
            "Stdlib.Arith.PeanoNat.Nat.add_comm",
            project_path="/data/stdlib",
        ))

        # create_session should be called with the internal name
        call_args = sm.create_session.call_args
        proof_name_arg = call_args[0][1]  # second positional arg
        assert proof_name_arg == "Nat.add_comm", (
            f"Expected 'Nat.add_comm' but got '{proof_name_arg}'"
        )

    def test_extraction_record_keeps_fqn(self):
        """The ExtractionRecord stores the original FQN, not the
        internal proof name."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionRecord

        sm = AsyncMock()
        sm.create_session = AsyncMock(return_value=("session-1", Mock()))
        sm.extract_trace = AsyncMock(return_value=Mock(
            total_steps=0, steps=[], partial=False,
        ))
        sm.get_premises = AsyncMock(return_value=[])
        sm.close_session = AsyncMock()

        result = asyncio.run(extract_single_proof(
            sm, "stdlib", "Arith/PeanoNat.v",
            "Stdlib.Arith.PeanoNat.Nat.add_comm",
            project_path="/data/stdlib",
        ))

        assert isinstance(result, ExtractionRecord)
        assert result.theorem_name == "Stdlib.Arith.PeanoNat.Nat.add_comm"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Removal of regex enumeration
# ═══════════════════════════════════════════════════════════════════════════


class TestRegexEnumerationRemoved:
    """Regex-based enumeration functions no longer exist in campaign module."""

    def test_theorem_re_removed(self):
        import Poule.extraction.campaign as mod

        assert not hasattr(mod, "_THEOREM_RE"), (
            "_THEOREM_RE should be deleted — enumeration is now index-based"
        )

    def test_enumerate_theorems_removed(self):
        import Poule.extraction.campaign as mod

        assert not hasattr(mod, "_enumerate_theorems"), (
            "_enumerate_theorems should be deleted — enumeration is now index-based"
        )

    def test_build_plan_from_regex_removed(self):
        import Poule.extraction.campaign as mod

        assert not hasattr(mod, "_build_plan_from_regex"), (
            "_build_plan_from_regex should be deleted — enumeration is now index-based"
        )

    def test_index_db_path_required(self, tmp_path):
        """build_campaign_plan raises ValueError when index_db_path is None."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()

        with pytest.raises(ValueError, match="index_db_path"):
            build_campaign_plan([str(proj)], scope_filter=None)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Summary statistics with no_proof_body (§4.3)
# ═══════════════════════════════════════════════════════════════════════════


class TestSummaryNoProofBody:
    """ExtractionSummary includes no_proof_body count separate from failed."""

    def test_extraction_summary_has_no_proof_body_field(self):
        from Poule.extraction.types import ExtractionSummary

        summary = ExtractionSummary(
            schema_version=1,
            record_type="extraction_summary",
            total_theorems_found=100,
            total_extracted=80,
            total_failed=5,
            total_no_proof_body=10,
            total_skipped=5,
            per_project=[],
        )
        assert summary.total_no_proof_body == 10

    def test_project_summary_has_no_proof_body_field(self):
        from Poule.extraction.types import ProjectSummary

        ps = ProjectSummary(
            project_id="stdlib",
            theorems_found=100,
            extracted=80,
            failed=5,
            no_proof_body=10,
            skipped=5,
            per_file=[],
        )
        assert ps.no_proof_body == 10

    def test_file_summary_has_no_proof_body_field(self):
        from Poule.extraction.types import FileSummary

        fs = FileSummary(
            source_file="Init/Logic.v",
            theorems_found=20,
            extracted=15,
            failed=1,
            no_proof_body=3,
            skipped=1,
        )
        assert fs.no_proof_body == 3

    def test_summary_invariant(self):
        """extracted + failed + no_proof_body + skipped == theorems_found."""
        from Poule.extraction.types import ExtractionSummary

        summary = ExtractionSummary(
            schema_version=1,
            record_type="extraction_summary",
            total_theorems_found=100,
            total_extracted=80,
            total_failed=5,
            total_no_proof_body=10,
            total_skipped=5,
            per_project=[],
        )
        total = (
            summary.total_extracted
            + summary.total_failed
            + summary.total_no_proof_body
            + summary.total_skipped
        )
        assert total == summary.total_theorems_found
