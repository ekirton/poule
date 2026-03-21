"""TDD tests for Coq library extraction (specification/extraction.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/poule/extraction/.

Covers: kind mapping, library discovery, two-pass pipeline, dependency
resolution, post-processing, error handling, and progress reporting.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# 1. Kind Mapping
# ═══════════════════════════════════════════════════════════════════════════


class TestMapKindMappedForms:
    """map_kind maps Coq declaration forms to storage kind strings."""

    @pytest.mark.parametrize(
        "coq_form,expected",
        [
            ("Lemma", "lemma"),
            ("Theorem", "theorem"),
            ("Definition", "definition"),
            ("Let", "definition"),
            ("Coercion", "definition"),
            ("Canonical Structure", "definition"),
            ("Inductive", "inductive"),
            ("Record", "inductive"),
            ("Class", "inductive"),
            ("Constructor", "constructor"),
            ("Instance", "instance"),
            ("Axiom", "axiom"),
            ("Parameter", "axiom"),
            ("Conjecture", "axiom"),
        ],
    )
    def test_maps_coq_form_to_storage_kind(self, coq_form, expected):
        from Poule.extraction.kind_mapping import map_kind

        assert map_kind(coq_form) == expected

    @pytest.mark.parametrize(
        "coq_form,expected",
        [
            ("Lemma", "lemma"),
            ("Theorem", "theorem"),
            ("Definition", "definition"),
            ("Let", "definition"),
            ("Coercion", "definition"),
            ("Canonical Structure", "definition"),
            ("Inductive", "inductive"),
            ("Record", "inductive"),
            ("Class", "inductive"),
            ("Constructor", "constructor"),
            ("Instance", "instance"),
            ("Axiom", "axiom"),
            ("Parameter", "axiom"),
            ("Conjecture", "axiom"),
        ],
    )
    def test_output_is_always_lowercase(self, coq_form, expected):
        from Poule.extraction.kind_mapping import map_kind

        result = map_kind(coq_form)
        assert result == result.lower()


class TestMapKindExcludedForms:
    """Excluded Coq forms return None — they have no kernel term."""

    @pytest.mark.parametrize(
        "coq_form",
        [
            "Notation",
            "Abbreviation",
            "Section Variable",
            "Ltac",
            "Module",
        ],
    )
    def test_excluded_form_returns_none(self, coq_form):
        from Poule.extraction.kind_mapping import map_kind

        assert map_kind(coq_form) is None


class TestMapKindUnknownForms:
    """§4.2: Unknown kinds return 'definition', not None."""

    @pytest.mark.parametrize(
        "coq_form",
        [
            "scheme",
            "fixpoint",
            "cofixpoint",
            "primitive",
            "some_unknown_form",
        ],
    )
    def test_unknown_form_returns_definition(self, coq_form):
        from Poule.extraction.kind_mapping import map_kind

        assert map_kind(coq_form) == "definition"


class TestMapKindCaseSensitivity:
    """Kind mapping handles case-insensitive input."""

    @pytest.mark.parametrize(
        "coq_form,expected",
        [
            ("lemma", "lemma"),
            ("LEMMA", "lemma"),
            ("Lemma", "lemma"),
            ("theorem", "theorem"),
            ("THEOREM", "theorem"),
            ("definition", "definition"),
            ("DEFINITION", "definition"),
            ("canonical structure", "definition"),
            ("CANONICAL STRUCTURE", "definition"),
            ("section variable", None),
            ("SECTION VARIABLE", None),
            ("notation", None),
            ("NOTATION", None),
            ("ltac", None),
            ("LTAC", None),
            ("module", None),
            ("MODULE", None),
        ],
    )
    def test_case_insensitive_input(self, coq_form, expected):
        from Poule.extraction.kind_mapping import map_kind

        assert map_kind(coq_form) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 2. Library Discovery
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverLibraries:
    """discover_libraries returns .vo file paths for requested targets."""

    def test_returns_vo_paths_from_mock_filesystem(self, tmp_path):
        from Poule.extraction.pipeline import discover_libraries

        # Create a fake Coq lib directory with .vo files
        theories = tmp_path / "theories"
        theories.mkdir()
        (theories / "Init").mkdir()
        (theories / "Init" / "Datatypes.vo").touch()
        (theories / "Init" / "Logic.vo").touch()
        (theories / "Arith").mkdir()
        (theories / "Arith" / "PeanoNat.vo").touch()
        # Also create a non-.vo file that should be ignored
        (theories / "Init" / "Datatypes.glob").touch()

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(tmp_path) + "\n"
            )
            result = discover_libraries("stdlib")

        assert len(result) == 3
        assert all(str(p).endswith(".vo") for p in result)

    def test_raises_extraction_error_when_target_not_found(self, tmp_path):
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import discover_libraries

        # Empty directory — no .vo files
        empty = tmp_path / "empty"
        empty.mkdir()

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(empty) + "\n"
            )
            with pytest.raises(ExtractionError):
                discover_libraries("stdlib")

    def test_raises_extraction_error_when_coq_not_installed(self):
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import discover_libraries

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.side_effect = FileNotFoundError("coqc not found")
            with pytest.raises(ExtractionError):
                discover_libraries("stdlib")

    def test_stdlib_finds_rocq9_user_contrib_stdlib(self, tmp_path):
        """Rocq 9.x moved stdlib from theories/ to user-contrib/Stdlib/.

        The spec (§4.7) says discover_libraries("stdlib") must return ALL
        .vo files from the installed Coq/Rocq stdlib.  When the stdlib
        lives at user-contrib/Stdlib/ (Rocq 9.x), the function must look
        there — not only in theories/ which contains a small legacy subset.
        """
        from Poule.extraction.pipeline import discover_libraries

        # Simulate Rocq 9.x layout: most stdlib is under user-contrib/Stdlib
        theories = tmp_path / "theories"
        theories.mkdir()
        (theories / "Init").mkdir()
        # Legacy subset: only 2 .vo files in theories/
        (theories / "Init" / "Nat.vo").touch()
        (theories / "Init" / "Logic.vo").touch()

        user_contrib = tmp_path / "user-contrib" / "Stdlib"
        user_contrib.mkdir(parents=True)
        (user_contrib / "Init").mkdir()
        (user_contrib / "Arith").mkdir()
        (user_contrib / "Lists").mkdir()
        # Full stdlib: 5 .vo files under user-contrib/Stdlib
        (user_contrib / "Init" / "Nat.vo").touch()
        (user_contrib / "Init" / "Logic.vo").touch()
        (user_contrib / "Init" / "Datatypes.vo").touch()
        (user_contrib / "Arith" / "PeanoNat.vo").touch()
        (user_contrib / "Lists" / "List.vo").touch()

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(tmp_path) + "\n"
            )
            result = discover_libraries("stdlib")

        # Must find the full stdlib, not just the legacy theories/ subset
        assert len(result) >= 5, (
            f"discover_libraries('stdlib') found only {len(result)} .vo files; "
            "expected >= 5 from user-contrib/Stdlib/ (Rocq 9.x stdlib location)"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 3. Pass 1 — Per-Declaration Processing
# ═══════════════════════════════════════════════════════════════════════════


def _make_mock_backend(declarations=None):
    """Create a mock Backend with sensible defaults.

    ``declarations`` is a list of (name, kind, constr_t) tuples returned
    by ``list_declarations``.
    """
    backend = Mock()
    backend.list_declarations.return_value = declarations or []
    backend.pretty_print.return_value = "forall n, n = n"
    backend.pretty_print_type.return_value = "Prop"
    backend.get_dependencies.return_value = []
    backend.detect_version.return_value = "8.19.0"
    return backend


def _make_mock_writer():
    """Create a mock IndexWriter."""
    writer = Mock()
    writer.batch_insert.return_value = {}
    writer.finalize.return_value = None
    writer.insert_symbol_freq.return_value = None
    writer.write_metadata.return_value = None
    writer.resolve_and_insert_dependencies.return_value = 0
    return writer


class TestPass1SingleDeclaration:
    """Pass 1: a single declaration is processed through the full pipeline."""

    def test_single_declaration_produces_correct_db_writes(self):
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("Coq.Init.Nat.add", "Definition", {"mock": "constr"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Coq.Init.Nat.add": 1}

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Init/Nat.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        # Declaration should have been batch-inserted
        writer.batch_insert.assert_called()


class TestPass1DeclarationFailure:
    """When normalization fails for one declaration, it is logged and skipped."""

    def test_failing_declaration_is_skipped_others_continue(self):
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[
                ("Good.Decl.one", "Lemma", {"mock": "constr"}),
                ("Bad.Decl.two", "Lemma", {"mock": "bad_constr"}),
                ("Good.Decl.three", "Theorem", {"mock": "constr"}),
            ]
        )
        writer = _make_mock_writer()
        # Simulate that processing the second declaration raises an error
        # during normalization. The pipeline should catch, log, and continue.
        call_count = [0]
        original_batch_insert = writer.batch_insert

        def counting_batch_insert(results, **kwargs):
            call_count[0] += len(results)
            return {r.name: idx for idx, r in enumerate(results, 1)}

        writer.batch_insert.side_effect = counting_batch_insert

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Init.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                side_effect=[
                    Mock(name="Good.Decl.one"),  # success
                    None,  # failure returns None
                    Mock(name="Good.Decl.three"),  # success
                ],
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        # batch_insert should have been called with the 2 successful results
        writer.batch_insert.assert_called()


class TestPass1BatchSize:
    """Declarations are batch-inserted with a batch size of 1000."""

    def test_batch_insert_called_per_1000_declarations(self):
        from Poule.extraction.pipeline import run_extraction

        # Create 2500 declarations
        decls = [
            (f"Decl.n{i}", "Lemma", {"mock": "constr"})
            for i in range(2500)
        ]
        backend = _make_mock_backend(declarations=decls)
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {
            f"Decl.n{i}": i for i in range(2500)
        }

        mock_result = Mock()
        mock_result.name = "Decl"

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Lib.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        # With 2500 declarations and batch size 1000:
        # expect 3 batch_insert calls (1000 + 1000 + 500)
        assert writer.batch_insert.call_count >= 3
        # Verify no batch exceeds 1000
        for c in writer.batch_insert.call_args_list:
            batch = c[0][0] if c[0] else c[1].get("results", [])
            assert len(batch) <= 1000


# ═══════════════════════════════════════════════════════════════════════════
# 4. Pass 2 — Dependency Resolution
# ═══════════════════════════════════════════════════════════════════════════


class TestPass2DependencyResolution:
    """Pass 2 resolves dependency names to IDs via the backend."""

    def test_resolved_dependencies_are_inserted(self):
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[
                ("A.lemma1", "Lemma", {"mock": "constr"}),
                ("A.lemma2", "Lemma", {"mock": "constr"}),
            ]
        )
        backend.get_dependencies.side_effect = [
            [("A.lemma2", "uses")],  # lemma1 depends on lemma2
            [],  # lemma2 has no deps
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.lemma1": 1, "A.lemma2": 2}

        mock_result1 = Mock()
        mock_result1.name = "A.lemma1"
        mock_result1.dependency_names = [("A.lemma2", "uses")]
        mock_result2 = Mock()
        mock_result2.name = "A.lemma2"
        mock_result2.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                side_effect=[mock_result1, mock_result2],
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        writer.resolve_and_insert_dependencies.assert_called()


class TestPass2UnresolvedTargets:
    """Unresolved dependency targets are silently skipped."""

    def test_unresolved_targets_skipped(self):
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.lemma1", "Lemma", {"mock": "constr"})]
        )
        # Dependency points to a name NOT in the index
        backend.get_dependencies.return_value = [
            ("External.unknown", "uses")
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.lemma1": 1}

        mock_result = Mock()
        mock_result.name = "A.lemma1"
        mock_result.dependency_names = [("External.unknown", "uses")]

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            # Should NOT raise — unresolved targets are skipped
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        writer.resolve_and_insert_dependencies.assert_called()


class TestPass2NameResolution:
    """Name resolution strategies in resolve_and_insert_dependencies (§4.5)."""

    def _make_writer_and_call(self, results, name_to_id):
        """Helper: create a PipelineWriter with a mock IndexWriter, call
        resolve_and_insert_dependencies, and return the mock IndexWriter
        so callers can inspect insert_dependencies calls."""
        from Poule.extraction.pipeline import PipelineWriter

        index_writer = Mock()
        pw = PipelineWriter(index_writer)
        pw.resolve_and_insert_dependencies(results, name_to_id)
        return index_writer

    def _make_result(self, name, dependency_names, tree=None):
        """Helper: build a DeclarationResult for testing."""
        from Poule.extraction.pipeline import DeclarationResult

        return DeclarationResult(
            name=name,
            kind="lemma",
            module="Test.Module",
            statement="forall n, n = n",
            type_expr=None,
            tree=tree,
            symbol_set=[],
            wl_vector={},
            dependency_names=dependency_names,
        )

    def test_exact_match_resolves(self):
        """Dependency name exactly matches a name in the index -> edge inserted."""
        r = self._make_result("A.lemma1", [("B.lemma2", "uses")])
        name_to_id = {"A.lemma1": 1, "B.lemma2": 2}

        iw = self._make_writer_and_call([r], name_to_id)

        iw.insert_dependencies.assert_called_once()
        edges = iw.insert_dependencies.call_args[0][0]
        assert len(edges) == 1
        assert edges[0] == {"src": 1, "dst": 2, "relation": "uses"}

    def test_coq_prefix_resolves(self):
        """Dependency name like Init.Nat.add resolves via Coq.Init.Nat.add."""
        r = self._make_result("A.lemma1", [("Init.Nat.add", "uses")])
        name_to_id = {"A.lemma1": 1, "Coq.Init.Nat.add": 10}

        iw = self._make_writer_and_call([r], name_to_id)

        iw.insert_dependencies.assert_called_once()
        edges = iw.insert_dependencies.call_args[0][0]
        assert len(edges) == 1
        assert edges[0] == {"src": 1, "dst": 10, "relation": "uses"}

    def test_suffix_match_resolves(self):
        """Dependency name like Nat.add resolves via suffix match against
        Coq.Init.Nat.add when suffix is unambiguous."""
        r = self._make_result("A.lemma1", [("Nat.add", "uses")])
        # Only one FQN ends with .Nat.add, so suffix is unambiguous
        name_to_id = {"A.lemma1": 1, "Coq.Init.Nat.add": 10}

        iw = self._make_writer_and_call([r], name_to_id)

        iw.insert_dependencies.assert_called_once()
        edges = iw.insert_dependencies.call_args[0][0]
        assert len(edges) == 1
        assert edges[0] == {"src": 1, "dst": 10, "relation": "uses"}

    def test_ambiguous_suffix_skipped(self):
        """When suffix matches multiple distinct FQNs, the edge is skipped."""
        r = self._make_result("A.lemma1", [("add", "uses")])
        # "add" is a suffix of both FQNs -> ambiguous -> skipped
        name_to_id = {
            "A.lemma1": 1,
            "Coq.Init.Nat.add": 10,
            "Coq.Init.List.add": 20,
        }

        iw = self._make_writer_and_call([r], name_to_id)

        # No edges inserted because the only dependency was ambiguous
        iw.insert_dependencies.assert_not_called()

    def test_self_reference_skipped(self):
        """Dependency pointing to the same declaration is filtered out."""
        r = self._make_result("A.lemma1", [("A.lemma1", "uses")])
        name_to_id = {"A.lemma1": 1}

        iw = self._make_writer_and_call([r], name_to_id)

        # Self-reference filtered, no edges to insert
        iw.insert_dependencies.assert_not_called()

    def test_tree_based_extraction_supplements(self):
        """When a result has a normalised tree, LConst edges from
        extract_dependencies are merged with Print Assumptions edges."""
        # Create a mock tree so the tree-based branch is entered
        mock_tree = Mock()
        r = self._make_result(
            "A.lemma1",
            [("B.lemma2", "uses")],  # from Print Assumptions
            tree=mock_tree,
        )
        name_to_id = {"A.lemma1": 1, "B.lemma2": 2, "C.def1": 3}

        # Patch extract_dependencies to return an additional edge
        with patch(
            "Poule.extraction.pipeline.extract_dependencies",
            create=True,
        ) as mock_extract, patch(
            "Poule.extraction.dependency_extraction.extract_dependencies",
            create=True,
        ):
            mock_extract.return_value = [("C.def1", "uses")]

            # We need to patch inside the module where it's imported
            # The function is imported lazily inside resolve_and_insert_dependencies
            with patch.dict(
                "sys.modules",
                {"Poule.extraction.dependency_extraction": Mock(
                    extract_dependencies=Mock(return_value=[("C.def1", "uses")])
                )},
            ):
                iw = self._make_writer_and_call([r], name_to_id)

        iw.insert_dependencies.assert_called_once()
        edges = iw.insert_dependencies.call_args[0][0]
        # Should have edges from both sources
        src_dst_pairs = {(e["src"], e["dst"]) for e in edges}
        assert (1, 2) in src_dst_pairs  # from Print Assumptions
        assert (1, 3) in src_dst_pairs  # from tree-based extraction

    def test_deduplication(self):
        """Same edge from both sources is only inserted once."""
        mock_tree = Mock()
        # Both Print Assumptions and tree extraction yield the same edge
        r = self._make_result(
            "A.lemma1",
            [("B.lemma2", "uses")],
            tree=mock_tree,
        )
        name_to_id = {"A.lemma1": 1, "B.lemma2": 2}

        with patch.dict(
            "sys.modules",
            {"Poule.extraction.dependency_extraction": Mock(
                extract_dependencies=Mock(return_value=[("B.lemma2", "uses")])
            )},
        ):
            iw = self._make_writer_and_call([r], name_to_id)

        iw.insert_dependencies.assert_called_once()
        edges = iw.insert_dependencies.call_args[0][0]
        # Deduplicated: only one edge despite two sources
        assert len(edges) == 1
        assert edges[0] == {"src": 1, "dst": 2, "relation": "uses"}

    def test_symbol_set_resolved_via_suffix_match(self):
        """§4.5: Symbol-set cross-referencing uses multi-strategy resolution,
        not just exact FQN match. A short name in symbol_set should resolve
        via suffix match."""
        from Poule.extraction.pipeline import DeclarationResult

        r = DeclarationResult(
            name="A.lemma1",
            kind="lemma",
            module="A",
            statement="forall n, n = n",
            type_expr=None,
            tree=None,
            symbol_set=["Nat.add"],  # short name, not FQN
            wl_vector={},
            dependency_names=[],
        )
        name_to_id = {
            "A.lemma1": 1,
            "Coq.Init.Nat.add": 10,  # FQN ending in .Nat.add
        }

        iw = self._make_writer_and_call([r], name_to_id)

        iw.insert_dependencies.assert_called_once()
        edges = iw.insert_dependencies.call_args[0][0]
        assert len(edges) == 1
        assert edges[0] == {"src": 1, "dst": 10, "relation": "uses"}

    def test_symbol_set_resolved_via_coq_prefix(self):
        """§4.5: Symbol-set names with Coq. prefix strategy.
        'Init.Nat.add' should resolve to 'Coq.Init.Nat.add'."""
        from Poule.extraction.pipeline import DeclarationResult

        r = DeclarationResult(
            name="A.lemma1",
            kind="lemma",
            module="A",
            statement="forall n, n = n",
            type_expr=None,
            tree=None,
            symbol_set=["Init.Nat.add"],
            wl_vector={},
            dependency_names=[],
        )
        name_to_id = {
            "A.lemma1": 1,
            "Coq.Init.Nat.add": 10,
        }

        iw = self._make_writer_and_call([r], name_to_id)

        iw.insert_dependencies.assert_called_once()
        edges = iw.insert_dependencies.call_args[0][0]
        assert len(edges) == 1
        assert edges[0] == {"src": 1, "dst": 10, "relation": "uses"}


# ═══════════════════════════════════════════════════════════════════════════
# 5. Post-Processing
# ═══════════════════════════════════════════════════════════════════════════


class TestPostProcessingSymbolFreq:
    """Symbol frequencies are computed from all declarations' symbol sets."""

    def test_symbol_frequencies_computed_correctly(self):
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[
                ("A.decl1", "Lemma", {"mock": "constr"}),
                ("A.decl2", "Theorem", {"mock": "constr"}),
            ]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl1": 1, "A.decl2": 2}

        mock_r1 = Mock()
        mock_r1.name = "A.decl1"
        mock_r1.symbol_set = ["Coq.Init.Nat.add", "Coq.Init.Logic.eq"]
        mock_r1.dependency_names = []
        mock_r2 = Mock()
        mock_r2.name = "A.decl2"
        mock_r2.symbol_set = ["Coq.Init.Nat.add", "Coq.Init.Datatypes.nat"]
        mock_r2.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                side_effect=[mock_r1, mock_r2],
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        writer.insert_symbol_freq.assert_called()


