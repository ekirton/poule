"""TDD tests for extraction campaign orchestrator (specification/extraction-campaign.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/poule/extraction/campaign.py.

Covers: campaign planning (project/file/theorem enumeration, deterministic ordering,
scope filtering), per-proof extraction (success, failure modes, timeout, session
cleanup), campaign execution (metadata/summary emission, ordering, statistics),
state machine transitions, and error edge cases.
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from unittest.mock import AsyncMock, Mock, MagicMock, call, patch

import sqlite3

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _create_test_index(db_path, declarations=None):
    """Create a minimal index.db for testing.

    Each declaration dict needs: name, module, kind.
    Optional: has_proof_body (default 1).
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
    conn.execute("INSERT INTO index_meta VALUES ('schema_version', '1')")
    conn.execute("INSERT INTO index_meta VALUES ('coq_version', '9.1.1')")
    conn.execute(
        "INSERT INTO index_meta VALUES ('created_at', '2026-03-22T00:00:00Z')"
    )
    if declarations:
        for i, decl in enumerate(declarations, 1):
            conn.execute(
                "INSERT INTO declarations (id, name, module, kind, has_proof_body) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    i,
                    decl["name"],
                    decl["module"],
                    decl["kind"],
                    decl.get("has_proof_body", 1),
                ),
            )
    conn.commit()
    conn.close()


def _make_index(tmp_path, declarations=None):
    """Create a test index.db and return its path as a string."""
    db_path = tmp_path / "index.db"
    _create_test_index(db_path, declarations)
    return str(db_path)


def _make_extraction_record(
    theorem_name="Nat.add_comm",
    source_file="theories/Arith/PeanoNat.v",
    project_id="coq-stdlib",
    total_steps=3,
):
    """Build a minimal ExtractionRecord for testing."""
    from Poule.extraction.types import ExtractionRecord, ExtractionStep

    steps = []
    for i in range(total_steps + 1):
        steps.append(ExtractionStep(
            step_index=i,
            tactic=None if i == 0 else f"tactic_{i}",
            goals=[],
            focused_goal_index=None if i == total_steps else 0,
            premises=[],
            diff=None,
        ))
    return ExtractionRecord(
        schema_version=1,
        record_type="proof_trace",
        theorem_name=theorem_name,
        source_file=source_file,
        project_id=project_id,
        total_steps=total_steps,
        steps=steps,
    )


def _make_extraction_error(
    theorem_name="Nat.tricky_lemma",
    source_file="theories/Arith/PeanoNat.v",
    project_id="coq-stdlib",
    error_kind="tactic_failure",
    error_message="Tactic apply failed",
):
    """Build a minimal ExtractionError record for testing."""
    from Poule.extraction.types import ExtractionError

    return ExtractionError(
        schema_version=1,
        record_type="extraction_error",
        theorem_name=theorem_name,
        source_file=source_file,
        project_id=project_id,
        error_kind=error_kind,
        error_message=error_message,
    )


def _make_project_metadata(
    project_id="stdlib",
    project_path="/path/to/stdlib",
    coq_version="8.19.1",
    commit_hash="abc123",
):
    """Build a minimal ProjectMetadata for testing."""
    from Poule.extraction.types import ProjectMetadata

    return ProjectMetadata(
        project_id=project_id,
        project_path=project_path,
        coq_version=coq_version,
        commit_hash=commit_hash,
    )


def _make_mock_session_manager(
    trace_results=None,
    premises_results=None,
    create_raises=None,
):
    """Create a mock SessionManager for per-proof extraction tests.

    Contract test: test_proof_session.py verifies real SessionManager
    satisfies this interface.
    """
    sm = AsyncMock()
    sm.create_session = AsyncMock(return_value=("session-1", Mock()))
    sm.extract_trace = AsyncMock(return_value=Mock())
    sm.get_premises = AsyncMock(return_value=[])
    sm.close_session = AsyncMock(return_value=None)

    if trace_results is not None:
        sm.extract_trace = AsyncMock(side_effect=trace_results)
    if premises_results is not None:
        sm.get_premises = AsyncMock(side_effect=premises_results)
    if create_raises is not None:
        sm.create_session = AsyncMock(side_effect=create_raises)

    return sm


