"""TDD tests for the Fill Admits Orchestrator (specification/fill-admits-orchestrator.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/search/fill_admits.py exists.

Spec: specification/fill-admits-orchestrator.md
Architecture: doc/architecture/fill-admits-orchestrator.md
Data model: doc/architecture/data-models/proof-types.md

Import paths under test:
  poule.search.fill_admits  (fill_admits, locate_admits)
  poule.search.types        (AdmitLocation, FillAdmitsResult, AdmitResult)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _import_fill_admits():
    from poule.search.fill_admits import fill_admits
    return fill_admits


def _import_locate_admits():
    from poule.search.fill_admits import locate_admits
    return locate_admits


def _import_types():
    from poule.search.types import AdmitLocation, FillAdmitsResult, AdmitResult
    return AdmitLocation, FillAdmitsResult, AdmitResult


def _import_search_types():
    from poule.search.types import SearchResult, ProofStep
    return SearchResult, ProofStep


def _import_session_types():
    from poule.session.types import Goal, ProofState
    return Goal, ProofState


def _import_session_errors():
    from poule.session.errors import (
        FILE_NOT_FOUND,
        PROOF_NOT_FOUND,
        BACKEND_CRASHED,
        SessionError,
    )
    return FILE_NOT_FOUND, PROOF_NOT_FOUND, BACKEND_CRASHED, SessionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proof_state(step_index=0, is_complete=False, session_id="test"):
    Goal, ProofState = _import_session_types()
    goals = [] if is_complete else [Goal(index=0, type="n + 0 = n", hypotheses=[])]
    return ProofState(
        schema_version=1,
        session_id=session_id,
        step_index=step_index,
        is_complete=is_complete,
        focused_goal_index=None if is_complete else 0,
        goals=goals,
    )


def _make_search_result(status="success", tactics=None):
    SearchResult, ProofStep = _import_search_types()
    if status == "success":
        steps = []
        for t in (tactics or ["reflexivity."]):
            steps.append(ProofStep(
                tactic=t,
                state_before=_make_proof_state(),
                state_after=_make_proof_state(is_complete=True),
            ))
        return SearchResult(
            status="success",
            proof_script=steps,
            best_partial=None,
            states_explored=5,
            unique_states=3,
            wall_time_ms=500,
            llm_unavailable=False,
        )
    else:
        return SearchResult(
            status="failure",
            proof_script=None,
            best_partial=None,
            states_explored=200,
            unique_states=150,
            wall_time_ms=30000,
            llm_unavailable=False,
        )


def _make_mock_session_manager():
    manager = AsyncMock()
    manager.create_session.return_value = ("session_1", _make_proof_state())
    manager.step_forward.return_value = _make_proof_state(step_index=1)
    manager.close_session.return_value = None
    return manager


def _make_mock_search_engine(results=None):
    engine = AsyncMock()
    if results is not None:
        engine.proof_search.side_effect = results
    else:
        engine.proof_search.return_value = _make_search_result("success")
    return engine


# ===========================================================================
# 1. Admit Location — §4.2
# ===========================================================================

class TestLocateAdmits:
    """§4.2: locate_admits requirements."""

    def test_finds_admit_dot(self):
        """Finds 'admit.' tokens in source."""
        locate_admits = _import_locate_admits()
        AdmitLocation, _, _ = _import_types()
        contents = "Lemma foo : True. Proof. admit. Qed."
        result = locate_admits(contents)
        assert len(result) == 1
        assert isinstance(result[0], AdmitLocation)

    def test_finds_admitted_dot(self):
        """Finds 'Admitted.' tokens in source."""
        locate_admits = _import_locate_admits()
        contents = "Lemma foo : True. Proof. Admitted."
        result = locate_admits(contents)
        assert len(result) == 1

    def test_case_sensitive(self):
        """Matching is case-sensitive: 'admit.' but not 'ADMIT.' (Coq conventions)."""
        locate_admits = _import_locate_admits()
        contents = "Lemma foo : True. Proof. ADMIT. Qed."
        result = locate_admits(contents)
        assert len(result) == 0

    def test_excludes_comments(self):
        """Admits inside Coq comments (* ... *) are excluded."""
        locate_admits = _import_locate_admits()
        contents = "(* admit. *)\nLemma foo : True. Proof. trivial. Qed."
        result = locate_admits(contents)
        assert len(result) == 0

    def test_excludes_nested_comments(self):
        """Admits inside nested comments are excluded."""
        locate_admits = _import_locate_admits()
        contents = "(* outer (* admit. *) still comment *)\nLemma foo : True. Proof. trivial. Qed."
        result = locate_admits(contents)
        assert len(result) == 0

    def test_multiple_admits_sorted_by_line(self):
        """Multiple admits are returned sorted by line number (ascending)."""
        locate_admits = _import_locate_admits()
        contents = (
            "Lemma foo : True. Proof. admit. Qed.\n"
            "Lemma bar : True. Proof. admit. Qed.\n"
        )
        result = locate_admits(contents)
        assert len(result) == 2
        assert result[0].line_number < result[1].line_number

    def test_no_admits_returns_empty(self):
        """A file with no admits returns an empty list."""
        locate_admits = _import_locate_admits()
        contents = "Lemma foo : True. Proof. trivial. Qed."
        result = locate_admits(contents)
        assert result == []

    def test_admit_location_has_required_fields(self):
        """Each AdmitLocation has proof_name, admit_index, line_number, column_range."""
        locate_admits = _import_locate_admits()
        AdmitLocation, _, _ = _import_types()
        contents = "Lemma foo : True. Proof. admit. Qed."
        result = locate_admits(contents)
        assert len(result) == 1
        loc = result[0]
        assert hasattr(loc, "proof_name")
        assert hasattr(loc, "admit_index")
        assert hasattr(loc, "line_number")
        assert hasattr(loc, "column_range")
        assert loc.line_number >= 1
        assert loc.admit_index >= 0

    def test_column_range_covers_admit_text(self):
        """column_range byte offsets cover the admit text."""
        locate_admits = _import_locate_admits()
        contents = "Lemma foo : True. Proof. admit. Qed."
        result = locate_admits(contents)
        loc = result[0]
        start, end = loc.column_range
        line = contents.split("\n")[loc.line_number - 1]
        assert line[start:end] in ("admit.", "Admitted.")

    def test_mixed_admit_and_admitted(self):
        """File with both admit. and Admitted. finds both."""
        locate_admits = _import_locate_admits()
        contents = (
            "Lemma foo : True. Proof. admit. Qed.\n"
            "Lemma bar : True. Proof. Admitted.\n"
        )
        result = locate_admits(contents)
        assert len(result) == 2

    def test_empty_file(self):
        """Empty file returns empty list."""
        locate_admits = _import_locate_admits()
        result = locate_admits("")
        assert result == []


# ===========================================================================
# 2. Fill Admits Entry Point — §4.1
# ===========================================================================

class TestFillAdmitsEntryPoint:
    """§4.1: fill_admits entry point requirements."""

    @pytest.mark.asyncio
    async def test_file_not_found_returns_error(self):
        """Given a non-existent file, returns FILE_NOT_FOUND error."""
        fill_admits = _import_fill_admits()
        FILE_NOT_FOUND, _, _, SessionError = _import_session_errors()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine()

        with pytest.raises(Exception) as exc_info:
            await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path="/nonexistent/path.v",
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
        # Should raise or return FILE_NOT_FOUND
        # The spec says "returns FILE_NOT_FOUND error immediately"

    @pytest.mark.asyncio
    async def test_no_admits_returns_zero_result(self):
        """Given a file with no admits, returns total_admits=0 with unmodified script."""
        fill_admits = _import_fill_admits()
        _, FillAdmitsResult, _ = _import_types()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine()

        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write("Lemma foo : True. Proof. trivial. Qed.\n")
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            assert isinstance(result, FillAdmitsResult)
            assert result.total_admits == 0
            assert result.filled == 0
            assert result.unfilled == 0
            assert result.results == []
            assert "trivial" in result.modified_script
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_two_admits_one_filled(self):
        """Spec §9 example: two admits, one filled, one unfilled."""
        fill_admits = _import_fill_admits()
        _, FillAdmitsResult, _ = _import_types()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine(results=[
            _make_search_result("success", ["reflexivity."]),
            _make_search_result("failure"),
        ])

        import tempfile, os
        content = (
            "Lemma foo : 0 + 0 = 0. Proof. admit. Qed.\n"
            "Lemma bar : forall n, complex n. Proof. admit. Qed.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            assert result.total_admits == 2
            assert result.filled == 1
            assert result.unfilled == 1
            assert len(result.results) == 2
            assert result.results[0].status == "filled"
            assert result.results[1].status == "unfilled"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_empty_file_path_returns_error(self):
        """Empty file_path returns FILE_NOT_FOUND error (§7.1)."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine()
        with pytest.raises(Exception):
            await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path="",
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )


