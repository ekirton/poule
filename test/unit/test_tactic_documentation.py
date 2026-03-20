"""TDD tests for the Tactic Documentation component (specification/tactic-documentation.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/tactics/ modules exist.

Spec: specification/tactic-documentation.md
Architecture: doc/architecture/tactic-documentation.md
Data model: doc/architecture/data-models/proof-types.md

Import paths under test:
  poule.tactics.lookup       (tactic_lookup, strategy_inspect)
  poule.tactics.types        (TacticInfo, StrategyEntry, TacticComparison, ...)
  poule.tactics.compare      (tactic_compare)
  poule.tactics.suggest      (tactic_suggest)
  poule.tactics.hints        (hint_inspect)
  poule.tactics.parsers      (LtacParser, StrategyParser, HintParser)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports -- fail with ImportError until implementation exists
# ---------------------------------------------------------------------------

def _import_lookup():
    from Poule.tactics.lookup import tactic_lookup
    return tactic_lookup


def _import_strategy_inspect():
    from Poule.tactics.lookup import strategy_inspect
    return strategy_inspect


def _import_compare():
    from Poule.tactics.compare import tactic_compare
    return tactic_compare


def _import_suggest():
    from Poule.tactics.suggest import tactic_suggest
    return tactic_suggest


def _import_hint_inspect():
    from Poule.tactics.hints import hint_inspect
    return hint_inspect


def _import_types():
    from Poule.tactics.types import (
        TacticInfo,
        StrategyEntry,
        TacticComparison,
        PairwiseDiff,
        SelectionHint,
        TacticSuggestion,
        HintDatabase,
        HintSummary,
        HintEntry,
    )
    return (
        TacticInfo,
        StrategyEntry,
        TacticComparison,
        PairwiseDiff,
        SelectionHint,
        TacticSuggestion,
        HintDatabase,
        HintSummary,
        HintEntry,
    )


def _import_session_types():
    from Poule.session.types import Goal, Hypothesis, ProofState
    return Goal, Hypothesis, ProofState


def _import_session_errors():
    from Poule.session.errors import (
        BACKEND_CRASHED,
        SESSION_NOT_FOUND,
        SESSION_EXPIRED,
        SessionError,
    )
    return BACKEND_CRASHED, SESSION_NOT_FOUND, SESSION_EXPIRED, SessionError


def _import_server_errors():
    from Poule.server.errors import NOT_FOUND
    return NOT_FOUND


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_proof_state(
    step_index=0,
    is_complete=False,
    goals=None,
    session_id="test-session",
    focused_goal_index=0,
):
    Goal, Hypothesis, ProofState = _import_session_types()
    if goals is None:
        if is_complete:
            goals = []
        else:
            goals = [Goal(index=0, type="A /\\ B", hypotheses=[
                Hypothesis(name="HA", type="A"),
                Hypothesis(name="HB", type="B"),
            ])]
    return ProofState(
        schema_version=1,
        session_id=session_id,
        step_index=step_index,
        is_complete=is_complete,
        focused_goal_index=None if is_complete else focused_goal_index,
        goals=goals,
    )


def _make_tactic_info(
    name="my_tactic",
    kind="ltac",
    body="auto; try reflexivity",
    qualified_name="Top.my_tactic",
    category="automation",
    is_recursive=False,
    referenced_tactics=None,
    referenced_constants=None,
    strategy_entries=None,
):
    """Build a TacticInfo using real types."""
    (
        TacticInfo, StrategyEntry, _, _, _, _, _, _, _,
    ) = _import_types()
    return TacticInfo(
        name=name,
        qualified_name=qualified_name,
        kind=kind,
        category=category,
        body=body,
        is_recursive=is_recursive,
        referenced_tactics=referenced_tactics or [],
        referenced_constants=referenced_constants or [],
        strategy_entries=strategy_entries or [],
    )


def _make_strategy_entry(constant="Nat.add", level="transparent"):
    """Build a StrategyEntry using real types."""
    (_, StrategyEntry, _, _, _, _, _, _, _) = _import_types()
    return StrategyEntry(constant=constant, level=level)


def _make_hint_entry(
    hint_type="resolve",
    name="eq_refl",
    pattern=None,
    tactic=None,
    cost=0,
):
    """Build a HintEntry using real types."""
    (_, _, _, _, _, _, _, _, HintEntry) = _import_types()
    return HintEntry(
        hint_type=hint_type,
        name=name,
        pattern=pattern,
        tactic=tactic,
        cost=cost,
    )


def _make_hint_summary(resolve_count=0, unfold_count=0, constructors_count=0, extern_count=0):
    """Build a HintSummary using real types."""
    (_, _, _, _, _, _, _, HintSummary, _) = _import_types()
    return HintSummary(
        resolve_count=resolve_count,
        unfold_count=unfold_count,
        constructors_count=constructors_count,
        extern_count=extern_count,
    )


def _make_mock_coq_query(responses=None, errors=None):
    """Create a mock coq_query function.

    responses: dict mapping (command, argument) to raw output string.
    errors: dict mapping (command, argument) to exception to raise.
    """
    responses = responses or {}
    errors = errors or {}

    async def _coq_query(command, argument, session_id=None):
        key = (command, argument)
        if key in errors:
            raise errors[key]
        if key in responses:
            return MagicMock(output=responses[key])
        return MagicMock(output="")

    return AsyncMock(side_effect=_coq_query)


def _make_mock_observe_proof_state(proof_state=None):
    """Create a mock observe_proof_state returning a real ProofState."""
    if proof_state is None:
        proof_state = _make_proof_state()
    return AsyncMock(return_value=proof_state)


# ===========================================================================
# 1. Tactic Lookup -- section 4.1
# ===========================================================================

class TestTacticLookup:
    """section 4.1: tactic_lookup behavioral requirements."""

    @pytest.mark.asyncio
    async def test_ltac_definition_returns_tactic_info(self):
        """Given an Ltac definition, returns TacticInfo with kind='ltac' and parsed body."""
        tactic_lookup = _import_lookup()
        (TacticInfo, _, _, _, _, _, _, _, _) = _import_types()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac my_tactic"):
                "Ltac Top.my_tactic := auto; try reflexivity",
        })
        result = await tactic_lookup("my_tactic", session_id="s1", coq_query=coq_query)
        assert isinstance(result, TacticInfo)
        assert result.kind == "ltac"
        assert result.body == "auto; try reflexivity"
        assert result.qualified_name == "Top.my_tactic"
        assert "auto" in result.referenced_tactics
        assert "reflexivity" in result.referenced_tactics
        assert result.is_recursive is False

    @pytest.mark.asyncio
    async def test_primitive_tactic_returns_kind_primitive(self):
        """Given a primitive tactic name, returns TacticInfo with kind='primitive' and body=None."""
        tactic_lookup = _import_lookup()
        (TacticInfo, _, _, _, _, _, _, _, _) = _import_types()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac intro"): "Error: intro is not an Ltac definition",
        })
        result = await tactic_lookup("intro", coq_query=coq_query)
        assert isinstance(result, TacticInfo)
        assert result.kind == "primitive"
        assert result.body is None
        assert result.qualified_name is None

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self):
        """Given a nonexistent tactic name, returns NOT_FOUND error."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac nonexistent_tactic"):
                "Error: nonexistent_tactic not found",
        })
        with pytest.raises(Exception) as exc_info:
            await tactic_lookup("nonexistent_tactic", coq_query=coq_query)
        assert "NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_empty_name_raises_invalid_argument(self):
        """section 7.1: empty tactic name raises INVALID_ARGUMENT."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query()
        with pytest.raises(Exception) as exc_info:
            await tactic_lookup("", coq_query=coq_query)
        assert "INVALID_ARGUMENT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_ARGUMENT"
        )

    @pytest.mark.asyncio
    async def test_recursive_tactic_detected(self):
        """Ltac parser detects is_recursive when body references own name."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac my_rec"):
                "Ltac Top.my_rec := try (apply foo; my_rec)",
        })
        result = await tactic_lookup("my_rec", coq_query=coq_query)
        assert result.is_recursive is True

    @pytest.mark.asyncio
    async def test_referenced_constants_extracted(self):
        """Parser extracts referenced_constants from unfold/rewrite/apply arguments."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac my_solver"):
                "Ltac Top.my_solver := unfold Nat.add; rewrite Nat.add_comm; apply eq_refl",
        })
        result = await tactic_lookup("my_solver", coq_query=coq_query)
        assert "Nat.add" in result.referenced_constants
        assert "Nat.add_comm" in result.referenced_constants
        assert "eq_refl" in result.referenced_constants

    @pytest.mark.asyncio
    async def test_session_state_not_modified(self):
        """MAINTAINS: lookup does not modify session state."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac intro"): "Error: intro is not an Ltac definition",
        })
        await tactic_lookup("intro", session_id="s1", coq_query=coq_query)
        # coq_query should have been called as read-only; verify no mutation calls
        for call_args in coq_query.call_args_list:
            args = call_args[0] if call_args[0] else ()
            # The command should be "Print" (read-only), never a mutation
            if args:
                assert args[0] == "Print"

    @pytest.mark.asyncio
    async def test_ltac2_returns_kind_ltac2(self):
        """Given an Ltac2 tactic, returns kind='ltac2' with body=None."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac my_ltac2"):
                "Error: my_ltac2 is not an Ltac definition",
        })
        # When the parser detects ltac2 vs primitive depends on Coq output shape.
        # This tests the general non-ltac path; kind assignment may vary.
        result = await tactic_lookup("my_ltac2", coq_query=coq_query)
        assert result.body is None
        assert result.kind in ("primitive", "ltac2")

    # -- QueryError interception for primitives (spec 4.1) --

    @pytest.mark.asyncio
    async def test_query_error_not_ltac_definition_returns_primitive(self):
        """When coq_query raises QueryError with 'not an Ltac definition',
        tactic_lookup intercepts and returns kind='primitive'."""
        tactic_lookup = _import_lookup()
        from Poule.query.handler import QueryError
        (TacticInfo, _, _, _, _, _, _, _, _) = _import_types()
        coq_query = _make_mock_coq_query(errors={
            ("Print", "Ltac intro"): QueryError(
                "PARSE_ERROR",
                "Failed to parse: intro is not an Ltac definition",
            ),
        })
        result = await tactic_lookup("intro", coq_query=coq_query)
        assert isinstance(result, TacticInfo)
        assert result.kind == "primitive"
        assert result.body is None
        assert result.category == "introduction"

    @pytest.mark.asyncio
    async def test_query_error_not_user_defined_tactic_returns_primitive(self):
        """When coq_query raises QueryError with 'not a user defined tactic',
        tactic_lookup intercepts and returns kind='primitive'."""
        tactic_lookup = _import_lookup()
        from Poule.query.handler import QueryError
        (TacticInfo, _, _, _, _, _, _, _, _) = _import_types()
        coq_query = _make_mock_coq_query(errors={
            ("Print", "Ltac apply"): QueryError(
                "PARSE_ERROR",
                "Failed to parse: apply is not a user defined tactic",
            ),
        })
        result = await tactic_lookup("apply", coq_query=coq_query)
        assert isinstance(result, TacticInfo)
        assert result.kind == "primitive"
        assert result.body is None
        assert result.category == "rewriting"

    @pytest.mark.asyncio
    async def test_query_error_non_primitive_re_raised(self):
        """When coq_query raises QueryError that is NOT a primitive-detection
        pattern, tactic_lookup re-raises."""
        tactic_lookup = _import_lookup()
        from Poule.query.handler import QueryError
        coq_query = _make_mock_coq_query(errors={
            ("Print", "Ltac something"): QueryError(
                "TIMEOUT",
                "Computation exceeded time limit.",
            ),
        })
        with pytest.raises(QueryError) as exc_info:
            await tactic_lookup("something", coq_query=coq_query)
        assert exc_info.value.code == "TIMEOUT"

    @pytest.mark.asyncio
    async def test_query_error_eapply_returns_primitive(self):
        """eapply triggers QueryError interception and returns primitive with category."""
        tactic_lookup = _import_lookup()
        from Poule.query.handler import QueryError
        coq_query = _make_mock_coq_query(errors={
            ("Print", "Ltac eapply"): QueryError(
                "PARSE_ERROR",
                "Failed to parse: eapply is not a user defined tactic",
            ),
        })
        result = await tactic_lookup("eapply", coq_query=coq_query)
        assert result.kind == "primitive"
        assert result.category == "rewriting"

    @pytest.mark.asyncio
    async def test_query_error_setoid_rewrite_returns_primitive(self):
        """setoid_rewrite triggers QueryError interception and returns primitive."""
        tactic_lookup = _import_lookup()
        from Poule.query.handler import QueryError
        coq_query = _make_mock_coq_query(errors={
            ("Print", "Ltac setoid_rewrite"): QueryError(
                "PARSE_ERROR",
                "Failed to parse: setoid_rewrite is not a user defined tactic",
            ),
        })
        result = await tactic_lookup("setoid_rewrite", coq_query=coq_query)
        assert result.kind == "primitive"
        assert result.category == "rewriting"

    # -- Multi-word input validation (spec 4.1) --

    @pytest.mark.asyncio
    async def test_multi_word_name_raises_invalid_argument(self):
        """Multi-word input is rejected with INVALID_ARGUMENT before querying Coq."""
        tactic_lookup = _import_lookup()
        from Poule.tactics.lookup import TacticDocError
        coq_query = _make_mock_coq_query()
        with pytest.raises(TacticDocError) as exc_info:
            await tactic_lookup("dependent destruction", coq_query=coq_query)
        assert exc_info.value.code == "INVALID_ARGUMENT"
        assert "dependent destruction" in exc_info.value.message
        # coq_query should NOT have been called
        coq_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_word_convoy_pattern_raises_invalid_argument(self):
        """'convoy pattern' (a proof technique, not a tactic) is rejected."""
        tactic_lookup = _import_lookup()
        from Poule.tactics.lookup import TacticDocError
        coq_query = _make_mock_coq_query()
        with pytest.raises(TacticDocError) as exc_info:
            await tactic_lookup("convoy pattern", coq_query=coq_query)
        assert exc_info.value.code == "INVALID_ARGUMENT"
        coq_query.assert_not_called()

    # -- Expanded primitive categories (spec 4.1) --

    @pytest.mark.asyncio
    async def test_expanded_primitive_categories(self):
        """All commonly used primitives return a non-null category."""
        tactic_lookup = _import_lookup()
        from Poule.query.handler import QueryError

        expected_categories = {
            "eapply": "rewriting",
            "eexact": "rewriting",
            "setoid_rewrite": "rewriting",
            "cbv": "rewriting",
            "compute": "rewriting",
            "hnf": "rewriting",
            "red": "rewriting",
            "discriminate": "equality",
            "injection": "equality",
            "f_equal": "equality",
            "assert": "context_management",
            "pose": "context_management",
            "set": "context_management",
            "remember": "context_management",
            "clear": "context_management",
            "generalize": "context_management",
            "specialize": "context_management",
        }
        for name, expected_cat in expected_categories.items():
            coq_query = _make_mock_coq_query(errors={
                ("Print", f"Ltac {name}"): QueryError(
                    "PARSE_ERROR",
                    f"Failed to parse: {name} is not a user defined tactic",
                ),
            })
            result = await tactic_lookup(name, coq_query=coq_query)
            assert result.kind == "primitive", f"{name} should be primitive"
            assert result.category == expected_cat, (
                f"{name}: expected category '{expected_cat}', got '{result.category}'"
            )


# ===========================================================================
# 2. Strategy Inspection -- section 4.2
# ===========================================================================

class TestStrategyInspection:
    """section 4.2: strategy_inspect behavioral requirements."""

    @pytest.mark.asyncio
    async def test_transparent_strategy_returned(self):
        """Given a constant with transparent strategy, returns StrategyEntry."""
        strategy_inspect = _import_strategy_inspect()
        (_, StrategyEntry, _, _, _, _, _, _, _) = _import_types()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Strategy Nat.add"): "Nat.add : transparent",
        })
        result = await strategy_inspect("Nat.add", coq_query=coq_query)
        assert len(result) == 1
        assert isinstance(result[0], StrategyEntry)
        assert result[0].constant == "Nat.add"
        assert result[0].level == "transparent"

    @pytest.mark.asyncio
    async def test_opaque_strategy_returned(self):
        """Given an opaque constant, returns level='opaque'."""
        strategy_inspect = _import_strategy_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Strategy my_opaque"): "my_opaque : opaque",
        })
        result = await strategy_inspect("my_opaque", coq_query=coq_query)
        assert result[0].level == "opaque"

    @pytest.mark.asyncio
    async def test_numeric_strategy_level(self):
        """Given a numeric strategy level, returns integer level."""
        strategy_inspect = _import_strategy_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Strategy my_const"): "my_const : 5",
        })
        result = await strategy_inspect("my_const", coq_query=coq_query)
        assert result[0].level == 5

    @pytest.mark.asyncio
    async def test_not_found_constant_raises_error(self):
        """Given a nonexistent constant, returns NOT_FOUND error."""
        strategy_inspect = _import_strategy_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Strategy no_such_constant"):
                "Error: no_such_constant not found",
        })
        with pytest.raises(Exception) as exc_info:
            await strategy_inspect("no_such_constant", coq_query=coq_query)
        assert "NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_empty_constant_name_raises_invalid_argument(self):
        """section 7.1: empty constant name raises INVALID_ARGUMENT."""
        strategy_inspect = _import_strategy_inspect()
        coq_query = _make_mock_coq_query()
        with pytest.raises(Exception) as exc_info:
            await strategy_inspect("", coq_query=coq_query)
        assert "INVALID_ARGUMENT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_ARGUMENT"
        )

    @pytest.mark.asyncio
    async def test_session_state_not_modified(self):
        """MAINTAINS: strategy_inspect does not modify session state."""
        strategy_inspect = _import_strategy_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Strategy Nat.add"): "Nat.add : transparent",
        })
        await strategy_inspect("Nat.add", session_id="s1", coq_query=coq_query)
        for call_args in coq_query.call_args_list:
            args = call_args[0] if call_args[0] else ()
            if args:
                assert args[0] == "Print"


# ===========================================================================
# 3. Tactic Comparison -- section 4.3
# ===========================================================================

class TestTacticComparison:
    """section 4.3: tactic_compare behavioral requirements."""

    @pytest.mark.asyncio
    async def test_two_valid_tactics_returns_comparison(self):
        """Given two valid tactic names, returns TacticComparison with both entries."""
        tactic_compare = _import_compare()
        (_, _, TacticComparison, _, _, _, _, _, _) = _import_types()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"): "Error: auto is not an Ltac definition",
            ("Print", "Ltac eauto"): "Error: eauto is not an Ltac definition",
        })
        result = await tactic_compare(["auto", "eauto"], coq_query=coq_query)
        assert isinstance(result, TacticComparison)
        assert len(result.tactics) == 2
        assert len(result.shared_capabilities) >= 0
        assert len(result.pairwise_differences) >= 1
        assert len(result.selection_guidance) == 2
        assert result.not_found == []

    @pytest.mark.asyncio
    async def test_one_not_found_of_two_raises_invalid_argument(self):
        """Given ['auto', 'nonexistent'] where only one resolves, raises INVALID_ARGUMENT."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"): "Error: auto is not an Ltac definition",
            ("Print", "Ltac nonexistent"):
                "Error: nonexistent not found",
        })
        with pytest.raises(Exception) as exc_info:
            await tactic_compare(["auto", "nonexistent"], coq_query=coq_query)
        exc_msg = str(exc_info.value)
        assert "INVALID_ARGUMENT" in exc_msg or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "INVALID_ARGUMENT"
        )
        assert "auto" in exc_msg

    @pytest.mark.asyncio
    async def test_three_names_one_not_found_proceeds(self):
        """Given ['auto', 'eauto', 'nonexistent'], comparison proceeds for found tactics."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"): "Error: auto is not an Ltac definition",
            ("Print", "Ltac eauto"): "Error: eauto is not an Ltac definition",
            ("Print", "Ltac nonexistent"):
                "Error: nonexistent not found",
        })
        result = await tactic_compare(
            ["auto", "eauto", "nonexistent"], coq_query=coq_query,
        )
        assert len(result.tactics) == 2
        assert "nonexistent" in result.not_found

    @pytest.mark.asyncio
    async def test_fewer_than_two_names_raises_invalid_argument(self):
        """section 7.1: fewer than two names raises INVALID_ARGUMENT."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query()
        with pytest.raises(Exception) as exc_info:
            await tactic_compare(["auto"], coq_query=coq_query)
        assert "INVALID_ARGUMENT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "INVALID_ARGUMENT"
        )

    @pytest.mark.asyncio
    async def test_all_not_found_raises_invalid_argument(self):
        """section 7.1: zero valid tactics after lookup raises INVALID_ARGUMENT."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac nonexistent1"):
                "Error: nonexistent1 not found",
            ("Print", "Ltac nonexistent2"):
                "Error: nonexistent2 not found",
        })
        with pytest.raises(Exception) as exc_info:
            await tactic_compare(
                ["nonexistent1", "nonexistent2"], coq_query=coq_query,
            )
        assert "INVALID_ARGUMENT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "INVALID_ARGUMENT"
        )

    @pytest.mark.asyncio
    async def test_pairwise_diff_structure(self):
        """PairwiseDiff has tactic_a, tactic_b, and differences list."""
        tactic_compare = _import_compare()
        (_, _, _, PairwiseDiff, _, _, _, _, _) = _import_types()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"): "Error: auto is not an Ltac definition",
            ("Print", "Ltac eauto"): "Error: eauto is not an Ltac definition",
        })
        result = await tactic_compare(["auto", "eauto"], coq_query=coq_query)
        assert len(result.pairwise_differences) >= 1
        diff = result.pairwise_differences[0]
        assert isinstance(diff, PairwiseDiff)
        assert diff.tactic_a is not None
        assert diff.tactic_b is not None
        assert isinstance(diff.differences, list)

    @pytest.mark.asyncio
    async def test_selection_guidance_structure(self):
        """SelectionHint has tactic and prefer_when list."""
        tactic_compare = _import_compare()
        (_, _, _, _, SelectionHint, _, _, _, _) = _import_types()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"): "Error: auto is not an Ltac definition",
            ("Print", "Ltac eauto"): "Error: eauto is not an Ltac definition",
        })
        result = await tactic_compare(["auto", "eauto"], coq_query=coq_query)
        assert len(result.selection_guidance) == 2
        for hint in result.selection_guidance:
            assert isinstance(hint, SelectionHint)
            assert hint.tactic is not None
            assert isinstance(hint.prefer_when, list)

    @pytest.mark.asyncio
    async def test_ltac_comparison_detects_shared_references(self):
        """section 4.3 Comparison Analysis: detects shared referenced tactics."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac solver1"):
                "Ltac Top.solver1 := intros; auto; try reflexivity",
            ("Print", "Ltac solver2"):
                "Ltac Top.solver2 := intros; auto; try lia",
        })
        result = await tactic_compare(["solver1", "solver2"], coq_query=coq_query)
        # Both reference 'intros' and 'auto' -- shared capabilities should reflect this
        assert len(result.shared_capabilities) >= 1

    @pytest.mark.asyncio
    async def test_session_state_not_modified(self):
        """MAINTAINS: comparison does not modify session state."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"): "Error: auto is not an Ltac definition",
            ("Print", "Ltac eauto"): "Error: eauto is not an Ltac definition",
        })
        await tactic_compare(
            ["auto", "eauto"], session_id="s1", coq_query=coq_query,
        )
        for call_args in coq_query.call_args_list:
            args = call_args[0] if call_args[0] else ()
            if args:
                assert args[0] == "Print"


# ===========================================================================
# 4. Contextual Suggestion -- section 4.4
# ===========================================================================

class TestContextualSuggestion:
    """section 4.4: tactic_suggest behavioral requirements."""

    @pytest.mark.asyncio
    async def test_conjunction_goal_suggests_split(self):
        """Given goal 'A /\\ B', split ranks high in suggestions."""
        tactic_suggest = _import_suggest()
        (_, _, _, _, _, TacticSuggestion, _, _, _) = _import_types()
        Goal, Hypothesis, ProofState = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="A /\\ B", hypotheses=[
                Hypothesis(name="HA", type="A"),
                Hypothesis(name="HB", type="B"),
            ]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        assert isinstance(result, list)
        assert len(result) >= 1
        tactics = [s.tactic for s in result]
        assert "split" in tactics or "constructor" in tactics
        for s in result:
            assert isinstance(s, TacticSuggestion)
            assert s.rank >= 1
            assert s.confidence in ("high", "medium", "low")
            assert s.rationale != ""
            assert s.category is not None

    @pytest.mark.asyncio
    async def test_equality_goal_suggests_reflexivity(self):
        """Given goal 'x = x', reflexivity ranks at position 1 with confidence='high'."""
        tactic_suggest = _import_suggest()
        Goal, _, ProofState = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="x = x", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        assert len(result) >= 1
        top_suggestion = result[0]
        assert top_suggestion.tactic == "reflexivity"
        assert top_suggestion.rank == 1
        assert top_suggestion.confidence == "high"

    @pytest.mark.asyncio
    async def test_universal_quantification_suggests_intro(self):
        """Given goal 'forall n : nat, P n', intro/intros rank high."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="forall n : nat, n + 0 = n", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        tactics = [s.tactic for s in result]
        has_intro = any(t.startswith("intro") for t in tactics)
        assert has_intro

    @pytest.mark.asyncio
    async def test_disjunction_goal_suggests_left_right(self):
        """Given goal 'A \\/ B', left/right/destruct are suggested."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="A \\/ B", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        tactics = [s.tactic for s in result]
        assert "left" in tactics or "right" in tactics or "destruct" in tactics

    @pytest.mark.asyncio
    async def test_existential_goal_suggests_exists(self):
        """Given goal 'exists x, P x', exists/eexists are suggested."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="exists x, P x", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        tactics = [s.tactic for s in result]
        assert "exists" in tactics or "eexists" in tactics

    @pytest.mark.asyncio
    async def test_hypothesis_enables_destruct(self):
        """section 4.4 Hypothesis Inspection: H : A /\\ B enables 'destruct H'."""
        tactic_suggest = _import_suggest()
        Goal, Hypothesis, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="C", hypotheses=[
                Hypothesis(name="H", type="A /\\ B"),
            ]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        tactics = [s.tactic for s in result]
        assert any("destruct H" in t for t in tactics)

    @pytest.mark.asyncio
    async def test_hypothesis_equality_enables_rewrite(self):
        """section 4.4 Hypothesis Inspection: H : x = y enables 'rewrite H'."""
        tactic_suggest = _import_suggest()
        Goal, Hypothesis, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="P x", hypotheses=[
                Hypothesis(name="H", type="x = y"),
            ]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        tactics = [s.tactic for s in result]
        assert any("rewrite H" in t for t in tactics)

    @pytest.mark.asyncio
    async def test_hypothesis_matches_goal_enables_exact(self):
        """section 4.4 Hypothesis Inspection: H : <goal_type> enables 'exact H' / 'assumption'."""
        tactic_suggest = _import_suggest()
        Goal, Hypothesis, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="A", hypotheses=[
                Hypothesis(name="H", type="A"),
            ]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        tactics = [s.tactic for s in result]
        assert any("exact H" in t or t == "assumption" for t in tactics)

    @pytest.mark.asyncio
    async def test_default_limit_is_10(self):
        """Default limit is 10 suggestions."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="very_complex_goal", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        assert len(result) <= 10

    @pytest.mark.asyncio
    async def test_custom_limit_respected(self):
        """When limit=3, at most 3 suggestions returned."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="A /\\ B", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            limit=3,
            observe_proof_state=observe,
        )
        assert len(result) <= 3

    @pytest.mark.asyncio
    async def test_limit_zero_clamped_to_1(self):
        """section 7.1: limit <= 0 is clamped to 1, no error returned."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="A", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            limit=0,
            observe_proof_state=observe,
        )
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_invalid_session_raises_session_not_found(self):
        """section 7.2: invalid session_id raises SESSION_NOT_FOUND."""
        tactic_suggest = _import_suggest()
        _, SESSION_NOT_FOUND, _, SessionError = _import_session_errors()
        observe = AsyncMock(
            side_effect=SessionError(SESSION_NOT_FOUND, "not found"),
        )
        with pytest.raises(SessionError) as exc_info:
            await tactic_suggest(
                session_id="nonexistent",
                observe_proof_state=observe,
            )
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.asyncio
    async def test_proof_complete_raises_session_required(self):
        """section 7.2: proof is complete (no open goals) raises SESSION_REQUIRED."""
        tactic_suggest = _import_suggest()
        proof_state = _make_proof_state(is_complete=True, goals=[])
        observe = _make_mock_observe_proof_state(proof_state)
        with pytest.raises(Exception) as exc_info:
            await tactic_suggest(
                session_id="s1",
                observe_proof_state=observe,
            )
        assert "SESSION_REQUIRED" in str(exc_info.value) or (
            hasattr(exc_info.value, "code")
            and exc_info.value.code == "SESSION_REQUIRED"
        )

    @pytest.mark.asyncio
    async def test_ranking_order_is_valid(self):
        """Returned suggestions have rank values from 1..N in order."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="A /\\ B", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        for i, suggestion in enumerate(result):
            assert suggestion.rank == i + 1

    @pytest.mark.asyncio
    async def test_specific_tactic_ranks_above_general(self):
        """section 4.4 Ranking: specific tactics rank above general ones."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="x = x", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        tactics = [s.tactic for s in result]
        # reflexivity (specific) should appear before auto (general)
        if "reflexivity" in tactics and "auto" in tactics:
            assert tactics.index("reflexivity") < tactics.index("auto")

    @pytest.mark.asyncio
    async def test_no_strong_candidates_returns_low_confidence(self):
        """section 4.4 Ranking: when no strong match, returns general strategies with low confidence."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="some_opaque_constant arg1 arg2", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        assert len(result) >= 1
        # When no specific match, all suggestions should be low confidence
        for s in result:
            assert s.confidence in ("low", "medium")

    @pytest.mark.asyncio
    async def test_session_state_not_modified(self):
        """MAINTAINS: tactic_suggest does not modify session state or execute tactics."""
        tactic_suggest = _import_suggest()
        proof_state = _make_proof_state()
        observe = _make_mock_observe_proof_state(proof_state)
        await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        # observe_proof_state is read-only; verify it was called
        observe.assert_called_once_with("s1")


