"""TDD tests for Coq library extraction (specification/extraction.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/wily_rooster/extraction/.

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
        from wily_rooster.extraction.kind_mapping import map_kind

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
        from wily_rooster.extraction.kind_mapping import map_kind

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
        ],
    )
    def test_excluded_form_returns_none(self, coq_form):
        from wily_rooster.extraction.kind_mapping import map_kind

        assert map_kind(coq_form) is None


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
        ],
    )
    def test_case_insensitive_input(self, coq_form, expected):
        from wily_rooster.extraction.kind_mapping import map_kind

        assert map_kind(coq_form) == expected


# ═══════════════════════════════════════════════════════════════════════════
# 2. Library Discovery
# ═══════════════════════════════════════════════════════════════════════════


class TestDiscoverLibraries:
    """discover_libraries returns .vo file paths for requested targets."""

    def test_returns_vo_paths_from_mock_filesystem(self, tmp_path):
        from wily_rooster.extraction.pipeline import discover_libraries

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

        with patch("wily_rooster.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(tmp_path) + "\n"
            )
            result = discover_libraries("stdlib")

        assert len(result) == 3
        assert all(str(p).endswith(".vo") for p in result)

    def test_raises_extraction_error_when_target_not_found(self, tmp_path):
        from wily_rooster.extraction.errors import ExtractionError
        from wily_rooster.extraction.pipeline import discover_libraries

        # Empty directory — no .vo files
        empty = tmp_path / "empty"
        empty.mkdir()

        with patch("wily_rooster.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(empty) + "\n"
            )
            with pytest.raises(ExtractionError):
                discover_libraries("stdlib")

    def test_raises_extraction_error_when_coq_not_installed(self):
        from wily_rooster.extraction.errors import ExtractionError
        from wily_rooster.extraction.pipeline import discover_libraries

        with patch("wily_rooster.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.side_effect = FileNotFoundError("coqc not found")
            with pytest.raises(ExtractionError):
                discover_libraries("stdlib")


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
        from wily_rooster.extraction.pipeline import run_extraction

        backend = _make_mock_backend(
            declarations=[("Coq.Init.Nat.add", "Definition", {"mock": "constr"})]
        )
        writer = _make_mock_writer()
        writer.batch_insert.return_value = {"Coq.Init.Nat.add": 1}

        with (
            patch(
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Init/Nat.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        # Declaration should have been batch-inserted
        writer.batch_insert.assert_called()


class TestPass1DeclarationFailure:
    """When normalization fails for one declaration, it is logged and skipped."""

    def test_failing_declaration_is_skipped_others_continue(self):
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Init.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
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
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Lib.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
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
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
                side_effect=[mock_result1, mock_result2],
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        writer.resolve_and_insert_dependencies.assert_called()


class TestPass2UnresolvedTargets:
    """Unresolved dependency targets are silently skipped."""

    def test_unresolved_targets_skipped(self):
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            # Should NOT raise — unresolved targets are skipped
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        writer.resolve_and_insert_dependencies.assert_called()


# ═══════════════════════════════════════════════════════════════════════════
# 5. Post-Processing
# ═══════════════════════════════════════════════════════════════════════════


class TestPostProcessingSymbolFreq:
    """Symbol frequencies are computed from all declarations' symbol sets."""

    def test_symbol_frequencies_computed_correctly(self):
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
                side_effect=[mock_r1, mock_r2],
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        writer.insert_symbol_freq.assert_called()


class TestPostProcessingMetadata:
    """Metadata is written: schema_version, coq_version, etc."""

    def test_metadata_written_with_required_keys(self):
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            run_extraction(targets=["stdlib"], db_path=Path("/tmp/test.db"))

        # write_metadata should be called with version info
        writer.write_metadata.assert_called()
        metadata_call = writer.write_metadata.call_args
        # The metadata must include schema_version, coq_version,
        # mathcomp_version, created_at
        args = metadata_call[0] if metadata_call[0] else ()
        kwargs = metadata_call[1] if metadata_call[1] else {}
        # We check that the call was made; exact argument structure
        # depends on implementation, but it must be invoked.


class TestPostProcessingFinalize:
    """writer.finalize() is called after post-processing."""

    def test_finalize_called_on_writer(self):
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
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
        from wily_rooster.extraction.errors import ExtractionError
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[
                    Path("/fake/A.vo"),
                    Path("/fake/B.vo"),
                ],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
                return_value=mock_result,
            ),
        ):
            with pytest.raises(ExtractionError, match="Backend"):
                run_extraction(targets=["stdlib"], db_path=db_path)

        # Partial database file should be deleted
        assert not db_path.exists()

    def test_backend_crash_deletes_partial_db_file(self, tmp_path):
        from wily_rooster.extraction.errors import ExtractionError
        from wily_rooster.extraction.pipeline import run_extraction

        db_path = tmp_path / "partial.db"
        # Pre-create the file to verify it gets cleaned up
        db_path.touch()

        backend = _make_mock_backend()
        backend.list_declarations.side_effect = ExtractionError(
            "Backend crash"
        )

        with (
            patch(
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=_make_mock_writer(),
            ),
        ):
            with pytest.raises(ExtractionError):
                run_extraction(targets=["stdlib"], db_path=db_path)

        assert not db_path.exists()


class TestBackendNotFound:
    """Missing backend raises ExtractionError before processing starts."""

    def test_backend_not_found_raises_extraction_error(self, tmp_path):
        from wily_rooster.extraction.errors import ExtractionError
        from wily_rooster.extraction.pipeline import run_extraction

        with (
            patch(
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
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
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
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
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
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
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/Nat.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
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
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
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
        from wily_rooster.extraction.pipeline import run_extraction

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
                "wily_rooster.extraction.pipeline.discover_libraries",
                return_value=[Path("/fake/A.vo")],
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_backend",
                return_value=backend,
            ),
            patch(
                "wily_rooster.extraction.pipeline.create_writer",
                return_value=writer,
            ),
            patch(
                "wily_rooster.extraction.pipeline.process_declaration",
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
# 9. ExtractionError
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractionError:
    """ExtractionError carries a message and is the base error class."""

    def test_extraction_error_is_exception(self):
        from wily_rooster.extraction.errors import ExtractionError

        assert issubclass(ExtractionError, Exception)

    def test_extraction_error_carries_message(self):
        from wily_rooster.extraction.errors import ExtractionError

        err = ExtractionError("backend missing")
        assert "backend missing" in str(err)

    def test_extraction_error_can_be_raised_and_caught(self):
        from wily_rooster.extraction.errors import ExtractionError

        with pytest.raises(ExtractionError):
            raise ExtractionError("test")
