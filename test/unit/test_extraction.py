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
    backend._get_child_rss_bytes.return_value = 0
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
            declarations=[("Stdlib.Init.Nat.add", "Definition", {"mock": "constr"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Stdlib.Init.Nat.add": 1}

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


class TestProcessDeclarationMergesTreeDeps:
    """process_declaration pre-merges tree-extracted deps into dependency_names."""

    def test_process_declaration_merges_tree_deps(self):
        """dependency_names includes tree-extracted deps after process_declaration."""
        from Poule.extraction.pipeline import process_declaration

        mock_tree = Mock()
        backend = Mock()
        backend.pretty_print.return_value = "forall n, n = n"
        backend.pretty_print_type.return_value = "Prop"

        with patch("Poule.normalization.normalize.coq_normalize", return_value=mock_tree), \
             patch("Poule.normalization.cse.cse_normalize"), \
             patch("Poule.channels.const_jaccard.extract_consts", return_value=[]), \
             patch("Poule.channels.wl_kernel.wl_histogram", return_value={}), \
             patch(
                 "Poule.extraction.dependency_extraction.extract_dependencies",
                 return_value=[("B.helper", "uses")],
             ):
            result = process_declaration(
                "A.lemma1",
                "Lemma",
                object(),  # non-dict constr_t triggers normalization path
                backend,
                "A",
                statement="forall n, n = n",
                dependency_names=[("C.dep1", "uses")],
            )

        assert result is not None
        dep_targets = [t for t, _rel in result.dependency_names]
        # Tree dep "B.helper" should have been merged
        assert "B.helper" in dep_targets
        # Original dep should still be present
        assert "C.dep1" in dep_targets

    def test_process_declaration_tree_dep_failure_is_silent(self):
        """If extract_dependencies raises, dependency_names is unchanged."""
        from Poule.extraction.pipeline import process_declaration

        backend = Mock()
        backend.pretty_print.return_value = "forall n, n = n"
        backend.pretty_print_type.return_value = "Prop"

        # Use a dict constr_t with type_signature to trigger text-based path
        # that will produce a tree, then patch extract_dependencies to fail
        with patch(
            "Poule.extraction.dependency_extraction.extract_dependencies",
            side_effect=RuntimeError("boom"),
        ):
            result = process_declaration(
                "A.lemma1",
                "Lemma",
                {"type_signature": "nat -> nat"},
                backend,
                "A",
                statement="forall n, n = n",
                dependency_names=[("C.dep1", "uses")],
            )

        assert result is not None
        # Original deps preserved even if tree dep extraction failed
        dep_targets = [t for t, _rel in result.dependency_names]
        assert "C.dep1" in dep_targets


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
        name_to_id = {"A.lemma1": 1, "Stdlib.Init.Nat.add": 10}

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
        name_to_id = {"A.lemma1": 1, "Stdlib.Init.Nat.add": 10}

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
            "Stdlib.Init.Nat.add": 10,
            "Stdlib.Init.List.add": 20,
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
        """Tree deps are pre-merged into dependency_names by process_declaration.

        resolve_and_insert_dependencies no longer reads r.tree — it just
        processes whatever is in dependency_names.  Tree is None because
        it was nulled after batch_insert to save memory.
        """
        # Tree deps already merged into dependency_names by process_declaration
        r = self._make_result(
            "A.lemma1",
            [("B.lemma2", "uses"), ("C.def1", "uses")],
            tree=None,
        )
        name_to_id = {"A.lemma1": 1, "B.lemma2": 2, "C.def1": 3}

        iw = self._make_writer_and_call([r], name_to_id)

        iw.insert_dependencies.assert_called_once()
        edges = iw.insert_dependencies.call_args[0][0]
        # Should have edges from both sources (pre-merged)
        src_dst_pairs = {(e["src"], e["dst"]) for e in edges}
        assert (1, 2) in src_dst_pairs  # from Print Assumptions
        assert (1, 3) in src_dst_pairs  # from tree-based extraction

    def test_deduplication(self):
        """Same edge appearing twice in dependency_names is only inserted once."""
        # Both Print Assumptions and tree extraction yielded the same edge;
        # process_declaration merged them into dependency_names.
        r = self._make_result(
            "A.lemma1",
            [("B.lemma2", "uses"), ("B.lemma2", "uses")],
            tree=None,
        )
        name_to_id = {"A.lemma1": 1, "B.lemma2": 2}

        iw = self._make_writer_and_call([r], name_to_id)

        iw.insert_dependencies.assert_called_once()
        edges = iw.insert_dependencies.call_args[0][0]
        # Deduplicated: only one edge despite duplicate entries
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
            "Stdlib.Init.Nat.add": 10,  # FQN ending in .Nat.add
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
            "Stdlib.Init.Nat.add": 10,
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
        mock_r1.symbol_set = ["Stdlib.Init.Nat.add", "Stdlib.Init.Logic.eq"]
        mock_r1.dependency_names = []
        mock_r2 = Mock()
        mock_r2.name = "A.decl2"
        mock_r2.symbol_set = ["Stdlib.Init.Nat.add", "Stdlib.Init.Datatypes.nat"]
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

        result = CoqLspBackend._parse_about_kind("pred", messages)

        assert result.kind == "definition", (
            f"Expected 'definition' (Constant preferred over Notation), got {result.kind!r}"
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

        result = CoqLspBackend._parse_about_kind("foo", messages)

        assert result.kind == "notation", (
            f"Expected 'notation' when only Notation is present, got {result.kind!r}"
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
# 7b. max_files sampling
# ═══════════════════════════════════════════════════════════════════════════


class TestMaxFilesSampling:
    """run_extraction(max_files=N) randomly samples N .vo files."""

    def test_max_files_samples_subset(self):
        """When max_files < total .vo files, only max_files are processed."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl", "Lemma", {"mock": "c"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl": 1}

        mock_result = Mock()
        mock_result.name = "A.decl"
        mock_result.dependency_names = []

        # 10 .vo files discovered, but max_files=3
        all_vo = [Path(f"/fake/Module{i}.vo") for i in range(10)]

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=all_vo,
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
                max_files=3,
            )

        # Backend should have been called for exactly 3 .vo files
        assert backend.list_declarations.call_count == 3

    def test_max_files_none_processes_all(self):
        """When max_files is None, all .vo files are processed."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl", "Lemma", {"mock": "c"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl": 1}

        mock_result = Mock()
        mock_result.name = "A.decl"
        mock_result.dependency_names = []

        all_vo = [Path(f"/fake/Module{i}.vo") for i in range(5)]

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=all_vo,
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
                max_files=None,
            )

        assert backend.list_declarations.call_count == 5

    def test_max_files_greater_than_total_processes_all(self):
        """When max_files >= total .vo files, all are processed (no error)."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl", "Lemma", {"mock": "c"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl": 1}

        mock_result = Mock()
        mock_result.name = "A.decl"
        mock_result.dependency_names = []

        all_vo = [Path(f"/fake/Module{i}.vo") for i in range(3)]

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=all_vo,
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
                max_files=100,
            )

        assert backend.list_declarations.call_count == 3

    def test_max_files_progress_callback(self):
        """Progress callback reports sampling when max_files is active."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl", "Lemma", {"mock": "c"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl": 1}

        mock_result = Mock()
        mock_result.name = "A.decl"
        mock_result.dependency_names = []

        all_vo = [Path(f"/fake/Module{i}.vo") for i in range(10)]
        progress = Mock()

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=all_vo,
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
                max_files=4,
                progress_callback=progress,
            )

        msgs = [str(c) for c in progress.call_args_list]
        found_sampled = any("Sampled" in m and "--max-files 4" in m for m in msgs)
        assert found_sampled, f"Expected sampling progress message, got: {msgs}"

    def test_max_files_sampled_files_are_sorted(self):
        """Sampled .vo files are sorted by path for deterministic import order."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl", "Lemma", {"mock": "c"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.decl": 1}

        mock_result = Mock()
        mock_result.name = "A.decl"
        mock_result.dependency_names = []

        # Create paths that sort differently than discovery order
        all_vo = [Path(f"/fake/Z{i}.vo") for i in range(5)] + \
                 [Path(f"/fake/A{i}.vo") for i in range(5)]

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=all_vo,
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
                max_files=5,
            )

        # Verify the .vo paths passed to list_declarations are sorted
        called_paths = [
            c[0][0] for c in backend.list_declarations.call_args_list
        ]
        assert called_paths == sorted(called_paths)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Full Pipeline Integration (mock backend, 3 declarations)
# ═══════════════════════════════════════════════════════════════════════════


class TestFullRunIntegration:
    """End-to-end: mock backend with 3 declarations → correct DB writes."""

    def test_three_declarations_full_pipeline(self, tmp_path):
        from Poule.extraction.pipeline import run_extraction

        # 3 declarations: 1 lemma, 1 theorem, 1 notation (excluded)
        decls = [
            ("Stdlib.Init.Nat.add_comm", "Lemma", {"mock": "constr1"}),
            ("Stdlib.Init.Nat.add_assoc", "Theorem", {"mock": "constr2"}),
            ("Stdlib.Init.Nat.add_notation", "Notation", {"mock": "constr3"}),
        ]
        backend = _make_mock_backend(declarations=decls)
        backend.get_dependencies.side_effect = [
            [("Stdlib.Init.Nat.add_assoc", "uses")],  # add_comm uses add_assoc
            [],  # add_assoc has no deps
        ]

        writer = _make_mock_writer()
        name_to_id = {
            "Stdlib.Init.Nat.add_comm": 1,
            "Stdlib.Init.Nat.add_assoc": 2,
        }
        writer.batch_insert.return_value = name_to_id

        # process_declaration returns None for Notation (excluded),
        # valid results for the other two
        result_comm = Mock()
        result_comm.name = "Stdlib.Init.Nat.add_comm"
        result_comm.kind = "lemma"
        result_comm.symbol_set = ["Stdlib.Init.Nat.add", "Stdlib.Init.Logic.eq"]
        result_comm.dependency_names = [
            ("Stdlib.Init.Nat.add_assoc", "uses")
        ]

        result_assoc = Mock()
        result_assoc.name = "Stdlib.Init.Nat.add_assoc"
        result_assoc.kind = "theorem"
        result_assoc.symbol_set = ["Stdlib.Init.Nat.add"]
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

    def test_query_phase_restarts_backend_when_rss_exceeds_threshold(
        self, tmp_path
    ):
        """Backend is restarted between import-path groups only when
        coq-lsp RSS exceeds the threshold (specification §4.12)."""
        from Poule.extraction.pipeline import run_extraction

        # Two .vo files from different modules → two import-path groups.
        vo1 = Path("/fake/user-contrib/Pkg/Mod1.vo")
        vo2 = Path("/fake/user-contrib/Pkg/Mod2.vo")

        # Each .vo file yields one declaration.
        def fake_list_declarations(vo_path, **kwargs):
            if vo_path == vo1:
                return [("Pkg.Mod1.foo", "Lemma", {"type_signature": "nat", "source": "coq-lsp"})]
            if vo_path == vo2:
                return [("Pkg.Mod2.bar", "Lemma", {"type_signature": "nat", "source": "coq-lsp"})]
            return []

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = fake_list_declarations
        backend.query_declaration_data.side_effect = lambda names, **kw: {
            n: ("stmt", []) for n in names
        }
        # Simulate high RSS so restarts trigger.
        backend._get_child_rss_bytes.return_value = 10 * 1024 * 1024 * 1024

        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Pkg.Mod1.foo": 1, "Pkg.Mod2.bar": 2}

        mock_r1 = Mock()
        mock_r1.name = "Pkg.Mod1.foo"
        mock_r1.dependency_names = []
        mock_r2 = Mock()
        mock_r2.name = "Pkg.Mod2.bar"
        mock_r2.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[vo1, vo2],
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
            run_extraction(targets=["stdlib"], db_path=tmp_path / "test.db")

        # With high RSS: collecting phase restarts after each .vo (2 restarts),
        # query phase restarts between groups (1 restart). Total: >= 3 stop calls.
        assert backend.stop.call_count >= 3, (
            f"Expected >= 3 stop() calls with high RSS, "
            f"got {backend.stop.call_count}"
        )

        # query_declaration_data was called twice (once per group).
        assert backend.query_declaration_data.call_count == 2

    def test_query_phase_skips_restart_when_rss_is_low(
        self, tmp_path
    ):
        """Backend is NOT restarted when RSS stays under the threshold."""
        from Poule.extraction.pipeline import run_extraction

        vo1 = Path("/fake/user-contrib/Pkg/Mod1.vo")
        vo2 = Path("/fake/user-contrib/Pkg/Mod2.vo")

        def fake_list_declarations(vo_path, **kwargs):
            if vo_path == vo1:
                return [("Pkg.Mod1.foo", "Lemma", {"type_signature": "nat", "source": "coq-lsp"})]
            if vo_path == vo2:
                return [("Pkg.Mod2.bar", "Lemma", {"type_signature": "nat", "source": "coq-lsp"})]
            return []

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = fake_list_declarations
        backend.query_declaration_data.side_effect = lambda names, **kw: {
            n: ("stmt", []) for n in names
        }
        # Low RSS — no restarts should happen.
        backend._get_child_rss_bytes.return_value = 100 * 1024 * 1024  # 100 MiB

        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Pkg.Mod1.foo": 1, "Pkg.Mod2.bar": 2}

        mock_r1 = Mock()
        mock_r1.name = "Pkg.Mod1.foo"
        mock_r1.dependency_names = []
        mock_r2 = Mock()
        mock_r2.name = "Pkg.Mod2.bar"
        mock_r2.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[vo1, vo2],
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
            run_extraction(targets=["stdlib"], db_path=tmp_path / "test.db")

        # Only the final cleanup stop — no mid-pipeline restarts.
        assert backend.stop.call_count <= 1, (
            f"Expected <= 1 stop() call with low RSS, "
            f"got {backend.stop.call_count}"
        )

    def test_query_phase_restarts_between_batches_within_single_group(
        self, tmp_path
    ):
        """When a single import group has >50 declarations, the pipeline
        splits it into batch-sized chunks and checks RSS between them.
        With high RSS, the backend is restarted mid-group (spec §4.12)."""
        from Poule.extraction.pipeline import run_extraction

        # Single .vo file → single import group, but 60 declarations
        # (> batch_size of 50) → should produce 2 batches.
        vo = Path("/fake/user-contrib/Pkg/BigMod.vo")
        decl_names = [f"Pkg.BigMod.decl_{i}" for i in range(60)]

        def fake_list_declarations(vo_path, **kwargs):
            return [
                (name, "Lemma", {"type_signature": "nat", "source": "coq-lsp"})
                for name in decl_names
            ]

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = fake_list_declarations
        backend.query_declaration_data.side_effect = lambda names, **kw: {
            n: ("stmt", []) for n in names
        }
        # High RSS to trigger restarts between batches.
        backend._get_child_rss_bytes.return_value = 10 * 1024 * 1024 * 1024

        writer = _make_mock_writer()
        writer.batch_insert.return_value = {n: i for i, n in enumerate(decl_names)}

        mock_results = []
        for name in decl_names:
            r = Mock()
            r.name = name
            r.dependency_names = []
            mock_results.append(r)

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[vo],
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
                side_effect=mock_results,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=tmp_path / "test.db")

        # query_declaration_data should be called multiple times for the
        # single group (once per batch chunk), not just once.
        assert backend.query_declaration_data.call_count >= 2, (
            f"Expected >= 2 query_declaration_data calls for 60 decls "
            f"(batch_size=50), got {backend.query_declaration_data.call_count}"
        )

        # With high RSS: at least one mid-group restart should occur.
        # Collection phase: 1 restart (after the single .vo file).
        # Query phase: at least 1 restart between batch chunks.
        # Total: >= 2 stop calls (excluding final cleanup).
        assert backend.stop.call_count >= 2, (
            f"Expected >= 2 stop() calls (collection + intra-group restart), "
            f"got {backend.stop.call_count}"
        )

    def test_pass1_restarts_backend_between_batches_when_rss_high(
        self, tmp_path
    ):
        """Pass 1 checks RSS every 50 declarations and restarts
        coq-lsp when it exceeds the threshold (spec §4.12)."""
        from Poule.extraction.pipeline import run_extraction

        # Create enough declarations to trigger at least 2 RSS checks (every 50).
        num_decls = 110
        vo = Path("/fake/user-contrib/Pkg/Huge.vo")
        decl_names = [f"Pkg.Huge.d{i}" for i in range(num_decls)]

        def fake_list_declarations(vo_path, **kwargs):
            return [
                (n, "Lemma", {"type_signature": "nat", "source": "coq-lsp"})
                for n in decl_names
            ]

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = fake_list_declarations
        backend.query_declaration_data.side_effect = lambda names, **kw: {
            n: ("stmt", []) for n in names
        }
        # Low RSS during collection + query phases, high during Pass 1.
        # Switch to high RSS when process_declaration is first called
        # (unique to Pass 1).
        rss_state = {"phase": "early"}

        LOW_RSS = 100 * 1024 * 1024  # 100 MiB
        HIGH_RSS = 10 * 1024 * 1024 * 1024  # 10 GiB

        def rss_by_phase():
            return HIGH_RSS if rss_state["phase"] == "pass1" else LOW_RSS

        backend._get_child_rss_bytes.side_effect = lambda: rss_by_phase()

        writer = _make_mock_writer()
        writer.batch_insert.return_value = {n: i for i, n in enumerate(decl_names)}

        mock_results = []
        for name in decl_names:
            r = Mock()
            r.name = name
            r.dependency_names = []
            mock_results.append(r)

        result_iter = iter(mock_results)

        def tracking_process_decl(*args, **kwargs):
            rss_state["phase"] = "pass1"
            return next(result_iter)

        # Track restart pairs (stop+start) during pass1.  The final
        # cleanup calls stop() without start(), so only true restarts
        # produce a stop→start pair.
        pass1_restarts = []

        def tracking_stop(*a, **kw):
            if rss_state["phase"] == "pass1":
                pass1_restarts.append("stop")

        def tracking_start(*a, **kw):
            if rss_state["phase"] == "pass1" and pass1_restarts and pass1_restarts[-1] == "stop":
                pass1_restarts.append("start")

        backend.stop = Mock(side_effect=tracking_stop)
        backend.start = Mock(side_effect=tracking_start)

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[vo],
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
                side_effect=tracking_process_decl,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=tmp_path / "test.db")

        # At least one stop→start restart pair during Pass 1.
        restart_pairs = pass1_restarts.count("start")
        assert restart_pairs >= 1, (
            f"Expected >= 1 restart (stop+start) during Pass 1, "
            f"got {restart_pairs}. Events: {pass1_restarts}"
        )

    def test_collection_passes_rss_check_to_list_declarations(
        self, tmp_path
    ):
        """Pipeline passes an rss_check callback to list_declarations
        during declaration collection (spec §4.12)."""
        from Poule.extraction.pipeline import run_extraction

        vo = Path("/fake/user-contrib/Pkg/Mod.vo")

        captured_kwargs = []

        def capturing_list_declarations(vo_path, **kwargs):
            captured_kwargs.append(kwargs)
            return [("Pkg.Mod.foo", "Lemma", {"type_signature": "nat", "source": "coq-lsp"})]

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = capturing_list_declarations
        backend.query_declaration_data.side_effect = lambda names, **kw: {
            n: ("stmt", []) for n in names
        }

        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Pkg.Mod.foo": 1}

        mock_r = Mock()
        mock_r.name = "Pkg.Mod.foo"
        mock_r.dependency_names = []

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[vo],
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
                return_value=mock_r,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=tmp_path / "test.db")

        # list_declarations should have been called with rss_check kwarg.
        assert len(captured_kwargs) == 1
        assert "rss_check" in captured_kwargs[0]
        assert callable(captured_kwargs[0]["rss_check"])

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
# 13b. Empty Statement Fallback (§4.4 step 7)
# ═══════════════════════════════════════════════════════════════════════════


class TestEmptyStatementFallback:
    """When pretty_print returns empty, synthesize statement from type_signature
    (§4.4 step 7, updated)."""

    def test_empty_prefetched_statement_synthesizes_from_type_signature(self):
        """Pre-fetched empty string triggers type_signature fallback."""
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        constr_t = {"name": "TM_type", "type_signature": "Type", "source": "coq-lsp"}

        result = process_declaration(
            "Interval.Tactic.Private.TM.TMI.TM_type", "Definition", constr_t,
            backend, "/fake.vo",
            statement="", dependency_names=[],
        )

        assert result is not None
        assert result.statement == "TM_type : Type"
        backend.pretty_print.assert_not_called()

    def test_none_statement_with_empty_pretty_print_synthesizes(self):
        """When statement is None and pretty_print returns empty, fall back to
        type_signature synthesis."""
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        backend.pretty_print.return_value = ""
        constr_t = {"name": "foo", "type_signature": "nat -> nat", "source": "coq-lsp"}

        result = process_declaration(
            "Mod.Sub.foo", "Definition", constr_t, backend, "/fake.vo",
        )

        assert result is not None
        assert result.statement == "foo : nat -> nat"

    def test_fallback_uses_fqn_when_no_type_signature(self):
        """When type_signature is also unavailable, use FQN as statement."""
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        backend.pretty_print.return_value = ""
        backend.pretty_print_type.return_value = None
        constr_t = {"name": "bar", "source": "coq-lsp"}

        result = process_declaration(
            "Mod.Sub.bar", "Definition", constr_t, backend, "/fake.vo",
        )

        assert result is not None
        assert result.statement == "Mod.Sub.bar"


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
            "nat": "Stdlib.Init.Datatypes.nat",
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
        assert "Stdlib.Init.Datatypes.nat" in result.symbol_set
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
        constr_t = Const(fqn="Stdlib.Init.Nat.add")

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

        # Two .vo files both contain "Stdlib.Init.Nat.add"
        backend = _make_mock_backend()
        backend.list_declarations.side_effect = [
            [("Stdlib.Init.Nat.add", "Definition", {"mock": "constr1"})],
            [("Stdlib.Init.Nat.add", "Definition", {"mock": "constr2"})],
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Stdlib.Init.Nat.add": 1}

        result_mock = Mock()
        result_mock.name = "Stdlib.Init.Nat.add"
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
            [("Stdlib.Init.Nat.add", "Definition", {"mock": "constr1"})],
            [("Stdlib.Init.Nat.mul", "Definition", {"mock": "constr2"})],
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {
            "Stdlib.Init.Nat.add": 1,
            "Stdlib.Init.Nat.mul": 2,
        }

        result_add = Mock()
        result_add.name = "Stdlib.Init.Nat.add"
        result_add.kind = "definition"
        result_add.symbol_set = []
        result_add.dependency_names = []

        result_mul = Mock()
        result_mul.name = "Stdlib.Init.Nat.mul"
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


class TestReExportAliasCapture:
    """During deduplication, when a duplicate declaration is found from a
    different .vo file, the pipeline derives a re-export alias and stores it.

    Spec: extraction.md §4.4 "Re-export alias capture"."""

    def test_re_export_alias_captured(self, tmp_path):
        """ListDef.vo has canonical Coq.Lists.ListDef.map; List.vo re-exports
        it as Coq.Lists.List.map (different FQN, same declared_library).
        The re-export is detected via declared_library and an alias is stored."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend()
        # list_declarations returns DIFFERENT FQNs from different .vo files
        # (this matches real behavior: FQN = canonical_module + short_name)
        backend.list_declarations.side_effect = [
            [("Stdlib.Lists.ListDef.map", "Definition", {
                "declared_library": "Stdlib.Lists.ListDef",
                "type_signature": "forall A B, (A -> B) -> list A -> list B",
            })],
            [("Stdlib.Lists.List.map", "Definition", {
                "declared_library": "Stdlib.Lists.ListDef",
                "type_signature": "forall A B, (A -> B) -> list A -> list B",
            })],
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Stdlib.Lists.ListDef.map": 1}

        result_mock = Mock()
        result_mock.name = "Stdlib.Lists.ListDef.map"
        result_mock.kind = "definition"
        result_mock.symbol_set = []
        result_mock.dependency_names = []

        db_path = tmp_path / "index.db"

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[
                    Path("/fake/user-contrib/Stdlib/Lists/ListDef.vo"),
                    Path("/fake/user-contrib/Stdlib/Lists/List.vo"),
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
                return_value=result_mock,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        # writer.insert_re_export_aliases should be called with the alias
        writer.insert_re_export_aliases.assert_called_once()
        aliases = writer.insert_re_export_aliases.call_args[0][0]
        assert "Stdlib.Lists.List.map" in aliases
        assert aliases["Stdlib.Lists.List.map"] == "Stdlib.Lists.ListDef.map"

    def test_no_alias_when_same_module(self, tmp_path):
        """When declared_library matches the .vo file's canonical module,
        no alias is recorded — the declaration is not a re-export."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = [
            [("Stdlib.Init.Nat.add", "Definition", {
                "declared_library": "Corelib.Init.Nat",
                "type_signature": "nat -> nat -> nat",
            })],
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Stdlib.Init.Nat.add": 1}

        result_mock = Mock()
        result_mock.name = "Stdlib.Init.Nat.add"
        result_mock.kind = "definition"
        result_mock.symbol_set = []
        result_mock.dependency_names = []

        db_path = tmp_path / "index.db"

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[
                    Path("/fake/user-contrib/Stdlib/Init/Nat.vo"),
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
                return_value=result_mock,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        # insert_re_export_aliases should be called with empty dict
        writer.insert_re_export_aliases.assert_called_once()
        aliases = writer.insert_re_export_aliases.call_args[0][0]
        assert len(aliases) == 0

    def test_re_export_declared_library_none(self, tmp_path):
        """When declared_library is None (Coq 8.x), fallback dedup runs
        and no alias is captured for declarations with different FQNs."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = [
            [("Stdlib.Init.Nat.add", "Definition", {"type_signature": "nat -> nat -> nat"})],
            [("Stdlib.Init.Nat2.add", "Definition", {"type_signature": "nat -> nat -> nat"})],
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Stdlib.Init.Nat.add": 1, "Stdlib.Init.Nat2.add": 2}

        result_mock = Mock()
        result_mock.name = "Stdlib.Init.Nat.add"
        result_mock.kind = "definition"
        result_mock.symbol_set = []
        result_mock.dependency_names = []

        db_path = tmp_path / "index.db"

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[
                    Path("/fake/user-contrib/Stdlib/Init/Nat.vo"),
                    Path("/fake/user-contrib/Stdlib/Init/Nat2.vo"),
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
                return_value=result_mock,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        # No aliases — declared_library is absent, different FQNs
        writer.insert_re_export_aliases.assert_called_once()
        aliases = writer.insert_re_export_aliases.call_args[0][0]
        assert len(aliases) == 0


# ═══════════════════════════════════════════════════════════════════════════
# 13b. _normalize_declared_library — §4.4
# ═══════════════════════════════════════════════════════════════════════════


class TestNormalizeDeclaredLibrary:
    """_normalize_declared_library converts declared_library strings to
    canonical module format matching _vo_to_canonical_module output.

    Spec: extraction.md §4.4 re-export detection normalization."""

    def test_stdlib_prefix(self):
        from Poule.extraction.pipeline import _normalize_declared_library

        assert _normalize_declared_library("Stdlib.Numbers.NatInt.NZAdd") == "Stdlib.Numbers.NatInt.NZAdd"

    def test_corelib_prefix(self):
        from Poule.extraction.pipeline import _normalize_declared_library

        assert _normalize_declared_library("Corelib.Init.Nat") == "Stdlib.Init.Nat"

    def test_non_stdlib_unchanged(self):
        from Poule.extraction.pipeline import _normalize_declared_library

        assert _normalize_declared_library("mathcomp.ssreflect.ssrbool") == "mathcomp.ssreflect.ssrbool"

    def test_bare_stdlib(self):
        from Poule.extraction.pipeline import _normalize_declared_library

        assert _normalize_declared_library("Stdlib") == "Stdlib"

    def test_bare_corelib(self):
        from Poule.extraction.pipeline import _normalize_declared_library

        assert _normalize_declared_library("Corelib") == "Stdlib"


# ═══════════════════════════════════════════════════════════════════════════
# 14. FQN Derivation — §4.1.2
# ═══════════════════════════════════════════════════════════════════════════


class TestVoToLogicalPath:
    """_vo_to_logical_path derives correct logical module paths from .vo paths.

    Spec §4.1.2: The logical module path is derived from the .vo file path
    using heuristic path parsing (stripping known prefixes such as
    user-contrib/, theories/, and version-specific prefixes like Stdlib/).
    """

    def test_stdlib_rocq9_produces_stdlib_prefix(self):
        """user-contrib/Stdlib/Arith/PeanoNat.vo → Stdlib.Arith.PeanoNat (canonical)"""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path("/opt/coq/user-contrib/Stdlib/Arith/PeanoNat.vo")
        # _vo_to_logical_path returns the import path (no Stdlib prefix)
        assert CoqLspBackend._vo_to_logical_path(path) == "Arith.PeanoNat"
        # _vo_to_canonical_module returns the canonical name (with Stdlib prefix)
        assert CoqLspBackend._vo_to_canonical_module(path) == "Stdlib.Arith.PeanoNat"

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
        """user-contrib/Stdlib/Init/Nat.vo → Stdlib.Init.Nat (canonical)"""
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        path = Path("/opt/coq/user-contrib/Stdlib/Init/Nat.vo")
        # _vo_to_logical_path returns import path (stripped Stdlib prefix)
        assert CoqLspBackend._vo_to_logical_path(path) == "Init.Nat"
        # _vo_to_canonical_module returns canonical name
        assert CoqLspBackend._vo_to_canonical_module(path) == "Stdlib.Init.Nat"


class TestFQNDerivationInListDeclarations:
    """list_declarations returns fully qualified names by prepending the
    logical module path to short names from Search output.

    Spec §4.1.2: The fully qualified name is constructed by prepending the
    .vo file's logical module path to the short name returned by Search.
    """

    def test_short_names_get_module_path_prepended(self):
        """Given Search returns Nat.add_comm, the returned name should be
        Coq.Arith.PeanoNat.Nat.add_comm."""
        from Poule.extraction.backends.coqlsp_backend import AboutResult, CoqLspBackend

        backend = CoqLspBackend()
        # Patch internal methods to avoid needing a real coq-lsp process
        backend._ensure_alive = Mock()
        backend._run_vernac_query = Mock(return_value=(
            [],
            [{"text": "Nat.add_comm : forall n m, n + m = m + n", "level": 3}],
        ))
        backend._batch_get_about_metadata = Mock(return_value=[
            AboutResult("lemma", "opaque", "Stdlib.Numbers.NatInt.NZAdd", 59),
        ])

        vo_path = Path("/opt/coq/user-contrib/Stdlib/Arith/PeanoNat.vo")
        decls = backend.list_declarations(vo_path)

        assert len(decls) == 1
        name, _kind, _constr_t = decls[0]
        assert name == "Stdlib.Arith.PeanoNat.Nat.add_comm", (
            f"Expected FQN, got short name: {name}"
        )

    def test_mathcomp_short_names_get_module_path_prepended(self):
        """Given Search returns negb_involutive, the returned name should be
        mathcomp.ssreflect.ssrbool.negb_involutive."""
        from Poule.extraction.backends.coqlsp_backend import AboutResult, CoqLspBackend

        backend = CoqLspBackend()
        backend._ensure_alive = Mock()
        backend._run_vernac_query = Mock(return_value=(
            [],
            [{"text": "negb_involutive : forall b, negb (negb b) = b", "level": 3}],
        ))
        backend._batch_get_about_metadata = Mock(return_value=[
            AboutResult("lemma", None, None, None),
        ])

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
            ("Stdlib.Init.Nat.add", "Definition", {"type_signature": "nat -> nat -> nat", "source": "coq-lsp"}),
        ]

        result_mock = Mock()
        result_mock.name = "Stdlib.Init.Nat.add"
        result_mock.kind = "definition"
        result_mock.symbol_set = []
        result_mock.dependency_names = []

        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Stdlib.Init.Nat.add": 1}

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

        deps = backend.get_dependencies("Stdlib.Arith.PeanoNat.Nat.add_comm")
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

        data = backend.query_declaration_data(["Stdlib.Arith.PeanoNat.Nat.add_comm"])
        assert "Stdlib.Arith.PeanoNat.Nat.add_comm" in data
        _statement, deps = data["Stdlib.Arith.PeanoNat.Nat.add_comm"]
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
        backend.locate.return_value = "Stdlib.Init.Datatypes.nat"

        resolved = resolve_symbols({"nat"}, backend)

        assert "Stdlib.Init.Datatypes.nat" in resolved

    def test_infix_operators_resolved(self):
        """Infix operators like '+' are resolved via Locate (spec §4.4.1)."""
        from Poule.extraction.pipeline import resolve_symbols

        backend = _make_mock_backend()
        backend.locate.side_effect = lambda name: {
            "+": "Stdlib.Init.Nat.add",
            "nat": "Stdlib.Init.Datatypes.nat",
        }.get(name)

        resolved = resolve_symbols({"+", "nat"}, backend)

        assert "Stdlib.Init.Nat.add" in resolved
        assert "Stdlib.Init.Datatypes.nat" in resolved

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
            "Stdlib.Init.Nat.add",
            "Stdlib.ZArith.BinInt.Z.add",
        ]

        resolved = resolve_symbols({"+"}, backend)

        assert "Stdlib.Init.Nat.add" in resolved
        assert "Stdlib.ZArith.BinInt.Z.add" in resolved

    def test_empty_input_returns_empty(self):
        """Empty symbol set produces empty result."""
        from Poule.extraction.pipeline import resolve_symbols

        backend = _make_mock_backend()

        resolved = resolve_symbols(set(), backend)

        assert resolved == set()


# ═══════════════════════════════════════════════════════════════════════════
# 19. type_expr Fallback to pretty_print_type (spec §4.4 step 8)
# ═══════════════════════════════════════════════════════════════════════════


class TestTypeExprFallback:
    """When constr_t lacks type_signature, process_declaration falls back
    to backend.pretty_print_type() (spec §4.4 step 8)."""

    def test_fallback_to_pretty_print_type_when_no_type_sig(self):
        """Dict constr_t without type_signature triggers pretty_print_type."""
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        backend.pretty_print_type.return_value = "nat -> nat -> nat"
        constr_t = {"name": "Nat.add", "source": "coq-lsp"}

        result = process_declaration(
            "Nat.add", "Definition", constr_t, backend, "/fake/Nat.vo",
            statement="Nat.add = ...", dependency_names=[],
        )

        assert result is not None
        assert result.type_expr == "nat -> nat -> nat"
        backend.pretty_print_type.assert_called_once_with("Nat.add")

    def test_fallback_returns_none_when_pretty_print_type_fails(self):
        """When pretty_print_type raises, type_expr is None (not fatal)."""
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        backend.pretty_print_type.side_effect = Exception("backend error")
        constr_t = {"name": "Nat.add", "source": "coq-lsp"}

        result = process_declaration(
            "Nat.add", "Definition", constr_t, backend, "/fake/Nat.vo",
            statement="Nat.add = ...", dependency_names=[],
        )

        assert result is not None
        assert result.type_expr is None

    def test_no_fallback_when_type_sig_present(self):
        """type_signature in constr_t prevents pretty_print_type call."""
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
# 20. Parse Failure Partial Result (spec §4.4 step 1)
# ═══════════════════════════════════════════════════════════════════════════


class TestParseFailurePartialResult:
    """When type parsing fails, the declaration is stored with partial data:
    no tree, empty symbol set, empty WL vector, node_count=1 (spec §4.4)."""

    def test_partial_result_fields(self):
        from Poule.extraction.pipeline import process_declaration

        backend = _make_mock_backend()
        # constr_t without type_signature — parsing has nothing to parse
        constr_t = {"name": "Broken.decl", "source": "coq-lsp"}

        result = process_declaration(
            "Broken.decl", "Definition", constr_t, backend, "/fake.vo",
            statement="stmt", dependency_names=[],
        )

        assert result is not None
        assert result.tree is None
        assert result.symbol_set == []
        assert result.wl_vector == {}

    def test_partial_result_stored_with_node_count_one(self):
        """PipelineWriter.batch_insert sets node_count=1 when tree is None."""
        from Poule.extraction.pipeline import PipelineWriter

        mock_writer = Mock()
        mock_writer.insert_declarations.return_value = {"A": 1}
        mock_writer.insert_wl_vectors.return_value = None
        pw = PipelineWriter(mock_writer)

        mock_result = Mock()
        mock_result.name = "A"
        mock_result.module = "M"
        mock_result.kind = "definition"
        mock_result.statement = "stmt"
        mock_result.type_expr = None
        mock_result.tree = None  # no tree — parse failure
        mock_result.symbol_set = []
        mock_result.wl_vector = {}

        pw.batch_insert([mock_result])

        decl_dicts = mock_writer.insert_declarations.call_args[0][0]
        assert decl_dicts[0]["node_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# 21. Metadata Timestamp Format (spec §4.7)
# ═══════════════════════════════════════════════════════════════════════════


class TestMetadataTimestampFormat:
    """created_at uses ISO 8601 with seconds precision and Z suffix (spec §4.7)."""

    def test_created_at_is_iso8601_utc(self):
        import re

        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl1", "Lemma", {"mock": "constr"})]
        )
        backend.detect_version.return_value = "9.1.1"
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
                return_value="9.1.1",
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        kwargs = writer.write_metadata.call_args[1]
        ts = kwargs["created_at"]
        # Must match ISO 8601: YYYY-MM-DDTHH:MM:SSZ
        assert re.match(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", ts
        ), f"Timestamp {ts!r} does not match ISO 8601 with Z suffix"


# ═══════════════════════════════════════════════════════════════════════════
# 22. Per-Library Metadata Values (spec §4.7)
# ═══════════════════════════════════════════════════════════════════════════


class TestPerLibraryMetadataValues:
    """Per-library extraction writes correct library identifier and version."""

    def test_library_key_matches_target(self):
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("A.decl1", "Lemma", {"mock": "constr"})]
        )
        backend.detect_version.return_value = "9.1.1"
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
                return_value="2.5.0",
            ),
        ):
            run_extraction(targets=["mathcomp"], db_path=Path("/tmp/test.db"))

        kwargs = writer.write_metadata.call_args[1]
        assert kwargs["library"] == "mathcomp"
        assert kwargs["library_version"] == "2.5.0"

    def test_declarations_count_matches_indexed(self):
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[
                ("A.d1", "Lemma", {"mock": "constr"}),
                ("A.d2", "Theorem", {"mock": "constr"}),
            ]
        )
        backend.detect_version.return_value = "9.1.1"
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"A.d1": 1, "A.d2": 2}

        mock_r = Mock()
        mock_r.name = "A.d1"
        mock_r.dependency_names = []

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
                return_value=mock_r,
            ),
            patch(
                "Poule.extraction.pipeline.detect_library_version",
                return_value="9.1.1",
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        kwargs = writer.write_metadata.call_args[1]
        assert kwargs["declarations"] == "2"


# ═══════════════════════════════════════════════════════════════════════════
# 23. Multi-Line Type Signature Parsing (spec §4.1.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiLineTypeSigParsing:
    """coq-lsp may break long type signatures across lines (spec §4.1.1).
    The parser must join continuation lines into a single type signature."""

    def test_multiline_type_sig_collapsed_to_single_line(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        raw = "forall (n : nat),\n  n + 0 = n"
        result = CoqLspBackend._normalize_type_sig(raw)
        assert result == "forall (n : nat), n + 0 = n"

    def test_leading_whitespace_on_continuation_stripped(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        raw = "forall (A : Type)\n    (x : A),\n    x = x"
        result = CoqLspBackend._normalize_type_sig(raw)
        assert result == "forall (A : Type) (x : A), x = x"

    def test_single_line_unchanged(self):
        from Poule.extraction.backends.coqlsp_backend import CoqLspBackend

        raw = "nat -> nat -> nat"
        result = CoqLspBackend._normalize_type_sig(raw)
        assert result == "nat -> nat -> nat"


# ═══════════════════════════════════════════════════════════════════════════
# 24. Resolve Cache Shared Across Declarations (spec §4.4.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestResolveCacheSharedAcrossRun:
    """A single resolution cache is shared across all declarations in an
    indexing run, so that each unique symbol is resolved at most once
    (spec §4.4.1 step 2)."""

    def test_single_cache_across_multiple_declarations(self):
        """Two declarations sharing symbol 'nat' should only trigger one Locate."""
        from Poule.extraction.pipeline import resolve_symbols

        backend = _make_mock_backend()
        backend.locate.return_value = "Stdlib.Init.Datatypes.nat"

        shared_cache: dict = {}

        # First declaration: 'nat' not in cache, triggers Locate
        resolve_symbols({"nat"}, backend, cache=shared_cache)
        assert backend.locate.call_count == 1

        # Second declaration: 'nat' in cache, no Locate
        resolve_symbols({"nat", "bool"}, backend, cache=shared_cache)
        # 'bool' is new, 'nat' is cached → only 1 additional call
        assert backend.locate.call_count == 2


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
        mock_r1.symbol_set = ["Stdlib.Init.Datatypes.nat"]  # FQN
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
        assert "Stdlib.Init.Datatypes.nat" in freq_dict


# ═══════════════════════════════════════════════════════════════════════════
# Proof-body detection (specification/extraction.md §4.4 step 9)
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectProofBodySignal0ModuleAlias:
    """Signal 0: module alias line → has_proof_body=2 (§4.4 step 9)."""

    def _make_source(self, tmp_path, lib_name, content):
        """Helper: create a .v file at user-contrib/<lib_name>/<leaf>.v."""
        parts = lib_name.split(".")
        source_dir = tmp_path / "user-contrib" / "/".join(parts[:-1])
        source_dir.mkdir(parents=True, exist_ok=True)
        v_file = source_dir / f"{parts[-1]}.v"
        v_file.write_text(content)
        return tmp_path / "user-contrib"

    def test_module_alias_returns_2_for_lemma(self, tmp_path):
        """GIVEN a lemma whose declared_line points to 'Module I1 := FloatIntervalFull F.'
        WHEN detect_proof_body runs
        THEN has_proof_body=2 (functor-instantiated, proof in another file).
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Interval.Tactic", (
            "Require Import Float_full.\n"
            "Module IntervalTactic (F : FloatOps).\n"
            "Module I1 := FloatIntervalFull F.\n"
            "End IntervalTactic.\n"
        ))
        result = detect_proof_body(
            "Interval.Tactic.Private.I1.F'.classify_real", "lemma",
            opacity=None, declared_line=3,
            declared_library="Interval.Tactic",
            lib_root=lib_root,
        )
        assert result == 2

    def test_module_alias_returns_2_for_theorem(self, tmp_path):
        """Module alias detection applies to theorems too."""
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Interval.Tactic", (
            "Module IT := IntervalTacticAux F I1.\n"
        ))
        result = detect_proof_body(
            "Interval.Tactic.Private.IT1.some_thm", "theorem",
            opacity=None, declared_line=1,
            declared_library="Interval.Tactic",
            lib_root=lib_root,
        )
        assert result == 2

    def test_module_alias_returns_2_for_opaque(self, tmp_path):
        """Signal 0 takes priority over Signal 1 (opacity).
        Even if opaque, a functor-instantiated declaration is not extractable
        from the host file.
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Interval.Tactic", (
            "Module I1 := FloatIntervalFull F.\n"
        ))
        result = detect_proof_body(
            "Interval.Tactic.I1.opaque_lemma", "lemma",
            opacity="opaque", declared_line=1,
            declared_library="Interval.Tactic",
            lib_root=lib_root,
        )
        assert result == 2

    def test_module_definition_block_returns_1_not_2(self, tmp_path):
        """GIVEN declared_line points to 'Module Private.' (a definition block, not alias)
        WHEN detect_proof_body runs
        THEN has_proof_body is NOT 2 — only 'Module X :=' triggers signal 0.
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Interval.Tactic", (
            "Module Private.\n"
            "Lemma foo : True.\n"
            "Proof. exact I. Qed.\n"
            "End Private.\n"
        ))
        result = detect_proof_body(
            "Interval.Tactic.Private.foo", "lemma",
            opacity=None, declared_line=1,
            declared_library="Interval.Tactic",
            lib_root=lib_root,
        )
        assert result != 2  # Should be 1 (via signal 2: kind=lemma)

    def test_no_declared_line_skips_signal_0(self):
        """Without declared_line, signal 0 is skipped → falls through to later signals."""
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body(
            "Foo.bar", "lemma", opacity=None,
        )
        assert result == 1  # Signal 2: kind=lemma

    def test_module_alias_with_leading_whitespace(self, tmp_path):
        """Module alias lines may have leading whitespace."""
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Interval.Tactic", (
            "  Module I1 := FloatIntervalFull F.\n"
        ))
        result = detect_proof_body(
            "Interval.Tactic.I1.some_decl", "lemma",
            opacity=None, declared_line=1,
            declared_library="Interval.Tactic",
            lib_root=lib_root,
        )
        assert result == 2


class TestDetectProofBodySignal1Opacity:
    """Signal 1: opacity is informational only, no short-circuit (§4.4 step 9)."""

    def _make_source(self, tmp_path, lib_name, content):
        """Helper: create a .v file at user-contrib/<lib_name>/<leaf>.v."""
        parts = lib_name.split(".")
        source_dir = tmp_path / "user-contrib" / "/".join(parts[:-1])
        source_dir.mkdir(parents=True, exist_ok=True)
        v_file = source_dir / f"{parts[-1]}.v"
        v_file.write_text(content)
        return tmp_path / "user-contrib"

    def test_opaque_without_source_info_returns_0(self):
        """GIVEN opacity='opaque' and no declared_line/declared_library
        WHEN detect_proof_body runs
        THEN has_proof_body=0 (opacity alone is insufficient; Signal 3
        cannot run without source info, conservative default).
        """
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body(
            "Stdlib.Arith.PeanoNat.Nat.add_comm", "definition",
            opacity="opaque",
        )
        assert result == 0

    def test_opaque_with_proof_requiring_keyword_returns_1(self, tmp_path):
        """GIVEN opacity='opaque' and source line starts with Lemma
        WHEN detect_proof_body runs
        THEN has_proof_body=1 (Signal 3 confirms proof script exists).
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Foo", (
            "(* preamble *)\n"
            "Lemma add_0_l : forall n, 0 + n = n.\n"
            "Proof. auto. Qed.\n"
        ))
        result = detect_proof_body(
            "Test.Foo.add_0_l", "definition",
            opacity="opaque", declared_library="Stdlib.Test.Foo",
            declared_line=2, lib_root=lib_root,
        )
        assert result == 1

    def test_opaque_autogenerated_returns_0(self, tmp_path):
        """GIVEN opacity='opaque' but source line is HB.instance (auto-generated)
        WHEN detect_proof_body runs
        THEN has_proof_body=0 (Signal 3: not a proof-requiring keyword).
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "mathcomp.algebra.archimedean", (
            "(* preamble *)\n"
            "HB.instance Definition _ := Num.IntDomain_isNumDomain.Build R intrP floorP.\n"
        ))
        result = detect_proof_body(
            "mathcomp.algebra.archimedean.Num.Builders_19.floorP", "definition",
            opacity="opaque", declared_library="mathcomp.algebra.archimedean",
            declared_line=2, lib_root=lib_root,
        )
        assert result == 0


class TestDetectProofBodySignal2Kind:
    """Signal 2: kind ∈ {lemma, theorem} → 1 for Coq ≤8.x (§4.4 step 9)."""

    def test_lemma_kind_returns_1(self):
        """GIVEN kind='lemma' and opacity=None (Coq 8.x preserves Vernacular kind)
        WHEN detect_proof_body runs
        THEN has_proof_body=1 (Lemma always enters proof mode).
        """
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body("Foo.bar", "lemma", opacity=None)
        assert result == 1

    def test_theorem_kind_returns_1(self):
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body("Foo.baz", "theorem", opacity=None)
        assert result == 1

    def test_lemma_kind_transparent_returns_1(self):
        """Lemma proved with Defined. is transparent but still has proof body."""
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body(
            "Foo.bar", "lemma", opacity="transparent",
        )
        assert result == 1

    def test_definition_kind_without_declared_line_returns_0(self):
        """GIVEN kind='definition' and opacity=None, no declared_line
        WHEN detect_proof_body runs
        THEN has_proof_body=0 (definition is ambiguous, conservative default).
        """
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body("Foo.qux", "definition", opacity=None)
        assert result == 0


class TestDetectProofBodySignal3LineAnchored:
    """Signal 3: line-anchored .v source check (§4.4 step 9)."""

    def _make_source(self, tmp_path, lib_name, content):
        """Helper: create a .v file at user-contrib/<lib_name>/<leaf>.v."""
        parts = lib_name.split(".")
        source_dir = tmp_path / "user-contrib" / "/".join(parts[:-1])
        source_dir.mkdir(parents=True, exist_ok=True)
        v_file = source_dir / f"{parts[-1]}.v"
        v_file.write_text(content)
        return tmp_path / "user-contrib"

    def test_lemma_keyword_at_declared_line(self, tmp_path):
        """GIVEN declared_line points to a line starting with 'Lemma'
        WHEN detect_proof_body runs
        THEN has_proof_body=1 (Lemma is proof-requiring).
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test", (
            "(* preamble *)\n"
            "Lemma foo : 1 + 1 = 2.\n"
            "Proof. reflexivity. Qed.\n"
        ))
        result = detect_proof_body(
            "Test.foo", "definition",
            opacity="transparent", declared_line=2,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_theorem_keyword_at_declared_line(self, tmp_path):
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Theorem bar : True.\nProof. exact I. Qed.\n")
        result = detect_proof_body(
            "Test.bar", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_proposition_keyword_at_declared_line(self, tmp_path):
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Proposition p : True.\nProof. exact I. Qed.\n")
        result = detect_proof_body(
            "Test.p", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_corollary_keyword_at_declared_line(self, tmp_path):
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Corollary c : True.\nProof. exact I. Qed.\n")
        result = detect_proof_body(
            "Test.c", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_fact_keyword_at_declared_line(self, tmp_path):
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Fact f : True.\nProof. exact I. Qed.\n")
        result = detect_proof_body(
            "Test.f", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_remark_keyword_at_declared_line(self, tmp_path):
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Remark r : True.\nProof. exact I. Qed.\n")
        result = detect_proof_body(
            "Test.r", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_definition_with_proof_keyword(self, tmp_path):
        """GIVEN transparent Definition with 'Proof.' after declared_line
        WHEN detect_proof_body runs
        THEN has_proof_body=1 (Proof keyword found scanning forward).
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Definition bar : nat.\nProof. exact 0. Defined.\n")
        result = detect_proof_body(
            "Test.bar", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_definition_with_proof_using(self, tmp_path):
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Definition foo : nat.\nProof using. exact 0. Defined.\n")
        result = detect_proof_body(
            "Test.foo", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_definition_with_proof_with(self, tmp_path):
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Definition foo : nat.\nProof with auto. auto. Defined.\n")
        result = detect_proof_body(
            "Test.foo", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_definition_with_assign_returns_0(self, tmp_path):
        """GIVEN transparent definition with := at declared_line
        WHEN detect_proof_body runs
        THEN has_proof_body=0 (no Proof keyword found).
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Definition eq := @eq nat.\n")
        result = detect_proof_body(
            "Test.eq", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 0

    def test_no_declared_line_returns_0(self):
        """GIVEN transparent declaration without declared_line
        WHEN detect_proof_body runs
        THEN has_proof_body=0 (conservative default).
        """
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body(
            "Foo.bar", "definition",
            opacity="transparent", declared_line=None,
        )
        assert result == 0

    def test_missing_v_file_returns_0(self):
        """GIVEN declared_line but .v file does not exist
        WHEN detect_proof_body runs
        THEN has_proof_body=0 (conservative default).
        """
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body(
            "Foo.bar", "definition",
            opacity="transparent", declared_line=5,
            declared_library="Stdlib.Missing.Module",
            lib_root=None,
        )
        assert result == 0

    def test_nested_module_same_short_name(self, tmp_path):
        """GIVEN two declarations with same short name in nested modules
        WHEN detect_proof_body runs with correct declared_line for each
        THEN each gets the correct has_proof_body value.

        This is the key regression test: the old regex approach had a
        short-name collision bug. The line-anchored approach fixes it.
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test", (
            "Module A.\n"
            "  Definition bar := 42.\n"
            "End A.\n"
            "\n"
            "Module B.\n"
            "  Lemma bar : 1 + 1 = 2.\n"
            "  Proof. reflexivity. Qed.\n"
            "End B.\n"
        ))
        # A.bar: := definition on line 2 → 0
        result_a = detect_proof_body(
            "Test.A.bar", "definition",
            opacity="transparent", declared_line=2,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result_a == 0

        # B.bar: Lemma on line 6 → 1
        result_b = detect_proof_body(
            "Test.B.bar", "definition",
            opacity="transparent", declared_line=6,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result_b == 1

    def test_instance_with_proof(self, tmp_path):
        """GIVEN transparent Instance with Proof block
        WHEN detect_proof_body runs
        THEN has_proof_body=1.
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Instance foo : SomeClass nat.\nProof. constructor. Defined.\n")
        result = detect_proof_body(
            "Test.foo", "instance",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 1

    def test_instance_with_assign_returns_0(self, tmp_path):
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Test.Test",
            "Instance foo : SomeClass nat := { method := fun x => x }.\n")
        result = detect_proof_body(
            "Test.foo", "instance",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Test.Test",
            lib_root=lib_root,
        )
        assert result == 0

    def test_declared_library_resolves_correct_file(self, tmp_path):
        """GIVEN declared_library pointing to a different module than the discovery path
        WHEN detect_proof_body runs
        THEN it reads the .v file for declared_library.
        """
        from Poule.extraction.pipeline import detect_proof_body

        lib_root = self._make_source(tmp_path, "Stdlib.Source.Source",
            "Definition foo : nat.\nProof. exact 0. Defined.\n")
        result = detect_proof_body(
            "Source.foo", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Source.Source",
            lib_root=lib_root,
        )
        assert result == 1

    def test_declared_library_prefix_stripping(self, tmp_path):
        """declared_library with first component stripped (e.g., Stdlib → lib_root)."""
        from Poule.extraction.pipeline import detect_proof_body

        # Create file at lib_root/Source/Source.v (stripping "Stdlib" prefix)
        source_dir = tmp_path / "user-contrib" / "Source"
        source_dir.mkdir(parents=True)
        v_file = source_dir / "Source.v"
        v_file.write_text("Lemma foo : True.\nProof. exact I. Qed.\n")

        result = detect_proof_body(
            "Source.foo", "definition",
            opacity="transparent", declared_line=1,
            declared_library="Stdlib.Source.Source",
            lib_root=tmp_path / "user-contrib",
        )
        assert result == 1


class TestDetectProofBodyCorelibAlias:
    """Signal 3 with Corelib.* declared_library resolves to Stdlib/ paths
    (Rocq 9.x compatibility — spec §4.4 step 9)."""

    def _make_source(self, tmp_path, lib_name, content):
        """Helper: create a .v file at user-contrib/<lib_name>/<leaf>.v."""
        parts = lib_name.split(".")
        source_dir = tmp_path / "user-contrib" / "/".join(parts[:-1])
        source_dir.mkdir(parents=True, exist_ok=True)
        v_file = source_dir / f"{parts[-1]}.v"
        v_file.write_text(content)
        return tmp_path / "user-contrib"

    def test_corelib_declared_library_resolves_to_stdlib(self, tmp_path):
        """GIVEN declared_library='Corelib.Init.Nat' but .v file is at Stdlib/Init/Nat.v
        WHEN detect_proof_body runs
        THEN the .v file is found via Corelib→Stdlib alias and has_proof_body=1.
        """
        from Poule.extraction.pipeline import detect_proof_body

        # File is at Stdlib/Init/Nat.v (Rocq 9.x layout)
        lib_root = self._make_source(tmp_path, "Stdlib.Init.Nat", (
            "Lemma addn0 : forall n, n + 0 = n.\n"
            "Proof. intros. ring. Qed.\n"
        ))
        result = detect_proof_body(
            "Nat.addn0", "definition",
            opacity="transparent", declared_line=1,
            # About reports Corelib.Init.Nat but file is at Stdlib/Init/Nat.v
            declared_library="Corelib.Init.Nat",
            lib_root=lib_root,
        )
        assert result == 1

    def test_corelib_alias_in_refine_kind(self, tmp_path):
        """refine_kind must also resolve Corelib→Stdlib for kind recovery."""
        from Poule.extraction.pipeline import refine_kind

        lib_root = self._make_source(tmp_path, "Stdlib.Init.Nat", (
            "Lemma addn0 : forall n, n + 0 = n.\n"
            "Proof. intros. ring. Qed.\n"
        ))
        result = refine_kind(
            "definition",
            declared_line=1,
            declared_library="Corelib.Init.Nat",
            lib_root=lib_root,
        )
        assert result == "lemma"

    def test_resolve_v_path_corelib_to_stdlib(self, tmp_path):
        """_resolve_v_path resolves Corelib.X.Y to Stdlib/X/Y.v."""
        from Poule.extraction.pipeline import _resolve_v_path

        lib_root = self._make_source(tmp_path, "Stdlib.Init.Nat", "")
        result = _resolve_v_path("Corelib.Init.Nat", lib_root)
        assert result is not None
        assert "Stdlib" in str(result)


class TestDetectProofBodyKindFilter:
    """Kind filter: excluded kinds get has_proof_body=0 (§4.4 step 9)."""

    def test_inductive_returns_0_even_if_opaque(self):
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body(
            "Stdlib.Init.Datatypes.nat", "inductive", opacity="opaque",
        )
        assert result == 0

    def test_constructor_returns_0(self):
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body(
            "Stdlib.Init.Datatypes.O", "constructor", opacity="opaque",
        )
        assert result == 0

    def test_axiom_returns_0(self):
        from Poule.extraction.pipeline import detect_proof_body

        result = detect_proof_body(
            "Stdlib.Init.Logic.functional_extensionality", "axiom",
            opacity=None,
        )
        assert result == 0


# ═══════════════════════════════════════════════════════════════════════════
# Dangling re-export alias validation — §4.4
# ═══════════════════════════════════════════════════════════════════════════


class TestDanglingReExportAliasValidation:
    """When a re-export alias's canonical_fqn doesn't resolve to any
    extracted declaration, the re-exported declaration must be kept
    instead of being skipped.

    This happens when the canonical module is a functor body whose
    declarations are not directly extractable as top-level names
    (e.g., Coq.Numbers.NatInt.NZOrder.le_refl).

    Spec: extraction.md §4.4 re-export detection."""

    def test_dangling_alias_keeps_declaration(self, tmp_path):
        """When canonical_fqn points to a non-existent declaration,
        the re-exported declaration is kept and no alias is stored."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend()
        # NZOrder.vo yields no declarations (functor body)
        # PeanoNat.vo yields le_refl declared in NZOrder
        backend.list_declarations.side_effect = [
            [],  # NZOrder.vo — empty (functor body)
            [("Stdlib.Arith.PeanoNat.Nat.le_refl", "Definition", {
                "declared_library": "Stdlib.Numbers.NatInt.NZOrder",
                "type_signature": "forall n : nat, n <= n",
            })],
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {
            "Stdlib.Arith.PeanoNat.Nat.le_refl": 1,
        }

        result_mock = Mock()
        result_mock.name = "Stdlib.Arith.PeanoNat.Nat.le_refl"
        result_mock.kind = "definition"
        result_mock.symbol_set = []
        result_mock.dependency_names = []

        db_path = tmp_path / "index.db"
        process_mock = Mock(return_value=result_mock)

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[
                    Path("/fake/user-contrib/Stdlib/Numbers/NatInt/NZOrder.vo"),
                    Path("/fake/user-contrib/Stdlib/Arith/PeanoNat.vo"),
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
                process_mock,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        # The declaration should be processed (not skipped)
        process_mock.assert_called_once()

        # The alias should NOT be stored (canonical target doesn't exist)
        writer.insert_re_export_aliases.assert_called_once()
        aliases = writer.insert_re_export_aliases.call_args[0][0]
        assert "Stdlib.Arith.PeanoNat.Nat.le_refl" not in aliases

    def test_valid_alias_still_works(self, tmp_path):
        """When canonical_fqn exists, the alias is kept and the
        re-export is skipped (existing behavior preserved)."""
        from Poule.extraction.pipeline import run_extraction

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = [
            [("Stdlib.Lists.ListDef.map", "Definition", {
                "declared_library": "Stdlib.Lists.ListDef",
                "type_signature": "forall A B, (A -> B) -> list A -> list B",
            })],
            [("Stdlib.Lists.List.map", "Definition", {
                "declared_library": "Stdlib.Lists.ListDef",
                "type_signature": "forall A B, (A -> B) -> list A -> list B",
            })],
        ]
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Stdlib.Lists.ListDef.map": 1}

        result_mock = Mock()
        result_mock.name = "Stdlib.Lists.ListDef.map"
        result_mock.kind = "definition"
        result_mock.symbol_set = []
        result_mock.dependency_names = []

        db_path = tmp_path / "index.db"
        process_mock = Mock(return_value=result_mock)

        with (
            patch(
                "Poule.extraction.pipeline.discover_libraries",
                return_value=[
                    Path("/fake/user-contrib/Stdlib/Lists/ListDef.vo"),
                    Path("/fake/user-contrib/Stdlib/Lists/List.vo"),
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
                process_mock,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=db_path)

        # Only the canonical declaration should be processed
        process_mock.assert_called_once()

        # The alias should be stored
        writer.insert_re_export_aliases.assert_called_once()
        aliases = writer.insert_re_export_aliases.call_args[0][0]
        assert "Stdlib.Lists.List.map" in aliases
        assert aliases["Stdlib.Lists.List.map"] == "Stdlib.Lists.ListDef.map"