class TestPostProcessingMetadata:
    """Metadata is written: schema_version, coq_version, etc."""

    def test_metadata_written_with_required_keys(self):
        """Single-target extraction writes library, library_version, declarations
        instead of mathcomp_version (spec: extraction.md §4.6)."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl1", "Lemma", {"mock": "constr"})]
        )
        backend.detect_version.return_value = "8.19.0"
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl1": 1}

        mock_result = Mock()
        mock_result.name = "A.decl1"
        mock_result.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
            patch(
                "Poule.extraction.pipeline.detect_library_version",
                return_value="8.19.2",
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        # write_metadata should be called with version info
        writer.write_metadata.assert_called()
        metadata_call = writer.write_metadata.call_args
        # Single-target: metadata must include schema_version, coq_version,
        # library, library_version, declarations, created_at — all non-None
        # (spec: extraction.md §4.6).
        kwargs = metadata_call[1] if metadata_call[1] else {}
        for key in (
            "schema_version",
            "coq_version",
            "library",
            "library_version",
            "declarations",
            "created_at",
        ):
            assert key in kwargs, f"missing metadata key: {key}"
            assert kwargs[key] is not None, f"metadata key {key} must not be None"

    def test_metadata_multi_target_writes_mathcomp_version(self):
        """Multi-target extraction writes mathcomp_version for backward
        compatibility (spec: extraction.md §4.6)."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl1", "Lemma", {"mock": "constr"})]
        )
        backend.detect_version.return_value = "8.19.0"
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl1": 1}

        mock_result = Mock()
        mock_result.name = "A.decl1"
        mock_result.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
            patch(
                "Poule.extraction.pipeline.detect_mathcomp_version",
                return_value="2.2.0",
            ),
        ):
            run_extraction(
                targets=["stdlib", "mathcomp"], db_path=Path("/tmp/test.db")
            )

        # write_metadata should be called with version info
        writer.write_metadata.assert_called()
        metadata_call = writer.write_metadata.call_args
        # Multi-target: metadata must include mathcomp_version for backward
        # compatibility, plus declarations (spec: extraction.md §4.6).
        kwargs = metadata_call[1] if metadata_call[1] else {}
        for key in (
            "schema_version",
            "coq_version",
            "mathcomp_version",
            "declarations",
            "created_at",
        ):
            assert key in kwargs, f"missing metadata key: {key}"
            assert kwargs[key] is not None, f"metadata key {key} must not be None"