# ===========================================================================
# 3. Per-Admit Processing — §4.3
# ===========================================================================

class TestPerAdmitProcessing:
    """§4.3: Per-admit processing requirements."""

    @pytest.mark.asyncio
    async def test_each_admit_gets_fresh_session(self):
        """MAINTAINS: Each admit is processed with a fresh session (§4.3)."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine(results=[
            _make_search_result("success"),
            _make_search_result("success"),
        ])

        import tempfile, os
        content = (
            "Lemma foo : True. Proof. admit. Qed.\n"
            "Lemma bar : True. Proof. admit. Qed.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            # create_session called once per admit
            assert manager.create_session.call_count == 2
            # close_session called once per admit
            assert manager.close_session.call_count == 2
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_session_open_failure_records_error_continues(self):
        """When session open fails, record error and continue to next admit (§4.3)."""
        fill_admits = _import_fill_admits()
        _, PROOF_NOT_FOUND, _, SessionError = _import_session_errors()
        manager = _make_mock_session_manager()
        # First admit: session open fails; second: succeeds
        call_count = [0]

        async def _create_session(file_path, proof_name):
            call_count[0] += 1
            if call_count[0] == 1:
                raise SessionError(PROOF_NOT_FOUND, "not found")
            return ("session_2", _make_proof_state())

        manager.create_session.side_effect = _create_session
        engine = _make_mock_search_engine(results=[
            _make_search_result("success"),
        ])

        import tempfile, os
        content = (
            "Lemma foo : True. Proof. admit. Qed.\n"
            "Lemma bar : True. Proof. admit. Qed.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            assert result.total_admits == 2
            # First admit has error
            assert result.results[0].status == "unfilled"
            assert result.results[0].error is not None
            # Second admit succeeded
            assert result.results[1].status == "filled"
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_backend_crash_does_not_affect_subsequent(self):
        """Backend crash on one admit doesn't affect subsequent admits (§4.3)."""
        fill_admits = _import_fill_admits()
        _, _, BACKEND_CRASHED, SessionError = _import_session_errors()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine()

        call_count = [0]
        async def _search(session_id, timeout, max_depth, max_breadth):
            call_count[0] += 1
            if call_count[0] == 1:
                raise SessionError(BACKEND_CRASHED, "crashed")
            return _make_search_result("success")

        engine.proof_search.side_effect = _search

        import tempfile, os
        content = (
            "Lemma foo : True. Proof. admit. Qed.\n"
            "Lemma bar : True. Proof. admit. Qed.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            assert result.results[0].status == "unfilled"
            assert result.results[0].error is not None
            assert result.results[1].status == "filled"
        finally:
            os.unlink(path)


# ===========================================================================
# 4. Script Assembly — §4.4
# ===========================================================================

class TestScriptAssembly:
    """§4.4: Script assembly requirements."""

    @pytest.mark.asyncio
    async def test_filled_admit_replaced_in_script(self):
        """Filled admits are replaced with the tactic sequence in modified_script."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine(results=[
            _make_search_result("success", ["reflexivity."]),
        ])

        import tempfile, os
        content = "Lemma foo : 0 + 0 = 0. Proof. admit. Qed.\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            assert "reflexivity." in result.modified_script
            assert "admit." not in result.modified_script
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_unfilled_admit_unchanged_in_script(self):
        """Unfilled admits remain as-is in modified_script."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine(results=[
            _make_search_result("failure"),
        ])

        import tempfile, os
        content = "Lemma bar : forall n, complex n. Proof. admit. Qed.\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            assert "admit." in result.modified_script
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_content_outside_admits_unchanged(self):
        """MAINTAINS: No content outside admit text spans is modified (§4.4)."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine(results=[
            _make_search_result("success", ["reflexivity."]),
        ])

        import tempfile, os
        content = "Lemma foo : 0 + 0 = 0. Proof. admit. Qed.\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            # The surrounding proof structure should be intact
            assert "Lemma foo" in result.modified_script
            assert "Proof." in result.modified_script
            assert "Qed." in result.modified_script
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_multi_tactic_replacement(self):
        """Multi-tactic proof replaces admit with formatted sequence (§4.4)."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine(results=[
            _make_search_result("success", ["intro n.", "simpl.", "reflexivity."]),
        ])

        import tempfile, os
        content = "Lemma foo : forall n, n + 0 = n. Proof. admit. Qed.\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            # All three tactics should appear in the modified script
            assert "intro n." in result.modified_script
            assert "simpl." in result.modified_script
            assert "reflexivity." in result.modified_script
            assert "admit." not in result.modified_script
        finally:
            os.unlink(path)


