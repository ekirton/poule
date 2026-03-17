"""Few-shot context retrieval from extracted training data.

Spec: specification/proof-search-engine.md §4.9
"""

from __future__ import annotations

from typing import Any, Optional

from poule.session.types import ProofState


def retrieve_few_shot(
    proof_state: ProofState,
    training_data_index: Optional[Any] = None,
    k: int = 5,
) -> list[tuple[str, str]]:
    """Retrieve (state_summary, tactic) pairs from training data.

    When no training data index is available, returns an empty list silently.
    Returns at most k results.
    """
    if training_data_index is None:
        return []

    results = training_data_index.search(proof_state)
    return results[:k]
