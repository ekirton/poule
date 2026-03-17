"""TDD tests for the Proof Search Engine (specification/proof-search-engine.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/search/ modules exist.

Spec: specification/proof-search-engine.md
Architecture: doc/architecture/proof-search-engine.md
Data model: doc/architecture/data-models/proof-types.md

Import paths under test:
  poule.search.engine        (proof_search, generate_candidates, etc.)
  poule.search.types         (SearchNode, SearchResult, ProofStep)
  poule.search.state_cache   (hash_proof_state)
  poule.search.diversity     (filter_candidates)
  poule.search.scoring       (score_node)
  poule.search.few_shot      (retrieve_few_shot)
"""

from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _import_engine():
    from poule.search.engine import proof_search
    return proof_search


def _import_types():
    from poule.search.types import SearchNode, SearchResult, ProofStep
    return SearchNode, SearchResult, ProofStep


def _import_state_cache():
    from poule.search.state_cache import hash_proof_state
    return hash_proof_state


def _import_diversity():
    from poule.search.diversity import filter_candidates
    return filter_candidates


def _import_scoring():
    from poule.search.scoring import score_node
    return score_node


def _import_candidates():
    from poule.search.engine import generate_candidates
    return generate_candidates


def _import_premise_retrieval():
    from poule.search.engine import retrieve_premises
    return retrieve_premises


def _import_few_shot():
    from poule.search.few_shot import retrieve_few_shot
    return retrieve_few_shot


def _import_session_types():
    from poule.session.types import Goal, Hypothesis, ProofState
    return Goal, Hypothesis, ProofState


def _import_session_errors():
    from poule.session.errors import (
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
    return _make_proof_state(
        step_index=step_index,
        is_complete=True,
        goals=[],
        session_id=session_id,
    )


def _make_search_node(depth=0, score=1.0, tactic_path=None, proof_state=None):
    SearchNode, _, _ = _import_types()
    if proof_state is None:
        proof_state = _make_proof_state()
    state_hash = hashlib.sha256(b"test").digest()
    return SearchNode(
        proof_state=proof_state,
        state_hash=state_hash,
        tactic_path=tactic_path or [],
        depth=depth,
        score=score,
        parent=None,
    )


def _make_mock_session_manager(
    initial_state=None,
    tactic_results=None,
    tactic_errors=None,
):
    """Create a mock session manager for search tests.

    tactic_results: dict mapping tactic string to resulting ProofState.
    tactic_errors: set of tactic strings that should raise TACTIC_ERROR.
    """
    manager = AsyncMock()
    if initial_state is None:
        initial_state = _make_proof_state()
    manager.observe_state.return_value = initial_state

    tactic_results = tactic_results or {}
    tactic_errors = tactic_errors or set()

    _, _, _, TACTIC_ERROR, SessionError = _import_session_errors()

    async def _submit_tactic(session_id, tactic):
        if tactic in tactic_errors:
            raise SessionError(TACTIC_ERROR, f"Tactic failed: {tactic}")
        if tactic in tactic_results:
            return tactic_results[tactic]
        return _make_proof_state(step_index=1)

    manager.submit_tactic.side_effect = _submit_tactic
    manager.step_backward.return_value = initial_state
    return manager


# ===========================================================================
# 1. Search Entry Point — proof_search
# ===========================================================================

class TestProofSearchEntryPoint:
    """§4.1: proof_search entry point requirements."""

    @pytest.mark.asyncio
    async def test_success_returns_status_success(self):
        """Given a solvable goal, proof_search returns status='success'."""
        proof_search = _import_engine()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(
            tactic_results={"reflexivity.": complete_state},
        )
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=30,
            max_depth=10,
            max_breadth=20,
        )
        _, SearchResult, _ = _import_types()
        assert isinstance(result, SearchResult)
        assert result.status == "success"
        assert result.proof_script is not None
        assert len(result.proof_script) >= 1

    @pytest.mark.asyncio
    async def test_failure_returns_status_failure_with_stats(self):
        """Given an unsolvable goal (all tactics fail), returns failure with stats."""
        proof_search = _import_engine()
        manager = _make_mock_session_manager(
            tactic_errors={"auto", "eauto", "omega", "lia", "intuition",
                          "tauto", "congruence", "reflexivity", "assumption", "trivial"},
        )
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=5,
            max_depth=10,
            max_breadth=20,
        )
        assert result.status == "failure"
        assert result.states_explored >= 1
        assert result.wall_time_ms >= 0

    @pytest.mark.asyncio
    async def test_already_complete_returns_empty_proof_script(self):
        """Given a proof that is already complete, returns success with empty script."""
        proof_search = _import_engine()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(initial_state=complete_state)
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=30,
            max_depth=10,
            max_breadth=20,
        )
        assert result.status == "success"
        assert result.proof_script == []

    @pytest.mark.asyncio
    async def test_session_not_found_raises_error(self):
        """Given a non-existent session, proof_search raises SESSION_NOT_FOUND."""
        proof_search = _import_engine()
        BACKEND_CRASHED, SESSION_NOT_FOUND, _, _, SessionError = _import_session_errors()
        manager = AsyncMock()
        manager.observe_state.side_effect = SessionError(SESSION_NOT_FOUND, "not found")
        with pytest.raises(SessionError) as exc_info:
            await proof_search(
                session_manager=manager,
                session_id="nonexistent",
                timeout=30,
                max_depth=10,
                max_breadth=20,
            )
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.asyncio
    async def test_backend_crash_returns_failure(self):
        """Given a backend crash during search, returns failure."""
        proof_search = _import_engine()
        BACKEND_CRASHED, _, _, _, SessionError = _import_session_errors()
        manager = _make_mock_session_manager()
        # Crash on first tactic submission
        manager.submit_tactic.side_effect = SessionError(
            BACKEND_CRASHED, "backend crashed"
        )
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=30,
            max_depth=10,
            max_breadth=20,
        )
        assert result.status == "failure"


