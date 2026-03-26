"""TDD tests for the fusion module — written before implementation.

Tests target the public API defined in specification/fusion.md:
  - clamp_score(score) -> float in [0.0, 1.0]
  - node_category(label) -> str (category name)
  - collapse_match(tree_a, tree_b) -> float in [0.0, 1.0]
  - structural_score(wl, ted, cm, cj, has_ted) -> float
  - rrf_fuse(ranked_lists, k=60) -> list of (decl_id, rrf_score) sorted desc

Implementation will live in src/poule/fusion/fusion.py.
"""

from __future__ import annotations

import pytest

from Poule.fusion.fusion import (
    clamp_score,
    node_category,
    collapse_match,
    structural_score,
    rrf_fuse,
    weighted_rrf_fuse,
)
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
)
from Poule.models.enums import SortKind
from Poule.models.tree import TreeNode, ExprTree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def leaf(label) -> TreeNode:
    """Create a leaf TreeNode."""
    return TreeNode(label=label, children=[])


def node(label, children) -> TreeNode:
    """Create an interior TreeNode with children."""
    return TreeNode(label=label, children=children)


def _count_nodes(tn: TreeNode) -> int:
    """Recursively count nodes in a TreeNode."""
    return 1 + sum(_count_nodes(c) for c in tn.children)


def tree(root: TreeNode) -> ExprTree:
    """Create an ExprTree from a root, computing node_count automatically."""
    return ExprTree(root=root, node_count=_count_nodes(root))


# ===========================================================================
# 1. clamp_score
# ===========================================================================


class TestClampScore:
    """clamp_score returns max(0.0, min(1.0, score))."""

    def test_in_range_unchanged(self):
        assert clamp_score(0.5) == 0.5

    def test_negative_clamped_to_zero(self):
        assert clamp_score(-0.1) == 0.0

    def test_above_one_clamped_to_one(self):
        assert clamp_score(1.5) == 1.0

    def test_zero_boundary(self):
        assert clamp_score(0.0) == 0.0

    def test_one_boundary(self):
        assert clamp_score(1.0) == 1.0


# ===========================================================================
# 2. node_category
# ===========================================================================


class TestNodeCategory:
    """node_category maps each NodeLabel to the correct category string."""

    # Binder: LAbs, LProd, LLet
    def test_labs_is_binder(self):
        assert node_category(LAbs()) == "Binder"

    def test_lprod_is_binder(self):
        assert node_category(LProd()) == "Binder"

    def test_llet_is_binder(self):
        assert node_category(LLet()) == "Binder"

    # Application: LApp
    def test_lapp_is_application(self):
        assert node_category(LApp()) == "Application"

    # ConstantRef: LConst, LInd, LConstruct
    def test_lconst_is_constant_ref(self):
        assert node_category(LConst("Stdlib.Init.Nat.add")) == "ConstantRef"

    def test_lind_is_constant_ref(self):
        assert node_category(LInd("Stdlib.Init.Datatypes.nat")) == "ConstantRef"

    def test_lconstruct_is_constant_ref(self):
        assert node_category(LConstruct("Stdlib.Init.Datatypes.nat", 0)) == "ConstantRef"

    # Variable: LRel, LCseVar
    def test_lrel_is_variable(self):
        assert node_category(LRel(0)) == "Variable"

    def test_lcsevar_is_variable(self):
        assert node_category(LCseVar(1)) == "Variable"

    # Sort: LSort
    def test_lsort_is_sort(self):
        assert node_category(LSort(SortKind.PROP)) == "Sort"

    # Control: LCase, LFix, LCoFix
    def test_lcase_is_control(self):
        assert node_category(LCase("nat")) == "Control"

    def test_lfix_is_control(self):
        assert node_category(LFix(0)) == "Control"

    def test_lcofix_is_control(self):
        assert node_category(LCoFix(0)) == "Control"

    # Projection: LProj
    def test_lproj_is_projection(self):
        assert node_category(LProj("proj_name")) == "Projection"

    # Primitive: LPrimitive
    def test_lprimitive_is_primitive(self):
        assert node_category(LPrimitive(42)) == "Primitive"