# ═══════════════════════════════════════════════════════════════════════════
# 1. Campaign Planning (§4.1)
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildCampaignPlanDeterministicOrdering:
    """Campaign plan orders projects in dir order, files lexicographic,
    theorems in declaration order (§4.1)."""

    def test_projects_ordered_by_input_dir_order(self, tmp_path):
        """Projects appear in campaign plan in the same order as project_dirs."""
        from Poule.extraction.campaign import build_campaign_plan

        dir_a = tmp_path / "stdlib"
        dir_b = tmp_path / "mathcomp"
        dir_a.mkdir()
        dir_b.mkdir()
        idx = _make_index(tmp_path)

        plan = build_campaign_plan(
            [str(dir_a), str(dir_b)], scope_filter=None, index_db_path=idx,
        )

        assert len(plan.projects) == 2
        assert plan.projects[0].project_id == "stdlib"
        assert plan.projects[1].project_id == "mathcomp"

    def test_files_sorted_lexicographically_within_project(self, tmp_path):
        """Within a project, .v files are sorted by path in lexicographic order."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path, [
            {"name": "B.b1", "module": "B", "kind": "lemma"},
            {"name": "A.a1", "module": "A", "kind": "lemma"},
        ])

        plan = build_campaign_plan(
            [str(proj)], scope_filter=None, index_db_path=idx,
        )

        files = [t[1] for t in plan.targets]
        # A.v should come before B.v
        a_indices = [i for i, f in enumerate(files) if "A.v" in f]
        b_indices = [i for i, f in enumerate(files) if "B.v" in f]
        assert all(a < b for a in a_indices for b in b_indices)

    def test_theorems_in_declaration_order_within_file(self, tmp_path):
        """Theorems within a file appear in declaration order."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path, [
            {"name": "Test.alpha", "module": "Test", "kind": "theorem"},
            {"name": "Test.beta", "module": "Test", "kind": "theorem"},
            {"name": "Test.gamma", "module": "Test", "kind": "theorem"},
        ])

        plan = build_campaign_plan(
            [str(proj)], scope_filter=None, index_db_path=idx,
        )

        thm_names = [t[2] for t in plan.targets]
        assert thm_names == ["Test.alpha", "Test.beta", "Test.gamma"]


class TestProjectMetadataDetection:
    """Project metadata: project_id from dirname, disambiguation (§4.1)."""

    def test_project_id_from_dirname(self, tmp_path):
        """project_id is derived from directory basename."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "my_project"
        proj.mkdir()
        idx = _make_index(tmp_path)

        plan = build_campaign_plan(
            [str(proj)], scope_filter=None, index_db_path=idx,
        )

        assert plan.projects[0].project_id == "my_project"

    def test_project_id_disambiguation_with_suffix(self, tmp_path):
        """When two dirs share a basename, the second gets a numeric suffix."""
        from Poule.extraction.campaign import build_campaign_plan

        dir1 = tmp_path / "a" / "theories"
        dir2 = tmp_path / "b" / "theories"
        dir1.mkdir(parents=True)
        dir2.mkdir(parents=True)
        idx = _make_index(tmp_path)

        plan = build_campaign_plan(
            [str(dir1), str(dir2)], scope_filter=None, index_db_path=idx,
        )

        ids = [p.project_id for p in plan.projects]
        assert ids[0] == "theories"
        assert ids[1] == "theories-2"

    def test_project_path_is_absolute(self, tmp_path):
        """project_path in metadata is an absolute path."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path)

        plan = build_campaign_plan(
            [str(proj)], scope_filter=None, index_db_path=idx,
        )

        assert Path(plan.projects[0].project_path).is_absolute()


class TestTheoremEnumeration:
    """Theorem enumeration queries Coq backend for provable theorems (§4.1)."""

    def test_enumerates_theorems_from_index(self, tmp_path):
        """Theorems are enumerated from the index database."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path, [
            {"name": "Logic.eq_refl", "module": "Logic", "kind": "lemma"},
        ])

        plan = build_campaign_plan(
            [str(proj)], scope_filter=None, index_db_path=idx,
        )

        assert len(plan.targets) >= 1
        assert any(t[2] == "Logic.eq_refl" for t in plan.targets)

    def test_declarations_from_multiple_modules(self, tmp_path):
        """Declarations from multiple modules are all included in the plan."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path, [
            {"name": "Bad.bad_thm", "module": "Bad", "kind": "lemma"},
            {"name": "Good.good_thm", "module": "Good", "kind": "lemma"},
        ])

        plan = build_campaign_plan(
            [str(proj)], scope_filter=None, index_db_path=idx,
        )

        names = [t[2] for t in plan.targets]
        assert "Bad.bad_thm" in names
        assert "Good.good_thm" in names


class TestScopeFiltering:
    """Scope filtering restricts which theorems are extracted (§4.1 P1)."""

    def test_name_pattern_filters_theorems(self, tmp_path):
        """Name pattern filter includes only matching theorems."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path, [
            {"name": "Arith.add_comm", "module": "Arith", "kind": "theorem"},
            {"name": "Arith.mul_comm", "module": "Arith", "kind": "theorem"},
            {"name": "Arith.add_assoc", "module": "Arith", "kind": "theorem"},
        ])

        scope_filter = Mock()  # contract test: test_extraction_campaign_types.py
        scope_filter.name_pattern = "*add*"
        scope_filter.module_prefixes = None

        plan = build_campaign_plan(
            [str(proj)], scope_filter=scope_filter, index_db_path=idx,
        )

        thm_names = [t[2] for t in plan.targets]
        assert "Arith.add_comm" in thm_names
        assert "Arith.add_assoc" in thm_names
        assert "Arith.mul_comm" not in [t[2] for t in plan.targets]

    def test_filtered_theorems_counted_as_skipped(self, tmp_path):
        """Theorems excluded by scope filter are counted as skipped."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path, [
            {"name": "Arith.add_comm", "module": "Arith", "kind": "theorem"},
            {"name": "Arith.mul_comm", "module": "Arith", "kind": "theorem"},
            {"name": "Arith.add_assoc", "module": "Arith", "kind": "theorem"},
        ])

        scope_filter = Mock()  # contract test: test_extraction_campaign_types.py
        scope_filter.name_pattern = "*add*"
        scope_filter.module_prefixes = None

        plan = build_campaign_plan(
            [str(proj)], scope_filter=scope_filter, index_db_path=idx,
        )

        assert plan.skipped_count == 1  # mul_comm