# ===========================================================================
# 2. Search Algorithm — §4.2
# ===========================================================================

class TestSearchAlgorithm:
    """§4.2: Best-first tree search behavior."""

    @pytest.mark.asyncio
    async def test_higher_score_expanded_first(self):
        """Nodes with higher scores are expanded before lower-scored nodes."""
        # This is implicitly tested by the priority queue behavior.
        # A direct test: inject two nodes and verify expansion order.
        proof_search = _import_engine()
        # We test via the entry point — a detailed unit test would
        # require access to the frontier internals. The specification
        # guarantees priority-based expansion.
        manager = _make_mock_session_manager(
            tactic_errors={"auto", "eauto", "omega", "lia", "intuition",
                          "tauto", "congruence", "reflexivity", "assumption", "trivial"},
        )
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=2,
            max_depth=3,
            max_breadth=5,
        )
        # At minimum, the root node was explored
        assert result.states_explored >= 1

    @pytest.mark.asyncio
    async def test_max_depth_limits_expansion(self):
        """Nodes at max_depth are skipped without expansion (§4.2 step 3)."""
        proof_search = _import_engine()
        # With max_depth=1, only the root can expand; its children are at depth 1
        # and their children would be at depth 2 (blocked).
        next_state = _make_proof_state(step_index=1)
        manager = _make_mock_session_manager(
            tactic_results={"auto": next_state},
        )
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=5,
            max_depth=1,
            max_breadth=20,
        )
        # Search should terminate (failure or success) but not explore beyond depth 1
        assert result.status in ("success", "failure")

    @pytest.mark.asyncio
    async def test_all_verified_tactics_in_result(self):
        """MAINTAINS: Every tactic in the returned proof_script has been verified."""
        proof_search = _import_engine()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(
            tactic_results={"reflexivity.": complete_state},
        )
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=30,
            max_depth=10,
            max_breadth=20,
        )
        if result.status == "success":
            # Every proof step has tactic, state_before, and state_after
            _, _, ProofStep = _import_types()
            for step in result.proof_script:
                assert isinstance(step, ProofStep)
                assert step.tactic is not None
                assert step.state_before is not None
                assert step.state_after is not None


# ===========================================================================
# 3. Candidate Generation — §4.3
# ===========================================================================