# ===========================================================================
# 3-7. collapse_match
# ===========================================================================


class TestCollapseMatchIdenticalTrees:
    """Test 3: Identical trees should yield 1.0."""

    def test_single_leaf(self):
        t = tree(leaf(LConst("a")))
        assert collapse_match(t, t) == pytest.approx(1.0)

    def test_interior_tree(self):
        root = node(LProd(), [leaf(LSort(SortKind.PROP)), leaf(LRel(0))])
        t = tree(root)
        assert collapse_match(t, t) == pytest.approx(1.0)


class TestCollapseMatchSameCategoryRoots:
    """Test 4: Same category roots, same children -> high score."""

    def test_same_category_different_labels_with_matching_children(self):
        # LAbs and LProd are both Binder category.
        # tree_a: LAbs -> [LConst("a")]
        # tree_b: LProd -> [LInd("b"), LRel(0)]
        # Roots: same category (Binder), different label -> 0.5 for root node.
        # For children: tree_a has 1 child, tree_b has 2.
        # Pairwise by position: child 0 of a (LConst) vs child 0 of b (LInd)
        #   -> same category (ConstantRef), same label type? No, different label.
        #   -> same category -> 0.5 (leaves, no further recursion).
        # Unmatched child 1 of b -> 0.
        # Node scores: root 0.5, child-pair 0.5, unmatched 0.0
        # Total node scores = 0.5 + 0.5 = 1.0
        # max(nc_a=2, nc_b=3) = 3
        # Final = 1.0 / 3 = 0.333...
        tree_a = tree(node(LAbs(), [leaf(LConst("a"))]))
        tree_b = tree(node(LProd(), [leaf(LInd("b")), leaf(LRel(0))]))
        result = collapse_match(tree_a, tree_b)
        assert result == pytest.approx(1.0 / 3.0, abs=1e-6)

    def test_same_label_roots_matching_children(self):
        # Both LProd with matching leaf children (same category).
        # LProd -> [LSort(PROP), LRel(0)]  vs  LProd -> [LSort(SET), LRel(1)]
        # Root: same label -> 1.0
        # Child 0: LSort vs LSort -> same label -> 1.0
        # Child 1: LRel vs LRel -> same label -> 1.0
        # Total = 1.0 + 1.0 + 1.0 = 3.0
        # max(nc_a=3, nc_b=3) = 3
        # Final = 3.0 / 3.0 = 1.0
        tree_a = tree(node(LProd(), [leaf(LSort(SortKind.PROP)), leaf(LRel(0))]))
        tree_b = tree(node(LProd(), [leaf(LSort(SortKind.SET)), leaf(LRel(1))]))
        result = collapse_match(tree_a, tree_b)
        assert result == pytest.approx(1.0)


class TestCollapseMatchDifferentCategoryRoots:
    """Test 5: Different category roots -> 0.0."""

    def test_app_vs_prod(self):
        # LApp (Application) vs LProd (Binder) -> different categories.
        tree_a = tree(node(LApp(), [leaf(LConst("a")), leaf(LRel(0))]))
        tree_b = tree(node(LProd(), [leaf(LSort(SortKind.PROP)), leaf(LRel(0))]))
        assert collapse_match(tree_a, tree_b) == pytest.approx(0.0)

    def test_const_leaf_vs_sort_leaf(self):
        # LConst (ConstantRef) vs LSort (Sort) -> different categories.
        tree_a = tree(leaf(LConst("a")))
        tree_b = tree(leaf(LSort(SortKind.PROP)))
        assert collapse_match(tree_a, tree_b) == pytest.approx(0.0)


