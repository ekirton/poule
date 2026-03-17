"""Hard negative sampling from accessible premises."""

from __future__ import annotations

import random


def sample_hard_negatives(
    state: str,
    positive_premises: set[str],
    accessible_premises: set[str],
    k: int = 3,
    corpus: set[str] | None = None,
) -> list[str]:
    candidates = accessible_premises - positive_premises

    if not candidates and corpus is not None:
        candidates = corpus - positive_premises

    candidates_list = sorted(candidates)  # sorted for determinism before sampling
    if len(candidates_list) <= k:
        return candidates_list

    return random.sample(candidates_list, k)