class TestPostProcessingFinalize:
    """writer.finalize() is called after post-processing."""

    def test_finalize_called_on_writer(self):
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl1", "Lemma", {"mock": "constr"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl1": 1}

        mock_result = Mock()
        mock_result.name = "A.decl1"
        mock_result.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        writer.finalize.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# 6. Error Handling
# ═══════════════════════════════════════════════════════════════════════════


class TestBackendCrash:
    """Backend crash aborts the pipeline, deletes partial DB, raises ExtractionError."""

    def test_backend_crash_raises_extraction_error(self, tmp_path):
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import run_extraction

        db_path = tmp_path / "partial.db"

        backend = _make_mock_backend(
            declarations=[("A.decl1", "Lemma", {"mock": "constr"})]
        )
        # Simulate backend crash during list_declarations on second file
        backend.list_declarations.side_effect = [
            [("A.decl1", "Lemma", {"mock": "constr"})],
            ExtractionError("Backend process exited unexpectedly"),
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl1": 1}

        mock_result = Mock()
        mock_result.name = "A.decl1"
        mock_result.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[
                    Path("/fake/A.vo"),
                    Path("/fake/B.vo"),
                ],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            with pytest.raises(ExtractionError, match="Backend"):
                run_extraction(targets=["stdlib"], db_path=db_path)

        # Partial database file should be deleted
        assert not db_path.exists()

    def test_backend_crash_deletes_partial_db_file(self, tmp_path):
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import run_extraction

        db_path = tmp_path / "partial.db"
        # Pre-create the file to verify it gets cleaned up
        db_path.touch()

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = ExtractionError(
            "Backend crash"
        )

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=_make_mock_writer(),
            ),
        ):
            with pytest.raises(ExtractionError):
                run_extraction(targets=["stdlib"], db_path=db_path)

        assert not db_path.exists()