class TestCollapseMatchDifferentChildCounts:
    """Test 6: Different child counts -> unmatched children score 0."""

    def test_one_vs_three_children(self):
        # LCase("nat") with 1 child vs LCase("nat") with 3 children.
        # Same label -> 1.0 for root.
        # Pairwise: child 0 matches. Children 1,2 of b are unmatched -> 0.
        # Root: 1.0, child 0 pair: LConst("a") vs LConst("a") -> same label -> 1.0
        # Unmatched: 0.0, 0.0
        # Total = 1.0 + 1.0 = 2.0
        # max(nc_a=2, nc_b=4) = 4
        # Final = 2.0 / 4.0 = 0.5
        tree_a = tree(node(LCase("nat"), [leaf(LConst("a"))]))
        tree_b = tree(
            node(
                LCase("nat"),
                [leaf(LConst("a")), leaf(LConst("b")), leaf(LConst("c"))],
            )
        )
        result = collapse_match(tree_a, tree_b)
        assert result == pytest.approx(0.5)


class TestCollapseMatchMixedLevels:
    """Test 7: Mixed match levels across a deeper tree."""

    def test_mixed_match(self):
        # tree_a: LProd -> [LConst("a"), LProd -> [LRel(0), LRel(1)]]
        # tree_b: LProd -> [LInd("b"),   LProd -> [LRel(0), LSort(PROP)]]
        #
        # Root: LProd == LProd -> 1.0
        # Child 0: LConst("a") vs LInd("b") -> same category (ConstantRef) -> 0.5
        # Child 1: LProd vs LProd -> same label -> 1.0
        #   Grandchild 0: LRel(0) vs LRel(0) -> same label -> 1.0
        #   Grandchild 1: LRel(1) vs LSort(PROP) -> diff category -> 0.0
        # Total node scores = 1.0 + 0.5 + 1.0 + 1.0 + 0.0 = 3.5
        # Both trees: 5 nodes each -> max(5,5) = 5
        # Final = 3.5 / 5.0 = 0.7
        tree_a = tree(
            node(
                LProd(),
                [
                    leaf(LConst("a")),
                    node(LProd(), [leaf(LRel(0)), leaf(LRel(1))]),
                ],
            )
        )
        tree_b = tree(
            node(
                LProd(),
                [
                    leaf(LInd("b")),
                    node(LProd(), [leaf(LRel(0)), leaf(LSort(SortKind.PROP))]),
                ],
            )
        )
        result = collapse_match(tree_a, tree_b)
        assert result == pytest.approx(0.7)


# ===========================================================================
# 8-11. structural_score
# ===========================================================================


class TestStructuralScoreWithTED:
    """Test 8: structural_score with has_ted=True uses TED weights."""

    def test_spec_example(self):
        # 0.15*0.8 + 0.40*0.9 + 0.30*0.7 + 0.15*0.6
        # = 0.12 + 0.36 + 0.21 + 0.09 = 0.78
        result = structural_score(
            wl=0.8, ted=0.9, cm=0.7, cj=0.6, has_ted=True
        )
        assert result == pytest.approx(0.78)


class TestStructuralScoreWithoutTED:
    """Test 9: structural_score with has_ted=False omits TED."""

    def test_spec_example(self):
        # 0.25*0.8 + 0.50*0.7 + 0.25*0.6
        # = 0.20 + 0.35 + 0.15 = 0.70
        result = structural_score(
            wl=0.8, ted=0.0, cm=0.7, cj=0.6, has_ted=False
        )
        assert result == pytest.approx(0.70)


class TestStructuralScoreAllZeros:
    """Test 10: All zero inputs -> 0.0."""

    def test_with_ted(self):
        assert structural_score(0.0, 0.0, 0.0, 0.0, has_ted=True) == pytest.approx(
            0.0
        )

    def test_without_ted(self):
        assert structural_score(0.0, 0.0, 0.0, 0.0, has_ted=False) == pytest.approx(
            0.0
        )


