"""TDD tests for the fusion module — written before implementation.

Tests target the public API defined in specification/fusion.md:
  - clamp_score(score) -> float in [0.0, 1.0]
  - node_category(label) -> str (category name)
  - collapse_match(tree_a, tree_b) -> float in [0.0, 1.0]
  - structural_score(wl, ted, cm, cj, has_ted) -> float
  - rrf_fuse(ranked_lists, k=60) -> list of (decl_id, rrf_score) sorted desc

Implementation will live in src/wily_rooster/fusion/fusion.py.
"""

from __future__ import annotations

import pytest

from wily_rooster.fusion.fusion import (
    clamp_score,
    node_category,
    collapse_match,
    structural_score,
    rrf_fuse,
)
from wily_rooster.models.labels import (
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
from wily_rooster.models.enums import SortKind
from wily_rooster.models.tree import TreeNode, ExprTree


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
        assert node_category(LConst("Coq.Init.Nat.add")) == "ConstantRef"

    def test_lind_is_constant_ref(self):
        assert node_category(LInd("Coq.Init.Datatypes.nat")) == "ConstantRef"

    def test_lconstruct_is_constant_ref(self):
        assert node_category(LConstruct("Coq.Init.Datatypes.nat", 0)) == "ConstantRef"

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
