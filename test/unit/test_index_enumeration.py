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
    Optional keys: id, statement, type_expr, node_count, symbol_set.
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
        "  symbol_set TEXT DEFAULT '[]'"
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
                "INSERT INTO declarations (id, name, module, kind, statement) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    decl.get("id", i),
                    decl["name"],
                    decl["module"],
                    decl["kind"],
                    decl.get("statement", f"Statement of {decl['name']}"),
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

        result = module_to_source_file("Coq.Reals.Ranalysis1", "Coq.")
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

        result = module_to_source_file("Corelib.Init.Logic", "Coq.")
        assert result == "Init/Logic.v"

    def test_deeply_nested_module(self):
        from Poule.extraction.campaign import module_to_source_file

        result = module_to_source_file(
            "Coq.Arith.PeanoNat", "Coq."
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
            {"name": "Coq.Init.Logic.eq_refl", "module": "Coq.Init.Logic", "kind": "lemma"},
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm", "module": "Coq.Arith.PeanoNat", "kind": "theorem"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Coq.")
        assert len(targets) == 2

    def test_includes_instances(self, tmp_path):
        """Instance declarations are included (previously missed by regex)."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Coq.Classes.Morphisms.eq_Reflexive", "module": "Coq.Classes.Morphisms", "kind": "instance"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Coq.")
        assert len(targets) == 1
        assert targets[0][3] == "instance"  # decl_kind

    def test_includes_definitions(self, tmp_path):
        """Definition declarations are included."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Coq.Init.Datatypes.andb", "module": "Coq.Init.Datatypes", "kind": "definition"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Coq.")
        assert len(targets) == 1
        assert targets[0][3] == "definition"

    def test_excludes_inductives_and_constructors(self, tmp_path):
        """Inductive and constructor kinds are not provable — exclude them."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Coq.Init.Datatypes.nat", "module": "Coq.Init.Datatypes", "kind": "inductive"},
            {"name": "Coq.Init.Datatypes.O", "module": "Coq.Init.Datatypes", "kind": "constructor"},
            {"name": "Coq.Init.Logic.eq_refl", "module": "Coq.Init.Logic", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Coq.")
        assert len(targets) == 1
        names = [t[2] for t in targets]
        assert "Coq.Init.Logic.eq_refl" in names

    def test_excludes_axioms(self, tmp_path):
        """Axioms have no proof body — exclude them."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Coq.Logic.ClassicalFacts.prop_degen", "module": "Coq.Logic.ClassicalFacts", "kind": "axiom"},
            {"name": "Coq.Init.Logic.eq_refl", "module": "Coq.Init.Logic", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Coq.")
        assert len(targets) == 1

    def test_targets_contain_fqn(self, tmp_path):
        """Theorem names are fully qualified from the index, not short names."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm", "module": "Coq.Arith.PeanoNat", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Coq.")
        assert targets[0][2] == "Coq.Arith.PeanoNat.Nat.add_comm"

    def test_targets_contain_source_file(self, tmp_path):
        """Source file is derived from module path."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm", "module": "Coq.Arith.PeanoNat", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Coq.")
        assert targets[0][1] == "Arith/PeanoNat.v"

    def test_targets_ordered_by_module_then_name(self, tmp_path):
        """Targets are ordered by (module, name) — deterministic ordering."""
        from Poule.extraction.campaign import _enumerate_from_index

        db_path = tmp_path / "index.db"
        proj = tmp_path / "stdlib"
        proj.mkdir()

        _create_test_index_db(db_path, [
            {"name": "Coq.Arith.PeanoNat.Nat.mul_comm", "module": "Coq.Arith.PeanoNat", "kind": "lemma"},
            {"name": "Coq.Init.Logic.eq_refl", "module": "Coq.Init.Logic", "kind": "lemma"},
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm", "module": "Coq.Arith.PeanoNat", "kind": "lemma"},
        ])

        targets = _enumerate_from_index(str(db_path), [str(proj)], module_prefix="Coq.")
        names = [t[2] for t in targets]
        # Within Coq.Arith.PeanoNat, add_comm before mul_comm (alphabetical)
        # Coq.Arith before Coq.Init
        assert names.index("Coq.Arith.PeanoNat.Nat.add_comm") < names.index("Coq.Arith.PeanoNat.Nat.mul_comm")
        assert names.index("Coq.Arith.PeanoNat.Nat.mul_comm") < names.index("Coq.Init.Logic.eq_refl")


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
            {"name": "Coq.Init.Logic.eq_refl", "module": "Coq.Init.Logic", "kind": "lemma"},
            {"name": "mathcomp.algebra.ring.mulrC", "module": "mathcomp.algebra.ring", "kind": "lemma"},
        ])

        reader = IndexReader.open(db_path)
        decls = reader.get_provable_declarations(module_prefix="Coq.")
        reader.close()

        assert len(decls) == 1
        assert decls[0]["name"] == "Coq.Init.Logic.eq_refl"

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
            sm, "proj", "Init/Datatypes.v", "Coq.Init.Datatypes.andb",
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
            {"name": "Coq.Init.Logic.eq_refl", "module": "Coq.Init.Logic", "kind": "lemma"},
        ])

        # Should work with index_db_path
        plan = build_campaign_plan(
            [str(proj)], index_db_path=str(db_path), module_prefix="Coq."
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
                module_prefix="Coq."
            )

    def test_targets_use_fqn_from_index(self, tmp_path):
        """Campaign targets use fully qualified names from the index."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "stdlib"
        proj.mkdir()
        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm", "module": "Coq.Arith.PeanoNat", "kind": "lemma"},
        ])

        plan = build_campaign_plan(
            [str(proj)], index_db_path=str(db_path), module_prefix="Coq."
        )
        # Targets are now 4-tuples: (project_id, source_file, fqn, decl_kind)
        assert plan.targets[0][2] == "Coq.Arith.PeanoNat.Nat.add_comm"

    def test_targets_include_decl_kind(self, tmp_path):
        """Campaign targets include declaration kind as fourth element."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "stdlib"
        proj.mkdir()
        db_path = tmp_path / "index.db"
        _create_test_index_db(db_path, [
            {"name": "Coq.Init.Logic.eq_refl", "module": "Coq.Init.Logic", "kind": "lemma"},
            {"name": "Coq.Classes.Morphisms.eq_Reflexive", "module": "Coq.Classes.Morphisms", "kind": "instance"},
        ])

        plan = build_campaign_plan(
            [str(proj)], index_db_path=str(db_path), module_prefix="Coq."
        )
        kinds = {t[3] for t in plan.targets}
        assert "lemma" in kinds
        assert "instance" in kinds


# ═══════════════════════════════════════════════════════════════════════════
# 6. Removal of regex enumeration
# ═══════════════════════════════════════════════════════════════════════════


class TestRegexEnumerationRemoved:
    """_THEOREM_RE and _enumerate_theorems no longer exist in campaign module."""

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