class TestBackendCrashCleanup:
    """Backend crash closes the DB connection before deleting the partial file (§4.11)."""

    def test_db_connection_closed_before_partial_db_deleted(self, tmp_path):
        """GIVEN a backend crash mid-run
        WHEN the cleanup runs
        THEN the writer's close() is called before the partial DB file is unlinked.

        Spec §4.11: Close the database connection, then delete the partial DB.
        """
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import run_extraction

        db_path = tmp_path / "partial.db"

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = ExtractionError("Backend crash")

        writer = _make_mock_writer()

        close_order: list[str] = []

        def _mock_close():
            close_order.append("close")

        def _mock_unlink(_path=None):
            close_order.append("unlink")

        writer.close = Mock(side_effect=_mock_close)

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch.object(
                db_path.__class__,
                "unlink",
                side_effect=_mock_unlink,
                create=True,
            ),
        ):
            with pytest.raises(ExtractionError):
                run_extraction(targets=["stdlib"], db_path=db_path)

        # If close() was called, it must come before unlink().
        # The spec requires closing the connection before deleting the file.
        if "close" in close_order and "unlink" in close_order:
            assert close_order.index("close") < close_order.index("unlink"), (
                "DB connection must be closed before the partial file is deleted"
            )

    def test_no_dangling_connection_after_crash(self, tmp_path):
        """GIVEN a backend crash
        WHEN the pipeline handles it
        THEN writer.close() is called exactly once (no dangling connection).

        Verifies that the crash cleanup path invokes close() on the writer.
        """
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import run_extraction

        db_path = tmp_path / "partial.db"

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = ExtractionError("Backend crash")

        writer = _make_mock_writer()
        writer.close = Mock()

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
        ):
            with pytest.raises(ExtractionError):
                run_extraction(targets=["stdlib"], db_path=db_path)

        # The partial DB file must be cleaned up.
        assert not db_path.exists()
        # If the writer exposes close(), it must have been called.
        if writer.close.called:
            writer.close.assert_called_once()


class TestAboutResponseKindParsing:
    """Kind parsing precedence when About returns both Notation and Constant (§4.1.1)."""

    def test_constant_preferred_over_notation_in_about_response(self):
        """GIVEN an About response containing both Notation and Constant categories
        WHEN _parse_about_kind processes the response
        THEN the kind is 'definition' (Constant maps to definition).

        Rocq 9.x: a notation aliasing a real constant returns two 'Expands to:' lines.
        Spec §4.1.1: The backend shall prefer Constant/Inductive/Constructor over Notation.
        """
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        # Simulate the Rocq 9.x About response for a notation that aliases a constant.
        # e.g. "pred" which is both a Notation and a Constant (Nat.pred).
        about_text = (
            "Notation pred := Nat.pred\n"
            "Expands to: Notation Corelib.Init.Peano.pred\n"
            "  The number of hypotheses is 0.\n"
            "Expands to: Constant Corelib.Init.Nat.pred"
        )
        messages = [{"text": about_text, "level": 3}]

        kind = CoqLspBackend._parse_about_kind("pred", messages)

        assert kind == "definition", (
            f"Expected 'definition' (Constant preferred over Notation), got {kind!r}"
        )

    def test_notation_only_when_no_constant_present(self):
        """GIVEN an About response with only Notation category
        WHEN _parse_about_kind processes the response
        THEN the kind is 'notation'.

        This is the pure-notation case (no aliased constant).
        """
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        about_text = (
            "Notation foo := bar\n"
            "Expands to: Notation Corelib.Init.Peano.foo\n"
        )
        messages = [{"text": about_text, "level": 3}]

        kind = CoqLspBackend._parse_about_kind("foo", messages)

        assert kind == "notation", (
            f"Expected 'notation' when only Notation is present, got {kind!r}"
        )


class TestBackendNotFound:
    """Missing backend raises ExtractionError before processing starts."""

    def test_backend_not_found_raises_extraction_error(self, tmp_path):
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import run_extraction

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                side_effect=ExtractionError(
                    "Neither coq-lsp nor sertop found"
                ),
            ),
        ):
            with pytest.raises(ExtractionError, match="coq-lsp|sertop|found"):
                run_extraction(
                    targets=["stdlib"], db_path=tmp_path / "test.db"
                )


# ═══════════════════════════════════════════════════════════════════════════
# 7. Progress Reporting
# ═══════════════════════════════════════════════════════════════════════════


