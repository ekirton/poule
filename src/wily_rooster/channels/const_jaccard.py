"""Const Name Jaccard channel.

Lightweight structural similarity based on Jaccard similarity of constant
name sets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wily_rooster.models.tree import ExprTree

from wily_rooster.channels.mepo import extract_consts


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Return |A & B| / |A | B|; 0.0 when both empty."""
    union = set_a | set_b
    if not union:
        return 0.0
    return float(len(set_a & set_b)) / float(len(union))


def const_jaccard_rank(
    query_tree: ExprTree,
    candidates: list[int],
    declaration_symbols: dict[int, set[str]],
) -> list[tuple[int, float]]:
    """Score each candidate by Jaccard similarity of constant name sets.

    Returns (decl_id, jaccard_score) for every candidate.
    """
    query_consts = extract_consts(query_tree)
    results: list[tuple[int, float]] = []
    for cid in candidates:
        cand_syms = declaration_symbols.get(cid, set())
        score = jaccard_similarity(query_consts, cand_syms)
        results.append((cid, score))
    return results