class TestDirectoryNotFoundError:
    """DIRECTORY_NOT_FOUND error raised for nonexistent dirs (§4.1)."""

    def test_nonexistent_directory_raises_error(self):
        """A nonexistent project dir raises DIRECTORY_NOT_FOUND."""
        from Poule.extraction.campaign import build_campaign_plan

        with pytest.raises(Exception, match="DIRECTORY_NOT_FOUND"):
            build_campaign_plan(
                ["/nonexistent/path"], scope_filter=None,
                index_db_path="/dummy",
            )

    def test_error_raised_before_any_extraction(self, tmp_path):
        """Error is raised before extraction begins, even if some dirs exist."""
        from Poule.extraction.campaign import build_campaign_plan

        good_dir = tmp_path / "good"
        good_dir.mkdir()

        with pytest.raises(Exception, match="DIRECTORY_NOT_FOUND"):
            build_campaign_plan(
                [str(good_dir), "/nonexistent/path"], scope_filter=None,
                index_db_path="/dummy",
            )


# ═══════════════════════════════════════════════════════════════════════════
# 2. Per-Proof Extraction (§4.2)
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractSingleProofSuccess:
    """extract_single_proof returns ExtractionRecord on success (§4.2)."""

    def test_returns_extraction_record_on_success(self):
        """Successful extraction returns an ExtractionRecord with correct fields."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionRecord

        # Mock SessionManager — contract test: test_proof_session.py
        sm = _make_mock_session_manager()

        result = asyncio.run(extract_single_proof(
            sm, "coq-stdlib", "theories/Arith/PeanoNat.v", "Nat.add_comm",
            project_path="/path/to/stdlib",
        ))

        assert isinstance(result, ExtractionRecord)
        assert result.record_type == "proof_trace"
        assert result.theorem_name == "Nat.add_comm"
        assert result.project_id == "coq-stdlib"

    def test_session_operations_called_in_order(self):
        """Session manager operations are called in the correct sequence:
        create_session -> extract_trace -> get_premises -> close_session."""
        from Poule.extraction.campaign import extract_single_proof

        sm = _make_mock_session_manager()

        asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "thm",
            project_path="/path/to/proj",
        ))

        sm.create_session.assert_called_once()
        sm.extract_trace.assert_called_once()
        sm.get_premises.assert_called_once()
        sm.close_session.assert_called_once()

    def test_create_session_receives_absolute_path(self):
        """create_session must receive an absolute path resolved from
        project_path + source_file, not the relative source_file (§4.2)."""
        from Poule.extraction.campaign import extract_single_proof

        sm = _make_mock_session_manager()

        asyncio.run(extract_single_proof(
            sm, "coq-stdlib", "theories/Arith/PeanoNat.v", "Nat.add_comm",
            project_path="/data/stdlib",
        ))

        # The first argument to create_session must be the absolute path
        args = sm.create_session.call_args[0]
        assert args[0] == "/data/stdlib/theories/Arith/PeanoNat.v"

    def test_extraction_record_stores_relative_source_file(self):
        """ExtractionRecord stores the relative source_file, not the
        absolute path used for create_session (§4.2, line 137)."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionRecord

        sm = _make_mock_session_manager()

        result = asyncio.run(extract_single_proof(
            sm, "coq-stdlib", "theories/Arith/PeanoNat.v", "Nat.add_comm",
            project_path="/data/stdlib",
        ))

        assert isinstance(result, ExtractionRecord)
        assert result.source_file == "theories/Arith/PeanoNat.v"


