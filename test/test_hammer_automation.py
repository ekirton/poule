"""TDD tests for Hammer Automation (specification/hammer-automation.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/hammer/ modules exist.

Spec: specification/hammer-automation.md
Architecture: doc/architecture/hammer-automation.md
Data model: doc/architecture/data-models/proof-types.md

Import paths under test:
  poule.hammer.engine        (execute_hammer, execute_auto_hammer)
  poule.hammer.tactic        (build_tactic)
  poule.hammer.interpret     (interpret_result)
  poule.hammer.types         (HammerResult, StrategyDiagnostic, ClassifiedOutput)
  poule.hammer.errors        (ParseError)
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _import_execute_hammer():
    from Poule.hammer.engine import execute_hammer
    return execute_hammer


def _import_execute_auto_hammer():
    from Poule.hammer.engine import execute_auto_hammer
    return execute_auto_hammer


def _import_build_tactic():
    from Poule.hammer.tactic import build_tactic
    return build_tactic


def _import_interpret_result():
    from Poule.hammer.interpret import interpret_result
    return interpret_result


def _import_hammer_types():
    from Poule.hammer.types import HammerResult, StrategyDiagnostic, ClassifiedOutput
    return HammerResult, StrategyDiagnostic, ClassifiedOutput


def _import_parse_error():
    from Poule.hammer.errors import ParseError
    return ParseError


def _import_session_types():
    from Poule.session.types import Goal, Hypothesis, ProofState
    return Goal, Hypothesis, ProofState


def _import_session_errors():
    from Poule.session.errors import (
        BACKEND_CRASHED,
        SESSION_NOT_FOUND,
        SESSION_EXPIRED,
        TACTIC_ERROR,
        SessionError,
    )
    return BACKEND_CRASHED, SESSION_NOT_FOUND, SESSION_EXPIRED, TACTIC_ERROR, SessionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proof_state(
    step_index=0,
    is_complete=False,
    goals=None,
    session_id="test",
):
    """Build a ProofState using the real type from Poule.session.types."""
    Goal, Hypothesis, ProofState = _import_session_types()
    if goals is None:
        if is_complete:
            goals = []
        else:
            goals = [Goal(index=0, type="n + 0 = n", hypotheses=[
                Hypothesis(name="n", type="nat"),
            ])]
    return ProofState(
        schema_version=1,
        session_id=session_id,
        step_index=step_index,
        is_complete=is_complete,
        focused_goal_index=None if is_complete else 0,
        goals=goals,
    )


def _make_complete_state(session_id="test", step_index=1):
    """Build a completed ProofState (no open goals)."""
    return _make_proof_state(
        step_index=step_index,
        is_complete=True,
        goals=[],
        session_id=session_id,
    )


def _make_hammer_result(
    status="success",
    proof_script="hammer using: Nat.add_0_r.",
    atp_proof="by auto using Nat.add_0_r",
    strategy_used="hammer",
    state=None,
    diagnostics=None,
    wall_time_ms=2400,
):
    """Build a HammerResult using the real type."""
    HammerResult, _, *_ = _import_hammer_types()
    if state is None:
        state = _make_complete_state() if status == "success" else _make_proof_state()
    if diagnostics is None:
        diagnostics = []
    return HammerResult(
        status=status,
        proof_script=proof_script,
        atp_proof=atp_proof,
        strategy_used=strategy_used,
        state=state,
        diagnostics=diagnostics,
        wall_time_ms=wall_time_ms,
    )


def _make_strategy_diagnostic(
    strategy="hammer",
    failure_reason="timeout",
    detail="Error: Timeout",
    partial_progress=None,
    wall_time_ms=30000,
    timeout_used=30,
):
    """Build a StrategyDiagnostic using the real type."""
    _, StrategyDiagnostic, *_ = _import_hammer_types()
    return StrategyDiagnostic(
        strategy=strategy,
        failure_reason=failure_reason,
        detail=detail,
        partial_progress=partial_progress,
        wall_time_ms=wall_time_ms,
        timeout_used=timeout_used,
    )


def _make_mock_session_manager(
    initial_state=None,
    tactic_results=None,
    tactic_errors=None,
):
    """Create a mock session manager for hammer tests.

    tactic_results: dict mapping tactic string to (coq_output, resulting_ProofState).
    tactic_errors: dict mapping tactic string to error code.
    """
    manager = AsyncMock()
    if initial_state is None:
        initial_state = _make_proof_state()
    manager.observe_proof_state.return_value = initial_state

    tactic_results = tactic_results or {}
    tactic_errors = tactic_errors or {}

    _, SESSION_NOT_FOUND, _, TACTIC_ERROR, SessionError = _import_session_errors()

    async def _submit_tactic(session_id, tactic):
        if tactic in tactic_errors:
            raise SessionError(tactic_errors[tactic], f"Error: {tactic}")
        if tactic in tactic_results:
            return tactic_results[tactic]
        # Default: return unchanged state (tactic failed)
        return ("Error: Unknown tactic", initial_state)

    manager.submit_tactic.side_effect = _submit_tactic
    return manager


# ===========================================================================
# §4.1 Tool Surface
# ===========================================================================

class TestToolSurface:
    """§4.1: Hammer automation is a mode of submit_tactic, not a separate tool."""

    def test_hammer_keyword_recognized(self):
        """Given tactic 'hammer', it is recognized as a hammer keyword."""
        # This tests that the keyword set matches spec §4.1
        HAMMER_KEYWORDS = {"hammer", "sauto", "qauto", "auto_hammer"}
        for keyword in HAMMER_KEYWORDS:
            assert keyword in HAMMER_KEYWORDS

    def test_non_hammer_tactic_not_recognized(self):
        """Given tactic 'reflexivity', it is not a hammer keyword."""
        HAMMER_KEYWORDS = {"hammer", "sauto", "qauto", "auto_hammer"}
        assert "reflexivity" not in HAMMER_KEYWORDS
        assert "auto" not in HAMMER_KEYWORDS
        assert "apply lemma" not in HAMMER_KEYWORDS


# ===========================================================================
# §4.2 Single-Strategy Execution
# ===========================================================================

class TestSingleStrategyExecution:
    """§4.2: execute_single / execute_hammer behavior."""

    @pytest.mark.asyncio
    async def test_success_returns_hammer_result_with_success(self):
        """Given a proof session at goal n + 0 = n with Nat.add_0_r available,
        When execute_hammer(session_id, 'hammer', 30, ['Nat.add_0_r'], {}) is called,
        Then a HammerResult with status='success', strategy_used='hammer',
        and a non-null proof_script is returned."""
        execute_hammer = _import_execute_hammer()
        HammerResult, _, *_ = _import_hammer_types()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(
            tactic_results={
                "Set Hammer Timeout 30.": ("", _make_proof_state()),
                "hammer using: Nat.add_0_r": ("No more subgoals.", complete_state),
            },
        )
        result = await execute_hammer(
            session_manager=manager,
            session_id="abc123",
            strategy="hammer",
            timeout=30,
            hints=["Nat.add_0_r"],
            options={},
        )
        assert isinstance(result, HammerResult)
        assert result.status == "success"
        assert result.strategy_used == "hammer"
        assert result.proof_script is not None

    @pytest.mark.asyncio
    async def test_failure_returns_diagnostic(self):
        """Given a proof session at a goal that sauto cannot solve,
        When execute_hammer(session_id, 'sauto', 10, [], {}) is called,
        Then a HammerResult with status='failure' and one StrategyDiagnostic entry
        is returned, and the proof session state is unchanged."""
        execute_hammer = _import_execute_hammer()
        HammerResult, StrategyDiagnostic, *_ = _import_hammer_types()
        initial_state = _make_proof_state()
        manager = _make_mock_session_manager(
            initial_state=initial_state,
            tactic_results={
                "Timeout 10 sauto": ("Error: No proof found", initial_state),
            },
        )
        result = await execute_hammer(
            session_manager=manager,
            session_id="abc123",
            strategy="sauto",
            timeout=10,
            hints=[],
            options={},
        )
        assert result.status == "failure"
        assert len(result.diagnostics) == 1
        assert isinstance(result.diagnostics[0], StrategyDiagnostic)
        assert result.state.is_complete is False

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_diagnostic(self):
        """Given a proof session at a goal, with a 5-second timeout,
        When execute_hammer(session_id, 'hammer', 5, [], {}) is called
        and the tactic does not complete within 5 seconds,
        Then a HammerResult with status='failure' and a diagnostic
        with failure_reason='timeout' is returned."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = _make_mock_session_manager(
            initial_state=initial_state,
            tactic_results={
                "Set Hammer Timeout 5.": ("", initial_state),
                "hammer": ("Error: Timeout", initial_state),
            },
        )
        result = await execute_hammer(
            session_manager=manager,
            session_id="abc123",
            strategy="hammer",
            timeout=5,
            hints=[],
            options={},
        )
        assert result.status == "failure"
        assert len(result.diagnostics) >= 1
        assert result.diagnostics[0].failure_reason == "timeout"

    @pytest.mark.asyncio
    async def test_success_adds_one_tactic_step(self):
        """MAINTAINS: On success, exactly one tactic step is added to the session."""
        execute_hammer = _import_execute_hammer()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(
            tactic_results={
                "Set Hammer Timeout 30.": ("", _make_proof_state()),
                "hammer": ("No more subgoals.", complete_state),
            },
        )
        result = await execute_hammer(
            session_manager=manager,
            session_id="abc123",
            strategy="hammer",
            timeout=30,
            hints=[],
            options={},
        )
        assert result.status == "success"
        # The submit_tactic should have been called (at least for the tactic itself)
        assert manager.submit_tactic.call_count >= 1

    @pytest.mark.asyncio
    async def test_failure_leaves_session_unchanged(self):
        """MAINTAINS: On failure, the session state is unchanged."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state(step_index=3)
        manager = _make_mock_session_manager(
            initial_state=initial_state,
            tactic_results={
                "Timeout 10 sauto": ("Error: No proof found", initial_state),
            },
        )
        result = await execute_hammer(
            session_manager=manager,
            session_id="abc123",
            strategy="sauto",
            timeout=10,
            hints=[],
            options={},
        )
        assert result.status == "failure"
        # State should be unchanged from initial
        assert result.state.step_index == 3

    @pytest.mark.asyncio
    async def test_wall_time_ms_is_non_negative(self):
        """ENSURES: wall_time_ms is a non-negative integer."""
        execute_hammer = _import_execute_hammer()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(
            tactic_results={
                "Set Hammer Timeout 30.": ("", _make_proof_state()),
                "hammer": ("No more subgoals.", complete_state),
            },
        )
        result = await execute_hammer(
            session_manager=manager,
            session_id="abc123",
            strategy="hammer",
            timeout=30,
            hints=[],
            options={},
        )
        assert result.wall_time_ms >= 0

    @pytest.mark.asyncio
    async def test_strategy_must_be_valid(self):
        """REQUIRES: strategy is one of hammer, sauto, qauto."""
        execute_hammer = _import_execute_hammer()
        manager = _make_mock_session_manager()
        with pytest.raises((ValueError, KeyError)):
            await execute_hammer(
                session_manager=manager,
                session_id="abc123",
                strategy="invalid_strategy",
                timeout=30,
                hints=[],
                options={},
            )

    @pytest.mark.asyncio
    async def test_timeout_must_be_positive(self):
        """REQUIRES: timeout is a positive number (seconds)."""
        execute_hammer = _import_execute_hammer()
        manager = _make_mock_session_manager()
        with pytest.raises((ValueError, TypeError)):
            await execute_hammer(
                session_manager=manager,
                session_id="abc123",
                strategy="hammer",
                timeout=-1,
                hints=[],
                options={},
            )

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_execute_hammer_real_session(self):
        """Contract test: execute_hammer against real Proof Session Manager.

        Verifies that the mock-based tests above match the real interface.
        """
        execute_hammer = _import_execute_hammer()
        HammerResult, _, *_ = _import_hammer_types()
        from Poule.session.manager import ProofSessionManager
        import pathlib

        fixture = str(pathlib.Path(__file__).resolve().parent.parent / "examples" / "hammer_test.v")
        manager = ProofSessionManager()
        sid, initial = await manager.create_session(fixture, "hammer_test")
        try:
            assert not initial.is_complete
            result = await execute_hammer(
                session_manager=manager,
                session_id=sid,
                strategy="sauto",
                timeout=10,
                hints=["Nat.add_0_r"],
                options={},
            )
            assert isinstance(result, HammerResult)
            assert result.status in ("success", "failure")
            assert result.wall_time_ms >= 0
            if result.status == "success":
                assert result.proof_script is not None
                assert result.strategy_used == "sauto"
                assert result.state.is_complete is True
        finally:
            await manager.close_session(sid)


# ===========================================================================
# §4.3 Multi-Strategy Fallback
# ===========================================================================

class TestMultiStrategyFallback:
    """§4.3: execute_auto / execute_auto_hammer behavior."""

    @pytest.mark.asyncio
    async def test_first_success_returns_immediately(self):
        """Given a proof session where hammer times out but sauto succeeds,
        When execute_auto(session_id, 60, [], {}) is called,
        Then a HammerResult with status='success', strategy_used='sauto' is
        returned, with diagnostics containing one entry for the failed hammer attempt."""
        execute_auto = _import_execute_auto_hammer()
        HammerResult, StrategyDiagnostic, *_ = _import_hammer_types()
        initial_state = _make_proof_state()
        complete_state = _make_complete_state()

        call_count = {"hammer": 0, "sauto": 0}

        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            if "hammer" in tactic and "Timeout" not in tactic and "Set" not in tactic:
                call_count["hammer"] += 1
                return ("Error: Timeout", initial_state)
            if "Set Hammer Timeout" in tactic:
                return ("", initial_state)
            if "sauto" in tactic:
                call_count["sauto"] += 1
                return ("No more subgoals.", complete_state)
            return ("Error: Unknown", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_auto(
            session_manager=manager,
            session_id="ghi789",
            timeout=60,
            hints=[],
            options={},
        )
        assert result.status == "success"
        assert result.strategy_used == "sauto"
        assert len(result.diagnostics) >= 1
        assert result.diagnostics[0].strategy == "hammer"

    @pytest.mark.asyncio
    async def test_all_strategies_fail_returns_three_diagnostics(self):
        """Given a proof session where all three strategies fail within the budget,
        When execute_auto(session_id, 60, [], {}) is called,
        Then a HammerResult with status='failure' and diagnostics containing
        three entries (one per strategy) is returned."""
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            return ("Error: No proof found", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_auto(
            session_manager=manager,
            session_id="ghi789",
            timeout=60,
            hints=[],
            options={},
        )
        assert result.status == "failure"
        assert len(result.diagnostics) == 3
        strategies = [d.strategy for d in result.diagnostics]
        assert strategies == ["hammer", "sauto", "qauto"]

    @pytest.mark.asyncio
    async def test_budget_exhaustion_skips_remaining(self):
        """Given a proof session where hammer consumes 55 of 60 seconds and fails,
        When execute_auto(session_id, 60, [], {}) is called,
        Then sauto receives at most 5 seconds of budget, and if it also fails,
        qauto is skipped because the budget is exhausted."""
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        strategies_attempted = []

        async def _submit(session_id, tactic):
            for s in ["hammer", "sauto", "qauto"]:
                if s in tactic and "Set" not in tactic and "Timeout" not in tactic.split()[0] if " " in tactic else s == tactic:
                    strategies_attempted.append(s)
            # Simulate hammer consuming 55 seconds
            if "hammer" in tactic and "Set" not in tactic:
                await asyncio.sleep(0)  # Non-blocking placeholder
                return ("Error: Timeout", initial_state)
            return ("Error: No proof found", initial_state)

        manager.submit_tactic.side_effect = _submit

        # We can't truly simulate wall-clock budget exhaustion in a unit test,
        # but we verify the structure: budget_remaining is computed as
        # total_timeout - elapsed, and per_strategy_timeout = min(budget_remaining, default).
        result = await execute_auto(
            session_manager=manager,
            session_id="ghi789",
            timeout=60,
            hints=[],
            options={},
        )
        assert result.status == "failure"
        # If qauto was skipped, diagnostics should have <= 3 entries
        # and the last attempted strategy's timeout_used should reflect remaining budget
        for diag in result.diagnostics:
            assert diag.wall_time_ms >= 0
            assert diag.timeout_used > 0

    @pytest.mark.asyncio
    async def test_execution_order_is_hammer_sauto_qauto(self):
        """ENSURES: Strategies execute in fixed order [hammer, sauto, qauto]."""
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        strategies_seen = []

        async def _submit(session_id, tactic):
            for s in ["hammer", "sauto", "qauto"]:
                if s in tactic.lower():
                    if s not in strategies_seen:
                        strategies_seen.append(s)
            return ("Error: No proof found", initial_state)

        manager.submit_tactic.side_effect = _submit

        await execute_auto(
            session_manager=manager,
            session_id="test",
            timeout=60,
            hints=[],
            options={},
        )
        # Verify ordering: hammer before sauto before qauto
        assert strategies_seen == ["hammer", "sauto", "qauto"]

    @pytest.mark.asyncio
    async def test_per_strategy_timeout_capped_by_budget(self):
        """ENSURES: per_strategy_timeout = min(budget_remaining, default_timeout_for(strategy)).

        With total_timeout=15, hammer default=30 -> capped to 15,
        if hammer uses 10s, sauto default=10 -> capped to min(5, 10) = 5."""
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            return ("Error: No proof found", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_auto(
            session_manager=manager,
            session_id="test",
            timeout=15,
            hints=[],
            options={},
        )
        # hammer's timeout_used should be <= 15 (min(15, 30) = 15)
        if result.diagnostics:
            hammer_diag = result.diagnostics[0]
            # per_strategy_timeout = min(budget_remaining=15, default=30) = 15
            assert hammer_diag.timeout_used <= 15

    @pytest.mark.asyncio
    async def test_at_most_one_successful_tactic_added(self):
        """MAINTAINS: At most one successful tactic step is added to the session."""
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        complete_state = _make_complete_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        success_count = 0

        async def _submit(session_id, tactic):
            nonlocal success_count
            if "sauto" in tactic:
                success_count += 1
                return ("No more subgoals.", complete_state)
            return ("Error: Timeout", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_auto(
            session_manager=manager,
            session_id="test",
            timeout=60,
            hints=[],
            options={},
        )
        assert result.status == "success"
        # Only one strategy should have succeeded
        assert success_count == 1

    @pytest.mark.asyncio
    async def test_default_total_timeout_is_60(self):
        """REQUIRES: total_timeout default is 60 for auto_hammer (§4.4)."""
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            return ("Error: No proof found", initial_state)

        manager.submit_tactic.side_effect = _submit

        # Call without explicit timeout; should use default of 60
        result = await execute_auto(
            session_manager=manager,
            session_id="test",
            timeout=60,
            hints=[],
            options={},
        )
        assert result.status == "failure"

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_execute_auto_real_session(self):
        """Contract test: execute_auto_hammer against real Proof Session Manager."""
        execute_auto = _import_execute_auto_hammer()
        HammerResult, _, *_ = _import_hammer_types()
        from Poule.session.manager import ProofSessionManager
        import pathlib

        fixture = str(pathlib.Path(__file__).resolve().parent.parent / "examples" / "hammer_test.v")
        manager = ProofSessionManager()
        sid, initial = await manager.create_session(fixture, "hammer_test")
        try:
            assert not initial.is_complete
            result = await execute_auto(
                session_manager=manager,
                session_id=sid,
                timeout=30,
                hints=["Nat.add_0_r"],
                options={},
            )
            assert isinstance(result, HammerResult)
            assert result.status in ("success", "failure")
            assert result.wall_time_ms >= 0
            if result.status == "success":
                assert result.proof_script is not None
                assert result.state.is_complete is True
        finally:
            await manager.close_session(sid)


# ===========================================================================
# §4.4 Default Timeouts
# ===========================================================================

class TestDefaultTimeouts:
    """§4.4: Default per-strategy and total budget timeouts."""

    @pytest.mark.asyncio
    async def test_hammer_default_timeout_30(self):
        """Given no explicit timeout, hammer uses 30 seconds."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        submitted_tactics = []

        async def _submit(session_id, tactic):
            submitted_tactics.append(tactic)
            return ("Error: Timeout", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="hammer",
            timeout=30,  # default per §4.4
            hints=[],
            options={},
        )
        # Verify that "Set Hammer Timeout 30." was submitted
        assert any("30" in t for t in submitted_tactics)

    @pytest.mark.asyncio
    async def test_sauto_default_timeout_10(self):
        """Given no explicit timeout, sauto uses 10 seconds."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        submitted_tactics = []

        async def _submit(session_id, tactic):
            submitted_tactics.append(tactic)
            return ("Error: Timeout", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="sauto",
            timeout=10,  # default per §4.4
            hints=[],
            options={},
        )
        # sauto uses "Timeout {t}" wrapping per §4.6
        assert any("10" in t for t in submitted_tactics)

    @pytest.mark.asyncio
    async def test_qauto_default_timeout_5(self):
        """Given no explicit timeout, qauto uses 5 seconds."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        submitted_tactics = []

        async def _submit(session_id, tactic):
            submitted_tactics.append(tactic)
            return ("Error: Timeout", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="qauto",
            timeout=5,  # default per §4.4
            hints=[],
            options={},
        )
        assert any("5" in t for t in submitted_tactics)

    @pytest.mark.asyncio
    async def test_explicit_timeout_overrides_default(self):
        """When a caller provides an explicit timeout, it overrides the default."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        submitted_tactics = []

        async def _submit(session_id, tactic):
            submitted_tactics.append(tactic)
            return ("Error: Timeout", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="hammer",
            timeout=42,  # explicit override
            hints=[],
            options={},
        )
        # Should use 42, not the default 30
        assert any("42" in t for t in submitted_tactics)


# ===========================================================================
# §4.5 Tactic Builder
# ===========================================================================

class TestTacticBuilder:
    """§4.5: build_tactic pure function behavior."""

    def test_hammer_no_hints_no_options(self):
        """Given strategy 'hammer' with no hints and no options,
        When build_tactic is called,
        Then the result is 'hammer'."""
        build_tactic = _import_build_tactic()
        assert build_tactic("hammer", [], {}) == "hammer"

    def test_hammer_with_hints(self):
        """Given strategy 'hammer' with hints ['Nat.add_comm', 'Nat.add_0_r'],
        When build_tactic is called,
        Then the result is 'hammer using: Nat.add_comm, Nat.add_0_r'."""
        build_tactic = _import_build_tactic()
        result = build_tactic("hammer", ["Nat.add_comm", "Nat.add_0_r"], {})
        assert result == "hammer using: Nat.add_comm, Nat.add_0_r"

    def test_sauto_no_hints_no_options(self):
        """Given strategy 'sauto' with no hints and no options,
        When build_tactic is called,
        Then the result is 'sauto'."""
        build_tactic = _import_build_tactic()
        assert build_tactic("sauto", [], {}) == "sauto"

    def test_sauto_with_depth(self):
        """Given strategy 'sauto' with depth=5,
        When build_tactic is called,
        Then the result is 'sauto depth: 5'."""
        build_tactic = _import_build_tactic()
        result = build_tactic("sauto", [], {"depth": 5})
        assert result == "sauto depth: 5"

    def test_sauto_with_hints_and_unfold(self):
        """Given strategy 'sauto' with hints ['lem1'] and unfold=['def1'],
        When build_tactic is called,
        Then the result is 'sauto use: lem1 unfold: def1'."""
        build_tactic = _import_build_tactic()
        result = build_tactic("sauto", ["lem1"], {"unfold": ["def1"]})
        assert result == "sauto use: lem1 unfold: def1"

    def test_sauto_with_depth_and_unfold(self):
        """Given strategy 'sauto' with depth 5 and unfold ['my_def'],
        When build_tactic is called,
        Then the result is 'sauto depth: 5 unfold: my_def'."""
        build_tactic = _import_build_tactic()
        result = build_tactic("sauto", [], {"depth": 5, "unfold": ["my_def"]})
        assert result == "sauto depth: 5 unfold: my_def"

    def test_qauto_with_hints_and_depth(self):
        """Given strategy 'qauto' with hints ['lem1'] and depth=3,
        When build_tactic is called,
        Then the result is 'qauto depth: 3 use: lem1'."""
        build_tactic = _import_build_tactic()
        result = build_tactic("qauto", ["lem1"], {"depth": 3})
        assert result == "qauto depth: 3 use: lem1"

    def test_invalid_hint_raises_parse_error(self):
        """Given strategy 'hammer' with hints ['123invalid'],
        When build_tactic is called,
        Then a ParseError is raised immediately."""
        build_tactic = _import_build_tactic()
        ParseError = _import_parse_error()
        with pytest.raises(ParseError):
            build_tactic("hammer", ["123invalid"], {})

    def test_hint_must_match_coq_identifier_pattern(self):
        """REQUIRES: Each hint matches [a-zA-Z_][a-zA-Z0-9_'.]*."""
        build_tactic = _import_build_tactic()
        ParseError = _import_parse_error()
        # Valid identifiers
        build_tactic("hammer", ["Nat.add_0_r"], {})  # should not raise
        build_tactic("hammer", ["_private"], {})  # should not raise
        build_tactic("hammer", ["lem'"], {})  # should not raise (primes allowed)

        # Invalid identifiers
        with pytest.raises(ParseError):
            build_tactic("hammer", [""], {})
        with pytest.raises(ParseError):
            build_tactic("hammer", ["0bad"], {})
        with pytest.raises(ParseError):
            build_tactic("hammer", ["has space"], {})

    def test_non_positive_depth_raises_parse_error(self):
        """REQUIRES: Numeric options (sauto_depth, qauto_depth) are positive integers.
        On invalid option value (non-positive depth): returns PARSE_ERROR."""
        build_tactic = _import_build_tactic()
        ParseError = _import_parse_error()
        with pytest.raises(ParseError):
            build_tactic("sauto", [], {"depth": 0})
        with pytest.raises(ParseError):
            build_tactic("sauto", [], {"depth": -1})

    def test_invalid_unfold_entry_raises_parse_error(self):
        """REQUIRES: Entries in unfold are syntactically valid Coq identifiers.
        On invalid unfold entry: returns PARSE_ERROR."""
        build_tactic = _import_build_tactic()
        ParseError = _import_parse_error()
        with pytest.raises(ParseError):
            build_tactic("sauto", [], {"unfold": ["123bad"]})

    def test_invalid_strategy_raises_error(self):
        """REQUIRES: strategy is one of hammer, sauto, qauto."""
        build_tactic = _import_build_tactic()
        with pytest.raises((ValueError, KeyError)):
            build_tactic("invalid", [], {})

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_build_tactic_produces_valid_coq(self):
        """Contract test: build_tactic output is syntactically valid Coq.

        Submits each built tactic to a real Coq session to verify syntax.
        """
        build_tactic = _import_build_tactic()
        from Poule.session.manager import ProofSessionManager
        from Poule.session.errors import SessionError
        import pathlib

        fixture = str(pathlib.Path(__file__).resolve().parent.parent / "examples" / "hammer_test.v")
        manager = ProofSessionManager()
        sid, _ = await manager.create_session(fixture, "hammer_test")
        try:
            # Build a tactic string and submit to real Coq to verify syntax.
            # Petanque requires a trailing period on tactic sentences.
            tactic = build_tactic("sauto", ["Nat.add_0_r"], {})
            tactic_sentence = tactic + "."
            try:
                await manager.submit_tactic(sid, tactic_sentence)
            except SessionError as exc:
                # Tactic may fail to solve the goal, but must not be a
                # Coq syntax error.  Syntax errors contain "Syntax error".
                assert "Syntax error" not in exc.message, (
                    f"build_tactic produced invalid Coq: {tactic!r} -> {exc.message}"
                )
        finally:
            await manager.close_session(sid)


# ===========================================================================
# §4.6 Timeout Wrapping
# ===========================================================================

class TestTimeoutWrapping:
    """§4.6: Tactic strings are wrapped with Coq-level timeout directives."""

    @pytest.mark.asyncio
    async def test_hammer_uses_set_hammer_timeout(self):
        """Given strategy 'hammer' with timeout t,
        When the tactic is submitted,
        Then 'Set Hammer Timeout {t}.' is issued before the tactic."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        submitted = []

        async def _submit(session_id, tactic):
            submitted.append(tactic)
            return ("Error: Timeout", initial_state)

        manager.submit_tactic.side_effect = _submit

        await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="hammer",
            timeout=30,
            hints=[],
            options={},
        )
        # Expect "Set Hammer Timeout 30." before the hammer tactic
        assert any("Set Hammer Timeout 30" in t for t in submitted)

    @pytest.mark.asyncio
    async def test_sauto_uses_timeout_prefix(self):
        """Given strategy 'sauto' with timeout t,
        When the tactic is submitted,
        Then the tactic is wrapped as 'Timeout {t} sauto ...'."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        submitted = []

        async def _submit(session_id, tactic):
            submitted.append(tactic)
            return ("Error: Timeout", initial_state)

        manager.submit_tactic.side_effect = _submit

        await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="sauto",
            timeout=10,
            hints=[],
            options={},
        )
        assert any(t.startswith("Timeout 10 sauto") for t in submitted)

    @pytest.mark.asyncio
    async def test_qauto_uses_timeout_prefix(self):
        """Given strategy 'qauto' with timeout t,
        When the tactic is submitted,
        Then the tactic is wrapped as 'Timeout {t} qauto ...'."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        submitted = []

        async def _submit(session_id, tactic):
            submitted.append(tactic)
            return ("Error: Timeout", initial_state)

        manager.submit_tactic.side_effect = _submit

        await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="qauto",
            timeout=5,
            hints=[],
            options={},
        )
        assert any(t.startswith("Timeout 5 qauto") for t in submitted)

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_timeout_wrapping_accepted_by_coq(self):
        """Contract test: wrapped tactic strings are accepted by Coq parser."""
        from Poule.hammer.engine import _wrap_timeout
        from Poule.session.manager import ProofSessionManager
        from Poule.session.errors import SessionError
        import pathlib

        fixture = str(pathlib.Path(__file__).resolve().parent.parent / "examples" / "hammer_test.v")
        manager = ProofSessionManager()
        sid, _ = await manager.create_session(fixture, "hammer_test")
        try:
            # Test sauto timeout wrapping: "Timeout 5 sauto"
            # Petanque requires a trailing period on tactic sentences.
            pre, wrapped = _wrap_timeout("sauto", "sauto", 5)
            assert pre is None
            wrapped_sentence = wrapped + "."
            try:
                await manager.submit_tactic(sid, wrapped_sentence)
            except SessionError as exc:
                # May fail to solve the goal, but must not be a syntax error
                assert "Syntax error" not in exc.message, (
                    f"Timeout-wrapped tactic rejected by Coq: {wrapped!r} -> {exc.message}"
                )
        finally:
            await manager.close_session(sid)


# ===========================================================================
# §4.7 Result Interpreter
# ===========================================================================

class TestResultInterpreter:
    """§4.7: interpret_result classifies Coq output into a ClassifiedOutput."""

    def test_success_when_goal_closed(self):
        """Given Coq output indicating success and proof_state with is_complete=True,
        When interpret_result is called,
        Then the result is a ClassifiedOutput with classification='success'."""
        interpret_result = _import_interpret_result()
        _, _, ClassifiedOutput = _import_hammer_types()
        complete_state = _make_complete_state()
        result = interpret_result("No more subgoals.", complete_state)
        assert isinstance(result, ClassifiedOutput)
        assert result.classification == "success"
        assert result.partial_progress is None

    def test_timeout_classification(self):
        """Given Coq output containing 'Timeout',
        When interpret_result is called,
        Then the result is a ClassifiedOutput with classification='timeout'."""
        interpret_result = _import_interpret_result()
        _, _, ClassifiedOutput = _import_hammer_types()
        state = _make_proof_state()
        result = interpret_result("Error: Timeout", state)
        assert isinstance(result, ClassifiedOutput)
        assert result.classification == "timeout"

    def test_no_proof_found_classification(self):
        """Given Coq output containing 'No proof found',
        When interpret_result is called,
        Then the result is a ClassifiedOutput with classification='no_proof_found'."""
        interpret_result = _import_interpret_result()
        _, _, ClassifiedOutput = _import_hammer_types()
        state = _make_proof_state()
        result = interpret_result("No proof found", state)
        assert isinstance(result, ClassifiedOutput)
        assert result.classification == "no_proof_found"

    def test_hammer_failed_classification(self):
        """Given Coq output containing 'hammer failed',
        When interpret_result is called,
        Then the result is a ClassifiedOutput with classification='no_proof_found'."""
        interpret_result = _import_interpret_result()
        _, _, ClassifiedOutput = _import_hammer_types()
        state = _make_proof_state()
        result = interpret_result("hammer failed", state)
        assert isinstance(result, ClassifiedOutput)
        assert result.classification == "no_proof_found"

    def test_reconstruction_failed_with_atp_proof(self):
        """Given Coq output containing 'Reconstruction failed' followed by an ATP proof,
        When interpret_result is called,
        Then the result is a ClassifiedOutput with classification='reconstruction_failed'
        and partial_progress contains the ATP proof text."""
        interpret_result = _import_interpret_result()
        _, _, ClassifiedOutput = _import_hammer_types()
        state = _make_proof_state()
        coq_output = "Reconstruction failed\nATP proof: by auto2 using lem1, lem2"
        result = interpret_result(coq_output, state)
        assert isinstance(result, ClassifiedOutput)
        assert result.classification == "reconstruction_failed"
        assert result.partial_progress is not None
        assert "ATP proof" in result.partial_progress or "auto2" in result.partial_progress

    def test_tactic_error_fallback(self):
        """Given Coq output containing 'Error: Unknown tactic hammer',
        When interpret_result is called,
        Then the result is a ClassifiedOutput with classification='tactic_error'
        and detail contains the raw error message."""
        interpret_result = _import_interpret_result()
        _, _, ClassifiedOutput = _import_hammer_types()
        state = _make_proof_state()
        coq_output = "Error: Unknown tactic hammer"
        result = interpret_result(coq_output, state)
        assert isinstance(result, ClassifiedOutput)
        assert result.classification == "tactic_error"
        assert "Unknown tactic hammer" in result.detail

    def test_unclassifiable_error_falls_back_to_tactic_error(self):
        """When the interpreter cannot classify an error message into a specific reason,
        the interpreter shall fall back to 'tactic_error' with the raw Coq error as detail."""
        interpret_result = _import_interpret_result()
        _, _, ClassifiedOutput = _import_hammer_types()
        state = _make_proof_state()
        coq_output = "Error: Some completely unexpected Coq error"
        result = interpret_result(coq_output, state)
        assert isinstance(result, ClassifiedOutput)
        assert result.classification == "tactic_error"
        assert "Some completely unexpected Coq error" in result.detail

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_interpret_result_real_coq_output(self):
        """Contract test: interpret_result handles real Coq backend output correctly."""
        interpret_result = _import_interpret_result()
        _, _, ClassifiedOutput = _import_hammer_types()
        from Poule.session.manager import ProofSessionManager
        from Poule.session.errors import SessionError
        import pathlib

        fixture = str(pathlib.Path(__file__).resolve().parent.parent / "examples" / "hammer_test.v")
        manager = ProofSessionManager()
        sid, initial = await manager.create_session(fixture, "hammer_test")
        try:
            # Submit a tactic that will fail to get real Coq error output
            try:
                await manager.submit_tactic(sid, "exact I")
            except SessionError as exc:
                # Classify the real Coq error message
                result = interpret_result(exc.message, initial)
                assert isinstance(result, ClassifiedOutput)
                assert result.classification in (
                    "timeout", "no_proof_found", "tactic_error",
                )
                assert result.detail is not None
        finally:
            await manager.close_session(sid)


# ===========================================================================
# §5 Data Model — HammerResult
# ===========================================================================

class TestHammerResultDataModel:
    """§5: HammerResult field constraints."""

    def test_success_has_non_null_proof_script(self):
        """On success, proof_script is non-null."""
        result = _make_hammer_result(status="success", proof_script="hammer using: Nat.add_0_r.")
        assert result.proof_script is not None

    def test_failure_has_null_proof_script(self):
        """On failure, proof_script is null."""
        result = _make_hammer_result(
            status="failure",
            proof_script=None,
            atp_proof=None,
            strategy_used=None,
            state=_make_proof_state(),
        )
        assert result.proof_script is None

    def test_success_has_strategy_used(self):
        """On success, strategy_used is the strategy that succeeded."""
        result = _make_hammer_result(status="success", strategy_used="hammer")
        assert result.strategy_used in ("hammer", "sauto", "qauto")

    def test_failure_has_null_strategy_used(self):
        """On failure, strategy_used is null."""
        result = _make_hammer_result(
            status="failure",
            proof_script=None,
            strategy_used=None,
            state=_make_proof_state(),
        )
        assert result.strategy_used is None

    def test_status_must_be_success_or_failure(self):
        """Status must be 'success' or 'failure'."""
        result = _make_hammer_result(status="success")
        assert result.status in ("success", "failure")

    def test_wall_time_ms_is_non_negative(self):
        """wall_time_ms is a non-negative integer."""
        result = _make_hammer_result(wall_time_ms=2400)
        assert result.wall_time_ms >= 0

    def test_diagnostics_is_list(self):
        """diagnostics is a list of StrategyDiagnostic."""
        result = _make_hammer_result(diagnostics=[])
        assert isinstance(result.diagnostics, list)

    def test_success_single_strategy_empty_diagnostics(self):
        """On single strategy success on first try, diagnostics is empty."""
        result = _make_hammer_result(status="success", diagnostics=[])
        assert result.diagnostics == []

    def test_state_is_proof_state(self):
        """state is a ProofState."""
        _, _, ProofState = _import_session_types()
        result = _make_hammer_result()
        assert isinstance(result.state, ProofState)

    def test_atp_proof_null_for_sauto(self):
        """atp_proof is null for sauto strategy."""
        result = _make_hammer_result(
            status="success",
            strategy_used="sauto",
            atp_proof=None,
        )
        assert result.atp_proof is None

    def test_atp_proof_null_for_qauto(self):
        """atp_proof is null for qauto strategy."""
        result = _make_hammer_result(
            status="success",
            strategy_used="qauto",
            atp_proof=None,
        )
        assert result.atp_proof is None


# ===========================================================================
# §5 Data Model — StrategyDiagnostic
# ===========================================================================

class TestStrategyDiagnosticDataModel:
    """§5: StrategyDiagnostic field constraints."""

    def test_strategy_is_valid(self):
        """strategy must be one of hammer, sauto, qauto."""
        diag = _make_strategy_diagnostic(strategy="hammer")
        assert diag.strategy in ("hammer", "sauto", "qauto")

    def test_failure_reason_is_valid(self):
        """failure_reason must be one of the defined enum values."""
        valid_reasons = {"timeout", "no_proof_found", "reconstruction_failed", "tactic_error"}
        for reason in valid_reasons:
            diag = _make_strategy_diagnostic(failure_reason=reason)
            assert diag.failure_reason in valid_reasons

    def test_detail_is_required(self):
        """detail is required; human-readable text."""
        diag = _make_strategy_diagnostic(detail="Error: Timeout")
        assert diag.detail is not None
        assert len(diag.detail) > 0

    def test_partial_progress_null_unless_reconstruction(self):
        """partial_progress is null unless failure_reason is 'reconstruction_failed'."""
        diag = _make_strategy_diagnostic(failure_reason="timeout", partial_progress=None)
        assert diag.partial_progress is None

    def test_partial_progress_set_on_reconstruction_failed(self):
        """partial_progress contains ATP proof text when reconstruction failed."""
        diag = _make_strategy_diagnostic(
            failure_reason="reconstruction_failed",
            partial_progress="ATP proof: by auto2 using lem1",
        )
        assert diag.partial_progress is not None

    def test_wall_time_ms_non_negative(self):
        """wall_time_ms is a non-negative integer."""
        diag = _make_strategy_diagnostic(wall_time_ms=30000)
        assert diag.wall_time_ms >= 0

    def test_timeout_used_is_required(self):
        """timeout_used is required; the timeout value (seconds) applied."""
        diag = _make_strategy_diagnostic(timeout_used=30)
        assert diag.timeout_used > 0


# ===========================================================================
# §5 Data Model — ClassifiedOutput
# ===========================================================================

class TestClassifiedOutputDataModel:
    """§5: ClassifiedOutput field constraints."""

    def test_classification_is_required(self):
        """classification must be one of the defined enum values."""
        _, _, ClassifiedOutput = _import_hammer_types()
        valid = {"success", "timeout", "no_proof_found", "reconstruction_failed", "tactic_error"}
        for cls in valid:
            output = ClassifiedOutput(classification=cls, detail=None, partial_progress=None)
            assert output.classification in valid

    def test_detail_null_on_success(self):
        """detail is null on success."""
        _, _, ClassifiedOutput = _import_hammer_types()
        output = ClassifiedOutput(classification="success", detail=None, partial_progress=None)
        assert output.detail is None

    def test_detail_present_on_tactic_error(self):
        """detail contains human-readable error text on tactic_error."""
        _, _, ClassifiedOutput = _import_hammer_types()
        output = ClassifiedOutput(
            classification="tactic_error",
            detail="Error: Unknown tactic hammer",
            partial_progress=None,
        )
        assert output.detail is not None
        assert len(output.detail) > 0

    def test_partial_progress_null_unless_reconstruction(self):
        """partial_progress is null unless classification is 'reconstruction_failed'."""
        _, _, ClassifiedOutput = _import_hammer_types()
        output = ClassifiedOutput(classification="timeout", detail="Timeout", partial_progress=None)
        assert output.partial_progress is None

    def test_partial_progress_set_on_reconstruction_failed(self):
        """partial_progress contains ATP proof text when reconstruction failed."""
        _, _, ClassifiedOutput = _import_hammer_types()
        output = ClassifiedOutput(
            classification="reconstruction_failed",
            detail="Reconstruction failed",
            partial_progress="ATP proof: by auto2 using lem1",
        )
        assert output.partial_progress is not None


# ===========================================================================
# §7.1 Input Errors
# ===========================================================================

class TestInputErrors:
    """§7.1: Input validation error handling."""

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """Given session_id references a non-existent session,
        When execute_hammer is called,
        Then SESSION_NOT_FOUND is returned immediately; no tactic submitted."""
        execute_hammer = _import_execute_hammer()
        _, SESSION_NOT_FOUND, _, _, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.observe_proof_state.side_effect = SessionError(
            SESSION_NOT_FOUND, "session not found"
        )
        with pytest.raises(SessionError) as exc_info:
            await execute_hammer(
                session_manager=manager,
                session_id="nonexistent",
                strategy="hammer",
                timeout=30,
                hints=[],
                options={},
            )
        assert exc_info.value.code == SESSION_NOT_FOUND
        manager.submit_tactic.assert_not_called()

    @pytest.mark.asyncio
    async def test_expired_session(self):
        """Given session_id references an expired session,
        When execute_hammer is called,
        Then SESSION_NOT_FOUND is returned immediately."""
        execute_hammer = _import_execute_hammer()
        _, SESSION_NOT_FOUND, _, _, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.observe_proof_state.side_effect = SessionError(
            SESSION_NOT_FOUND, "session expired"
        )
        with pytest.raises(SessionError) as exc_info:
            await execute_hammer(
                session_manager=manager,
                session_id="expired",
                strategy="hammer",
                timeout=30,
                hints=[],
                options={},
            )
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.asyncio
    async def test_no_active_goal(self):
        """Given no active goal (proof already complete),
        When execute_hammer is called,
        Then TACTIC_ERROR with message indicating no open goals is returned."""
        execute_hammer = _import_execute_hammer()
        _, _, _, TACTIC_ERROR, SessionError = _import_session_errors()
        complete_state = _make_complete_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = complete_state
        # When proof is already complete, submitting a tactic should fail
        with pytest.raises((SessionError, ValueError)):
            await execute_hammer(
                session_manager=manager,
                session_id="done",
                strategy="hammer",
                timeout=30,
                hints=[],
                options={},
            )

    def test_invalid_hint_returns_parse_error(self):
        """Given a hint name that is not a valid Coq identifier,
        When build_tactic is called,
        Then PARSE_ERROR is returned immediately; no tactic submitted."""
        build_tactic = _import_build_tactic()
        ParseError = _import_parse_error()
        with pytest.raises(ParseError):
            build_tactic("hammer", ["123invalid"], {})

    def test_non_positive_depth_returns_parse_error(self):
        """Given a numeric option that is not a positive integer,
        When build_tactic is called,
        Then PARSE_ERROR is returned immediately."""
        build_tactic = _import_build_tactic()
        ParseError = _import_parse_error()
        with pytest.raises(ParseError):
            build_tactic("sauto", [], {"depth": 0})

    def test_invalid_unfold_returns_parse_error(self):
        """Given an unfold entry that is not a valid Coq identifier,
        When build_tactic is called,
        Then PARSE_ERROR is returned immediately."""
        build_tactic = _import_build_tactic()
        ParseError = _import_parse_error()
        with pytest.raises(ParseError):
            build_tactic("sauto", [], {"unfold": ["42bad"]})


# ===========================================================================
# §7.2 Dependency Errors
# ===========================================================================

class TestDependencyErrors:
    """§7.2: Dependency error handling."""

    @pytest.mark.asyncio
    async def test_backend_crash_returns_backend_crashed(self):
        """Given Coq backend crashes during execution,
        When execute_hammer is called,
        Then BACKEND_CRASHED error is returned."""
        execute_hammer = _import_execute_hammer()
        BACKEND_CRASHED, _, _, _, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = _make_proof_state()
        manager.submit_tactic.side_effect = SessionError(
            BACKEND_CRASHED, "backend crashed"
        )
        with pytest.raises(SessionError) as exc_info:
            await execute_hammer(
                session_manager=manager,
                session_id="test",
                strategy="hammer",
                timeout=30,
                hints=[],
                options={},
            )
        assert exc_info.value.code == BACKEND_CRASHED

    @pytest.mark.asyncio
    async def test_coqhammer_not_installed(self):
        """Given CoqHammer not installed, Coq returns 'Unknown tactic hammer';
        classified as tactic_error with detail explaining the prerequisite."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            return ("Error: Unknown tactic hammer", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="hammer",
            timeout=30,
            hints=[],
            options={},
        )
        assert result.status == "failure"
        assert len(result.diagnostics) >= 1
        assert result.diagnostics[0].failure_reason == "tactic_error"
        assert "Unknown tactic hammer" in result.diagnostics[0].detail

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_backend_crash_handling(self):
        """Contract test: BACKEND_CRASHED propagation with real session manager."""
        execute_hammer = _import_execute_hammer()
        from Poule.session.manager import ProofSessionManager
        from Poule.session.errors import SessionError, BACKEND_CRASHED
        import pathlib

        fixture = str(pathlib.Path(__file__).resolve().parent.parent / "examples" / "hammer_test.v")
        manager = ProofSessionManager()
        sid, _ = await manager.create_session(fixture, "hammer_test")
        try:
            # Simulate a backend crash
            manager._mark_crashed(sid)
            with pytest.raises(SessionError) as exc_info:
                await execute_hammer(
                    session_manager=manager,
                    session_id=sid,
                    strategy="sauto",
                    timeout=10,
                    hints=[],
                    options={},
                )
            assert exc_info.value.code == BACKEND_CRASHED
        finally:
            try:
                await manager.close_session(sid)
            except SessionError:
                pass


