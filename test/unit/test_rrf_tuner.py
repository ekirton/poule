"""TDD tests for the RRF tuner module — written before implementation.

Tests target:
  - extract_goal_type(proof_state_text) -> str
  - PrecomputedQuery dataclass
  - evaluate_cached(cached, k, weights, limit) -> float
  - RRFTuner.tune(val_data, ctx, output_dir, ...) -> RRFTuningResult
"""

from __future__ import annotations

import pytest

from Poule.fusion.rrf_tuner import (
    extract_goal_type,
    PrecomputedQuery,
    evaluate_cached,
    RRFTuner,
    RRFTuningResult,
)


# ===========================================================================
# 1. extract_goal_type
# ===========================================================================


class TestExtractGoalType:
    """Extract the focused goal's type from serialized proof state text.

    The format from serialize_goals is:
      hyp_name : hyp_type
      goal_type

    Multiple goals are separated by blank lines.
    """

    def test_single_goal_no_hypotheses(self):
        """A proof state with just a goal type, no hypotheses."""
        state = "forall n : nat, n + 0 = n"
        assert extract_goal_type(state) == "forall n : nat, n + 0 = n"

    def test_single_goal_with_hypotheses(self):
        """Hypotheses are 'name : type' lines; goal type is the last line."""
        state = "n : nat\nm : nat\nn + m = m + n"
        assert extract_goal_type(state) == "n + m = m + n"

    def test_multiple_goals_returns_first(self):
        """Multiple goals separated by blank lines; return first goal's type."""
        state = "n : nat\nn + 0 = n\n\nm : nat\nm + 0 = m"
        assert extract_goal_type(state) == "n + 0 = n"

    def test_empty_string(self):
        assert extract_goal_type("") == ""

    def test_hypothesis_with_colon_in_type(self):
        """Hypothesis types can contain colons (e.g., 'H : x : nat')."""
        state = "H : forall x : nat, x = x\nP x"
        assert extract_goal_type(state) == "P x"

    def test_single_line_is_goal_type(self):
        """A single line with no ' : ' is the goal type itself."""
        state = "True"
        assert extract_goal_type(state) == "True"


# ===========================================================================
# 2. PrecomputedQuery
# ===========================================================================


class TestPrecomputedQuery:
    """PrecomputedQuery holds cached channel results for a single query."""

    def test_construction(self):
        pq = PrecomputedQuery(
            structural=[("a", 0.9), ("b", 0.8)],
            mepo=[("b", 0.7), ("c", 0.6)],
            fts=[("c", 0.5)],
            ground_truth={"a", "c"},
        )
        assert pq.structural == [("a", 0.9), ("b", 0.8)]
        assert pq.ground_truth == {"a", "c"}


# ===========================================================================
# 3. evaluate_cached
# ===========================================================================