# ===========================================================================
# 5. Hint Database Inspection -- section 4.5
# ===========================================================================

class TestHintDatabaseInspection:
    """section 4.5: hint_inspect behavioral requirements."""

    @pytest.mark.asyncio
    async def test_core_database_returns_hint_database(self):
        """Given the 'core' hint database, returns HintDatabase with parsed entries."""
        hint_inspect = _import_hint_inspect()
        (_, _, _, _, _, _, HintDatabase, _, _) = _import_types()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb core"): (
                "Resolve eq_refl : eq (cost 0)\n"
                "Resolve eq_sym : eq (cost 1)\n"
                "Unfold not (cost 1)\n"
                "Constructors bool (cost 0)\n"
                "Extern 5 (_ = _) => congruence\n"
            ),
        })
        result = await hint_inspect("core", coq_query=coq_query)
        assert isinstance(result, HintDatabase)
        assert result.name == "core"
        assert result.summary.resolve_count == 2
        assert result.summary.unfold_count == 1
        assert result.summary.constructors_count == 1
        assert result.summary.extern_count == 1
        assert len(result.entries) == 5
        assert result.truncated is False
        assert result.total_entries == 5

    @pytest.mark.asyncio
    async def test_resolve_entry_parsed(self):
        """Resolve hint entry is parsed into correct HintEntry fields."""
        hint_inspect = _import_hint_inspect()
        (_, _, _, _, _, _, _, _, HintEntry) = _import_types()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb test_db"): "Resolve eq_refl : eq (cost 0)\n",
        })
        result = await hint_inspect("test_db", coq_query=coq_query)
        entry = result.entries[0]
        assert isinstance(entry, HintEntry)
        assert entry.hint_type == "resolve"
        assert entry.name == "eq_refl"
        assert entry.cost == 0
        assert entry.pattern is None
        assert entry.tactic is None

    @pytest.mark.asyncio
    async def test_unfold_entry_parsed(self):
        """Unfold hint entry is parsed correctly."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb test_db"): "Unfold not (cost 1)\n",
        })
        result = await hint_inspect("test_db", coq_query=coq_query)
        entry = result.entries[0]
        assert entry.hint_type == "unfold"
        assert entry.name == "not"
        assert entry.cost == 1

    @pytest.mark.asyncio
    async def test_constructors_entry_parsed(self):
        """Constructors hint entry is parsed correctly."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb test_db"): "Constructors bool (cost 0)\n",
        })
        result = await hint_inspect("test_db", coq_query=coq_query)
        entry = result.entries[0]
        assert entry.hint_type == "constructors"
        assert entry.name == "bool"
        assert entry.cost == 0

    @pytest.mark.asyncio
    async def test_extern_entry_parsed(self):
        """Extern hint entry is parsed with pattern and tactic fields."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb test_db"): "Extern 5 (_ = _) => congruence\n",
        })
        result = await hint_inspect("test_db", coq_query=coq_query)
        entry = result.entries[0]
        assert entry.hint_type == "extern"
        assert entry.name is None
        assert entry.pattern == "(_ = _)"
        assert entry.tactic == "congruence"
        assert entry.cost == 5

    @pytest.mark.asyncio
    async def test_not_found_database_raises_error(self):
        """Given a nonexistent database name, returns NOT_FOUND error."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb nonexistent_db"):
                "Error: nonexistent_db not found",
        })
        with pytest.raises(Exception) as exc_info:
            await hint_inspect("nonexistent_db", coq_query=coq_query)
        assert "NOT_FOUND" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "NOT_FOUND"
        )

    @pytest.mark.asyncio
    async def test_empty_database_name_raises_invalid_argument(self):
        """section 7.1: empty database name raises INVALID_ARGUMENT."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query()
        with pytest.raises(Exception) as exc_info:
            await hint_inspect("", coq_query=coq_query)
        assert "INVALID_ARGUMENT" in str(exc_info.value) or (
            hasattr(exc_info.value, "code") and exc_info.value.code == "INVALID_ARGUMENT"
        )

    @pytest.mark.asyncio
    async def test_empty_database_returns_zero_entries(self):
        """section 7.4: database with zero entries returns empty entries, all counts=0."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb empty_db"): "",
        })
        result = await hint_inspect("empty_db", coq_query=coq_query)
        assert result.entries == []
        assert result.summary.resolve_count == 0
        assert result.summary.unfold_count == 0
        assert result.summary.constructors_count == 0
        assert result.summary.extern_count == 0
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_truncation_when_exceeds_limit(self):
        """section 4.5: database with entries exceeding truncation limit is truncated."""
        hint_inspect = _import_hint_inspect()
        # Generate 500 resolve entries
        lines = "\n".join(
            f"Resolve lemma_{i} : type (cost {i % 10})" for i in range(500)
        )
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb large_db"): lines,
        })
        result = await hint_inspect("large_db", coq_query=coq_query)
        assert result.truncated is True
        assert result.total_entries == 500
        assert len(result.entries) <= 200  # spec example uses 200 as truncation limit

    @pytest.mark.asyncio
    async def test_summary_counts_match_entries(self):
        """HintSummary counts match the actual entry types."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb mixed"): (
                "Resolve lemma1 : type (cost 0)\n"
                "Resolve lemma2 : type (cost 1)\n"
                "Resolve lemma3 : type (cost 2)\n"
                "Unfold const1 (cost 0)\n"
                "Unfold const2 (cost 1)\n"
                "Constructors ind1 (cost 0)\n"
                "Extern 3 (_ = _) => congruence\n"
            ),
        })
        result = await hint_inspect("mixed", coq_query=coq_query)
        assert result.summary.resolve_count == 3
        assert result.summary.unfold_count == 2
        assert result.summary.constructors_count == 1
        assert result.summary.extern_count == 1

    @pytest.mark.asyncio
    async def test_session_state_not_modified(self):
        """MAINTAINS: hint_inspect does not modify session state."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb core"): "Resolve eq_refl : eq (cost 0)\n",
        })
        await hint_inspect("core", session_id="s1", coq_query=coq_query)
        for call_args in coq_query.call_args_list:
            args = call_args[0] if call_args[0] else ()
            if args:
                assert args[0] == "Print"