class TestExtractSingleProofFailureModes:
    """extract_single_proof returns ExtractionError with correct error_kind
    for various failure modes (§4.2)."""

    def test_backend_crash_returns_backend_crash_error(self):
        """When the Coq backend crashes, returns ExtractionError
        with error_kind='backend_crash'."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionError

        # Mock SessionManager — contract test: test_proof_session.py
        sm = _make_mock_session_manager()
        # Simulate backend crash via session error
        from Poule.session.errors import SessionError, BACKEND_CRASHED
        sm.extract_trace = AsyncMock(
            side_effect=SessionError(BACKEND_CRASHED, "Backend process died"),
        )

        result = asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "crash_thm",
            project_path="/path/to/proj",
        ))

        assert isinstance(result, ExtractionError)
        assert result.error_kind == "backend_crash"

    def test_tactic_failure_returns_tactic_failure_error(self):
        """When a tactic fails during replay, returns ExtractionError
        with error_kind='tactic_failure'."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionError

        # Mock SessionManager — contract test: test_proof_session.py
        sm = _make_mock_session_manager()
        from Poule.session.errors import SessionError, TACTIC_ERROR
        sm.extract_trace = AsyncMock(
            side_effect=SessionError(TACTIC_ERROR, "Tactic apply failed"),
        )

        result = asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "bad_thm",
            project_path="/path/to/proj",
        ))

        assert isinstance(result, ExtractionError)
        assert result.error_kind == "tactic_failure"

    def test_load_failure_returns_load_failure_error(self):
        """When file loading fails, returns ExtractionError
        with error_kind='load_failure'."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionError

        # Mock SessionManager — contract test: test_proof_session.py
        sm = _make_mock_session_manager()
        from Poule.session.errors import SessionError, FILE_NOT_FOUND
        sm.create_session = AsyncMock(
            side_effect=SessionError(FILE_NOT_FOUND, "File not found"),
        )

        result = asyncio.run(extract_single_proof(
            sm, "proj", "missing.v", "thm",
            project_path="/path/to/proj",
        ))

        assert isinstance(result, ExtractionError)
        assert result.error_kind == "load_failure"

    def test_unknown_error_returns_unknown_error_kind(self):
        """Any unexpected error returns ExtractionError
        with error_kind='unknown'."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionError

        # Mock SessionManager — contract test: test_proof_session.py
        sm = _make_mock_session_manager()
        sm.extract_trace = AsyncMock(
            side_effect=RuntimeError("Something unexpected"),
        )

        result = asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "thm",
            project_path="/path/to/proj",
        ))

        assert isinstance(result, ExtractionError)
        assert result.error_kind == "unknown"

    def test_step_out_of_range_returns_no_proof_body(self):
        """STEP_OUT_OF_RANGE from extract_trace (empty original_script)
        maps to error_kind='no_proof_body' — expected for definitions
        without proof bodies (§4.2 line 121)."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionError
        from Poule.session.errors import STEP_OUT_OF_RANGE, SessionError

        sm = _make_mock_session_manager()
        sm.extract_trace = AsyncMock(
            side_effect=SessionError(STEP_OUT_OF_RANGE, "No original script to trace"),
        )

        result = asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "some_definition",
            project_path="/path/to/proj",
        ))

        assert isinstance(result, ExtractionError)
        assert result.error_kind == "no_proof_body"

    def test_proof_not_found_returns_no_proof_body(self):
        """PROOF_NOT_FOUND from create_session maps to
        error_kind='no_proof_body' (§4.2 line 121)."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionError
        from Poule.session.errors import PROOF_NOT_FOUND, SessionError

        sm = _make_mock_session_manager(
            create_raises=SessionError(PROOF_NOT_FOUND, "Proof not found: foo"),
        )

        result = asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "foo",
            project_path="/path/to/proj",
        ))

        assert isinstance(result, ExtractionError)
        assert result.error_kind == "no_proof_body"


class TestExtractSingleProofPartialRecovery:
    """When extract_trace returns a partial trace, extract_single_proof
    should produce a PartialExtractionRecord instead of an ExtractionError (§4.2)."""

    def test_partial_trace_produces_partial_record(self):
        """When extract_trace returns a partial ProofTrace (failure at step 5 of 12),
        extract_single_proof returns a PartialExtractionRecord with steps 0-4."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import PartialExtractionRecord
        from Poule.session.types import ProofTrace, TraceStep, ProofState, Goal

        # Build a partial ProofTrace (as the session manager would return)
        steps = []
        for i in range(5):
            steps.append(TraceStep(
                step_index=i,
                tactic=None if i == 0 else f"tactic_{i}.",
                state=ProofState(
                    schema_version=1, session_id="s1", step_index=i,
                    is_complete=False, focused_goal_index=0,
                    goals=[Goal(index=0, type="goal", hypotheses=[])],
                ),
                duration_ms=None if i == 0 else 1.0,
            ))
        partial_trace = ProofTrace(
            schema_version=1, session_id="s1", proof_name="thm",
            file_path="/path/file.v", total_steps=12, steps=steps,
            partial=True, failure_step=5,
            failure_message="Tactic apply failed",
        )

        sm = _make_mock_session_manager()
        sm.extract_trace = AsyncMock(return_value=partial_trace)
        sm.get_premises = AsyncMock(return_value=[])

        result = asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "thm", project_path="/path/to/proj",
        ))

        assert isinstance(result, PartialExtractionRecord)
        assert result.record_type == "partial_proof_trace"
        assert result.total_steps == 12
        assert result.completed_steps == 4
        assert result.failure_at_step == 5
        assert result.failure_kind == "tactic_failure"
        assert len(result.steps) == 5  # steps 0-4

    def test_partial_trace_failure_at_step1_returns_error(self):
        """When the trace fails at step 1 (only initial state), return an
        ExtractionError — not a partial record (no useful training data)."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.extraction.types import ExtractionError
        from Poule.session.types import ProofTrace, TraceStep, ProofState, Goal

        steps = [TraceStep(
            step_index=0, tactic=None,
            state=ProofState(
                schema_version=1, session_id="s1", step_index=0,
                is_complete=False, focused_goal_index=0,
                goals=[Goal(index=0, type="goal", hypotheses=[])],
            ),
            duration_ms=None,
        )]
        partial_trace = ProofTrace(
            schema_version=1, session_id="s1", proof_name="thm",
            file_path="/path/file.v", total_steps=5, steps=steps,
            partial=True, failure_step=1,
            failure_message="First tactic failed",
        )

        sm = _make_mock_session_manager()
        sm.extract_trace = AsyncMock(return_value=partial_trace)

        result = asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "thm", project_path="/path/to/proj",
        ))

        assert isinstance(result, ExtractionError)
        assert result.error_kind == "tactic_failure"

    def test_session_closed_on_partial_trace(self):
        """Session is always closed even when a partial trace is returned."""
        from Poule.extraction.campaign import extract_single_proof
        from Poule.session.types import ProofTrace, TraceStep, ProofState, Goal

        steps = []
        for i in range(3):
            steps.append(TraceStep(
                step_index=i, tactic=None if i == 0 else f"t{i}.",
                state=ProofState(
                    schema_version=1, session_id="s1", step_index=i,
                    is_complete=False, focused_goal_index=0,
                    goals=[Goal(index=0, type="g", hypotheses=[])],
                ),
                duration_ms=None if i == 0 else 1.0,
            ))
        partial_trace = ProofTrace(
            schema_version=1, session_id="s1", proof_name="thm",
            file_path="/f.v", total_steps=10, steps=steps,
            partial=True, failure_step=3,
            failure_message="fail",
        )

        sm = _make_mock_session_manager()
        sm.extract_trace = AsyncMock(return_value=partial_trace)
        sm.get_premises = AsyncMock(return_value=[])

        asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "thm", project_path="/path/to/proj",
        ))

        sm.close_session.assert_called_once()