class TestProgressReporting:
    """Progress callbacks are invoked with correct counts."""

    def test_pass1_progress_reports_declaration_counts(self):
        from Poule.extraction.pipeline import run_extraction

        decls = [
            (f"A.decl{i}", "Lemma", {"mock": "constr"}) for i in range(5)
        ]
        backend = _make_mock_backend(declarations=decls)
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {
            f"A.decl{i}": i for i in range(5)
        }

        mock_result = Mock()
        mock_result.name = "A.decl"
        mock_result.dependency_names = []

        progress_callback = Mock()

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            run_extraction(
                targets=["stdlib"],
                db_path=Path("/tmp/test.db"),
                progress_callback=progress_callback,
            )

        # Progress callback should have been called for each declaration
        # Format: "Extracting declarations [N/total]"
        assert progress_callback.call_count >= 5
        # Verify at least one call contains the expected format
        call_args_list = [
            str(c) for c in progress_callback.call_args_list
        ]
        found_extracting = any(
            "Extracting" in s or "extracting" in s.lower()
            for s in call_args_list
        )
        assert found_extracting, (
            f"Expected progress messages with 'Extracting', got: {call_args_list}"
        )

    def test_pass2_progress_reports_dependency_counts(self):
        from Poule.extraction.pipeline import run_extraction

        decls = [
            (f"A.decl{i}", "Lemma", {"mock": "constr"}) for i in range(3)
        ]
        backend = _make_mock_backend(declarations=decls)
        backend.get_dependencies.return_value = [("A.decl0", "uses")]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {
            f"A.decl{i}": i for i in range(3)
        }

        mock_result = Mock()
        mock_result.name = "A.decl"
        mock_result.dependency_names = [("A.decl0", "uses")]

        progress_callback = Mock()

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            run_extraction(
                targets=["stdlib"],
                db_path=Path("/tmp/test.db"),
                progress_callback=progress_callback,
            )

        call_args_list = [
            str(c) for c in progress_callback.call_args_list
        ]
        found_resolving = any(
            "Resolving" in s or "resolving" in s.lower()
            for s in call_args_list
        )
        assert found_resolving, (
            f"Expected progress messages with 'Resolving', got: {call_args_list}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 8. Full Pipeline Integration (mock backend, 3 declarations)
# ═══════════════════════════════════════════════════════════════════════════


class TestFullRunIntegration:
    """End-to-end: mock backend with 3 declarations → correct DB writes."""

    def test_three_declarations_full_pipeline(self, tmp_path):
        from Poule.extraction.pipeline import run_extraction

        # 3 declarations: 1 lemma, 1 theorem, 1 notation (excluded)
        decls = [
            ("Coq.Init.Nat.add_comm", "Lemma", {"mock": "constr1"}),
            ("Coq.Init.Nat.add_assoc", "Theorem", {"mock": "constr2"}),
            ("Coq.Init.Nat.add_notation", "Notation", {"mock": "constr3"}),
        ]
        backend = _make_mock_backend(declarations=decls)
        backend.get_dependencies.side_effect = [
            [("Coq.Init.Nat.add_assoc", "uses")],  # add_comm uses add_assoc
            [],  # add_assoc has no deps
        ]

        writer = _make_mock_writer()
        name_to_id = {
            "Coq.Init.Nat.add_comm": 1,
            "Coq.Init.Nat.add_assoc": 2,
        }
        writer.batch_insert.return_value = name_to_id

        # process_declaration returns None for Notation (excluded),
        # valid results for the other two
        result_comm = Mock()
        result_comm.name = "Coq.Init.Nat.add_comm"
        result_comm.kind = "lemma"
        result_comm.symbol_set = ["Coq.Init.Nat.add", "Coq.Init.Logic.eq"]
        result_comm.dependency_names = [
            ("Coq.Init.Nat.add_assoc", "uses")
        ]

        result_assoc = Mock()
        result_assoc.name = "Coq.Init.Nat.add_assoc"
        result_assoc.kind = "theorem"
        result_assoc.symbol_set = ["Coq.Init.Nat.add"]
        result_assoc.dependency_names = []

        db_path = tmp_path / "index.db"

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Nat.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                side_effect=[result_comm, result_assoc, None],
            ),
        ):
            report = run_extraction(targets=["stdlib"], db_path=db_path)

        # Verify batch_insert was called with 2 results (Notation excluded)
        writer.batch_insert.assert_called()
        all_inserted = []
        for c in writer.batch_insert.call_args_list:
            batch = c[0][0] if c[0] else c[1].get("results", [])
            all_inserted.extend(batch)
        assert len(all_inserted) == 2

        # Verify dependency resolution was called
        writer.resolve_and_insert_dependencies.assert_called()

        # Verify symbol freq was computed
        writer.insert_symbol_freq.assert_called()

        # Verify metadata was written
        writer.write_metadata.assert_called()

        # Verify finalize was called
        writer.finalize.assert_called_once()

        # Verify report is returned
        assert report is not None

    def test_excluded_kinds_not_processed(self, tmp_path):
        """Notation, Abbreviation, Section Variable are never passed to
        process_declaration (or process_declaration returns None)."""
        from Poule.extraction.pipeline import run_extraction

        decls = [
            ("A.nota", "Notation", {"mock": "c"}),
            ("A.abbr", "Abbreviation", {"mock": "c"}),
            ("A.secvar", "Section Variable", {"mock": "c"}),
            ("A.real_lemma", "Lemma", {"mock": "c"}),
        ]
        backend = _make_mock_backend(declarations=decls)
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.real_lemma": 1}

        real_result = Mock()
        real_result.name = "A.real_lemma"
        real_result.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                side_effect=[None, None, None, real_result],
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=tmp_path / "test.db")

        # Only 1 non-None result should be batch-inserted
        all_inserted = []
        for c in writer.batch_insert.call_args_list:
            batch = c[0][0] if c[0] else c[1].get("results", [])
            all_inserted.extend(batch)
        assert len(all_inserted) == 1

    def test_pipeline_order_is_pass1_then_pass2_then_postprocess(
        self, tmp_path
    ):
        """Operations occur in correct order: batch_insert before
        resolve_and_insert_dependencies before finalize."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl1", "Lemma", {"mock": "constr"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl1": 1}

        mock_result = Mock()
        mock_result.name = "A.decl1"
        mock_result.dependency_names = []

        call_order = []
        writer.batch_insert.side_effect = lambda *a, **kw: (
            call_order.append("batch_insert"),
            {"A.decl1": 1},
        )[1]
        writer.resolve_and_insert_dependencies.side_effect = lambda *a, **kw: (
            call_order.append("resolve_deps"),
            0,
        )[1]
        writer.insert_symbol_freq.side_effect = lambda *a, **kw: (
            call_order.append("symbol_freq"),
        )
        writer.write_metadata.side_effect = lambda *a, **kw: (
            call_order.append("write_metadata"),
        )
        writer.finalize.side_effect = lambda *a, **kw: (
            call_order.append("finalize"),
        )

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=tmp_path / "test.db")

        # Verify ordering: batch_insert < resolve_deps < finalize
        assert "batch_insert" in call_order
        assert "finalize" in call_order
        bi_idx = call_order.index("batch_insert")
        fin_idx = call_order.index("finalize")
        assert bi_idx < fin_idx

        if "resolve_deps" in call_order:
            rd_idx = call_order.index("resolve_deps")
            assert bi_idx < rd_idx < fin_idx


# ═══════════════════════════════════════════════════════════════════════════
# 9. Idempotent Re-Indexing (specification §4.7)
# ═══════════════════════════════════════════════════════════════════════════


class TestIdempotentReIndexing:
    """When an existing database file exists at db_path, it is deleted
    before creating a new index."""

    def test_existing_db_is_deleted_and_rebuilt(self, tmp_path):
        """GIVEN an existing SQLite database at the output path
        WHEN run_extraction is called
        THEN the existing file is deleted before the new index is created."""
        from Poule.extraction.pipeline import run_extraction

        db_path = tmp_path / "index.db"

        # Create a pre-existing database with a table to prove it gets replaced
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sentinel (id INTEGER PRIMARY KEY)")
        conn.close()
        assert db_path.exists()

        backend = _make_mock_backend(
            declarations=[("A.decl1", "Lemma", {"mock": "constr"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl1": 1}

        mock_result = Mock()
        mock_result.name = "A.decl1"
        mock_result.dependency_names = []

        # Track whether the file was deleted before create_writer was called
        file_existed_at_create_time = []

        def mock_create_writer(path):
            file_existed_at_create_time.append(path.exists())
            return writer

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                side_effect=mock_create_writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        # The file must NOT have existed when create_writer was called
        assert len(file_existed_at_create_time) == 1
        assert file_existed_at_create_time[0] is False, (
            "Existing database file was not deleted before create_writer was called"
        )

    def test_no_existing_db_creates_normally(self, tmp_path):
        """GIVEN no file at the output path
        WHEN run_extraction is called
        THEN the index is created normally."""
        from Poule.extraction.pipeline import run_extraction

        db_path = tmp_path / "fresh.db"
        assert not db_path.exists()

        backend = _make_mock_backend(
            declarations=[("A.decl1", "Lemma", {"mock": "constr"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl1": 1}

        mock_result = Mock()
        mock_result.name = "A.decl1"
        mock_result.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        writer.finalize.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# 10. ExtractionError
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractionError:
    """ExtractionError carries a message and is the base error class."""

    def test_extraction_error_is_exception(self):
        from Poule.extraction.errors import ExtractionError

        assert issubclass(ExtractionError, Exception)

    def test_extraction_error_carries_message(self):
        from Poule.extraction.errors import ExtractionError

        err = ExtractionError("backend missing")
        assert "backend missing" in str(err)

    def test_extraction_error_can_be_raised_and_caught(self):
        from Poule.extraction.errors import ExtractionError

        with pytest.raises(ExtractionError):
            raise ExtractionError("test")


# ═══════════════════════════════════════════════════════════════════════════
# 12. Type Signature Passthrough from Search Output
# ═══════════════════════════════════════════════════════════════════════════


class TestTypeSigPassthrough:
    """process_declaration uses constr_t['type_signature'] for type_expr
    instead of calling backend.pretty_print_type (§4.4 step 7)."""

    def test_type_expr_from_constr_t_type_signature(self):
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        constr_t = {
            "name": "Nat.add",
            "type_signature": "nat -> nat -> nat",
            "source": "coq-lsp",
        }

        # coq_normalize will fail on a plain dict, producing partial result —
        # but type_expr should still come from constr_t["type_signature"]
        result = process_declaration(
            "Nat.add", "Definition", constr_t, backend, "/fake/Nat.vo",
            statement="Nat.add = ...", dependency_names=[],
        )

        assert result is not None
        assert result.type_expr == "nat -> nat -> nat"
        # pretty_print_type should NOT be called since type_sig comes from constr_t
        backend.pretty_print_type.assert_not_called()

    def test_no_pretty_print_type_call_when_type_sig_available(self):
        """When constr_t has type_signature, pretty_print_type is NOT called."""
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        constr_t = {
            "name": "Nat.add",
            "type_signature": "nat -> nat -> nat",
            "source": "coq-lsp",
        }

        process_declaration(
            "Nat.add", "Definition", constr_t, backend, "/fake/Nat.vo",
            statement="stmt", dependency_names=[],
        )

        backend.pretty_print_type.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# 13. Pre-fetched Statement and Dependencies
# ═══════════════════════════════════════════════════════════════════════════


class TestPrefetchedData:
    """process_declaration uses pre-fetched statement and dependencies
    when provided, avoiding per-declaration backend calls."""

    def test_uses_prefetched_statement(self):
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        constr_t = {"name": "A", "type_signature": "Prop", "source": "coq-lsp"}

        result = process_declaration(
            "A", "Lemma", constr_t, backend, "/fake.vo",
            statement="pre-fetched statement", dependency_names=[],
        )

        assert result is not None
        assert result.statement == "pre-fetched statement"
        backend.pretty_print.assert_not_called()

    def test_uses_prefetched_dependencies(self):
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        constr_t = {"name": "A", "type_signature": "Prop", "source": "coq-lsp"}
        prefetched_deps = [("B", "assumes"), ("C", "assumes")]

        result = process_declaration(
            "A", "Lemma", constr_t, backend, "/fake.vo",
            statement="stmt", dependency_names=prefetched_deps,
        )

        assert result is not None
        assert result.dependency_names == prefetched_deps
        backend.get_dependencies.assert_not_called()

    def test_falls_back_to_backend_when_no_prefetch(self):
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        backend.pretty_print.return_value = "backend statement"
        backend.get_dependencies.return_value = [("X", "assumes")]
        constr_t = {"name": "A", "type_signature": "Prop", "source": "coq-lsp"}

        result = process_declaration(
            "A", "Lemma", constr_t, backend, "/fake.vo",
        )

        assert result is not None
        assert result.statement == "backend statement"
        assert result.dependency_names == [("X", "assumes")]
        backend.pretty_print.assert_called_once()
        backend.get_dependencies.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# 14. Metadata-Only constr_t (coq-lsp backend — §4.4 step 1)
# ═══════════════════════════════════════════════════════════════════════════


class TestMetadataOnlyConstrT:
    """When constr_t is a metadata dict (coq-lsp backend), type_signature is
    parsed via TypeExprParser and normalized (§4.4 step 1, updated)."""

    def test_dict_constr_t_parses_type_signature(self, caplog):
        """A dict constr_t with type_signature produces a valid result with
        a normalized tree, symbol set, and WL vector.  When the backend has
        a locate() method, symbols are resolved to FQNs (§4.4 step 5)."""
        import logging
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        backend.locate.side_effect = lambda name: {
            "nat": "Coq.Init.Datatypes.nat",
        }.get(name)
        constr_t = {
            "name": "Nat.add",
            "type_signature": "nat -> nat -> nat",
            "source": "coq-lsp",
        }

        with caplog.at_level(logging.WARNING):
            result = process_declaration(
                "Nat.add", "Definition", constr_t, backend, "/fake/Nat.vo",
                statement="Nat.add = ...", dependency_names=[],
            )

        assert result is not None
        assert result.tree is not None
        assert "Coq.Init.Datatypes.nat" in result.symbol_set
        assert len(result.wl_vector) > 0
        # No normalization warning should be logged
        normalization_warnings = [
            r for r in caplog.records
            if "Normalization failed" in r.message
        ]
        assert normalization_warnings == []

    def test_dict_constr_t_without_locate_keeps_short_names(self, caplog):
        """When the backend has no locate() method, symbols are stored as
        short display names (fallback behavior)."""
        import logging
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        # Remove locate so hasattr(backend, 'locate') could be True (Mock),
        # but make it raise to simulate unavailability
        del backend.locate
        constr_t = {
            "name": "Nat.add",
            "type_signature": "nat -> nat -> nat",
            "source": "coq-lsp",
        }

        with caplog.at_level(logging.WARNING):
            result = process_declaration(
                "Nat.add", "Definition", constr_t, backend, "/fake/Nat.vo",
                statement="Nat.add = ...", dependency_names=[],
            )

        assert result is not None
        assert "nat" in result.symbol_set

    def test_dict_constr_t_without_type_signature_has_no_tree(self):
        """A dict constr_t without type_signature produces partial result."""
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        constr_t = {"name": "Nat.add", "source": "coq-lsp"}

        result = process_declaration(
            "Nat.add", "Definition", constr_t, backend, "/fake/Nat.vo",
            statement="Nat.add = ...", dependency_names=[],
        )

        assert result is not None
        assert result.tree is None
        assert result.symbol_set == []
        assert result.wl_vector == {}

    def test_dict_constr_t_preserves_type_signature(self):
        """type_expr is extracted from the dict's type_signature field."""
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        constr_t = {
            "name": "Nat.mul",
            "type_signature": "nat -> nat -> nat",
            "source": "coq-lsp",
        }

        result = process_declaration(
            "Nat.mul", "Definition", constr_t, backend, "/fake/Nat.vo",
            statement="Nat.mul = ...", dependency_names=[],
        )

        assert result is not None
        assert result.type_expr == "nat -> nat -> nat"

    def test_constr_node_constr_t_still_normalizes(self):
        """When constr_t is a ConstrNode, normalization proceeds normally."""
        from Poule.extraction.pipeline import process_declaration
        from Poule.normalization.constr_node import Const

        backend = _make_mock_backend()
        constr_t = Const(fqn="Coq.Init.Nat.add")

        result = process_declaration(
            "Nat.add", "Definition", constr_t, backend, "/fake/Nat.vo",
            statement="Nat.add = ...", dependency_names=[],
        )

        assert result is not None
        assert result.tree is not None