class TestStructuralScoreAllOnes:
    """Test 11: All one inputs -> 1.0."""

    def test_with_ted(self):
        assert structural_score(1.0, 1.0, 1.0, 1.0, has_ted=True) == pytest.approx(
            1.0
        )

    def test_without_ted(self):
        assert structural_score(1.0, 1.0, 1.0, 1.0, has_ted=False) == pytest.approx(
            1.0
        )


# ===========================================================================
# 12-16. rrf_fuse
# ===========================================================================


class TestRrfFuseSpecExample:
    """Test 12: Spec example — 2 lists, 4 items, check order [d2, d3, d1, d4]."""

    def test_two_channel_example(self):
        # List A: [d1 (rank 1), d2 (rank 2), d3 (rank 3)]
        # List B: [d2 (rank 1), d3 (rank 2), d4 (rank 3)]
        # d1: 1/(60+1) = 0.016393...
        # d2: 1/(60+2) + 1/(60+1) = 0.016129... + 0.016393... = 0.032522...
        # d3: 1/(60+3) + 1/(60+2) = 0.015873... + 0.016129... = 0.032002...
        # d4: 1/(60+3) = 0.015873...
        list_a = ["d1", "d2", "d3"]
        list_b = ["d2", "d3", "d4"]

        results = rrf_fuse([list_a, list_b], k=60)

        # Check ordering: d2, d3, d1, d4
        result_ids = [r[0] for r in results]
        assert result_ids == ["d2", "d3", "d1", "d4"]

        # Check scores
        scores = {r[0]: r[1] for r in results}
        assert scores["d1"] == pytest.approx(1 / 61, abs=1e-6)
        assert scores["d2"] == pytest.approx(1 / 62 + 1 / 61, abs=1e-6)
        assert scores["d3"] == pytest.approx(1 / 63 + 1 / 62, abs=1e-6)
        assert scores["d4"] == pytest.approx(1 / 63, abs=1e-6)


class TestRrfFuseSingleList:
    """Test 13: Single list -> ranks preserved."""

    def test_single_list_preserves_order(self):
        results = rrf_fuse([["a", "b", "c"]], k=60)
        result_ids = [r[0] for r in results]
        assert result_ids == ["a", "b", "c"]

        scores = {r[0]: r[1] for r in results}
        assert scores["a"] == pytest.approx(1 / 61, abs=1e-6)
        assert scores["b"] == pytest.approx(1 / 62, abs=1e-6)
        assert scores["c"] == pytest.approx(1 / 63, abs=1e-6)


class TestRrfFuseEmptyListInput:
    """Test 14: Empty list among inputs -> no contribution from that channel."""

    def test_empty_list_ignored(self):
        results = rrf_fuse([["a", "b"], []], k=60)
        result_ids = [r[0] for r in results]
        assert result_ids == ["a", "b"]

        scores = {r[0]: r[1] for r in results}
        assert scores["a"] == pytest.approx(1 / 61, abs=1e-6)
        assert scores["b"] == pytest.approx(1 / 62, abs=1e-6)


class TestRrfFuseAllEmpty:
    """Test 15: All lists empty -> empty result."""

    def test_all_empty(self):
        assert rrf_fuse([[], []], k=60) == []

    def test_no_lists(self):
        assert rrf_fuse([], k=60) == []


class TestRrfFuseItemInAllLists:
    """Test 16: Item in all lists gets highest score."""

    def test_item_in_all_three_lists_beats_single(self):
        # x appears at rank 1 in all 3 lists; y appears at rank 1 in only 1 list.
        results = rrf_fuse([["x", "y"], ["x"], ["x"]], k=60)
        scores = {r[0]: r[1] for r in results}
        assert scores["x"] == pytest.approx(3 * (1 / 61), abs=1e-6)
        assert scores["y"] == pytest.approx(1 / 62, abs=1e-6)
        # x should be ranked first
        assert results[0][0] == "x"


# ===========================================================================
# 17. rrf_fuse with (decl_id, score) pairs per spec §4.5
# ===========================================================================