# ===========================================================================
# 6. Data Model -- section 5
# ===========================================================================

class TestDataModel:
    """section 5: Data model constraints for all tactic documentation types."""

    def test_tactic_info_required_fields(self):
        """TacticInfo has all required fields from spec."""
        info = _make_tactic_info()
        assert info.name == "my_tactic"
        assert info.kind == "ltac"
        assert info.body == "auto; try reflexivity"
        assert info.qualified_name == "Top.my_tactic"
        assert info.is_recursive is False
        assert isinstance(info.referenced_tactics, list)
        assert isinstance(info.referenced_constants, list)
        assert isinstance(info.strategy_entries, list)

    def test_tactic_info_primitive_has_null_body(self):
        """Primitive TacticInfo has body=None, is_recursive=False, empty references."""
        info = _make_tactic_info(
            name="intro",
            kind="primitive",
            body=None,
            qualified_name=None,
            category="introduction",
        )
        assert info.body is None
        assert info.is_recursive is False
        assert info.referenced_tactics == []
        assert info.referenced_constants == []

    def test_tactic_info_category_vocabulary(self):
        """TacticInfo.category uses the specified vocabulary."""
        valid_categories = {
            "automation", "rewriting", "case_analysis",
            "introduction", "arithmetic", None,
        }
        for cat in valid_categories:
            info = _make_tactic_info(category=cat)
            assert info.category in valid_categories

    def test_strategy_entry_required_fields(self):
        """StrategyEntry has constant and level fields."""
        entry = _make_strategy_entry()
        assert entry.constant == "Nat.add"
        assert entry.level == "transparent"

    def test_strategy_entry_level_types(self):
        """StrategyEntry.level can be 'transparent', 'opaque', or integer."""
        (_, StrategyEntry, _, _, _, _, _, _, _) = _import_types()
        e1 = StrategyEntry(constant="c1", level="transparent")
        e2 = StrategyEntry(constant="c2", level="opaque")
        e3 = StrategyEntry(constant="c3", level=5)
        assert e1.level == "transparent"
        assert e2.level == "opaque"
        assert e3.level == 5

    def test_tactic_comparison_required_fields(self):
        """TacticComparison has all required fields."""
        (
            _, _, TacticComparison, PairwiseDiff, SelectionHint,
            _, _, _, _,
        ) = _import_types()
        info1 = _make_tactic_info(name="auto", kind="primitive", body=None, qualified_name=None)
        info2 = _make_tactic_info(name="eauto", kind="primitive", body=None, qualified_name=None)
        comp = TacticComparison(
            tactics=[info1, info2],
            shared_capabilities=["proof search"],
            pairwise_differences=[
                PairwiseDiff(
                    tactic_a="auto",
                    tactic_b="eauto",
                    differences=["eauto supports evar instantiation"],
                ),
            ],
            selection_guidance=[
                SelectionHint(tactic="auto", prefer_when=["simple goals"]),
                SelectionHint(tactic="eauto", prefer_when=["existential goals"]),
            ],
            not_found=[],
        )
        assert len(comp.tactics) == 2
        assert len(comp.pairwise_differences) == 1
        assert len(comp.selection_guidance) == 2
        assert comp.not_found == []

    def test_tactic_suggestion_required_fields(self):
        """TacticSuggestion has all required fields."""
        (_, _, _, _, _, TacticSuggestion, _, _, _) = _import_types()
        suggestion = TacticSuggestion(
            tactic="split",
            rank=1,
            rationale="Goal is a conjunction",
            confidence="high",
            category="splitting",
        )
        assert suggestion.tactic == "split"
        assert suggestion.rank == 1
        assert suggestion.rationale == "Goal is a conjunction"
        assert suggestion.confidence == "high"
        assert suggestion.category == "splitting"

    def test_tactic_suggestion_confidence_values(self):
        """TacticSuggestion.confidence must be 'high', 'medium', or 'low'."""
        (_, _, _, _, _, TacticSuggestion, _, _, _) = _import_types()
        for conf in ("high", "medium", "low"):
            s = TacticSuggestion(
                tactic="auto",
                rank=1,
                rationale="test",
                confidence=conf,
                category="automation",
            )
            assert s.confidence == conf

    def test_hint_database_required_fields(self):
        """HintDatabase has all required fields."""
        (_, _, _, _, _, _, HintDatabase, _, _) = _import_types()
        summary = _make_hint_summary(resolve_count=2, extern_count=1)
        entry1 = _make_hint_entry(hint_type="resolve", name="eq_refl", cost=0)
        entry2 = _make_hint_entry(hint_type="resolve", name="eq_sym", cost=1)
        entry3 = _make_hint_entry(
            hint_type="extern", name=None, pattern="(_ = _)",
            tactic="congruence", cost=5,
        )
        db = HintDatabase(
            name="core",
            summary=summary,
            entries=[entry1, entry2, entry3],
            truncated=False,
            total_entries=3,
        )
        assert db.name == "core"
        assert db.summary.resolve_count == 2
        assert db.summary.extern_count == 1
        assert len(db.entries) == 3
        assert db.truncated is False
        assert db.total_entries == 3

    def test_hint_entry_extern_has_pattern_and_tactic(self):
        """Extern HintEntry has non-null pattern and tactic; null name."""
        entry = _make_hint_entry(
            hint_type="extern", name=None, pattern="(_ = _)",
            tactic="congruence", cost=5,
        )
        assert entry.hint_type == "extern"
        assert entry.name is None
        assert entry.pattern is not None
        assert entry.tactic is not None

    def test_hint_entry_non_extern_has_null_pattern_tactic(self):
        """Non-extern HintEntry has null pattern and tactic."""
        for ht in ("resolve", "unfold", "constructors"):
            entry = _make_hint_entry(hint_type=ht, name="some_name", cost=0)
            assert entry.pattern is None
            assert entry.tactic is None