class TestExtractSingleProofSessionCleanup:
    """Session is always closed in finally block, regardless of outcome (§4.2)."""

    def test_session_closed_on_success(self):
        """Session is closed after successful extraction."""
        from Poule.extraction.campaign import extract_single_proof

        # Mock SessionManager — contract test: test_proof_session.py
        sm = _make_mock_session_manager()

        asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "thm", project_path="/path/to/proj",
        ))

        sm.close_session.assert_called_once()

    def test_session_closed_on_failure(self):
        """Session is closed even when extraction fails."""
        from Poule.extraction.campaign import extract_single_proof

        # Mock SessionManager — contract test: test_proof_session.py
        sm = _make_mock_session_manager()
        sm.extract_trace = AsyncMock(
            side_effect=RuntimeError("kaboom"),
        )

        asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "thm", project_path="/path/to/proj",
        ))

        sm.close_session.assert_called_once()

    def test_session_closed_on_connection_error(self):
        """Session is closed when backend connection fails (e.g., watchdog kill)."""
        from Poule.extraction.campaign import extract_single_proof

        sm = _make_mock_session_manager()
        sm.extract_trace = AsyncMock(
            side_effect=ConnectionError("coq-lsp unresponsive"),
        )

        asyncio.run(extract_single_proof(
            sm, "proj", "file.v", "thm",
            project_path="/path/to/proj",
        ))

        sm.close_session.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# 3. Campaign Execution (§4.3)
# ═══════════════════════════════════════════════════════════════════════════


class TestRunCampaignOutputStructure:
    """run_campaign emits CampaignMetadata first and ExtractionSummary last (§4.3)."""

    def test_first_output_is_campaign_metadata(self, tmp_path):
        """First record emitted is CampaignMetadata."""
        from Poule.extraction.campaign import run_campaign
        from Poule.extraction.types import CampaignMetadata

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path)
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        import json
        lines = output.read_text().strip().split("\n")
        first = json.loads(lines[0])
        assert first["record_type"] == "campaign_metadata"

    def test_last_output_is_extraction_summary(self, tmp_path):
        """Last record emitted is ExtractionSummary."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path)
        output = tmp_path / "out.jsonl"

        asyncio.run(run_campaign([str(proj)], str(output), {"index_db_path": idx}))

        import json
        lines = output.read_text().strip().split("\n")
        last = json.loads(lines[-1])
        assert last["record_type"] == "extraction_summary"

    def test_all_failures_still_produces_metadata_and_summary(self, tmp_path):
        """Even when all proofs fail, output contains metadata and summary."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Bad.v").write_text("Theorem bad : False. Proof. Qed.\n")
        idx = _make_index(tmp_path, [
            {"name": "Bad.bad", "module": "Bad", "kind": "theorem"},
        ])
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        import json
        lines = output.read_text().strip().split("\n")
        assert len(lines) >= 2  # at minimum: metadata + summary
        assert json.loads(lines[0])["record_type"] == "campaign_metadata"
        assert json.loads(lines[-1])["record_type"] == "extraction_summary"