class TestEvaluateCached:
    """evaluate_cached runs weighted RRF over pre-computed channel results
    and computes mean Recall@limit."""

    def test_perfect_recall(self):
        """All ground truth premises appear in top-32 → Recall@32 = 1.0."""
        cached = [
            PrecomputedQuery(
                structural=[("a", 0.9), ("b", 0.8)],
                mepo=[("a", 0.7)],
                fts=[("b", 0.6)],
                ground_truth={"a"},
            ),
        ]
        weights = {"structural": 1.0, "mepo": 1.0, "fts": 1.0}
        result = evaluate_cached(cached, k=60, weights=weights, limit=32)
        assert result == pytest.approx(1.0)

    def test_zero_recall(self):
        """Ground truth not in any channel → Recall@32 = 0.0."""
        cached = [
            PrecomputedQuery(
                structural=[("x", 0.9)],
                mepo=[("y", 0.7)],
                fts=[("z", 0.6)],
                ground_truth={"missing"},
            ),
        ]
        weights = {"structural": 1.0, "mepo": 1.0, "fts": 1.0}
        result = evaluate_cached(cached, k=60, weights=weights, limit=32)
        assert result == pytest.approx(0.0)

    def test_partial_recall(self):
        """One of two queries has a hit → 0.5."""
        cached = [
            PrecomputedQuery(
                structural=[("a", 0.9)],
                mepo=[],
                fts=[],
                ground_truth={"a"},
            ),
            PrecomputedQuery(
                structural=[("b", 0.9)],
                mepo=[],
                fts=[],
                ground_truth={"missing"},
            ),
        ]
        weights = {"structural": 1.0, "mepo": 1.0, "fts": 1.0}
        result = evaluate_cached(cached, k=60, weights=weights, limit=32)
        assert result == pytest.approx(0.5)

    def test_limit_excludes_lower_ranked(self):
        """With limit=1, only the top result counts."""
        # "b" is in both channels → highest RRF score → rank 1
        # "a" is only in structural → rank 2
        cached = [
            PrecomputedQuery(
                structural=[("a", 0.9), ("b", 0.8)],
                mepo=[("b", 0.7)],
                fts=[],
                ground_truth={"a"},  # "a" is at rank 2 after RRF
            ),
        ]
        weights = {"structural": 1.0, "mepo": 1.0, "fts": 1.0}
        result = evaluate_cached(cached, k=60, weights=weights, limit=1)
        assert result == pytest.approx(0.0)

    def test_empty_cached_returns_zero(self):
        weights = {"structural": 1.0, "mepo": 1.0, "fts": 1.0}
        result = evaluate_cached([], k=60, weights=weights, limit=32)
        assert result == pytest.approx(0.0)

    def test_weights_affect_ranking(self):
        """Weighting one channel heavily changes which items make top-k."""
        # Without weighting: "a" (structural rank 1) and "b" (mepo rank 1)
        # both score 1/61. With structural weight=0, only mepo contributes.
        cached = [
            PrecomputedQuery(
                structural=[("a", 0.9)],
                mepo=[("b", 0.7)],
                fts=[],
                ground_truth={"b"},
            ),
        ]
        # With structural silenced, only mepo contributes → "b" is rank 1
        weights = {"structural": 0.0, "mepo": 1.0, "fts": 1.0}
        result = evaluate_cached(cached, k=60, weights=weights, limit=1)
        assert result == pytest.approx(1.0)


# ===========================================================================
# 4. RRFTuner
# ===========================================================================


class TestRRFTuner:
    """RRFTuner.tune orchestrates Optuna to find optimal k and weights."""

    def test_returns_rrf_tuning_result(self, tmp_path):
        """Tuner returns an RRFTuningResult with expected fields."""
        cached = [
            PrecomputedQuery(
                structural=[("a", 0.9), ("b", 0.8)],
                mepo=[("a", 0.7), ("c", 0.6)],
                fts=[("b", 0.5)],
                ground_truth={"a"},
            ),
        ] * 10  # 10 identical queries for stability

        result = RRFTuner.tune(
            cached_results=cached,
            output_dir=tmp_path,
            n_trials=3,
            channel_names=["structural", "mepo", "fts"],
        )

        assert isinstance(result, RRFTuningResult)
        assert 1 <= result.best_k <= 100
        assert 0.0 <= result.best_recall_32 <= 1.0
        assert result.n_trials == 3
        assert (tmp_path / "rrf-study.db").exists()
        assert isinstance(result.best_weights, dict)
        assert set(result.best_weights.keys()) == {"structural", "mepo", "fts"}

    def test_resume_continues_study(self, tmp_path):
        """Resume=True continues an existing study."""
        cached = [
            PrecomputedQuery(
                structural=[("a", 0.9)],
                mepo=[],
                fts=[],
                ground_truth={"a"},
            ),
        ] * 10

        result1 = RRFTuner.tune(
            cached_results=cached,
            output_dir=tmp_path,
            n_trials=2,
            channel_names=["structural", "mepo", "fts"],
        )
        result2 = RRFTuner.tune(
            cached_results=cached,
            output_dir=tmp_path,
            n_trials=2,
            channel_names=["structural", "mepo", "fts"],
            resume=True,
        )
        # Second run should have completed 2 additional trials
        assert result2.n_trials == 4


class TestRRFTuningResult:
    """RRFTuningResult dataclass fields."""

    def test_construction(self):
        result = RRFTuningResult(
            best_k=45,
            best_weights={"structural": 1.2, "mepo": 0.8, "fts": 1.0},
            best_recall_32=0.75,
            n_trials=30,
            study_path="/tmp/study.db",
            all_trials=[],
        )
        assert result.best_k == 45
        assert result.best_weights["mepo"] == 0.8