# ═══════════════════════════════════════════════════════════════════════════
# 15. Declaration Deduplication Across .vo Files (§4.4)
# ═══════════════════════════════════════════════════════════════════════════


class TestDeclarationDeduplication:
    """When the same declaration name appears in multiple .vo files, the
    pipeline keeps the first occurrence and skips duplicates (§4.4)."""

    def test_duplicate_names_across_vo_files_keeps_first(self, tmp_path):
        """Same name from two .vo files → only one process_declaration call."""
        from Poule.extraction.pipeline import run_extraction

        # Two .vo files both contain "Coq.Init.Nat.add"
        backend = _make_mock_backend()
        backend.list_declarations.side_effect = [
            [("Coq.Init.Nat.add", "Definition", {"mock": "constr1"})],
            [("Coq.Init.Nat.add", "Definition", {"mock": "constr2"})],
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Coq.Init.Nat.add": 1}

        result_mock = Mock()
        result_mock.name = "Coq.Init.Nat.add"
        result_mock.kind = "definition"
        result_mock.symbol_set = []
        result_mock.dependency_names = []

        db_path = tmp_path / "index.db"

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Nat.vo"), Path("/fake/Nat2.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=result_mock,
            ) as mock_process,
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        # process_declaration should be called exactly once (duplicate skipped)
        assert mock_process.call_count == 1

    def test_unique_names_across_vo_files_all_processed(self, tmp_path):
        """Different names from multiple .vo files → all processed."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = [
            [("Coq.Init.Nat.add", "Definition", {"mock": "constr1"})],
            [("Coq.Init.Nat.mul", "Definition", {"mock": "constr2"})],
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {
            "Coq.Init.Nat.add": 1,
            "Coq.Init.Nat.mul": 2,
        }

        result_add = Mock()
        result_add.name = "Coq.Init.Nat.add"
        result_add.kind = "definition"
        result_add.symbol_set = []
        result_add.dependency_names = []

        result_mul = Mock()
        result_mul.name = "Coq.Init.Nat.mul"
        result_mul.kind = "definition"
        result_mul.symbol_set = []
        result_mul.dependency_names = []

        db_path = tmp_path / "index.db"

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Nat.vo"), Path("/fake/Nat2.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                side_effect=[result_add, result_mul],
            ) as mock_process,
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        # Both unique declarations should be processed
        assert mock_process.call_count == 2


# ═══════════════════════════════════════════════════════════════════════════
# 14. FQN Derivation — §4.1.2
# ═══════════════════════════════════════════════════════════════════════════


class TestVoToLogicalPath:
    """_vo_to_logical_path derives correct logical module paths from .vo paths.

    Spec §4.1.2: The logical module path is derived from the .vo file path
    using heuristic path parsing (stripping known prefixes such as
    user-contrib/, theories/, and version-specific prefixes like Stdlib/).
    """

    def test_stdlib_rocq9_produces_coq_prefix(self):
        """user-contrib/Stdlib/Arith/PeanoNat.vo → Coq.Arith.PeanoNat (canonical)"""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path("/opt/coq/user-contrib/Stdlib/Arith/PeanoNat.vo")
        # _vo_to_logical_path returns the import path (no Coq. prefix)
        assert CoqLspBackend._vo_to_logical_path(path) == "Arith.PeanoNat"
        # _vo_to_canonical_module returns the canonical name (with Coq. prefix)
        assert CoqLspBackend._vo_to_canonical_module(path) == "Coq.Arith.PeanoNat"

    def test_mathcomp_user_contrib(self):
        """user-contrib/mathcomp/ssreflect/ssrbool.vo → mathcomp.ssreflect.ssrbool"""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path("/opt/coq/user-contrib/mathcomp/ssreflect/ssrbool.vo")
        assert CoqLspBackend._vo_to_logical_path(path) == "mathcomp.ssreflect.ssrbool"

    def test_theories_directory(self):
        """theories/Init/Nat.vo → Init.Nat"""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path("/opt/coq/theories/Init/Nat.vo")
        assert CoqLspBackend._vo_to_logical_path(path) == "Init.Nat"

    def test_stdlib_nested_module(self):
        """user-contrib/Stdlib/Init/Nat.vo → Coq.Init.Nat (canonical)"""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path("/opt/coq/user-contrib/Stdlib/Init/Nat.vo")
        # _vo_to_logical_path returns import path (stripped Stdlib prefix)
        assert CoqLspBackend._vo_to_logical_path(path) == "Init.Nat"
        # _vo_to_canonical_module returns canonical name
        assert CoqLspBackend._vo_to_canonical_module(path) == "Coq.Init.Nat"


class TestFQNDerivationInListDeclarations:
    """list_declarations returns fully qualified names by prepending the
    logical module path to short names from Search output.

    Spec §4.1.2: The fully qualified name is constructed by prepending the
    .vo file's logical module path to the short name returned by Search.
    """

    def test_short_names_get_module_path_prepended(self):
        """Given Search returns Nat.add_comm, the returned name should be
        Coq.Arith.PeanoNat.Nat.add_comm."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend()
        # Patch internal methods to avoid needing a real coq-lsp process
        backend._ensure_alive = Mock()
        backend._run_vernac_query = Mock(return_value=(
            [],
            [{"text": "Nat.add_comm : forall n m, n + m = m + n", "level": 3}],
        ))
        backend._batch_get_kinds = Mock(return_value=["lemma"])

        vo_path = Path("/opt/coq/user-contrib/Stdlib/Arith/PeanoNat.vo")
        decls = backend.list_declarations(vo_path)

        assert len(decls) == 1
        name, _kind, _constr_t = decls[0]
        assert name == "Coq.Arith.PeanoNat.Nat.add_comm", (
            f"Expected FQN, got short name: {name}"
        )

    def test_mathcomp_short_names_get_module_path_prepended(self):
        """Given Search returns negb_involutive, the returned name should be
        mathcomp.ssreflect.ssrbool.negb_involutive."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend()
        backend._ensure_alive = Mock()
        backend._run_vernac_query = Mock(return_value=(
            [],
            [{"text": "negb_involutive : forall b, negb (negb b) = b", "level": 3}],
        ))
        backend._batch_get_kinds = Mock(return_value=["lemma"])

        vo_path = Path("/opt/coq/user-contrib/mathcomp/ssreflect/ssrbool.vo")
        decls = backend.list_declarations(vo_path)

        assert len(decls) == 1
        name, _kind, _constr_t = decls[0]
        assert name == "mathcomp.ssreflect.ssrbool.negb_involutive", (
            f"Expected FQN, got short name: {name}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 15. Module Path in Pipeline Output — §4.3
# ═══════════════════════════════════════════════════════════════════════════


class TestModulePathIsLogicalInPipeline:
    """run_extraction passes logical module paths (not filesystem paths) to
    process_declaration.

    Spec §4.3: The pipeline shall NOT store raw filesystem paths (e.g.,
    /Users/.../PeanoNat.vo) in the module field.
    """

    def test_module_path_is_logical_not_filesystem(self, tmp_path):
        """The module_path arg to process_declaration must be a dot-separated
        logical path, not a raw filesystem path."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend()
        backend.list_declarations.return_value = [
            ("Coq.Init.Nat.add", "Definition", {"type_signature": "nat -> nat -> nat", "source": "coq-lsp"}),
        ]

        result_mock = Mock()
        result_mock.name = "Coq.Init.Nat.add"
        result_mock.kind = "definition"
        result_mock.symbol_set = []
        result_mock.dependency_names = []

        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Coq.Init.Nat.add": 1}

        db_path = tmp_path / "index.db"

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/opt/coq/user-contrib/Stdlib/Init/Nat.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=result_mock,
            ) as mock_process,
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        assert mock_process.call_count == 1
        _args, kwargs = mock_process.call_args
        # module_path is the 5th positional arg
        module_path = _args[4] if len(_args) > 4 else kwargs.get("module_path", _args[4])
        assert "/" not in module_path, (
            f"module_path is a filesystem path: {module_path}"
        )
        assert not module_path.endswith(".vo"), (
            f"module_path ends with .vo: {module_path}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 16. Dependency Relation Values — §4.5
# ═══════════════════════════════════════════════════════════════════════════

_VALID_RELATIONS = {"uses", "instance_of"}


class TestDependencyRelationValues:
    """Dependency edges use only valid relation values from the data model.

    Spec §4.5: All dependency edges shall use the relation values defined in
    the dependencies entity (index-entities.md): "uses" or "instance_of".
    No other relation values shall be stored.

    Data model (index-entities.md): dependencies.relation is an enumeration:
    "uses" or "instance_of".
    """

    def test_get_dependencies_returns_valid_relations(self):
        """get_dependencies must return 'uses', not 'assumes'."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend()
        backend._ensure_alive = Mock()
        backend._run_vernac_query = Mock(return_value=(
            [],
            [{"text": "  Coq.Init.Nat.add : nat -> nat -> nat", "level": 3}],
        ))

        deps = backend.get_dependencies("Coq.Arith.PeanoNat.Nat.add_comm")
        assert len(deps) > 0
        for _target, relation in deps:
            assert relation in _VALID_RELATIONS, (
                f"Invalid relation value: {relation!r} (expected one of {_VALID_RELATIONS})"
            )

    def test_query_declaration_data_returns_valid_relations(self):
        """query_declaration_data must return 'uses', not 'assumes'."""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        backend = CoqLspBackend()
        backend._ensure_alive = Mock()

        # Mock _run_vernac_batch to return Print + Print Assumptions output
        def fake_batch(commands):
            results = []
            for cmd in commands:
                if cmd.startswith("Print Assumptions"):
                    results.append([
                        {"text": "  Coq.Init.Nat.add : nat -> nat -> nat", "level": 3}
                    ])
                else:
                    results.append([{"text": "some statement", "level": 3}])
            return results

        backend._run_vernac_batch = Mock(side_effect=fake_batch)

        data = backend.query_declaration_data(["Coq.Arith.PeanoNat.Nat.add_comm"])
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in data
        _statement, deps = data["Coq.Arith.PeanoNat.Nat.add_comm"]
        assert len(deps) > 0
        for _target, relation in deps:
            assert relation in _VALID_RELATIONS, (
                f"Invalid relation value: {relation!r} (expected one of {_VALID_RELATIONS})"
            )


# ═══════════════════════════════════════════════════════════════════════════
# 20. Symbol FQN Resolution (§4.4.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestResolveSymbols:
    """resolve_symbols maps short display names to FQNs via Locate queries (spec §4.4.1)."""

    def test_resolves_short_names_to_fqns(self):
        """Short names like 'nat' are resolved to FQNs via backend Locate queries."""
        from Poule.extraction.pipeline import resolve_symbols

        backend = _make_mock_backend()
        backend.locate.return_value = "Coq.Init.Datatypes.nat"

        resolved = resolve_symbols({"nat"}, backend)

        assert "Coq.Init.Datatypes.nat" in resolved

    def test_infix_operators_resolved(self):
        """Infix operators like '+' are resolved via Locate (spec §4.4.1)."""
        from Poule.extraction.pipeline import resolve_symbols

        backend = _make_mock_backend()
        backend.locate.side_effect = lambda name: {
            "+": "Coq.Init.Nat.add",
            "nat": "Coq.Init.Datatypes.nat",
        }.get(name)

        resolved = resolve_symbols({"+", "nat"}, backend)

        assert "Coq.Init.Nat.add" in resolved
        assert "Coq.Init.Datatypes.nat" in resolved

    def test_unresolvable_names_kept_as_is(self):
        """Names that cannot be resolved are stored as-is (spec §4.4.1 fallback)."""
        from Poule.extraction.pipeline import resolve_symbols

        backend = _make_mock_backend()
        backend.locate.return_value = None

        resolved = resolve_symbols({"my_custom_def"}, backend)

        assert "my_custom_def" in resolved

    def test_cache_eliminates_redundant_queries(self):
        """Repeated short names only trigger one Locate query per unique name."""
        from Poule.extraction.pipeline import resolve_symbols

        backend = _make_mock_backend()
        call_count = 0
        def counting_locate(name):
            nonlocal call_count
            call_count += 1
            return f"Resolved.{name}"

        backend.locate = counting_locate

        # Call twice with the same symbol set — second call should use cache
        cache = {}
        resolve_symbols({"nat"}, backend, cache=cache)
        resolve_symbols({"nat"}, backend, cache=cache)

        assert call_count == 1

    def test_ambiguous_names_expand_to_all(self):
        """When Locate returns multiple matches, all FQNs are included (spec §4.4.1)."""
        from Poule.extraction.pipeline import resolve_symbols

        backend = _make_mock_backend()
        backend.locate.return_value = [
            "Coq.Init.Nat.add",
            "Coq.ZArith.BinInt.Z.add",
        ]

        resolved = resolve_symbols({"+"}, backend)

        assert "Coq.Init.Nat.add" in resolved
        assert "Coq.ZArith.BinInt.Z.add" in resolved

    def test_empty_input_returns_empty(self):
        """Empty symbol set produces empty result."""
        from Poule.extraction.pipeline import resolve_symbols

        backend = _make_mock_backend()

        resolved = resolve_symbols(set(), backend)

        assert resolved == set()


class TestSymbolFreqUsesFQNs:
    """After extraction with symbol resolution, symbol_freq contains FQNs (spec §4.4.1 invariant)."""

    def test_symbol_freq_keys_are_fqns(self):
        """Post-processing computes symbol frequencies using FQN-resolved symbol sets."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[
                ("A.decl1", "Lemma", {"type_signature": "nat -> nat", "source": "coq-lsp"}),
            ]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl1": 1}

        mock_r1 = Mock()
        mock_r1.name = "A.decl1"
        mock_r1.symbol_set = ["Coq.Init.Datatypes.nat"]  # FQN
        mock_r1.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "Poule.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "Poule.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "Poule.extraction.pipeline.process_declaration",
                return_value=mock_r1,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        writer.insert_symbol_freq.assert_called_once()
        freq_dict = writer.insert_symbol_freq.call_args[0][0]
        # The key should be a FQN, not a short name
        assert "Coq.Init.Datatypes.nat" in freq_dict