class TestRrfFuseWithScoredPairs:
    """Spec §4.5: ranked_lists contains (decl_id, score) pairs ordered by
    score descending.  rrf_fuse must extract decl_id from each pair and
    compute RRF scores based on rank position.

    Existing tests 12-16 pass flat ID lists.  These tests verify the
    spec-required input format: lists of (decl_id, score) tuples."""

    def test_two_channels_with_scored_pairs(self):
        """Same as spec example (test 12), but using (decl_id, score) pairs
        as the spec requires.

        List A: [(d1, 0.9), (d2, 0.8), (d3, 0.7)]
        List B: [(d2, 0.95), (d3, 0.85), (d4, 0.75)]

        Expected RRF scores (k=60):
        d1: 1/(60+1) = 0.016393
        d2: 1/(60+2) + 1/(60+1) = 0.032522
        d3: 1/(60+3) + 1/(60+2) = 0.032002
        d4: 1/(60+3) = 0.015873

        Order: [d2, d3, d1, d4]
        """
        list_a = [("d1", 0.9), ("d2", 0.8), ("d3", 0.7)]
        list_b = [("d2", 0.95), ("d3", 0.85), ("d4", 0.75)]

        results = rrf_fuse([list_a, list_b], k=60)

        result_ids = [r[0] for r in results]
        assert result_ids == ["d2", "d3", "d1", "d4"]

        scores = {r[0]: r[1] for r in results}
        assert scores["d1"] == pytest.approx(1 / 61, abs=1e-6)
        assert scores["d2"] == pytest.approx(1 / 62 + 1 / 61, abs=1e-6)
        assert scores["d3"] == pytest.approx(1 / 63 + 1 / 62, abs=1e-6)
        assert scores["d4"] == pytest.approx(1 / 63, abs=1e-6)

    def test_single_channel_scored_pairs(self):
        """Single list of (decl_id, score) pairs preserves rank order."""
        results = rrf_fuse([
            [("a", 0.9), ("b", 0.7), ("c", 0.5)],
        ], k=60)

        result_ids = [r[0] for r in results]
        assert result_ids == ["a", "b", "c"]

        scores = {r[0]: r[1] for r in results}
        assert scores["a"] == pytest.approx(1 / 61, abs=1e-6)
        assert scores["b"] == pytest.approx(1 / 62, abs=1e-6)
        assert scores["c"] == pytest.approx(1 / 63, abs=1e-6)

    def test_mixed_integer_decl_ids(self):
        """rrf_fuse must work when decl_ids are integers (as returned by
        score_candidates and mepo_select)."""
        list_a = [(1, 0.9), (2, 0.8)]
        list_b = [(2, 0.95), (3, 0.85)]

        results = rrf_fuse([list_a, list_b], k=60)

        result_ids = [r[0] for r in results]
        # decl_id 2 appears in both lists → highest RRF score
        assert result_ids[0] == 2

        scores = {r[0]: r[1] for r in results}
        assert scores[2] == pytest.approx(1 / 62 + 1 / 61, abs=1e-6)
        assert scores[1] == pytest.approx(1 / 61, abs=1e-6)
        assert scores[3] == pytest.approx(1 / 62, abs=1e-6)

    def test_empty_scored_list_contributes_nothing(self):
        """An empty list among scored-pair lists contributes nothing."""
        results = rrf_fuse([
            [("a", 0.9), ("b", 0.7)],
            [],
        ], k=60)

        result_ids = [r[0] for r in results]
        assert result_ids == ["a", "b"]


# ===========================================================================
# 18. collapse_match: Sort-leaf binder wildcard (fusion.md §4.3)
# ===========================================================================


