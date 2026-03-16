"""MePo symbol-relevance channel.

Iterative symbol-overlap retrieval inspired by Sledgehammer's MePo
(Meng-Paulson) relevance filter.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wily_rooster.models.tree import ExprTree

from wily_rooster.models.labels import LConst, LInd, LConstruct


def symbol_weight(freq: int) -> float:
    """Return 1.0 + 2.0 / log2(freq + 1). Rare symbols receive higher weight."""
    return 1.0 + 2.0 / math.log2(freq + 1)


def mepo_relevance(
    candidate_symbols: set[str],
    working_set: set[str],
    symbol_frequencies: dict[str, int],
) -> float:
    """Compute weighted overlap normalized by candidate's total weight.

    Missing symbols (not in symbol_frequencies) are treated as freq=1.
    """
    if not candidate_symbols:
        return 0.0

    def _freq(s: str) -> int:
        return symbol_frequencies.get(s, 1)

    overlap = sum(symbol_weight(_freq(s)) for s in candidate_symbols & working_set)
    total = sum(symbol_weight(_freq(s)) for s in candidate_symbols)

    if total == 0.0:
        return 0.0
    return overlap / total


def mepo_select(
    query_symbols: set[str],
    inverted_index: dict[str, set[int]],
    symbol_frequencies: dict[str, int],
    declaration_symbols: dict[int, set[str]],
    p: float = 0.6,
    c: float = 2.4,
    max_rounds: int = 5,
) -> list[tuple[int, float]]:
    """Iterative MePo selection with decaying threshold.

    Returns (decl_id, relevance_score) pairs ordered by relevance descending.
    """
    if not query_symbols:
        return []

    S = set(query_symbols)
    t = p
    selected: dict[int, float] = {}

    for _ in range(max_rounds):
        # Find candidates reachable from current working set S
        candidates: set[int] = set()
        for sym in S:
            candidates |= inverted_index.get(sym, set())
        # Remove already-selected
        candidates -= set(selected.keys())

        # Score and select
        new_selected: dict[int, float] = {}
        for cid in candidates:
            csyms = declaration_symbols.get(cid, set())
            score = mepo_relevance(csyms, S, symbol_frequencies)
            if score >= t:
                new_selected[cid] = score

        if not new_selected:
            break

        # Batch expansion: add selected candidates' symbols to S after scoring
        selected.update(new_selected)
        for cid in new_selected:
            S |= declaration_symbols.get(cid, set())

        # Decay threshold
        t *= 1.0 / c

    # Return sorted by relevance descending
    return sorted(selected.items(), key=lambda x: x[1], reverse=True)


def extract_consts(tree: ExprTree) -> set[str]:
    """Extract fully qualified names from LConst, LInd, LConstruct nodes."""
    from wily_rooster.models.tree import TreeNode

    result: set[str] = set()

    def _walk(node: TreeNode) -> None:
        label = node.label
        if isinstance(label, (LConst, LInd)):
            result.add(label.name)
        elif isinstance(label, LConstruct):
            result.add(label.name)
        for child in node.children:
            _walk(child)

    _walk(tree.root)
    return result
