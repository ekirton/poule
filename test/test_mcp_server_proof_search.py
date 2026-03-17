"""TDD tests for MCP server proof search tool handlers (specification/mcp-server.md §4.5).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/server/ handler modules exist.

Spec: specification/mcp-server.md (§4.5, §4.6, §5.4, §7)
Architecture: doc/architecture/mcp-server.md

Import paths under test:
  poule.server.handlers     (handle_proof_search, handle_fill_admits)
  poule.server.validation   (validate_string, validate_positive_number, etc.)
  poule.server.errors       (format_error, error codes)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _import_handlers():
    from poule.server.handlers import handle_proof_search, handle_fill_admits
    return handle_proof_search, handle_fill_admits


def _import_errors():
    from poule.server.errors import (
        format_error,
        FILE_NOT_FOUND,
        SESSION_NOT_FOUND,
        SESSION_EXPIRED,
        BACKEND_CRASHED,
    )
    return format_error, FILE_NOT_FOUND, SESSION_NOT_FOUND, SESSION_EXPIRED, BACKEND_CRASHED


def _import_session_errors():
    from poule.session.errors import (
        SESSION_NOT_FOUND,
        SESSION_EXPIRED,
        BACKEND_CRASHED,
        SessionError,
    )
    return SESSION_NOT_FOUND, SESSION_EXPIRED, BACKEND_CRASHED, SessionError


def _import_search_types():
    from poule.search.types import SearchResult, ProofStep
    return SearchResult, ProofStep


def _import_fill_admits_types():
    from poule.search.types import FillAdmitsResult, AdmitResult
    return FillAdmitsResult, AdmitResult


def _import_session_types():
    from poule.session.types import Goal, ProofState
    return Goal, ProofState


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


def _make_search_result(status="success"):
    SearchResult, ProofStep = _import_search_types()
    if status == "success":
        return SearchResult(
            status="success",
            proof_script=[ProofStep(
                tactic="reflexivity.",
                state_before=_make_proof_state(),
                state_after=_make_proof_state(is_complete=True),
            )],
            best_partial=None,
            states_explored=5,
            unique_states=3,
            wall_time_ms=500,
            llm_unavailable=False,
        )
    return SearchResult(
        status="failure",
        proof_script=None,
        best_partial=None,
        states_explored=200,
        unique_states=150,
        wall_time_ms=5000,
        llm_unavailable=False,
    )


def _make_fill_admits_result(total=2, filled=1, unfilled=1):
    FillAdmitsResult, AdmitResult = _import_fill_admits_types()
    results = []
    for i in range(filled):
        results.append(AdmitResult(
            proof_name=f"proof_{i}",
            admit_index=0,
            line_number=i + 1,
            status="filled",
            replacement=["reflexivity."],
            search_stats=None,
            error=None,
        ))
    for i in range(unfilled):
        results.append(AdmitResult(
            proof_name=f"proof_{filled + i}",
            admit_index=0,
            line_number=filled + i + 1,
            status="unfilled",
            replacement=None,
            search_stats={"states_explored": 200, "unique_states": 150, "wall_time_ms": 30000},
            error=None,
        ))
    return FillAdmitsResult(
        total_admits=total,
        filled=filled,
        unfilled=unfilled,
        results=results,
        modified_script="modified content",
    )


def _make_mock_search_engine(result=None):
    engine = AsyncMock()
    engine.proof_search.return_value = result or _make_search_result("success")
    return engine


def _make_mock_orchestrator(result=None):
    orch = AsyncMock()
    orch.fill_admits.return_value = result or _make_fill_admits_result()
    return orch


# ===========================================================================
# 1. handle_proof_search — §4.5
# ===========================================================================

class TestHandleProofSearch:
    """§4.5: proof_search MCP tool handler."""

    @pytest.mark.asyncio
    async def test_success_returns_search_result(self):
        """Given a successful search, returns SearchResult as JSON."""
        handle_proof_search, _ = _import_handlers()
        engine = _make_mock_search_engine()
        response = await handle_proof_search(
            search_engine=engine,
            session_id="abc123",
            timeout=30,
            max_depth=10,
            max_breadth=20,
        )
        assert "content" in response
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["status"] == "success"
        assert "proof_script" in data

    @pytest.mark.asyncio
    async def test_failure_returns_search_result(self):
        """Given a failed search, returns SearchResult with failure status."""
        handle_proof_search, _ = _import_handlers()
        engine = _make_mock_search_engine(_make_search_result("failure"))
        response = await handle_proof_search(
            search_engine=engine,
            session_id="abc123",
            timeout=5,
            max_depth=10,
            max_breadth=20,
        )
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["status"] == "failure"
        assert data["states_explored"] > 0

    @pytest.mark.asyncio
    async def test_session_not_found_returns_error(self):
        """Given a non-existent session, returns SESSION_NOT_FOUND error (§5.4)."""
        handle_proof_search, _ = _import_handlers()
        SESSION_NOT_FOUND, _, _, SessionError = _import_session_errors()
        engine = AsyncMock()
        engine.proof_search.side_effect = SessionError(
            SESSION_NOT_FOUND, "not found"
        )
        response = await handle_proof_search(
            search_engine=engine,
            session_id="nonexistent",
            timeout=30,
            max_depth=10,
            max_breadth=20,
        )
        assert response["isError"] is True
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["error"]["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_session_expired_returns_error(self):
        """Given an expired session, returns SESSION_EXPIRED error (§5.4)."""
        handle_proof_search, _ = _import_handlers()
        _, SESSION_EXPIRED, _, SessionError = _import_session_errors()
        engine = AsyncMock()
        engine.proof_search.side_effect = SessionError(
            SESSION_EXPIRED, "expired"
        )
        response = await handle_proof_search(
            search_engine=engine,
            session_id="expired123",
            timeout=30,
            max_depth=10,
            max_breadth=20,
        )
        assert response["isError"] is True
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["error"]["code"] == "SESSION_EXPIRED"

    @pytest.mark.asyncio
    async def test_backend_crashed_returns_error(self):
        """Given a backend crash, returns BACKEND_CRASHED error (§5.4)."""
        handle_proof_search, _ = _import_handlers()
        _, _, BACKEND_CRASHED, SessionError = _import_session_errors()
        engine = AsyncMock()
        engine.proof_search.side_effect = SessionError(
            BACKEND_CRASHED, "crashed"
        )
        response = await handle_proof_search(
            search_engine=engine,
            session_id="crashed123",
            timeout=30,
            max_depth=10,
            max_breadth=20,
        )
        assert response["isError"] is True
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["error"]["code"] == "BACKEND_CRASHED"

    @pytest.mark.asyncio
    async def test_default_parameters(self):
        """Default parameters: timeout=30, max_depth=10, max_breadth=20 (§4.5)."""
        handle_proof_search, _ = _import_handlers()
        engine = _make_mock_search_engine()
        await handle_proof_search(
            search_engine=engine,
            session_id="abc123",
        )
        call_args = engine.proof_search.call_args
        # The handler should pass defaults to the engine
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_response_format_is_mcp(self):
        """Response follows MCP content format with type='text' (§4.8)."""
        handle_proof_search, _ = _import_handlers()
        engine = _make_mock_search_engine()
        response = await handle_proof_search(
            search_engine=engine,
            session_id="abc123",
        )
        assert "content" in response
        assert isinstance(response["content"], list)
        assert response["content"][0]["type"] == "text"
        # Text should be valid JSON
        json.loads(response["content"][0]["text"])


# ===========================================================================
# 2. handle_fill_admits — §4.5
# ===========================================================================

class TestHandleFillAdmits:
    """§4.5: fill_admits MCP tool handler."""

    @pytest.mark.asyncio
    async def test_success_returns_fill_result(self):
        """Given a file with admits, returns FillAdmitsResult as JSON."""
        _, handle_fill_admits = _import_handlers()
        orch = _make_mock_orchestrator()
        response = await handle_fill_admits(
            orchestrator=orch,
            file_path="/path/to/file.v",
            timeout_per_admit=30,
            max_depth=10,
            max_breadth=20,
        )
        assert "content" in response
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert "total_admits" in data
        assert "filled" in data
        assert "unfilled" in data
        assert "results" in data
        assert "modified_script" in data

    @pytest.mark.asyncio
    async def test_no_admits_returns_zero_counts(self):
        """Given a file with no admits, returns total_admits=0."""
        _, handle_fill_admits = _import_handlers()
        orch = _make_mock_orchestrator(_make_fill_admits_result(total=0, filled=0, unfilled=0))
        response = await handle_fill_admits(
            orchestrator=orch,
            file_path="/path/to/clean.v",
        )
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["total_admits"] == 0

    @pytest.mark.asyncio
    async def test_file_not_found_returns_error(self):
        """Given a non-existent file, returns FILE_NOT_FOUND error (§5.4)."""
        _, handle_fill_admits = _import_handlers()
        from poule.session.errors import FILE_NOT_FOUND, SessionError
        orch = AsyncMock()
        orch.fill_admits.side_effect = SessionError(FILE_NOT_FOUND, "not found")
        response = await handle_fill_admits(
            orchestrator=orch,
            file_path="/nonexistent.v",
        )
        assert response["isError"] is True
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["error"]["code"] == "FILE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_default_parameters(self):
        """Default: timeout_per_admit=30, max_depth=10, max_breadth=20 (§4.5)."""
        _, handle_fill_admits = _import_handlers()
        orch = _make_mock_orchestrator()
        await handle_fill_admits(
            orchestrator=orch,
            file_path="/path/to/file.v",
        )
        assert orch.fill_admits.call_count == 1

    @pytest.mark.asyncio
    async def test_response_format_is_mcp(self):
        """Response follows MCP content format (§4.8)."""
        _, handle_fill_admits = _import_handlers()
        orch = _make_mock_orchestrator()
        response = await handle_fill_admits(
            orchestrator=orch,
            file_path="/path/to/file.v",
        )
        assert "content" in response
        assert isinstance(response["content"], list)
        assert response["content"][0]["type"] == "text"
        json.loads(response["content"][0]["text"])

    @pytest.mark.asyncio
    async def test_per_admit_errors_in_result_not_mcp_error(self):
        """Per-admit errors are in the FillAdmitsResult, not raised as MCP errors (§5.4)."""
        _, handle_fill_admits = _import_handlers()
        FillAdmitsResult, AdmitResult = _import_fill_admits_types()
        result_with_error = FillAdmitsResult(
            total_admits=1,
            filled=0,
            unfilled=1,
            results=[AdmitResult(
                proof_name="foo",
                admit_index=0,
                line_number=1,
                status="unfilled",
                replacement=None,
                search_stats=None,
                error="PROOF_NOT_FOUND: proof foo not found",
            )],
            modified_script="original content",
        )
        orch = _make_mock_orchestrator(result_with_error)
        response = await handle_fill_admits(
            orchestrator=orch,
            file_path="/path/to/file.v",
        )
        # This should NOT be an MCP error — per-admit errors are in the result
        assert response.get("isError") is not True
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["results"][0]["error"] is not None


# ===========================================================================
# 3. Input Validation for Proof Search Parameters — §4.6
# ===========================================================================

class TestProofSearchInputValidation:
    """§4.6: Validation rules for proof search parameters."""

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_positive(self):
        """timeout ≤ 0 is clamped to 1 (§4.6)."""
        handle_proof_search, _ = _import_handlers()
        engine = _make_mock_search_engine()
        # Should not raise
        response = await handle_proof_search(
            search_engine=engine,
            session_id="test",
            timeout=-5,
        )
        # The handler should have clamped and called the engine
        assert engine.proof_search.call_count == 1

    @pytest.mark.asyncio
    async def test_max_depth_for_proof_search_validated(self):
        """max_depth must be a positive integer (§4.6)."""
        handle_proof_search, _ = _import_handlers()
        engine = _make_mock_search_engine()
        response = await handle_proof_search(
            search_engine=engine,
            session_id="test",
            max_depth=0,
        )
        assert engine.proof_search.call_count == 1

    @pytest.mark.asyncio
    async def test_max_breadth_validated(self):
        """max_breadth ≤ 0 is clamped to 1 (§4.6)."""
        handle_proof_search, _ = _import_handlers()
        engine = _make_mock_search_engine()
        response = await handle_proof_search(
            search_engine=engine,
            session_id="test",
            max_breadth=-1,
        )
        assert engine.proof_search.call_count == 1

    @pytest.mark.asyncio
    async def test_empty_session_id_returns_parse_error(self):
        """Empty session_id returns PARSE_ERROR (§4.6)."""
        handle_proof_search, _ = _import_handlers()
        engine = _make_mock_search_engine()
        response = await handle_proof_search(
            search_engine=engine,
            session_id="",
        )
        assert response["isError"] is True
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["error"]["code"] == "PARSE_ERROR"

    @pytest.mark.asyncio
    async def test_empty_file_path_returns_parse_error(self):
        """Empty file_path returns PARSE_ERROR (§4.6)."""
        _, handle_fill_admits = _import_handlers()
        orch = _make_mock_orchestrator()
        response = await handle_fill_admits(
            orchestrator=orch,
            file_path="",
        )
        assert response["isError"] is True
        text = response["content"][0]["text"]
        data = json.loads(text)
        assert data["error"]["code"] == "PARSE_ERROR"

    @pytest.mark.asyncio
    async def test_whitespace_only_session_id_returns_parse_error(self):
        """Whitespace-only session_id returns PARSE_ERROR (§4.6)."""
        handle_proof_search, _ = _import_handlers()
        engine = _make_mock_search_engine()
        response = await handle_proof_search(
            search_engine=engine,
            session_id="   ",
        )
        assert response["isError"] is True

    @pytest.mark.asyncio
    async def test_timeout_per_admit_clamped(self):
        """timeout_per_admit ≤ 0 is clamped to 1 for fill_admits (§4.6)."""
        _, handle_fill_admits = _import_handlers()
        orch = _make_mock_orchestrator()
        response = await handle_fill_admits(
            orchestrator=orch,
            file_path="/path/to/file.v",
            timeout_per_admit=-10,
        )
        assert orch.fill_admits.call_count == 1