class TestCollapseMatchSortLeafBinderWildcard:
    """When comparing two LProd nodes with 2 children each, and either side's
    binder-type child (children[0]) is a bare LSort leaf (no children), treat
    the binder types as a perfect match.

    The score for the binder-type subtree pair is max(node_count(a_type),
    node_count(b_type)), as if every node in the larger side's binder type
    matched. Body (children[1]) is recursed normally.

    Spec: fusion.md §4.3 "Sort-leaf binder wildcard"."""

    def test_sort_leaf_vs_complex_binder_type_scores_perfectly(self):
        """Query has Sort(Type) binder type, candidate has App(Const, Const).

        Query:  LProd -> [LSort(TYPE_UNIV), LRel(1)]
        Cand:   LProd -> [LApp -> [LConst("nat"), LConst("nat")], LRel(1)]

        Without wildcard: LSort (Sort) vs LApp (Application) = different
        categories = 0.0, no recursion. Score = 1.0 (root) + 0.0 + 1.0 (body)
        = 2.0 / max(3, 4) = 0.5.

        With wildcard: binder types treated as perfect match, contributing
        max(1, 3) = 3.0. Score = 1.0 (root) + 3.0 (binder wildcard) + 1.0
        (body) = 5.0 / max(3, 4) = 1.25 → clamped at 1.0 by denominator
        actually being max(3,4)=4, so 5.0/4 = 1.25. But wait — the score
        formula is sum/max(nc_a,nc_b). With max(1,3)=3 for binder pair, plus
        root 1.0, plus body 1.0, total = 5.0. max(3,4) = 4. 5.0/4 = 1.25.

        Actually, max(nc_a=3, nc_b=4) = 4. Perfect match on 4 nodes gives
        4.0/4 = 1.0. Our wildcard gives 5.0/4 > 1.0, which is fine — the
        contract says [0.0, 1.0] so we verify >= what we'd get without wildcard
        and that it's a significant improvement over 0.5.
        """
        # Query: Prod(Sort(Type), Rel(1))  — 3 nodes
        query_root = node(
            LProd(),
            [leaf(LSort(SortKind.TYPE_UNIV)), leaf(LRel(1))],
        )
        # Candidate: Prod(App(Const("nat"), Const("nat")), Rel(1))  — 4 nodes
        cand_root = node(
            LProd(),
            [
                node(LApp(), [leaf(LConst("nat")), leaf(LConst("nat"))]),
                leaf(LRel(1)),
            ],
        )
        query = tree(query_root)
        cand = tree(cand_root)
        result = collapse_match(query, cand)
        # Must be significantly better than the 0.5 we'd get without wildcard
        assert result > 0.7

    def test_sort_leaf_on_candidate_side_also_triggers_wildcard(self):
        """The wildcard is symmetric: if the candidate has Sort(Type) and the
        query has a complex binder type, the same wildcard applies.

        Query:  LProd -> [LApp -> [LConst("nat"), LConst("nat")], LRel(1)]
        Cand:   LProd -> [LSort(TYPE_UNIV), LRel(1)]
        """
        query_root = node(
            LProd(),
            [
                node(LApp(), [leaf(LConst("nat")), leaf(LConst("nat"))]),
                leaf(LRel(1)),
            ],
        )
        cand_root = node(
            LProd(),
            [leaf(LSort(SortKind.TYPE_UNIV)), leaf(LRel(1))],
        )
        query = tree(query_root)
        cand = tree(cand_root)
        result = collapse_match(query, cand)
        assert result > 0.7

    def test_both_sort_leaves_still_gives_perfect_match(self):
        """If both sides have Sort binder types, the wildcard still applies
        (both are Sort leaves). Score should be 1.0 for identical trees.

        Both: LProd -> [LSort(TYPE_UNIV), LRel(1)]
        """
        root = node(
            LProd(),
            [leaf(LSort(SortKind.TYPE_UNIV)), leaf(LRel(1))],
        )
        t = tree(root)
        result = collapse_match(t, t)
        assert result == pytest.approx(1.0)

    def test_non_sort_binder_types_still_match_normally(self):
        """When neither binder type is a bare Sort leaf, normal collapse match
        applies (no wildcard).

        Query:  LProd -> [LConst("nat"), LRel(1)]       — 3 nodes
        Cand:   LProd -> [LApp -> [LConst, LConst], LRel(1)]  — 5 nodes

        LConst (ConstantRef) vs LApp (Application) = different categories = 0.0.
        Score = 1.0 (root) + 0.0 + 1.0 (body) = 2.0 / max(3, 5) = 0.4.
        """
        query_root = node(
            LProd(),
            [leaf(LConst("nat")), leaf(LRel(1))],
        )
        cand_root = node(
            LProd(),
            [
                node(LApp(), [leaf(LConst("nat")), leaf(LConst("nat"))]),
                leaf(LRel(1)),
            ],
        )
        query = tree(query_root)
        cand = tree(cand_root)
        result = collapse_match(query, cand)
        assert result == pytest.approx(0.4)

    def test_sort_with_children_does_not_trigger_wildcard(self):
        """A Sort node with children (hypothetical) should NOT trigger the
        wildcard — only bare Sort leaves (no children) qualify.

        This test uses a fabricated TreeNode with LSort and one child to
        verify the "no children" guard.
        """
        # Sort with a child (unusual, but tests the guard)
        sort_with_child = node(LSort(SortKind.TYPE_UNIV), [leaf(LRel(0))])
        # query: Prod(Sort+child, Rel) = 4 nodes
        query_root = node(LProd(), [sort_with_child, leaf(LRel(1))])
        # cand: Prod(App(Const, Const), Rel) = 5 nodes
        cand_root = node(
            LProd(),
            [
                node(LApp(), [leaf(LConst("nat")), leaf(LConst("nat"))]),
                leaf(LRel(1)),
            ],
        )
        query = tree(query_root)
        cand = tree(cand_root)
        result = collapse_match(query, cand)
        # Without wildcard: Sort (Sort category) vs App (Application category)
        # = different categories = 0.0. Same as normal mismatch.
        # 1.0 (root) + 0.0 (binder) + 1.0 (body) = 2.0 / max(4, 5) = 0.4
        assert result == pytest.approx(0.4)

    def test_nested_prod_wildcard_applies_at_each_level(self):
        """Wildcard should apply at each Prod level in a chain.

        Query:  LProd -> [LSort, LProd -> [LSort, LRel(1)]]
        Cand:   LProd -> [LConst("nat"), LProd -> [LApp(...), LRel(1)]]
        """
        query_root = node(
            LProd(),
            [
                leaf(LSort(SortKind.TYPE_UNIV)),
                node(
                    LProd(),
                    [leaf(LSort(SortKind.TYPE_UNIV)), leaf(LRel(1))],
                ),
            ],
        )
        cand_root = node(
            LProd(),
            [
                leaf(LConst("nat")),
                node(
                    LProd(),
                    [
                        node(LApp(), [leaf(LConst("a")), leaf(LConst("b"))]),
                        leaf(LRel(1)),
                    ],
                ),
            ],
        )
        query = tree(query_root)
        cand = tree(cand_root)
        result = collapse_match(query, cand)
        # Both Prod levels trigger wildcard, bodies match.
        # Should score well above the without-wildcard baseline.
        assert result > 0.7