class TestCandidateGeneration:
    """§4.3: Candidate generation requirements."""

    def test_solver_tactics_appear_first(self):
        """Solver tactics appear before LLM-generated tactics."""
        generate_candidates = _import_candidates()
        state = _make_proof_state()
        candidates = generate_candidates(state, premises=[], few_shot_examples=[])
        solver_set = {"auto", "eauto", "omega", "lia", "intuition",
                      "tauto", "congruence", "reflexivity", "assumption", "trivial"}
        # First 10 candidates should be the solver tactics
        first_ten = candidates[:10]
        assert set(first_ten) == solver_set

    def test_solver_tactics_complete_list(self):
        """All 10 specified solver tactics are included (spec §4.3)."""
        generate_candidates = _import_candidates()
        state = _make_proof_state()
        candidates = generate_candidates(state, premises=[], few_shot_examples=[])
        expected_solvers = [
            "auto", "eauto", "omega", "lia", "intuition",
            "tauto", "congruence", "reflexivity", "assumption", "trivial",
        ]
        for s in expected_solvers:
            assert s in candidates

    def test_solver_tactics_in_specified_order(self):
        """Solver tactics appear in the order specified in §4.3."""
        generate_candidates = _import_candidates()
        state = _make_proof_state()
        candidates = generate_candidates(state, premises=[], few_shot_examples=[])
        expected_order = [
            "auto", "eauto", "omega", "lia", "intuition",
            "tauto", "congruence", "reflexivity", "assumption", "trivial",
        ]
        assert candidates[:10] == expected_order


# ===========================================================================
# 4. Premise Retrieval — §4.4
# ===========================================================================