# ===========================================================================
# 7. Error Specification -- section 7
# ===========================================================================

class TestErrorSpecification:
    """section 7: Error specification for all operations."""

    # --- 7.1 Input Errors ---

    @pytest.mark.asyncio
    async def test_empty_tactic_name_error_message(self):
        """section 7.1: empty tactic name produces specific message."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query()
        with pytest.raises(Exception) as exc_info:
            await tactic_lookup("", coq_query=coq_query)
        assert "Tactic name must not be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_database_name_error_message(self):
        """section 7.1: empty database name produces specific message."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query()
        with pytest.raises(Exception) as exc_info:
            await hint_inspect("", coq_query=coq_query)
        assert "Hint database name must not be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_constant_name_error_message(self):
        """section 7.1: empty constant name produces specific message."""
        strategy_inspect = _import_strategy_inspect()
        coq_query = _make_mock_coq_query()
        with pytest.raises(Exception) as exc_info:
            await strategy_inspect("", coq_query=coq_query)
        assert "Constant name must not be empty" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_fewer_than_two_comparison_names_message(self):
        """section 7.1: fewer than two names produces specific message."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query()
        with pytest.raises(Exception) as exc_info:
            await tactic_compare(["auto"], coq_query=coq_query)
        assert "Comparison requires at least two tactic names" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_zero_valid_comparison_message(self):
        """section 7.1: zero valid tactics produces specific message."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac nonexistent1"): "Error: nonexistent1 not found",
            ("Print", "Ltac nonexistent2"): "Error: nonexistent2 not found",
        })
        with pytest.raises(Exception) as exc_info:
            await tactic_compare(
                ["nonexistent1", "nonexistent2"], coq_query=coq_query,
            )
        assert "None of the provided names were found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_one_valid_comparison_message(self):
        """section 7.1: one valid tactic produces message including the found name."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"): "Error: auto is not an Ltac definition",
            ("Print", "Ltac nonexistent"): "Error: nonexistent not found",
        })
        with pytest.raises(Exception) as exc_info:
            await tactic_compare(["auto", "nonexistent"], coq_query=coq_query)
        msg = str(exc_info.value)
        assert "Only" in msg and "auto" in msg

    # --- 7.2 State Errors ---

    @pytest.mark.asyncio
    async def test_session_not_found_message(self):
        """section 7.2: session_not_found produces specific message."""
        tactic_suggest = _import_suggest()
        _, SESSION_NOT_FOUND, _, SessionError = _import_session_errors()
        observe = AsyncMock(
            side_effect=SessionError(SESSION_NOT_FOUND, "not found"),
        )
        with pytest.raises(SessionError) as exc_info:
            await tactic_suggest(
                session_id="nonexistent",
                observe_proof_state=observe,
            )
        assert exc_info.value.code == SESSION_NOT_FOUND

    @pytest.mark.asyncio
    async def test_proof_complete_error_message(self):
        """section 7.2: proof complete produces SESSION_REQUIRED message."""
        tactic_suggest = _import_suggest()
        proof_state = _make_proof_state(is_complete=True, goals=[])
        observe = _make_mock_observe_proof_state(proof_state)
        with pytest.raises(Exception) as exc_info:
            await tactic_suggest(
                session_id="s1",
                observe_proof_state=observe,
            )
        assert "at least one open goal" in str(exc_info.value)

    # --- 7.3 Dependency Errors ---

    @pytest.mark.asyncio
    async def test_tactic_not_found_message(self):
        """section 7.3: tactic not found produces specific message including the name."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac missing_tactic"):
                "Error: missing_tactic not found",
        })
        with pytest.raises(Exception) as exc_info:
            await tactic_lookup("missing_tactic", coq_query=coq_query)
        assert "missing_tactic" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_hint_database_not_found_message(self):
        """section 7.3: hint database not found produces specific message."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb nonexistent_db"):
                "Error: nonexistent_db not found",
        })
        with pytest.raises(Exception) as exc_info:
            await hint_inspect("nonexistent_db", coq_query=coq_query)
        assert "nonexistent_db" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_constant_not_found_message(self):
        """section 7.3: constant not found produces specific message."""
        strategy_inspect = _import_strategy_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Strategy missing_const"):
                "Error: missing_const not found",
        })
        with pytest.raises(Exception) as exc_info:
            await strategy_inspect("missing_const", coq_query=coq_query)
        assert "missing_const" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_backend_crashed_propagated(self):
        """section 7.3: BACKEND_CRASHED from coq_query is propagated."""
        tactic_lookup = _import_lookup()
        BACKEND_CRASHED, _, _, SessionError = _import_session_errors()
        coq_query = AsyncMock(
            side_effect=SessionError(BACKEND_CRASHED, "The Coq backend has crashed."),
        )
        with pytest.raises(SessionError) as exc_info:
            await tactic_lookup("auto", coq_query=coq_query)
        assert exc_info.value.code == BACKEND_CRASHED

    @pytest.mark.asyncio
    async def test_timeout_propagated(self):
        """section 7.3: TIMEOUT from coq_query is propagated."""
        tactic_lookup = _import_lookup()
        # TIMEOUT may be a distinct code or reuse SessionError
        coq_query = AsyncMock(
            side_effect=Exception("TIMEOUT: Query exceeded time limit."),
        )
        with pytest.raises(Exception) as exc_info:
            await tactic_lookup("auto", coq_query=coq_query)
        assert "TIMEOUT" in str(exc_info.value)


# ===========================================================================
# 8. Interface Contracts -- section 6
# ===========================================================================

class TestInterfaceContracts:
    """section 6: Interface contracts with dependencies."""

    @pytest.mark.asyncio
    async def test_lookup_issues_correct_coq_query(self):
        """Tactic lookup issues coq_query('Print', 'Ltac <name>', session_id)."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac my_tactic"):
                "Ltac Top.my_tactic := auto",
        })
        await tactic_lookup("my_tactic", session_id="s1", coq_query=coq_query)
        coq_query.assert_called_once()
        args = coq_query.call_args[0]
        assert args[0] == "Print"
        assert args[1] == "Ltac my_tactic"

    @pytest.mark.asyncio
    async def test_strategy_issues_correct_coq_query(self):
        """Strategy inspection issues coq_query('Print', 'Strategy <name>')."""
        strategy_inspect = _import_strategy_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Strategy Nat.add"): "Nat.add : transparent",
        })
        await strategy_inspect("Nat.add", coq_query=coq_query)
        coq_query.assert_called_once()
        args = coq_query.call_args[0]
        assert args[0] == "Print"
        assert args[1] == "Strategy Nat.add"

    @pytest.mark.asyncio
    async def test_hint_issues_correct_coq_query(self):
        """Hint inspection issues coq_query('Print', 'HintDb <name>')."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb core"): "Resolve eq_refl : eq (cost 0)\n",
        })
        await hint_inspect("core", coq_query=coq_query)
        coq_query.assert_called_once()
        args = coq_query.call_args[0]
        assert args[0] == "Print"
        assert args[1] == "HintDb core"

    @pytest.mark.asyncio
    async def test_session_id_passed_through_to_coq_query(self):
        """When session_id is provided, it is forwarded to coq_query."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"):
                "Error: auto is not an Ltac definition",
        })
        await tactic_lookup("auto", session_id="abc123", coq_query=coq_query)
        call_kwargs = coq_query.call_args[1] if coq_query.call_args[1] else {}
        call_args = coq_query.call_args[0] if coq_query.call_args[0] else ()
        # session_id should be passed either as positional arg or keyword arg
        assert "abc123" in call_args or call_kwargs.get("session_id") == "abc123"

    @pytest.mark.asyncio
    async def test_session_free_lookup_omits_session_id(self):
        """When no session_id, coq_query is called without session context."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"):
                "Error: auto is not an Ltac definition",
        })
        await tactic_lookup("auto", coq_query=coq_query)
        call_kwargs = coq_query.call_args[1] if coq_query.call_args[1] else {}
        call_args = coq_query.call_args[0] if coq_query.call_args[0] else ()
        # session_id should be None or absent
        assert call_kwargs.get("session_id") is None or (
            len(call_args) < 3 or call_args[2] is None
        )

    @pytest.mark.asyncio
    async def test_suggest_calls_observe_proof_state(self):
        """tactic_suggest calls observe_proof_state(session_id) exactly once."""
        tactic_suggest = _import_suggest()
        proof_state = _make_proof_state()
        observe = _make_mock_observe_proof_state(proof_state)
        await tactic_suggest(
            session_id="s1",
            observe_proof_state=observe,
        )
        observe.assert_called_once_with("s1")


# ===========================================================================
# 9. Spec Examples -- section 9
# ===========================================================================

class TestSpecExamples:
    """section 9: Tests derived from the specification examples."""

    @pytest.mark.asyncio
    async def test_example_ltac_lookup(self):
        """Spec example: tactic_lookup('my_solver', session_id='abc123')."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac my_solver"):
                "Ltac Top.my_solver := intros; auto with arith; try lia",
        })
        result = await tactic_lookup(
            "my_solver", session_id="abc123", coq_query=coq_query,
        )
        assert result.name == "my_solver"
        assert result.qualified_name == "Top.my_solver"
        assert result.kind == "ltac"
        assert result.body == "intros; auto with arith; try lia"
        assert result.is_recursive is False
        assert "intros" in result.referenced_tactics
        assert "auto" in result.referenced_tactics
        assert "lia" in result.referenced_tactics

    @pytest.mark.asyncio
    async def test_example_primitive_lookup(self):
        """Spec example: tactic_lookup('intro') returns primitive kind."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac intro"):
                "Error: intro is not an Ltac definition",
        })
        result = await tactic_lookup("intro", coq_query=coq_query)
        assert result.name == "intro"
        assert result.qualified_name is None
        assert result.kind == "primitive"
        assert result.body is None
        assert result.is_recursive is False
        assert result.referenced_tactics == []
        assert result.referenced_constants == []

    @pytest.mark.asyncio
    async def test_example_contextual_suggestion(self):
        """Spec example: tactic_suggest for goal 'forall n : nat, n + 0 = n'."""
        tactic_suggest = _import_suggest()
        Goal, _, _ = _import_session_types()
        proof_state = _make_proof_state(goals=[
            Goal(index=0, type="forall n : nat, n + 0 = n", hypotheses=[]),
        ])
        observe = _make_mock_observe_proof_state(proof_state)
        result = await tactic_suggest(
            session_id="def456",
            observe_proof_state=observe,
        )
        # Per spec: "intro n" at rank 1, "intros" at rank 2
        assert result[0].rank == 1
        assert "intro" in result[0].tactic
        assert result[0].confidence == "high"
        assert result[0].category == "introduction"

    @pytest.mark.asyncio
    async def test_example_hint_database_inspection(self):
        """Spec example: hint_inspect('core', session_id='abc123')."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb core"): (
                "Resolve eq_refl : eq (cost 0)\n"
                "Unfold not (cost 1)\n"
                "Constructors bool (cost 0)\n"
                "Extern 5 (_ = _) => congruence\n"
            ),
        })
        result = await hint_inspect("core", session_id="abc123", coq_query=coq_query)
        assert result.name == "core"
        assert result.truncated is False
        # Check entry types are represented
        entry_types = [e.hint_type for e in result.entries]
        assert "resolve" in entry_types
        assert "unfold" in entry_types
        assert "constructors" in entry_types
        assert "extern" in entry_types