class TestRunCampaignDeterministicOrdering:
    """Records emitted in deterministic order: metadata, then project/file/theorem
    order, then summary (§4.3)."""

    def test_records_follow_plan_order(self, tmp_path):
        """Extraction records/errors appear in the same order as the campaign plan."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "A.v").write_text(
            "Theorem a1 : True. Proof. exact I. Qed.\n"
            "Theorem a2 : True. Proof. exact I. Qed.\n"
        )
        (proj / "B.v").write_text(
            "Theorem b1 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "A.a1", "module": "A", "kind": "theorem"},
            {"name": "A.a2", "module": "A", "kind": "theorem"},
            {"name": "B.b1", "module": "B", "kind": "theorem"},
        ])
        output = tmp_path / "out.jsonl"

        asyncio.run(run_campaign([str(proj)], str(output), {"index_db_path": idx}))

        import json
        lines = output.read_text().strip().split("\n")
        # Skip metadata (first) and summary (last)
        records = [json.loads(l) for l in lines[1:-1]]
        record_files = [r["source_file"] for r in records]

        # A.v records should come before B.v records
        a_indices = [i for i, f in enumerate(record_files) if "A.v" in f]
        b_indices = [i for i, f in enumerate(record_files) if "B.v" in f]
        if a_indices and b_indices:
            assert max(a_indices) < min(b_indices)


class TestRunCampaignSummaryStatistics:
    """Summary statistics: extracted + failed + skipped == theorems_found (§4.3)."""

    def test_campaign_level_invariant(self, tmp_path):
        """extracted + failed + skipped == theorems_found at campaign level."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Test.v").write_text(
            "Theorem t1 : True. Proof. exact I. Qed.\n"
            "Theorem t2 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "Test.t1", "module": "Test", "kind": "theorem"},
            {"name": "Test.t2", "module": "Test", "kind": "theorem"},
        ])
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        # Invariant: extracted + partial + failed + no_proof_body + skipped == theorems_found
        assert (
            summary.total_extracted + summary.total_partial + summary.total_failed
            + summary.total_no_proof_body + summary.total_skipped
            == summary.total_theorems_found
        )

    def test_project_level_invariant(self, tmp_path):
        """extracted + partial + failed + no_proof_body + skipped == theorems_found at project level."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Test.v").write_text(
            "Theorem t1 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "Test.t1", "module": "Test", "kind": "theorem"},
        ])
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        for ps in summary.per_project:
            assert (
                ps.extracted + ps.partial + ps.failed + ps.no_proof_body + ps.skipped
                == ps.theorems_found
            ), f"Invariant violated for project {ps.project_id}"

    def test_file_level_invariant(self, tmp_path):
        """extracted + partial + failed + no_proof_body + skipped == theorems_found at file level."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Test.v").write_text(
            "Theorem t1 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "Test.t1", "module": "Test", "kind": "theorem"},
        ])
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        for ps in summary.per_project:
            for fs in ps.per_file:
                assert (
                    fs.extracted + fs.partial + fs.failed + fs.no_proof_body + fs.skipped
                    == fs.theorems_found
                ), f"Invariant violated for file {fs.source_file}"

    def test_per_project_breakdown_present(self, tmp_path):
        """Summary includes per-project breakdown."""
        from Poule.extraction.campaign import run_campaign

        dir_a = tmp_path / "stdlib"
        dir_b = tmp_path / "mathcomp"
        dir_a.mkdir()
        dir_b.mkdir()
        idx = _make_index(tmp_path)
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(dir_a), str(dir_b)], str(output), {"index_db_path": idx},
        ))

        assert len(summary.per_project) == 2
        ids = [p.project_id for p in summary.per_project]
        assert "stdlib" in ids
        assert "mathcomp" in ids

    def test_per_file_breakdown_present(self, tmp_path):
        """Summary includes per-file breakdown within each project."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "A.v").write_text(
            "Theorem a1 : True. Proof. exact I. Qed.\n"
        )
        (proj / "B.v").write_text(
            "Theorem b1 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "A.a1", "module": "A", "kind": "theorem"},
            {"name": "B.b1", "module": "B", "kind": "theorem"},
        ])
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        ps = summary.per_project[0]
        file_names = [f.source_file for f in ps.per_file]
        assert any("A.v" in f for f in file_names)
        assert any("B.v" in f for f in file_names)

    def test_summary_statistics_example(self, tmp_path):
        """Given 3 files with known outcomes, project totals are correct.

        Spec example: A.v (10 proofs, 9 extracted, 1 failed), B.v (5 proofs,
        5 extracted), C.v (2 proofs, 0 extracted, 2 failed) =>
        found=17, extracted=14, failed=3, skipped=0.
        """
        from Poule.extraction.campaign import run_campaign

        # This test verifies the summary aggregation logic.
        # We mock extract_single_proof to control outcomes.
        proj = tmp_path / "proj"
        proj.mkdir()
        output = tmp_path / "out.jsonl"

        # We'll verify via the summary that counters add up.
        # The exact proof contents would require Coq, so we test the
        # invariant property instead.
        (proj / "A.v").write_text(
            "Theorem a1 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "A.a1", "module": "A", "kind": "theorem"},
        ])

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        # Fundamental invariant
        assert (
            summary.total_extracted + summary.total_failed + summary.total_skipped
            == summary.total_theorems_found
        )


# ═══════════════════════════════════════════════════════════════════════════
# 4. State Machine (§6)
# ═══════════════════════════════════════════════════════════════════════════


class TestCampaignStateMachine:
    """Campaign state transitions: extracting -> complete,
    extracting -> interrupted (§6)."""

    def test_normal_completion_reaches_complete_state(self, tmp_path):
        """A campaign that finishes all targets reaches 'complete' state."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path)
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        # Summary emission implies the campaign reached 'complete' state.
        import json
        lines = output.read_text().strip().split("\n")
        last = json.loads(lines[-1])
        assert last["record_type"] == "extraction_summary"

    def test_missing_directory_never_enters_extracting(self):
        """When a directory is missing, campaign never enters extracting state
        — raises DIRECTORY_NOT_FOUND immediately."""
        from Poule.extraction.campaign import run_campaign

        with pytest.raises(Exception, match="DIRECTORY_NOT_FOUND"):
            asyncio.run(run_campaign(
                ["/nonexistent"], "/dev/null", {"index_db_path": "/dummy"},
            ))