# ===========================================================================
# 5. Data Model — §5
# ===========================================================================

class TestFillAdmitsDataModel:
    """§5: Data model constraints."""

    def test_admit_location_fields(self):
        """AdmitLocation has all required fields (§5)."""
        AdmitLocation, _, _ = _import_types()
        loc = AdmitLocation(
            proof_name="foo",
            admit_index=0,
            line_number=1,
            column_range=(25, 31),
        )
        assert loc.proof_name == "foo"
        assert loc.admit_index == 0
        assert loc.line_number == 1
        assert loc.column_range == (25, 31)

    def test_fill_admits_result_invariant(self):
        """unfilled = total_admits - filled (§5)."""
        _, FillAdmitsResult, _ = _import_types()
        result = FillAdmitsResult(
            total_admits=3,
            filled=1,
            unfilled=2,
            results=[],
            modified_script="",
        )
        assert result.unfilled == result.total_admits - result.filled

    def test_admit_result_filled_has_replacement(self):
        """On filled status, replacement is a tactic list (§5)."""
        _, _, AdmitResult = _import_types()
        r = AdmitResult(
            proof_name="foo",
            admit_index=0,
            line_number=1,
            status="filled",
            replacement=["reflexivity."],
            search_stats=None,
            error=None,
        )
        assert r.replacement is not None
        assert r.search_stats is None

    def test_admit_result_unfilled_has_search_stats(self):
        """On unfilled status with search failure, search_stats is set (§5)."""
        _, _, AdmitResult = _import_types()
        r = AdmitResult(
            proof_name="bar",
            admit_index=0,
            line_number=2,
            status="unfilled",
            replacement=None,
            search_stats={"states_explored": 200, "unique_states": 150, "wall_time_ms": 30000},
            error=None,
        )
        assert r.replacement is None
        assert r.search_stats is not None

    def test_admit_result_error_case(self):
        """When admit cannot be processed, error is non-null (§5)."""
        _, _, AdmitResult = _import_types()
        r = AdmitResult(
            proof_name="baz",
            admit_index=0,
            line_number=3,
            status="unfilled",
            replacement=None,
            search_stats=None,
            error="Proof not found",
        )
        assert r.error is not None