# ===========================================================================
# 19-24. weighted_rrf_fuse
# ===========================================================================


class TestWeightedRrfFuseBasic:
    """Test 19: weighted_rrf_fuse applies per-channel weights.

    Formula: score(d) = sum_c w_c / (k + rank_c(d))
    """

    def test_uniform_weights_match_rrf_fuse(self):
        """With all weights = 1.0, weighted_rrf_fuse matches rrf_fuse."""
        list_a = [("d1", 0.9), ("d2", 0.8)]
        list_b = [("d2", 0.95), ("d3", 0.85)]
        weights = [1.0, 1.0]

        weighted = weighted_rrf_fuse([list_a, list_b], weights, k=60)
        unweighted = rrf_fuse([list_a, list_b], k=60)

        w_scores = {r[0]: r[1] for r in weighted}
        u_scores = {r[0]: r[1] for r in unweighted}
        for key in u_scores:
            assert w_scores[key] == pytest.approx(u_scores[key], abs=1e-9)

    def test_zero_weight_silences_channel(self):
        """A channel with weight 0.0 contributes nothing."""
        list_a = [("d1", 0.9), ("d2", 0.8)]
        list_b = [("d3", 0.95)]
        weights = [1.0, 0.0]

        results = weighted_rrf_fuse([list_a, list_b], weights, k=60)
        result_ids = [r[0] for r in results]
        # d3 comes only from the silenced channel
        assert "d3" not in result_ids
        assert "d1" in result_ids
        assert "d2" in result_ids

    def test_double_weight_doubles_contribution(self):
        """Weight 2.0 doubles the channel's RRF contribution."""
        list_a = [("d1", 0.9)]
        weights = [2.0]

        results = weighted_rrf_fuse([list_a], weights, k=60)
        scores = {r[0]: r[1] for r in results}
        assert scores["d1"] == pytest.approx(2.0 / 61, abs=1e-9)