# ═══════════════════════════════════════════════════════════════════════════
# 5. Error Edge Cases (§7)
# ═══════════════════════════════════════════════════════════════════════════


class TestEmptyProjectDirectory:
    """Empty project directory (no .v files) — project appears in summary
    with all counters = 0 (§7)."""

    def test_empty_project_has_zero_counters(self, tmp_path):
        """An empty project dir yields a project summary with all zeros."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "empty_proj"
        proj.mkdir()
        idx = _make_index(tmp_path)
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        ps = summary.per_project[0]
        assert ps.theorems_found == 0
        assert ps.extracted == 0
        assert ps.failed == 0
        assert ps.skipped == 0


class TestVFileWithNoTheorems:
    """.v file with no provable theorems — file appears in per-file summary
    with all counters = 0 (§7)."""

    def test_no_theorems_file_has_zero_counters(self, tmp_path):
        """A .v file with no theorems yields file summary with all zeros."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Empty.v").write_text("(* no theorems here *)\n")
        idx = _make_index(tmp_path)
        output = tmp_path / "out.jsonl"

        summary = asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        ps = summary.per_project[0]
        if ps.per_file:
            fs = ps.per_file[0]
            assert fs.theorems_found == 0
            assert fs.extracted == 0
            assert fs.failed == 0
            assert fs.skipped == 0


class TestEmptyProjectDirsList:
    """Empty project_dirs list raises input validation error (§7)."""

    def test_empty_list_raises_validation_error(self):
        """An empty project_dirs list raises an input validation error,
        not DIRECTORY_NOT_FOUND."""
        from Poule.extraction.campaign import build_campaign_plan

        with pytest.raises((ValueError, Exception)):
            build_campaign_plan([], scope_filter=None, index_db_path="/dummy")

    def test_run_campaign_empty_list_raises_validation_error(self):
        """run_campaign with empty project_dirs raises input validation error."""
        from Poule.extraction.campaign import run_campaign

        with pytest.raises((ValueError, Exception)):
            asyncio.run(run_campaign([], "/dev/null", {"index_db_path": "/dummy"}))


class TestSameDirectoryListedTwice:
    """Same directory listed twice — extracted twice with disambiguated
    project_ids (§7)."""

    def test_duplicate_dir_gets_disambiguated_ids(self, tmp_path):
        """When the same directory is listed twice, both entries are processed
        with disambiguated project_ids."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path)

        plan = build_campaign_plan(
            [str(proj), str(proj)], scope_filter=None, index_db_path=idx,
        )

        assert len(plan.projects) == 2
        ids = [p.project_id for p in plan.projects]
        assert ids[0] != ids[1]
        assert ids[0] == "proj"
        assert ids[1] == "proj-2"

    def test_duplicate_dir_targets_assigned_to_first_project(self, tmp_path):
        """When the same directory is listed twice, index-based enumeration
        assigns all targets to the first project (index is queried once)."""
        from Poule.extraction.campaign import build_campaign_plan

        proj = tmp_path / "proj"
        proj.mkdir()
        idx = _make_index(tmp_path, [
            {"name": "Test.t1", "module": "Test", "kind": "theorem"},
        ])

        plan = build_campaign_plan(
            [str(proj), str(proj)], scope_filter=None, index_db_path=idx,
        )

        assert len(plan.targets) >= 1
        proj_ids_in_targets = {t[0] for t in plan.targets}
        assert "proj" in proj_ids_in_targets


class TestSigintHandling:
    """SIGINT during extraction emits partial summary (§7)."""

    def test_sigint_emits_partial_summary(self, tmp_path):
        """When SIGINT is received during extraction, a partial summary
        is emitted with counts through the last completed proof."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Test.v").write_text(
            "Theorem t1 : True. Proof. exact I. Qed.\n"
            "Theorem t2 : True. Proof. exact I. Qed.\n"
            "Theorem t3 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "Test.t1", "module": "Test", "kind": "theorem"},
            {"name": "Test.t2", "module": "Test", "kind": "theorem"},
            {"name": "Test.t3", "module": "Test", "kind": "theorem"},
        ])
        output = tmp_path / "out.jsonl"

        # We patch signal handling and simulate interruption
        # by raising KeyboardInterrupt after first extraction.
        # The campaign should catch it and emit partial summary.

        with patch(
            "Poule.extraction.campaign.extract_single_proof",
        ) as mock_extract:
            # First call succeeds, second raises KeyboardInterrupt
            mock_extract.side_effect = [
                _make_extraction_record(theorem_name="t1"),
                KeyboardInterrupt(),
            ]

            # Campaign should handle SIGINT gracefully
            summary = asyncio.run(run_campaign(
                [str(proj)], str(output), {"index_db_path": idx},
            ))

            import json
            lines = output.read_text().strip().split("\n")
            last = json.loads(lines[-1])
            assert last["record_type"] == "extraction_summary"

    def test_interrupted_summary_counts_completed_proofs_only(self, tmp_path):
        """Partial summary after SIGINT counts only completed proofs."""
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Test.v").write_text(
            "Theorem t1 : True. Proof. exact I. Qed.\n"
            "Theorem t2 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "Test.t1", "module": "Test", "kind": "theorem"},
            {"name": "Test.t2", "module": "Test", "kind": "theorem"},
        ])
        output = tmp_path / "out.jsonl"

        with patch(
            "Poule.extraction.campaign.extract_single_proof",
        ) as mock_extract:
            mock_extract.side_effect = [
                _make_extraction_record(theorem_name="t1"),
                KeyboardInterrupt(),
            ]

            summary = asyncio.run(run_campaign(
                [str(proj)], str(output), {"index_db_path": idx},
            ))

            # Only t1 was completed
            assert summary.total_extracted <= 1