# ===========================================================================
# 6. Input Validation — §7.1
# ===========================================================================

class TestFillAdmitsInputValidation:
    """§7.1: Input clamping behavior."""

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_1(self):
        """timeout_per_admit ≤ 0 is clamped to 1 second."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine()

        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write("Lemma foo : True. Proof. trivial. Qed.\n")
            f.flush()
            path = f.name

        try:
            # Should not raise — clamped to 1
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=-5,
                max_depth=10,
                max_breadth=20,
            )
            assert result.total_admits == 0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_max_depth_clamped_to_1(self):
        """max_depth ≤ 0 is clamped to 1."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine()

        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write("Lemma foo : True. Proof. trivial. Qed.\n")
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=0,
                max_breadth=20,
            )
            assert result.total_admits == 0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_max_breadth_clamped_to_1(self):
        """max_breadth ≤ 0 is clamped to 1."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine()

        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write("Lemma foo : True. Proof. trivial. Qed.\n")
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=-1,
            )
            assert result.total_admits == 0
        finally:
            os.unlink(path)


# ===========================================================================
# 7. Aggregate Outcomes — §7.3
# ===========================================================================

class TestAggregateOutcomes:
    """§7.3: Aggregate outcome requirements."""

    @pytest.mark.asyncio
    async def test_all_admits_filled(self):
        """When all admits are filled: filled = total_admits, unfilled = 0."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine(results=[
            _make_search_result("success"),
            _make_search_result("success"),
        ])

        import tempfile, os
        content = (
            "Lemma foo : True. Proof. admit. Qed.\n"
            "Lemma bar : True. Proof. admit. Qed.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            assert result.filled == result.total_admits
            assert result.unfilled == 0
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_no_admits_filled(self):
        """When no admits are filled: filled = 0, unfilled = total_admits."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine(results=[
            _make_search_result("failure"),
            _make_search_result("failure"),
        ])

        import tempfile, os
        content = (
            "Lemma foo : True. Proof. admit. Qed.\n"
            "Lemma bar : True. Proof. admit. Qed.\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            assert result.filled == 0
            assert result.unfilled == result.total_admits
        finally:
            os.unlink(path)

    @pytest.mark.asyncio
    async def test_no_admits_found(self):
        """When no admits are found: total_admits=0 with unmodified script."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine()

        import tempfile, os
        content = "Lemma foo : True. Proof. trivial. Qed.\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            assert result.total_admits == 0
            assert result.modified_script == content
        finally:
            os.unlink(path)


# ===========================================================================
# 8. NFR: File Not Modified on Disk — §8
# ===========================================================================

class TestNFR:
    """§8: Non-functional requirements."""

    @pytest.mark.asyncio
    async def test_original_file_not_modified(self):
        """The orchestrator shall not modify the original file on disk (§8)."""
        fill_admits = _import_fill_admits()
        manager = _make_mock_session_manager()
        engine = _make_mock_search_engine(results=[
            _make_search_result("success", ["reflexivity."]),
        ])

        import tempfile, os
        content = "Lemma foo : 0 + 0 = 0. Proof. admit. Qed.\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".v", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            await fill_admits(
                session_manager=manager,
                search_engine=engine,
                file_path=path,
                timeout_per_admit=30,
                max_depth=10,
                max_breadth=20,
            )
            # Read the file again — it should be unchanged
            with open(path) as f:
                assert f.read() == content
        finally:
            os.unlink(path)