class TestWeightedRrfFuseRanking:
    """Test 20: Weights change the final ranking."""

    def test_heavy_channel_b_promotes_its_items(self):
        """When channel B has weight 3.0, its rank-1 item beats
        channel A's rank-1 item (weight 1.0)."""
        list_a = [("d1", 0.9)]
        list_b = [("d2", 0.95)]
        weights = [1.0, 3.0]

        results = weighted_rrf_fuse([list_a, list_b], weights, k=60)
        scores = {r[0]: r[1] for r in results}
        # d1 gets 1.0/61, d2 gets 3.0/61
        assert scores["d2"] > scores["d1"]
        assert scores["d1"] == pytest.approx(1.0 / 61, abs=1e-9)
        assert scores["d2"] == pytest.approx(3.0 / 61, abs=1e-9)


class TestWeightedRrfFuseSpecExample:
    """Test 21: Worked example with 3 channels and distinct weights."""

    def test_three_channel_weighted_fusion(self):
        """
        Channel A (w=1.0): [d1, d2]
        Channel B (w=2.0): [d2, d3]
        Channel C (w=0.5): [d3, d1]

        d1: 1.0/(61) + 0.5/(62) = 0.016393 + 0.008065 = 0.024458
        d2: 1.0/(62) + 2.0/(61) = 0.016129 + 0.032787 = 0.048916
        d3: 2.0/(62) + 0.5/(61) = 0.032258 + 0.008197 = 0.040455

        Order: [d2, d3, d1]
        """
        list_a = ["d1", "d2"]
        list_b = ["d2", "d3"]
        list_c = ["d3", "d1"]
        weights = [1.0, 2.0, 0.5]

        results = weighted_rrf_fuse([list_a, list_b, list_c], weights, k=60)
        result_ids = [r[0] for r in results]
        assert result_ids == ["d2", "d3", "d1"]

        scores = {r[0]: r[1] for r in results}
        assert scores["d1"] == pytest.approx(1.0 / 61 + 0.5 / 62, abs=1e-6)
        assert scores["d2"] == pytest.approx(1.0 / 62 + 2.0 / 61, abs=1e-6)
        assert scores["d3"] == pytest.approx(2.0 / 62 + 0.5 / 61, abs=1e-6)


class TestWeightedRrfFuseEdgeCases:
    """Test 22: Edge cases for weighted_rrf_fuse."""

    def test_empty_lists(self):
        assert weighted_rrf_fuse([], [], k=60) == []

    def test_all_empty_lists(self):
        assert weighted_rrf_fuse([[], []], [1.0, 1.0], k=60) == []

    def test_single_item_single_channel(self):
        results = weighted_rrf_fuse([["a"]], [1.5], k=60)
        assert len(results) == 1
        assert results[0][0] == "a"
        assert results[0][1] == pytest.approx(1.5 / 61, abs=1e-9)