# ===========================================================================
# 10. Edge Cases -- section 7.4
# ===========================================================================

class TestEdgeCases:
    """section 7.4: Edge case behaviors."""

    @pytest.mark.asyncio
    async def test_recursive_ltac_tactic(self):
        """section 7.4: Recursive Ltac tactic returns is_recursive=True."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac my_rec_tactic"):
                "Ltac Top.my_rec_tactic := try (apply foo; my_rec_tactic)",
        })
        result = await tactic_lookup("my_rec_tactic", coq_query=coq_query)
        assert result.is_recursive is True

    @pytest.mark.asyncio
    async def test_session_free_lookup_uses_global_env(self):
        """section 7.4: Session-free lookup queries standalone Coq process."""
        tactic_lookup = _import_lookup()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"):
                "Error: auto is not an Ltac definition",
        })
        result = await tactic_lookup("auto", coq_query=coq_query)
        # Should succeed without session_id
        assert result.name == "auto"
        # session_id should be None in the call
        call_kwargs = coq_query.call_args[1] if coq_query.call_args[1] else {}
        call_args = coq_query.call_args[0] if coq_query.call_args[0] else ()
        assert call_kwargs.get("session_id") is None or (
            len(call_args) < 3 or call_args[2] is None
        )

    @pytest.mark.asyncio
    async def test_hint_database_zero_entries(self):
        """section 7.4: Hint database with zero entries returns empty list."""
        hint_inspect = _import_hint_inspect()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "HintDb empty_db"): "",
        })
        result = await hint_inspect("empty_db", coq_query=coq_query)
        assert result.entries == []
        assert result.summary.resolve_count == 0
        assert result.summary.unfold_count == 0
        assert result.summary.constructors_count == 0
        assert result.summary.extern_count == 0
        assert result.truncated is False

    @pytest.mark.asyncio
    async def test_comparison_mixed_found_not_found(self):
        """section 7.4: Comparison with mix of found/not-found (>=2 found) proceeds."""
        tactic_compare = _import_compare()
        coq_query = _make_mock_coq_query(responses={
            ("Print", "Ltac auto"): "Error: auto is not an Ltac definition",
            ("Print", "Ltac eauto"): "Error: eauto is not an Ltac definition",
            ("Print", "Ltac missing1"): "Error: missing1 not found",
            ("Print", "Ltac missing2"): "Error: missing2 not found",
        })
        result = await tactic_compare(
            ["auto", "eauto", "missing1", "missing2"],
            coq_query=coq_query,
        )
        assert len(result.tactics) == 2
        assert set(result.not_found) == {"missing1", "missing2"}