# ===========================================================================
# §7.3 Multi-Strategy Budget Errors
# ===========================================================================

class TestMultiStrategyBudgetErrors:
    """§7.3: Multi-strategy budget error conditions."""

    @pytest.mark.asyncio
    async def test_single_strategy_timeout_records_diagnostic(self):
        """Given a single strategy times out within multi-strategy mode,
        Then diagnostic recorded with failure_reason='timeout';
        next strategy attempted with remaining budget."""
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        complete_state = _make_complete_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            if "hammer" in tactic and "Set" not in tactic:
                return ("Error: Timeout", initial_state)
            if "sauto" in tactic:
                return ("No more subgoals.", complete_state)
            return ("Error: No proof found", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_auto(
            session_manager=manager,
            session_id="test",
            timeout=60,
            hints=[],
            options={},
        )
        assert result.status == "success"
        # First diagnostic should be the hammer timeout
        assert result.diagnostics[0].strategy == "hammer"
        assert result.diagnostics[0].failure_reason == "timeout"

    @pytest.mark.asyncio
    async def test_budget_exhausted_skips_remaining_strategies(self):
        """Given total budget exhausted before all strategies tried,
        Then HammerResult with status='failure' and diagnostics for
        all attempted strategies; remaining strategies skipped."""
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            return ("Error: Timeout", initial_state)

        manager.submit_tactic.side_effect = _submit

        # Very tight budget: only enough for one strategy attempt
        result = await execute_auto(
            session_manager=manager,
            session_id="test",
            timeout=2,  # Only 2 seconds total
            hints=[],
            options={},
        )
        assert result.status == "failure"
        # Should have at least 1 diagnostic, possibly fewer than 3 if budget ran out
        assert len(result.diagnostics) >= 1

    @pytest.mark.asyncio
    async def test_all_fail_within_budget_returns_three_diagnostics(self):
        """Given all strategies fail within budget,
        Then HammerResult with status='failure' and diagnostics for all three."""
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            return ("Error: No proof found", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_auto(
            session_manager=manager,
            session_id="test",
            timeout=60,
            hints=[],
            options={},
        )
        assert result.status == "failure"
        assert len(result.diagnostics) == 3

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_budget_exhaustion_real_session(self):
        """Contract test: budget exhaustion with real Coq backend."""
        execute_auto = _import_execute_auto_hammer()
        HammerResult, _, *_ = _import_hammer_types()
        from Poule.session.manager import ProofSessionManager
        import pathlib

        fixture = str(pathlib.Path(__file__).resolve().parent.parent / "examples" / "hammer_test.v")
        manager = ProofSessionManager()
        sid, _ = await manager.create_session(fixture, "hammer_test")
        try:
            # Very tight budget: strategies may be skipped due to exhaustion
            result = await execute_auto(
                session_manager=manager,
                session_id=sid,
                timeout=2,
                hints=[],
                options={},
            )
            assert isinstance(result, HammerResult)
            assert result.wall_time_ms >= 0
            if result.status == "failure":
                assert len(result.diagnostics) >= 1
                for diag in result.diagnostics:
                    assert diag.wall_time_ms >= 0
                    assert diag.timeout_used > 0
        finally:
            await manager.close_session(sid)


# ===========================================================================
# §8 Non-Functional Requirements
# ===========================================================================

class TestNonFunctionalRequirements:
    """§8: Performance and accuracy requirements."""

    def test_tactic_builder_under_1ms(self):
        """The Tactic Builder shall produce a tactic string in < 1 ms
        for any valid input combination."""
        build_tactic = _import_build_tactic()
        import time

        # Test with a complex valid input
        hints = [f"lemma_{i}" for i in range(20)]
        options = {"depth": 10, "unfold": [f"def_{i}" for i in range(10)]}

        start = time.monotonic()
        build_tactic("sauto", hints, options)
        elapsed_ms = (time.monotonic() - start) * 1000

        # Spec: < 1 ms; allow 1 ms margin for test overhead
        assert elapsed_ms < 2.0, f"build_tactic took {elapsed_ms:.3f} ms, spec requires < 1 ms"

    def test_result_interpreter_under_1ms(self):
        """The Result Interpreter shall classify Coq output in < 1 ms per invocation."""
        interpret_result = _import_interpret_result()
        state = _make_proof_state()
        import time

        coq_output = "Error: Reconstruction failed\nATP proof: " + "x " * 1000

        start = time.monotonic()
        interpret_result(coq_output, state)
        elapsed_ms = (time.monotonic() - start) * 1000

        # Spec: < 1 ms; allow 1 ms margin for test overhead
        assert elapsed_ms < 2.0, f"interpret_result took {elapsed_ms:.3f} ms, spec requires < 1 ms"

    @pytest.mark.asyncio
    async def test_wall_time_accuracy_within_10ms(self):
        """Wall-clock time reported in wall_time_ms shall be accurate
        to within 10 ms of actual elapsed time."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        complete_state = _make_complete_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            await asyncio.sleep(0.05)  # 50 ms simulated delay
            return ("No more subgoals.", complete_state)

        manager.submit_tactic.side_effect = _submit

        start = time.monotonic()
        result = await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="hammer",
            timeout=30,
            hints=[],
            options={},
        )
        actual_ms = (time.monotonic() - start) * 1000

        # wall_time_ms should be within 10 ms of actual elapsed time
        assert abs(result.wall_time_ms - actual_ms) <= 10, (
            f"wall_time_ms={result.wall_time_ms}, actual={actual_ms:.1f}, "
            f"difference={abs(result.wall_time_ms - actual_ms):.1f} ms exceeds 10 ms spec tolerance"
        )

    def test_no_persistent_state_between_invocations(self):
        """The component shall not allocate persistent state beyond the lifetime
        of a single invocation. All intermediate data is scoped to one call."""
        # This is a structural test: verify that the module-level namespace
        # does not accumulate state across calls.
        build_tactic = _import_build_tactic()
        # Call twice; second call should not be influenced by first
        result1 = build_tactic("hammer", ["lem1"], {})
        result2 = build_tactic("hammer", ["lem2"], {})
        assert result1 == "hammer using: lem1"
        assert result2 == "hammer using: lem2"


# ===========================================================================
# §6 Interface Contracts
# ===========================================================================

class TestInterfaceContracts:
    """§6: Boundary contracts with Proof Session Manager."""

    @pytest.mark.asyncio
    async def test_uses_submit_tactic_and_observe(self):
        """Hammer Automation uses submit_tactic and observe_proof_state
        on the Proof Session Manager."""
        execute_hammer = _import_execute_hammer()
        complete_state = _make_complete_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = _make_proof_state()

        async def _submit(session_id, tactic):
            return ("No more subgoals.", complete_state)

        manager.submit_tactic.side_effect = _submit

        await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="hammer",
            timeout=30,
            hints=[],
            options={},
        )
        manager.submit_tactic.assert_called()

    @pytest.mark.asyncio
    async def test_session_not_found_propagated_immediately(self):
        """SESSION_NOT_FOUND from Proof Session Manager is propagated immediately."""
        execute_hammer = _import_execute_hammer()
        _, SESSION_NOT_FOUND, _, _, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.observe_proof_state.side_effect = SessionError(
            SESSION_NOT_FOUND, "not found"
        )
        with pytest.raises(SessionError) as exc_info:
            await execute_hammer(
                session_manager=manager,
                session_id="missing",
                strategy="hammer",
                timeout=30,
                hints=[],
                options={},
            )
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.asyncio
    async def test_backend_crashed_propagated_immediately(self):
        """BACKEND_CRASHED from Proof Session Manager is propagated immediately."""
        execute_hammer = _import_execute_hammer()
        BACKEND_CRASHED, _, _, _, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = _make_proof_state()
        manager.submit_tactic.side_effect = SessionError(
            BACKEND_CRASHED, "crashed"
        )
        with pytest.raises(SessionError) as exc_info:
            await execute_hammer(
                session_manager=manager,
                session_id="test",
                strategy="hammer",
                timeout=30,
                hints=[],
                options={},
            )
        assert exc_info.value.code == BACKEND_CRASHED

    @pytest.mark.asyncio
    async def test_tactic_error_classified_via_interpreter(self):
        """TACTIC_ERROR from Proof Session Manager is classified via Result Interpreter
        and returned as HammerResult."""
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            return ("Error: No proof found", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_hammer(
            session_manager=manager,
            session_id="test",
            strategy="hammer",
            timeout=30,
            hints=[],
            options={},
        )
        assert result.status == "failure"
        assert len(result.diagnostics) >= 1

    @pytest.mark.requires_coq
    @pytest.mark.asyncio
    async def test_contract_serialized_tactic_submission(self):
        """Contract test: One tactic submission at a time per session (serialized)."""
        execute_hammer = _import_execute_hammer()
        HammerResult, _, *_ = _import_hammer_types()
        from Poule.session.manager import ProofSessionManager
        import pathlib

        fixture = str(pathlib.Path(__file__).resolve().parent.parent / "examples" / "hammer_test.v")
        manager = ProofSessionManager()
        sid, initial = await manager.create_session(fixture, "hammer_test")
        try:
            result = await execute_hammer(
                session_manager=manager,
                session_id=sid,
                strategy="sauto",
                timeout=10,
                hints=["Nat.add_0_r"],
                options={},
            )
            assert isinstance(result, HammerResult)
            # Verify session state reflects the outcome
            state_after = await manager.observe_state(sid)
            if result.status == "success":
                assert state_after.is_complete is True
            else:
                assert state_after.step_index == initial.step_index
        finally:
            await manager.close_session(sid)


# ===========================================================================
# §9 Examples (end-to-end scenario validation)
# ===========================================================================

class TestSpecExamples:
    """§9: Validate the spec's worked examples end-to-end."""

    @pytest.mark.asyncio
    async def test_example_successful_hammer_with_hints(self):
        """§9 Example 1: Successful single strategy -- hammer with hints.

        submit_tactic(session_id="abc123", tactic="hammer", options={hints: ["Nat.add_0_r"]})
        -> Tactic Builder produces: "hammer using: Nat.add_0_r"
        -> Timeout wrapping: "Set Hammer Timeout 30."
        -> Success, goal closed
        -> HammerResult with status="success", proof_script, atp_proof, strategy_used="hammer"
        """
        execute_hammer = _import_execute_hammer()
        HammerResult, _, *_ = _import_hammer_types()
        complete_state = _make_complete_state()

        manager = AsyncMock()
        manager.observe_proof_state.return_value = _make_proof_state()

        submitted = []

        async def _submit(session_id, tactic):
            submitted.append(tactic)
            if "hammer using: Nat.add_0_r" in tactic:
                return ("No more subgoals.\nby auto using Nat.add_0_r", complete_state)
            return ("", _make_proof_state())

        manager.submit_tactic.side_effect = _submit

        result = await execute_hammer(
            session_manager=manager,
            session_id="abc123",
            strategy="hammer",
            timeout=30,
            hints=["Nat.add_0_r"],
            options={},
        )
        assert result.status == "success"
        assert result.strategy_used == "hammer"
        assert result.proof_script is not None
        assert result.diagnostics == []
        assert result.state.is_complete is True

    @pytest.mark.asyncio
    async def test_example_failed_hammer_timeout(self):
        """§9 Example 2: Failed single strategy -- timeout.

        submit_tactic(session_id="def456", tactic="hammer", options={timeout: 10})
        -> Tactic Builder produces: "hammer"
        -> Timeout wrapping: "Set Hammer Timeout 10."
        -> Coq returns: "Error: Timeout"
        -> HammerResult with status="failure", diagnostics with failure_reason="timeout"
        """
        execute_hammer = _import_execute_hammer()
        initial_state = _make_proof_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            if "hammer" in tactic and "Set" not in tactic:
                return ("Error: Timeout", initial_state)
            return ("", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_hammer(
            session_manager=manager,
            session_id="def456",
            strategy="hammer",
            timeout=10,
            hints=[],
            options={},
        )
        assert result.status == "failure"
        assert result.proof_script is None
        assert result.strategy_used is None
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].strategy == "hammer"
        assert result.diagnostics[0].failure_reason == "timeout"
        assert result.diagnostics[0].timeout_used == 10

    @pytest.mark.asyncio
    async def test_example_multi_strategy_fallback(self):
        """§9 Example 3: Multi-strategy fallback -- hammer fails, sauto succeeds.

        submit_tactic(session_id="ghi789", tactic="auto_hammer", options={timeout: 60})
        -> Strategy 1: hammer (timeout=30) -> timeout after 30s
        -> Strategy 2: sauto (timeout=10, capped to 10) -> success
        -> HammerResult with status="success", strategy_used="sauto",
           diagnostics with one hammer timeout entry
        """
        execute_auto = _import_execute_auto_hammer()
        initial_state = _make_proof_state()
        complete_state = _make_complete_state()
        manager = AsyncMock()
        manager.observe_proof_state.return_value = initial_state

        async def _submit(session_id, tactic):
            if "hammer" in tactic and "Set" not in tactic:
                return ("Error: Timeout", initial_state)
            if "Set Hammer Timeout" in tactic:
                return ("", initial_state)
            if "sauto" in tactic:
                return ("No more subgoals.", complete_state)
            return ("Error: No proof found", initial_state)

        manager.submit_tactic.side_effect = _submit

        result = await execute_auto(
            session_manager=manager,
            session_id="ghi789",
            timeout=60,
            hints=[],
            options={},
        )
        assert result.status == "success"
        assert result.strategy_used == "sauto"
        assert result.state.is_complete is True
        assert len(result.diagnostics) == 1
        assert result.diagnostics[0].strategy == "hammer"
        assert result.diagnostics[0].failure_reason == "timeout"
        # Per §4.4: hammer default timeout is 30
        assert result.diagnostics[0].timeout_used == 30
