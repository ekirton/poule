"""Tests for tactic argument retrieval (spec §8.3, §8.4).

Tests ArgumentRetriever: retrieval strategy routing, hypothesis scanning,
graceful degradation, and integration with suggest_tactics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from Poule.models.responses import SearchResult
from Poule.session.types import Hypothesis
from Poule.tactics.types import TacticSuggestion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_search_result(name: str, score: float, statement: str = "") -> SearchResult:
    return SearchResult(
        name=name,
        statement=statement or f"{name} : forall x, x = x",
        type=f"forall x, x = x",
        module="Test.Module",
        kind="Lemma",
        score=score,
    )


def _make_hypothesis(name: str, type_str: str) -> Hypothesis:
    return Hypothesis(name=name, type=type_str)


# ---------------------------------------------------------------------------
# 1. ArgumentCandidate
# ---------------------------------------------------------------------------


class TestArgumentCandidate:
    """spec §8.3: ArgumentCandidate is a frozen dataclass with name and score."""

    def test_argument_candidate_fields(self):
        from Poule.tactics.argument_retriever import ArgumentCandidate

        c = ArgumentCandidate(name="Nat.add_0_r", score=0.82)
        assert c.name == "Nat.add_0_r"
        assert c.score == 0.82

    def test_argument_candidate_is_frozen(self):
        from Poule.tactics.argument_retriever import ArgumentCandidate

        c = ArgumentCandidate(name="Nat.add_0_r", score=0.82)
        with pytest.raises(AttributeError):
            c.name = "other"


# ---------------------------------------------------------------------------
# 2. ARGUMENT_FAMILIES mapping
# ---------------------------------------------------------------------------


class TestArgumentFamilies:
    """spec §8.3: tactic family classification."""

    def test_apply_is_type_match(self):
        from Poule.tactics.argument_retriever import ARGUMENT_FAMILIES

        assert ARGUMENT_FAMILIES["apply"] == "type_match"

    def test_exact_is_type_match(self):
        from Poule.tactics.argument_retriever import ARGUMENT_FAMILIES

        assert ARGUMENT_FAMILIES["exact"] == "type_match"

    def test_rewrite_is_rewrite_strategy(self):
        from Poule.tactics.argument_retriever import ARGUMENT_FAMILIES

        assert ARGUMENT_FAMILIES["rewrite"] == "rewrite"

    def test_intros_not_in_families(self):
        from Poule.tactics.argument_retriever import ARGUMENT_FAMILIES

        assert "intros" not in ARGUMENT_FAMILIES

    def test_simpl_not_in_families(self):
        from Poule.tactics.argument_retriever import ARGUMENT_FAMILIES

        assert "simpl" not in ARGUMENT_FAMILIES

    def test_auto_not_in_families(self):
        from Poule.tactics.argument_retriever import ARGUMENT_FAMILIES

        assert "auto" not in ARGUMENT_FAMILIES


# ---------------------------------------------------------------------------
# 3. ArgumentRetriever.retrieve() — core behavior
# ---------------------------------------------------------------------------


class TestArgumentRetriever:
    """spec §8.3: ArgumentRetriever retrieval logic."""

    def test_none_context_returns_empty(self):
        """spec §8.3: When pipeline_context is None, returns empty list."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        retriever = ArgumentRetriever(pipeline_context=None)
        result = retriever.retrieve("apply", "n + 0 = n", [])
        assert result == []

    def test_argument_free_family_returns_empty(self):
        """spec §8.3: Argument-free families return empty list."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        retriever = ArgumentRetriever(pipeline_context=ctx)
        assert retriever.retrieve("simpl", "n + 0 = n", []) == []
        assert retriever.retrieve("intros", "forall x, P x", []) == []
        assert retriever.retrieve("auto", "True", []) == []

    def test_apply_calls_search_by_type(self):
        """spec §8.3: apply strategy uses search_by_type with goal type."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        results = [
            _make_search_result("Nat.add_0_r", 0.82),
            _make_search_result("Nat.add_comm", 0.65),
        ]

        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type", return_value=results
        ) as mock_search:
            candidates = retriever.retrieve("apply", "n + 0 = n", [])
            mock_search.assert_called_once()
            call_args = mock_search.call_args
            assert call_args[0][0] is ctx  # pipeline_context
            assert call_args[0][1] == "n + 0 = n"  # goal_type

        assert len(candidates) >= 1
        assert candidates[0].name == "Nat.add_0_r"
        assert candidates[0].score == 0.82

    def test_exact_calls_search_by_type(self):
        """spec §8.3: exact strategy uses search_by_type."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        results = [_make_search_result("Nat.add_0_r", 0.9)]

        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type", return_value=results
        ):
            candidates = retriever.retrieve("exact", "n + 0 = n", [])

        assert len(candidates) == 1
        assert candidates[0].name == "Nat.add_0_r"

    def test_rewrite_filters_to_equalities(self):
        """spec §8.3: rewrite strategy filters results to equality lemmas."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        results = [
            _make_search_result("Nat.add_0_r", 0.82, "forall n, n + 0 = n"),
            _make_search_result("Nat.add_succ", 0.75, "forall n, nat -> nat"),
            _make_search_result("Nat.mul_comm", 0.65, "forall n m, n * m = m * n"),
        ]

        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type", return_value=results
        ):
            candidates = retriever.retrieve("rewrite", "n + 0 = n", [])

        # Only equality lemmas should be returned
        names = [c.name for c in candidates]
        assert "Nat.add_0_r" in names
        assert "Nat.mul_comm" in names
        assert "Nat.add_succ" not in names  # Not an equality

    def test_limit_respected(self):
        """spec §8.3: at most limit candidates returned."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        results = [
            _make_search_result(f"Lemma_{i}", 0.9 - i * 0.1)
            for i in range(10)
        ]

        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type", return_value=results
        ):
            candidates = retriever.retrieve("apply", "P x", [], limit=3)

        assert len(candidates) <= 3

    def test_results_sorted_by_score_descending(self):
        """spec §8.3: results sorted by score descending."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        results = [
            _make_search_result("Low", 0.3),
            _make_search_result("High", 0.9),
            _make_search_result("Mid", 0.6),
        ]

        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type", return_value=results
        ):
            candidates = retriever.retrieve("apply", "P x", [])

        scores = [c.score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_hypothesis_included_for_apply(self):
        """spec §8.3: hypotheses matching goal type are candidates for apply."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        hyps = [
            _make_hypothesis("H1", "n + 0 = n"),
            _make_hypothesis("H2", "nat"),
        ]

        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type", return_value=[]
        ):
            candidates = retriever.retrieve("apply", "n + 0 = n", hyps)

        names = [c.name for c in candidates]
        assert "H1" in names
        assert "H2" not in names  # Type doesn't match goal

    def test_hypothesis_included_for_rewrite(self):
        """spec §8.3: hypotheses containing = are candidates for rewrite."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        hyps = [
            _make_hypothesis("H1", "x = y"),
            _make_hypothesis("H2", "nat"),
        ]

        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type", return_value=[]
        ):
            candidates = retriever.retrieve("rewrite", "a + b = b + a", hyps)

        names = [c.name for c in candidates]
        assert "H1" in names
        assert "H2" not in names

    def test_hypothesis_priority_over_index(self):
        """spec §8.3: hypotheses take priority over index results (dedup)."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        hyps = [_make_hypothesis("H1", "n + 0 = n")]
        results = [_make_search_result("H1", 0.5)]  # Same name from index

        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type", return_value=results
        ):
            candidates = retriever.retrieve("apply", "n + 0 = n", hyps)

        h1_candidates = [c for c in candidates if c.name == "H1"]
        assert len(h1_candidates) == 1
        assert h1_candidates[0].score == 1.0  # Hypothesis score, not index score

    def test_retrieval_exception_returns_empty(self):
        """spec §8.3: exceptions from retrieval are caught, returns empty."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type",
            side_effect=RuntimeError("index corrupt"),
        ):
            candidates = retriever.retrieve("apply", "P x", [])

        assert candidates == []

    def test_unknown_family_returns_empty(self):
        """spec §8.3: unknown family names return empty."""
        from Poule.tactics.argument_retriever import ArgumentRetriever

        ctx = MagicMock()
        retriever = ArgumentRetriever(pipeline_context=ctx)
        with patch(
            "Poule.pipeline.search.search_by_type", return_value=[]
        ):
            assert retriever.retrieve("mythical_tactic", "P x", []) == []


# ---------------------------------------------------------------------------
# 4. set_retriever_context wiring (spec §8.4)
# ---------------------------------------------------------------------------


class TestSetRetrieverContext:
    """spec §8.4: set_retriever_context wires the pipeline context."""

    def test_set_retriever_context_enables_retrieval(self):
        """spec §8.4: after set_retriever_context, retriever has a context."""
        import Poule.tactics.suggest as suggest_mod

        # Reset singleton state
        suggest_mod._retriever = None
        suggest_mod._retriever_checked = False

        ctx = MagicMock()
        suggest_mod.set_retriever_context(ctx)

        retriever = suggest_mod._get_retriever()
        assert retriever is not None
        assert retriever._ctx is ctx

        # Clean up
        suggest_mod._retriever = None
        suggest_mod._retriever_checked = False

    def test_get_retriever_without_context_has_none_ctx(self):
        """spec §8.4: without set_retriever_context, retriever has None context."""
        import Poule.tactics.suggest as suggest_mod

        suggest_mod._retriever = None
        suggest_mod._retriever_checked = False

        retriever = suggest_mod._get_retriever()
        assert retriever is not None
        assert retriever._ctx is None

        # Clean up
        suggest_mod._retriever = None
        suggest_mod._retriever_checked = False
