"""Tactic argument retrieval from the search index.

Spec: specification/neural-training.md §8.3, §8.4.

Maps tactic family predictions to retrieval strategies that find
specific lemma candidates from the search index.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArgumentCandidate:
    """A candidate lemma argument for a tactic suggestion."""

    name: str
    score: float


# ---------------------------------------------------------------------------
# Family → strategy mapping
# ---------------------------------------------------------------------------

ARGUMENT_FAMILIES: dict[str, str] = {
    "apply": "type_match",
    "exact": "type_match",
    "rewrite": "rewrite",
}

# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


class ArgumentRetriever:
    """Resolves tactic family predictions into full tactic suggestions.

    Queries the retrieval pipeline for lemma candidates based on the
    tactic family's retrieval strategy.
    """

    def __init__(self, pipeline_context: Any | None) -> None:
        self._ctx = pipeline_context

    def retrieve(
        self,
        family: str,
        goal_type: str,
        hypotheses: list,
        limit: int = 5,
    ) -> list[ArgumentCandidate]:
        """Retrieve argument candidates for a tactic family.

        Returns at most ``limit`` candidates sorted by score descending.
        Returns an empty list for argument-free families or when no
        pipeline context is available.
        """
        if self._ctx is None:
            return []

        strategy = ARGUMENT_FAMILIES.get(family)
        if strategy is None:
            return []

        try:
            if strategy == "type_match":
                return self._type_match(goal_type, hypotheses, limit)
            elif strategy == "rewrite":
                return self._rewrite(goal_type, hypotheses, limit)
            return []
        except Exception:
            logger.warning(
                "Argument retrieval failed for family=%s", family, exc_info=True
            )
            return []

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------

    def _type_match(
        self, goal_type: str, hypotheses: list, limit: int
    ) -> list[ArgumentCandidate]:
        """Retrieve lemmas whose type matches the goal (for apply/exact)."""
        from Poule.pipeline.search import search_by_type

        results = search_by_type(self._ctx, goal_type, limit=limit * 2)

        # Build candidate dict: name → score (index results first)
        candidates: dict[str, float] = {}
        for r in results:
            candidates[r.name] = r.score

        # Hypotheses whose type matches the goal get score 1.0
        for h in hypotheses:
            if h.type.strip() == goal_type.strip():
                candidates[h.name] = 1.0  # Overwrite index score

        return self._top_k(candidates, limit)

    def _rewrite(
        self, goal_type: str, hypotheses: list, limit: int
    ) -> list[ArgumentCandidate]:
        """Retrieve equality lemmas for rewrite."""
        from Poule.pipeline.search import search_by_type

        results = search_by_type(self._ctx, goal_type, limit=limit * 3)

        # Filter to equality lemmas
        candidates: dict[str, float] = {}
        for r in results:
            if "=" in r.statement:
                candidates[r.name] = r.score

        # Hypotheses containing = are candidates
        for h in hypotheses:
            if "=" in h.type:
                candidates[h.name] = 1.0

        return self._top_k(candidates, limit)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _top_k(
        candidates: dict[str, float], limit: int
    ) -> list[ArgumentCandidate]:
        """Sort candidates by score descending and return top-k."""
        sorted_items = sorted(candidates.items(), key=lambda x: x[1], reverse=True)
        return [
            ArgumentCandidate(name=name, score=score)
            for name, score in sorted_items[:limit]
        ]