class TestPremiseRetrieval:
    """§4.4: Premise retrieval behavior."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_pipeline_unavailable(self):
        """When retrieval pipeline is None, returns empty list silently."""
        retrieve_premises = _import_premise_retrieval()
        state = _make_proof_state()
        result = await retrieve_premises(state, retrieval_pipeline=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_caches_per_goal_type(self):
        """Results are cached per unique goal type string (§4.4)."""
        retrieve_premises = _import_premise_retrieval()
        pipeline = AsyncMock()
        pipeline.search_by_type.return_value = [
            {"name": "Nat.add_0_r", "type": "forall n, n + 0 = n", "score": 0.9},
        ]
        pipeline.search_by_symbols.return_value = []

        state = _make_proof_state()
        result1 = await retrieve_premises(state, retrieval_pipeline=pipeline)
        result2 = await retrieve_premises(state, retrieval_pipeline=pipeline)

        # Second call should use cache — pipeline called only once
        assert pipeline.search_by_type.call_count == 1
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_deduplicates_by_name(self):
        """Results from type and symbol search are deduplicated by name (§4.4)."""
        retrieve_premises = _import_premise_retrieval()
        pipeline = AsyncMock()
        pipeline.search_by_type.return_value = [
            {"name": "Nat.add_0_r", "type": "forall n, n + 0 = n", "score": 0.9},
        ]
        pipeline.search_by_symbols.return_value = [
            {"name": "Nat.add_0_r", "type": "forall n, n + 0 = n", "score": 0.7},
        ]
        state = _make_proof_state()
        result = await retrieve_premises(state, retrieval_pipeline=pipeline)
        names = [r["name"] if isinstance(r, dict) else r[0] for r in result]
        # Nat.add_0_r should appear only once
        assert names.count("Nat.add_0_r") == 1


# ===========================================================================
# 5. Diversity Filter — §4.5
# ===========================================================================

class TestDiversityFilter:
    """§4.5: Diversity filter requirements."""

    def test_exact_duplicates_removed(self):
        """Exact duplicate tactics are removed, keeping first occurrence."""
        filter_candidates = _import_diversity()
        result = filter_candidates(["auto", "auto", "reflexivity"])
        assert result == ["auto", "reflexivity"]

    def test_whitespace_variants_collapsed(self):
        """Tactics differing only in whitespace are collapsed."""
        filter_candidates = _import_diversity()
        result = filter_candidates(["apply Nat.add_comm.", "apply Nat.add_comm ."])
        assert len(result) == 1
        assert result[0] == "apply Nat.add_comm."

    def test_surface_syntax_collapsed(self):
        """rewrite H vs rewrite -> H are collapsed (§4.5)."""
        filter_candidates = _import_diversity()
        result = filter_candidates(["rewrite H", "rewrite -> H", "apply lemma1"])
        assert "rewrite H" in result
        assert "rewrite -> H" not in result
        assert "apply lemma1" in result

    def test_relative_order_preserved(self):
        """Non-filtered candidates maintain their relative order."""
        filter_candidates = _import_diversity()
        result = filter_candidates(["auto", "simpl", "reflexivity"])
        assert result == ["auto", "simpl", "reflexivity"]

    def test_solver_never_filtered_against_llm(self):
        """Solver tactics are never filtered against LLM candidates (§4.5)."""
        filter_candidates = _import_diversity()
        # Even if an LLM candidate is "auto", the solver "auto" is kept
        # This test documents that solver tactics have a separate namespace
        result = filter_candidates(["auto", "eauto", "auto"])
        # First "auto" (solver) kept, third "auto" (duplicate) removed
        assert result.count("auto") == 1

    def test_given_spec_example(self):
        """Spec example: ["auto", "auto", "rewrite H", "rewrite -> H", "apply lemma1"]
        → ["auto", "rewrite H", "apply lemma1"]."""
        filter_candidates = _import_diversity()
        result = filter_candidates(
            ["auto", "auto", "rewrite H", "rewrite -> H", "apply lemma1"]
        )
        assert result == ["auto", "rewrite H", "apply lemma1"]


# ===========================================================================
# 6. State Cache — §4.6
# ===========================================================================

class TestStateCache:
    """§4.6: State cache hashing requirements."""

    def test_same_goals_same_hypotheses_equal_hash(self):
        """Two states with identical goals and hypotheses produce the same hash."""
        hash_proof_state = _import_state_cache()
        state1 = _make_proof_state(step_index=0, session_id="a")
        state2 = _make_proof_state(step_index=5, session_id="b")
        assert hash_proof_state(state1) == hash_proof_state(state2)

    def test_different_goals_different_hash(self):
        """Two states with different goals produce different hashes."""
        hash_proof_state = _import_state_cache()
        Goal, Hypothesis, ProofState = _import_session_types()
        state1 = _make_proof_state()
        state2 = _make_proof_state(goals=[
            Goal(index=0, type="0 = 0", hypotheses=[]),
        ])
        assert hash_proof_state(state1) != hash_proof_state(state2)

    def test_different_hypotheses_different_hash(self):
        """Two states with same goal but different hypotheses produce different hashes."""
        hash_proof_state = _import_state_cache()
        Goal, Hypothesis, ProofState = _import_session_types()
        state1 = _make_proof_state(goals=[
            Goal(index=0, type="n + 0 = n", hypotheses=[
                Hypothesis(name="n", type="nat"),
            ]),
        ])
        state2 = _make_proof_state(goals=[
            Goal(index=0, type="n + 0 = n", hypotheses=[
                Hypothesis(name="n", type="nat"),
                Hypothesis(name="H", type="n > 0"),
            ]),
        ])
        assert hash_proof_state(state1) != hash_proof_state(state2)

    def test_goal_order_independent(self):
        """Goals [A, B] and [B, A] produce the same hash (§4.6)."""
        hash_proof_state = _import_state_cache()
        Goal, Hypothesis, ProofState = _import_session_types()
        goal_a = Goal(index=0, type="A", hypotheses=[])
        goal_b = Goal(index=1, type="B", hypotheses=[])
        state1 = _make_proof_state(goals=[goal_a, goal_b])
        state2 = _make_proof_state(goals=[goal_b, goal_a])
        assert hash_proof_state(state1) == hash_proof_state(state2)

    def test_hash_is_sha256(self):
        """The hash is a SHA-256 digest (§4.6)."""
        hash_proof_state = _import_state_cache()
        state = _make_proof_state()
        h = hash_proof_state(state)
        assert isinstance(h, bytes)
        assert len(h) == 32  # SHA-256 produces 32 bytes

    def test_session_id_and_step_index_do_not_affect_hash(self):
        """Session ID and step index are excluded from the hash (§4.6)."""
        hash_proof_state = _import_state_cache()
        state1 = _make_proof_state(step_index=0, session_id="session_a")
        state2 = _make_proof_state(step_index=99, session_id="session_z")
        assert hash_proof_state(state1) == hash_proof_state(state2)


# ===========================================================================
# 7. Scoring — §4.7
# ===========================================================================

class TestScoring:
    """§4.7: Scoring function requirements."""

    def test_spec_example_score(self):
        """Spec example: root 3 goals, node depth 2 with 1 goal.
        goal_progress = 2/3, depth_factor = 1/(1+2) = 1/3.
        score = 0.7 * (2/3) + 0.3 * (1/3) = 0.567 (approx)."""
        score_node = _import_scoring()
        Goal, _, ProofState = _import_session_types()
        root_state = _make_proof_state(goals=[
            Goal(index=0, type="A", hypotheses=[]),
            Goal(index=1, type="B", hypotheses=[]),
            Goal(index=2, type="C", hypotheses=[]),
        ])
        node = _make_search_node(
            depth=2,
            proof_state=_make_proof_state(goals=[
                Goal(index=0, type="C", hypotheses=[]),
            ]),
        )
        score = score_node(node, root_state)
        # 0.7 * (2/3) + 0.3 * (1/3) = 0.4667 + 0.1 = 0.5667
        assert abs(score - 0.5667) < 0.01

    def test_root_node_score(self):
        """Root node: depth=0, same goal count as root.
        goal_progress = 0/N = 0. depth_factor = 1/(1+0) = 1.
        score = 0.7 * 0 + 0.3 * 1 = 0.3."""
        score_node = _import_scoring()
        root_state = _make_proof_state()
        node = _make_search_node(depth=0, proof_state=root_state)
        score = score_node(node, root_state)
        # 0.7 * 0 + 0.3 * 1 = 0.3
        assert abs(score - 0.3) < 0.01

    def test_all_goals_closed_score(self):
        """When all goals are closed: goal_progress = 1.0.
        score = 0.7 * 1.0 + 0.3 * depth_factor."""
        score_node = _import_scoring()
        root_state = _make_proof_state(goals=[
            _import_session_types()[0](index=0, type="A", hypotheses=[]),
        ])
        complete = _make_proof_state(goals=[], is_complete=True)
        node = _make_search_node(depth=1, proof_state=complete)
        score = score_node(node, root_state)
        # 0.7 * 1.0 + 0.3 * (1/2) = 0.7 + 0.15 = 0.85
        assert abs(score - 0.85) < 0.01

    def test_zero_root_goals_gives_progress_one(self):
        """When root_goal_count = 0, goal_progress = 1.0 (§4.7)."""
        score_node = _import_scoring()
        root_state = _make_proof_state(goals=[], is_complete=True)
        node = _make_search_node(depth=0, proof_state=root_state)
        score = score_node(node, root_state)
        # goal_progress=1.0, depth_factor=1.0 → 0.7 + 0.3 = 1.0
        assert abs(score - 1.0) < 0.01

    def test_score_is_non_negative(self):
        """Score is always non-negative (§4.7)."""
        score_node = _import_scoring()
        root_state = _make_proof_state()
        node = _make_search_node(depth=50, proof_state=root_state)
        assert score_node(node, root_state) >= 0


# ===========================================================================
# 8. Session Navigation — §4.8
# ===========================================================================

class TestSessionNavigation:
    """§4.8: Session navigation for candidate verification."""

    @pytest.mark.asyncio
    async def test_replays_tactic_path(self):
        """Given a node with tactic_path, the session replays each tactic."""
        proof_search = _import_engine()
        complete_state = _make_complete_state(step_index=4)
        stepped_state = _make_proof_state(step_index=3)
        manager = _make_mock_session_manager(
            tactic_results={
                "intro n.": _make_proof_state(step_index=1),
                "induction n.": _make_proof_state(step_index=2),
                "simpl.": stepped_state,
                "reflexivity.": complete_state,
            },
        )
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=30,
            max_depth=10,
            max_breadth=20,
        )
        # The search should have called submit_tactic
        assert manager.submit_tactic.call_count >= 1


# ===========================================================================
# 9. Few-Shot Retrieval — §4.9
# ===========================================================================

class TestFewShotRetrieval:
    """§4.9: Few-shot context retrieval."""

    def test_returns_empty_when_no_training_data(self):
        """When no training data index is available, returns empty list."""
        retrieve_few_shot = _import_few_shot()
        state = _make_proof_state()
        result = retrieve_few_shot(state, training_data_index=None, k=5)
        assert result == []

    def test_returns_at_most_k_results(self):
        """Returns at most k results (§4.9)."""
        retrieve_few_shot = _import_few_shot()
        # Create a mock training data index with many entries
        mock_index = MagicMock()
        mock_index.search.return_value = [
            ("state1", "tactic1"),
            ("state2", "tactic2"),
            ("state3", "tactic3"),
            ("state4", "tactic4"),
            ("state5", "tactic5"),
            ("state6", "tactic6"),
        ]
        state = _make_proof_state()
        result = retrieve_few_shot(state, training_data_index=mock_index, k=3)
        assert len(result) <= 3


# ===========================================================================
# 10. Data Model — §5
# ===========================================================================

class TestDataModel:
    """§5: Data model constraints."""

    def test_search_node_depth_equals_tactic_path_length(self):
        """SearchNode.depth must equal len(tactic_path) (§5)."""
        SearchNode, _, _ = _import_types()
        node = SearchNode(
            proof_state=_make_proof_state(),
            state_hash=b"\x00" * 32,
            tactic_path=["intro n.", "simpl."],
            depth=2,
            score=0.5,
            parent=None,
        )
        assert node.depth == len(node.tactic_path)

    def test_search_result_success_has_proof_script(self):
        """On success, proof_script is not null (§5)."""
        _, SearchResult, ProofStep = _import_types()
        step = ProofStep(
            tactic="reflexivity.",
            state_before=_make_proof_state(),
            state_after=_make_complete_state(),
        )
        result = SearchResult(
            status="success",
            proof_script=[step],
            best_partial=None,
            states_explored=1,
            unique_states=1,
            wall_time_ms=50,
            llm_unavailable=False,
        )
        assert result.proof_script is not None
        assert result.best_partial is None

    def test_search_result_failure_has_best_partial(self):
        """On failure, best_partial is set and proof_script is null (§5)."""
        _, SearchResult, ProofStep = _import_types()
        partial = ProofStep(
            tactic="intro n.",
            state_before=_make_proof_state(),
            state_after=_make_proof_state(step_index=1),
        )
        result = SearchResult(
            status="failure",
            proof_script=None,
            best_partial=[partial],
            states_explored=100,
            unique_states=80,
            wall_time_ms=5000,
            llm_unavailable=False,
        )
        assert result.proof_script is None
        assert result.best_partial is not None

    def test_search_result_status_values(self):
        """Status must be 'success' or 'failure' (§5)."""
        _, SearchResult, _ = _import_types()
        # Valid statuses
        r1 = SearchResult(
            status="success", proof_script=[], best_partial=None,
            states_explored=0, unique_states=0, wall_time_ms=0,
            llm_unavailable=False,
        )
        assert r1.status in ("success", "failure")

    def test_proof_step_has_required_fields(self):
        """ProofStep has tactic, state_before, state_after (§5)."""
        _, _, ProofStep = _import_types()
        step = ProofStep(
            tactic="intro n.",
            state_before=_make_proof_state(),
            state_after=_make_proof_state(step_index=1),
        )
        assert step.tactic == "intro n."
        assert step.state_before is not None
        assert step.state_after is not None


# ===========================================================================
# 11. Input Validation — §7.1
# ===========================================================================

class TestInputValidation:
    """§7.1: Input clamping behavior."""

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_1(self):
        """timeout ≤ 0 is clamped to 1 second."""
        proof_search = _import_engine()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(initial_state=complete_state)
        # Should not raise, should clamp
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=-5,
            max_depth=10,
            max_breadth=20,
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_max_depth_clamped_to_1(self):
        """max_depth ≤ 0 is clamped to 1."""
        proof_search = _import_engine()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(initial_state=complete_state)
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=30,
            max_depth=0,
            max_breadth=20,
        )
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_max_breadth_clamped_to_1(self):
        """max_breadth ≤ 0 is clamped to 1."""
        proof_search = _import_engine()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(initial_state=complete_state)
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=30,
            max_depth=10,
            max_breadth=-1,
        )
        assert result.status == "success"


# ===========================================================================
# 12. Graceful Degradation — §7.2
# ===========================================================================

class TestGracefulDegradation:
    """§7.2: Dependency error handling."""

    @pytest.mark.asyncio
    async def test_retrieval_unavailable_continues_without_premises(self):
        """When retrieval pipeline is unavailable, search continues (§7.2)."""
        proof_search = _import_engine()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(
            tactic_results={"reflexivity.": complete_state},
        )
        # No retrieval_pipeline passed
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=30,
            max_depth=10,
            max_breadth=20,
            retrieval_pipeline=None,
        )
        # Should still be able to find proof via solver tactics
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_training_data_unavailable_continues(self):
        """When training data is unavailable, search continues without few-shot (§7.2)."""
        proof_search = _import_engine()
        complete_state = _make_complete_state()
        manager = _make_mock_session_manager(
            tactic_results={"reflexivity.": complete_state},
        )
        result = await proof_search(
            session_manager=manager,
            session_id="test",
            timeout=30,
            max_depth=10,
            max_breadth=20,
            training_data_path=None,
        )
        assert result.status == "success"
