"""Metric fusion: collapse match, structural score, and Reciprocal Rank Fusion.

Implements the fusion strategies defined in specification/fusion.md.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from Poule.models.labels import (
    LAbs,
    LApp,
    LCase,
    LCoFix,
    LConst,
    LConstruct,
    LCseVar,
    LFix,
    LInd,
    LLet,
    LPrimitive,
    LProd,
    LProj,
    LRel,
    LSort,
    NodeLabel,
)
from Poule.models.tree import ExprTree, TreeNode


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

_CATEGORY_MAP: dict[type, str] = {
    LAbs: "Binder",
    LProd: "Binder",
    LLet: "Binder",
    LApp: "Application",
    LConst: "ConstantRef",
    LInd: "ConstantRef",
    LConstruct: "ConstantRef",
    LRel: "Variable",
    LCseVar: "Variable",
    LSort: "Sort",
    LCase: "Control",
    LFix: "Control",
    LCoFix: "Control",
    LProj: "Projection",
    LPrimitive: "Primitive",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def clamp_score(score: float) -> float:
    """Clamp *score* to [0.0, 1.0]."""
    return max(0.0, min(1.0, score))


def node_category(label: NodeLabel) -> str:
    """Return the category string for a given node label."""
    return _CATEGORY_MAP[type(label)]


def collapse_match(tree_a: ExprTree, tree_b: ExprTree) -> float:
    """Recursive structural similarity between two expression trees.

    Returns a float in [0.0, 1.0].
    """
    score_sum = _collapse_node(tree_a.root, tree_b.root)
    denominator = max(tree_a.node_count, tree_b.node_count)
    if denominator == 0:
        return 0.0
    return score_sum / denominator


def structural_score(
    wl: float,
    ted: float,
    cm: float,
    cj: float,
    *,
    has_ted: bool,
) -> float:
    """Weighted sum of fine-ranking channel scores.

    When *has_ted* is True the TED weight is included; otherwise the weight
    is redistributed across the remaining channels.
    """
    if has_ted:
        return 0.15 * wl + 0.40 * ted + 0.30 * cm + 0.15 * cj
    return 0.25 * wl + 0.50 * cm + 0.25 * cj


def rrf_fuse(
    ranked_lists: Sequence[Sequence],
    k: int = 60,
) -> list[tuple]:
    """Reciprocal Rank Fusion over multiple ranked lists.

    Each element of *ranked_lists* is a sequence of ``(decl_id, score)`` pairs
    ordered by score descending.  Returns ``[(decl_id, rrf_score), ...]``
    sorted by RRF score descending.
    """
    scores: defaultdict = defaultdict(float)
    for ranked in ranked_lists:
        for rank_0, item in enumerate(ranked):
            decl_id = item[0] if isinstance(item, tuple) else item
            scores[decl_id] += 1.0 / (k + rank_0 + 1)  # 1-based rank
    # Sort descending by score, then by insertion order for ties (stable sort)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def weighted_rrf_fuse(
    ranked_lists: Sequence[Sequence],
    weights: Sequence[float],
    k: int = 60,
) -> list[tuple]:
    """Weighted Reciprocal Rank Fusion over multiple ranked lists.

    Like ``rrf_fuse`` but each channel *c* is scaled by ``weights[c]``:

        score(d) = Σ_c  w_c / (k + rank_c(d))

    A weight of 0.0 silences a channel entirely.  Returns
    ``[(decl_id, weighted_rrf_score), ...]`` sorted descending.
    """
    scores: defaultdict = defaultdict(float)
    for ranked, weight in zip(ranked_lists, weights):
        if weight == 0.0:
            continue
        for rank_0, item in enumerate(ranked):
            decl_id = item[0] if isinstance(item, tuple) else item
            scores[decl_id] += weight / (k + rank_0 + 1)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _count_subtree(node: TreeNode) -> int:
    """Count nodes in a subtree (iterative)."""
    count = 0
    stack = [node]
    while stack:
        n = stack.pop()
        count += 1
        stack.extend(n.children)
    return count


def _is_sort_leaf(node: TreeNode) -> bool:
    """True if *node* is a bare LSort with no children."""
    return isinstance(node.label, LSort) and not node.children


def _collapse_node(a: TreeNode, b: TreeNode) -> float:
    """Return the sum of node-level scores for the subtree pair."""
    cat_a = node_category(a.label)
    cat_b = node_category(b.label)

    # Sort-leaf binder wildcard: when both roots are LProd with 2 children
    # and either side's binder-type child is a bare LSort leaf, treat the
    # binder types as a perfect match (spec: fusion.md §4.3).
    if (
        isinstance(a.label, LProd)
        and isinstance(b.label, LProd)
        and len(a.children) == 2
        and len(b.children) == 2
        and (_is_sort_leaf(a.children[0]) or _is_sort_leaf(b.children[0]))
    ):
        type_score = float(max(_count_subtree(a.children[0]),
                               _count_subtree(b.children[0])))
        body_score = _collapse_node(a.children[1], b.children[1])
        return 1.0 + type_score + body_score

    # Universal sort-leaf wildcard: a bare LSort (from parser's _ token)
    # matches any subtree, contributing the other subtree's full node count.
    if _is_sort_leaf(a) and not _is_sort_leaf(b):
        return float(_count_subtree(b))
    if _is_sort_leaf(b) and not _is_sort_leaf(a):
        return float(_count_subtree(a))

    if cat_a != cat_b:
        # Different category: 0.0, no recursion.
        return 0.0

    # Same category — determine node score.
    if type(a.label) is type(b.label):
        node_score = 1.0
    else:
        node_score = 0.5

    # Recurse into children pairwise.
    paired = min(len(a.children), len(b.children))
    child_score = 0.0
    for i in range(paired):
        child_score += _collapse_node(a.children[i], b.children[i])

    return node_score + child_score