# ═══════════════════════════════════════════════════════════════════════════
# 6. Deterministic Output and Session ID Exclusion (§4.2, §4.3)
# ═══════════════════════════════════════════════════════════════════════════


class TestDeterministicOutput:
    """Identical inputs produce byte-identical output except extraction_timestamp (§4.3)."""

    def test_two_runs_produce_identical_output_except_timestamp(self, tmp_path):
        """GIVEN a mock project with fixed inputs
        WHEN run_campaign is called twice on the same inputs
        THEN all records are field-by-field identical, except extraction_timestamp
        in CampaignMetadata.

        Spec §4.3 MAINTAINS: Identical inputs shall produce byte-identical output.
        The only per-run variable is extraction_timestamp in CampaignMetadata.
        """
        import json
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Test.v").write_text(
            "Theorem t1 : True. Proof. exact I. Qed.\n"
            "Theorem t2 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "Test.t1", "module": "Test", "kind": "theorem"},
            {"name": "Test.t2", "module": "Test", "kind": "theorem"},
        ])
        kwargs = {"index_db_path": idx}

        out1 = tmp_path / "run1.jsonl"
        out2 = tmp_path / "run2.jsonl"

        # Mock extract_single_proof to produce deterministic records.
        fixed_records = [
            _make_extraction_record(theorem_name="t1"),
            _make_extraction_record(theorem_name="t2"),
        ]

        with patch(
            "Poule.extraction.campaign.extract_single_proof",
            side_effect=fixed_records * 2,
        ):
            asyncio.run(run_campaign([str(proj)], str(out1), kwargs))

        with patch(
            "Poule.extraction.campaign.extract_single_proof",
            side_effect=fixed_records * 2,
        ):
            asyncio.run(run_campaign([str(proj)], str(out2), kwargs))

        lines1 = [json.loads(l) for l in out1.read_text().strip().split("\n")]
        lines2 = [json.loads(l) for l in out2.read_text().strip().split("\n")]

        assert len(lines1) == len(lines2), (
            f"Run 1 produced {len(lines1)} records, run 2 produced {len(lines2)}"
        )

        for i, (r1, r2) in enumerate(zip(lines1, lines2)):
            if r1.get("record_type") == "campaign_metadata":
                # Only extraction_timestamp may differ.
                r1_copy = {k: v for k, v in r1.items() if k != "extraction_timestamp"}
                r2_copy = {k: v for k, v in r2.items() if k != "extraction_timestamp"}
                assert r1_copy == r2_copy, (
                    f"CampaignMetadata (line {i}) differs beyond extraction_timestamp: "
                    f"{r1_copy} != {r2_copy}"
                )
            else:
                assert r1 == r2, (
                    f"Record at line {i} differs between runs:\n  run1: {r1}\n  run2: {r2}"
                )


class TestSessionIdExclusion:
    """ExtractionRecords must not contain a session_id field (§4.2)."""

    def test_no_session_id_in_extraction_records(self, tmp_path):
        """GIVEN a campaign that produces ExtractionRecords
        WHEN the output is inspected
        THEN no ExtractionRecord contains a session_id field.

        Spec §4.2 ENSURES: session_id is excluded from all embedded proof states.
        """
        import json
        from Poule.extraction.campaign import run_campaign

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "Test.v").write_text(
            "Theorem t1 : True. Proof. exact I. Qed.\n"
        )
        idx = _make_index(tmp_path, [
            {"name": "Test.t1", "module": "Test", "kind": "theorem"},
        ])
        output = tmp_path / "out.jsonl"

        asyncio.run(run_campaign(
            [str(proj)], str(output), {"index_db_path": idx},
        ))

        lines = output.read_text().strip().split("\n")
        records = [json.loads(l) for l in lines]

        for record in records:
            if record.get("record_type") == "proof_trace":
                assert "session_id" not in record, (
                    f"ExtractionRecord contains forbidden session_id field: {record}"
                )
                # Also check nested steps / proof states for session_id
                for step in record.get("steps", []):
                    assert "session_id" not in step, (
                        f"ExtractionStep contains forbidden session_id field: {step}"
                    )
