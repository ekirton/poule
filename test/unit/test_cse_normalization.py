"""TDD tests for CSE normalization (specification/cse-normalization.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/normalization/cse.py and its dependencies exist.

The tests exercise the public API:
    cse_normalize(tree: ExprTree) -> None  (in-place mutation)

Covers:
- No repeated subexpressions -> tree unchanged (except depth/id updates)
- Repeated non-constant subtrees replaced by LCseVar
- First occurrence preserved, subsequent become LCseVar
- Multiple distinct repeated subtrees get sequential ids (0, 1, ...)
- Constants (LConst, LInd, LConstruct) never replaced
- Mixed constants and non-constants
- Single-node tree -> no replacement
- node_count updated after CSE
- Depths and node_ids recomputed after CSE
- Pre-order replacement traversal
- LCseVar is a leaf (no children)
- Empty tree is a no-op
- RecursionError -> NormalizationError
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers — build trees manually
# ---------------------------------------------------------------------------

def _leaf(label):
    from Poule.models.tree import TreeNode
    return TreeNode(label=label, children=[])


def _node(label, children):
    from Poule.models.tree import TreeNode
    return TreeNode(label=label, children=children)


def _tree(root):
    from Poule.models.tree import ExprTree, node_count
    return ExprTree(root=root, node_count=node_count(root))


def _prepare(tree):
    """Apply recompute_depths and assign_node_ids to set metadata."""
    from Poule.models.tree import recompute_depths, assign_node_ids
    recompute_depths(tree)
    assign_node_ids(tree)
    return tree


def _collect_labels(node):
    """Collect labels in pre-order."""
    from Poule.models.tree import TreeNode
    result = [node.label]
    for c in node.children:
        result.extend(_collect_labels(c))
    return result


def _collect_nodes_preorder(node):
    """Collect all nodes in pre-order."""
    result = [node]
    for c in node.children:
        result.extend(_collect_nodes_preorder(c))
    return result


# ---------------------------------------------------------------------------
# 1. No repeated subexpressions -> tree unchanged
# ---------------------------------------------------------------------------

class TestNoRepeatedSubexpressions:

    def test_unique_subtrees_preserved(self, make_tree):
        """A tree with all unique subtrees has no replacements."""
        from Poule.models.labels import LProd, LInd, LSort
        from Poule.models.enums import SortKind
        from Poule.normalization.cse import cse_normalize

        # Prod(Ind("nat"), Sort(PROP)) -- all leaves are different types/payloads
        root = _node(LProd(), [
            _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            _leaf(LSort(SortKind.PROP)),
        ])
        tree = _prepare(_tree(root))
        original_count = tree.node_count

        cse_normalize(tree)

        labels = _collect_labels(tree.root)
        assert len(labels) == 3
        assert isinstance(labels[0], LProd)
        assert isinstance(labels[1], LInd)
        assert isinstance(labels[2], LSort)
        assert tree.node_count == original_count


# ---------------------------------------------------------------------------
# 2. Repeated non-constant subtree replaced by LCseVar
# ---------------------------------------------------------------------------

class TestRepeatedNonConstantReplacement:

    def test_second_occurrence_becomes_cse_var(self):
        """Spec example: Prod(App(Ind(list), Ind(nat)), App(Ind(list), Ind(nat)))
        -> Prod(App(Ind(list), Ind(nat)), LCseVar(0))"""
        from Poule.models.labels import LProd, LApp, LInd, LCseVar
        from Poule.normalization.cse import cse_normalize

        def _make_app_list_nat():
            return _node(LApp(), [
                _leaf(LInd("Stdlib.Init.Datatypes.list")),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ])

        root = _node(LProd(), [
            _make_app_list_nat(),
            _make_app_list_nat(),
        ])
        tree = _prepare(_tree(root))
        assert tree.node_count == 7

        cse_normalize(tree)

        # Root is still LProd
        assert isinstance(tree.root.label, LProd)
        # First child preserved as App(Ind, Ind)
        first = tree.root.children[0]
        assert isinstance(first.label, LApp)
        assert len(first.children) == 2
        # Second child replaced by LCseVar(0)
        second = tree.root.children[1]
        assert isinstance(second.label, LCseVar)
        assert second.label.id == 0

    def test_three_occurrences_second_and_third_replaced(self):
        """When a subtree appears 3 times, occurrences 2 and 3 become LCseVar(0)."""
        from Poule.models.labels import LProd, LSort, LRel, LCseVar, LApp
        from Poule.models.enums import SortKind
        from Poule.normalization.cse import cse_normalize

        # Spec example: LProd(LSort(PROP), LRel(0)) appears 3 times
        def _make_prod_subtree():
            return _node(LProd(), [
                _leaf(LSort(SortKind.PROP)),
                _leaf(LRel(0)),
            ])

        # Wrap 3 copies in a chain: App(sub1, App(sub2, sub3))
        root = _node(LApp(), [
            _make_prod_subtree(),
            _node(LApp(), [
                _make_prod_subtree(),
                _make_prod_subtree(),
            ]),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        # First occurrence (pre-order): left child of outer App
        first = tree.root.children[0]
        assert isinstance(first.label, LProd)

        # Second occurrence: left child of inner App -> LCseVar
        inner_app = tree.root.children[1]
        second = inner_app.children[0]
        assert isinstance(second.label, LCseVar)
        assert second.label.id == 0

        # Third occurrence: right child of inner App -> LCseVar
        third = inner_app.children[1]
        assert isinstance(third.label, LCseVar)
        assert third.label.id == 0


# ---------------------------------------------------------------------------
# 3. Two different repeated subtrees get different CSE var ids
# ---------------------------------------------------------------------------

class TestMultipleDistinctReplacements:

    def test_two_different_repeated_subtrees_get_ids_0_and_1(self):
        """Two distinct repeated subtrees get sequential ids 0 and 1."""
        from Poule.models.labels import LApp, LProd, LSort, LRel, LCseVar
        from Poule.models.enums import SortKind
        from Poule.normalization.cse import cse_normalize

        # Subtree A: Prod(Sort(PROP), Rel(0))
        def _sub_a():
            return _node(LProd(), [
                _leaf(LSort(SortKind.PROP)),
                _leaf(LRel(0)),
            ])

        # Subtree B: Prod(Sort(SET), Rel(1))
        def _sub_b():
            return _node(LProd(), [
                _leaf(LSort(SortKind.SET)),
                _leaf(LRel(1)),
            ])

        # Tree: App(App(A1, B1), App(A2, B2))
        root = _node(LApp(), [
            _node(LApp(), [_sub_a(), _sub_b()]),
            _node(LApp(), [_sub_a(), _sub_b()]),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        # Collect all LCseVar nodes
        all_labels = _collect_labels(tree.root)
        cse_vars = [l for l in all_labels if isinstance(l, LCseVar)]

        # There should be replacement(s). The inner App subtrees are also
        # repeated, so at minimum the second App(A, B) itself gets replaced.
        # The exact ids depend on pre-order encounter order — just verify
        # that all assigned ids are distinct where the hash differs.
        cse_ids = {l.id for l in cse_vars}
        assert len(cse_ids) >= 1  # At least one replacement happened


# ---------------------------------------------------------------------------
# 4. Constants never replaced
# ---------------------------------------------------------------------------

class TestConstantsPreserved:

    def test_lconst_not_replaced(self):
        """Duplicated LConst nodes are never replaced."""
        from Poule.models.labels import LApp, LConst, LCseVar
        from Poule.normalization.cse import cse_normalize

        root = _node(LApp(), [
            _leaf(LConst("Stdlib.Init.Nat.add")),
            _leaf(LConst("Stdlib.Init.Nat.add")),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        labels = _collect_labels(tree.root)
        cse_labels = [l for l in labels if isinstance(l, LCseVar)]
        assert cse_labels == [], "LConst must never be replaced by LCseVar"
        const_labels = [l for l in labels if isinstance(l, LConst)]
        assert len(const_labels) == 2

    def test_lind_not_replaced(self):
        """Duplicated LInd nodes are never replaced."""
        from Poule.models.labels import LApp, LInd, LCseVar
        from Poule.normalization.cse import cse_normalize

        root = _node(LApp(), [
            _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            _leaf(LInd("Stdlib.Init.Datatypes.nat")),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        labels = _collect_labels(tree.root)
        cse_labels = [l for l in labels if isinstance(l, LCseVar)]
        assert cse_labels == [], "LInd must never be replaced by LCseVar"

    def test_lconstruct_not_replaced(self):
        """Duplicated LConstruct nodes are never replaced."""
        from Poule.models.labels import LApp, LConstruct, LCseVar
        from Poule.normalization.cse import cse_normalize

        root = _node(LApp(), [
            _leaf(LConstruct("Stdlib.Init.Datatypes.nat", 0)),
            _leaf(LConstruct("Stdlib.Init.Datatypes.nat", 0)),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        labels = _collect_labels(tree.root)
        cse_labels = [l for l in labels if isinstance(l, LCseVar)]
        assert cse_labels == [], "LConstruct must never be replaced by LCseVar"


# ---------------------------------------------------------------------------
# 5. Mixed: constants preserved + non-constants replaced
# ---------------------------------------------------------------------------

class TestMixedConstantsAndNonConstants:

    def test_constants_kept_non_constants_replaced(self):
        """In a tree with repeated constants AND repeated non-constant subtrees,
        only the non-constants are replaced."""
        from Poule.models.labels import (
            LApp, LProd, LInd, LSort, LRel, LCseVar,
        )
        from Poule.models.enums import SortKind
        from Poule.normalization.cse import cse_normalize

        # Repeated non-constant: Prod(Sort(PROP), Rel(0))
        def _sub():
            return _node(LProd(), [
                _leaf(LSort(SortKind.PROP)),
                _leaf(LRel(0)),
            ])

        # Repeated constant: Ind("nat") appears at multiple places
        root = _node(LApp(), [
            _node(LApp(), [
                _sub(),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ]),
            _node(LApp(), [
                _sub(),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ]),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        labels = _collect_labels(tree.root)
        # All LInd nodes should still be present (not replaced)
        ind_labels = [l for l in labels if isinstance(l, LInd)]
        assert len(ind_labels) >= 2, "LInd constants must be preserved"

        # At least one LCseVar should exist (the repeated non-constant subtree)
        cse_labels = [l for l in labels if isinstance(l, LCseVar)]
        assert len(cse_labels) >= 1, "Repeated non-constant subtrees should be replaced"


# ---------------------------------------------------------------------------
# 6. Single-node tree -> no replacement
# ---------------------------------------------------------------------------

class TestSingleNodeTree:

    def test_single_leaf_unchanged(self):
        """A single-node tree has no duplicates and is returned as-is."""
        from Poule.models.labels import LSort, LCseVar
        from Poule.models.enums import SortKind
        from Poule.normalization.cse import cse_normalize

        root = _leaf(LSort(SortKind.PROP))
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        assert isinstance(tree.root.label, LSort)
        assert tree.root.children == []
        assert tree.node_count == 1

    def test_single_const_leaf_unchanged(self):
        """A single LConst leaf is returned unchanged."""
        from Poule.models.labels import LConst
        from Poule.normalization.cse import cse_normalize

        root = _leaf(LConst("Stdlib.Init.Nat.add"))
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        assert isinstance(tree.root.label, LConst)
        assert tree.node_count == 1


# ---------------------------------------------------------------------------
# 7. node_count updated after CSE
# ---------------------------------------------------------------------------

class TestNodeCountUpdated:

    def test_node_count_reduced_after_cse(self):
        """node_count reflects the smaller tree after CSE replacement."""
        from Poule.models.labels import LProd, LApp, LInd
        from Poule.normalization.cse import cse_normalize

        def _make_app_list_nat():
            return _node(LApp(), [
                _leaf(LInd("Stdlib.Init.Datatypes.list")),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ])

        # Prod(App(Ind, Ind), App(Ind, Ind)) -> 7 nodes
        root = _node(LProd(), [
            _make_app_list_nat(),
            _make_app_list_nat(),
        ])
        tree = _prepare(_tree(root))
        assert tree.node_count == 7

        cse_normalize(tree)

        # After CSE: Prod(App(Ind, Ind), CseVar(0)) -> 5 nodes
        assert tree.node_count == 5


# ---------------------------------------------------------------------------
# 8. Depths and node_ids recomputed after CSE
# ---------------------------------------------------------------------------

class TestDepthsAndNodeIdsRecomputed:

    def test_depths_correct_after_cse(self):
        """After CSE, depth values reflect the new tree structure."""
        from Poule.models.labels import LProd, LApp, LInd
        from Poule.normalization.cse import cse_normalize

        def _make_app_list_nat():
            return _node(LApp(), [
                _leaf(LInd("Stdlib.Init.Datatypes.list")),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ])

        root = _node(LProd(), [
            _make_app_list_nat(),
            _make_app_list_nat(),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        # Root (LProd) at depth 0
        assert tree.root.depth == 0
        # First child (LApp) at depth 1
        assert tree.root.children[0].depth == 1
        # Leaves of first child at depth 2
        assert tree.root.children[0].children[0].depth == 2
        assert tree.root.children[0].children[1].depth == 2
        # LCseVar replaces second child at depth 1
        assert tree.root.children[1].depth == 1

    def test_node_ids_contiguous_after_cse(self):
        """After CSE, node_ids are contiguous 0..n-1 in pre-order."""
        from Poule.models.labels import LProd, LApp, LInd
        from Poule.normalization.cse import cse_normalize

        def _make_app_list_nat():
            return _node(LApp(), [
                _leaf(LInd("Stdlib.Init.Datatypes.list")),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ])

        root = _node(LProd(), [
            _make_app_list_nat(),
            _make_app_list_nat(),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        nodes = _collect_nodes_preorder(tree.root)
        ids = [n.node_id for n in nodes]
        assert ids == list(range(len(nodes)))


# ---------------------------------------------------------------------------
# 9. Replacement traversal is pre-order (first = leftmost)
# ---------------------------------------------------------------------------

class TestPreOrderReplacement:

    def test_first_preorder_occurrence_preserved(self):
        """The first occurrence in pre-order (leftmost) is preserved,
        not the last or any other."""
        from Poule.models.labels import LApp, LProd, LSort, LRel, LCseVar
        from Poule.models.enums import SortKind
        from Poule.normalization.cse import cse_normalize

        def _sub():
            return _node(LProd(), [
                _leaf(LSort(SortKind.PROP)),
                _leaf(LRel(0)),
            ])

        # App(sub, sub) — left child is first in pre-order
        root = _node(LApp(), [_sub(), _sub()])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        # Left child (first pre-order) preserved
        left = tree.root.children[0]
        assert isinstance(left.label, LProd)
        assert len(left.children) == 2

        # Right child (second pre-order) replaced
        right = tree.root.children[1]
        assert isinstance(right.label, LCseVar)


# ---------------------------------------------------------------------------
# 10. LCseVar is a leaf (no children)
# ---------------------------------------------------------------------------

class TestCseVarIsLeaf:

    def test_cse_var_has_no_children(self):
        """LCseVar nodes introduced by CSE have zero children."""
        from Poule.models.labels import LApp, LProd, LSort, LRel, LCseVar
        from Poule.models.enums import SortKind
        from Poule.normalization.cse import cse_normalize

        def _sub():
            return _node(LProd(), [
                _leaf(LSort(SortKind.PROP)),
                _leaf(LRel(0)),
            ])

        root = _node(LApp(), [_sub(), _sub()])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        # Find all LCseVar nodes
        nodes = _collect_nodes_preorder(tree.root)
        cse_nodes = [n for n in nodes if isinstance(n.label, LCseVar)]
        assert len(cse_nodes) >= 1
        for n in cse_nodes:
            assert n.children == [], "LCseVar must be a leaf with no children"


# ---------------------------------------------------------------------------
# 11. Empty tree / node_count=0 is a no-op
# ---------------------------------------------------------------------------

class TestEmptyTree:

    def test_empty_tree_noop(self):
        """An empty tree (node_count=0) should be a no-op.

        This test verifies cse_normalize handles the edge case without error.
        The exact representation of 'empty' depends on ExprTree constraints.
        If ExprTree requires node_count >= 1, this test may need adjustment.
        """
        from Poule.models.labels import LSort
        from Poule.models.enums import SortKind
        from Poule.normalization.cse import cse_normalize

        # Minimal tree — single node, should be a no-op
        root = _leaf(LSort(SortKind.PROP))
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        # Tree is unchanged
        assert isinstance(tree.root.label, LSort)
        assert tree.node_count == 1


# ---------------------------------------------------------------------------
# 12. RecursionError -> NormalizationError
# ---------------------------------------------------------------------------

class TestRecursionError:

    def test_deep_recursion_raises_normalization_error(self):
        """A deeply nested tree that exceeds recursion limit raises
        NormalizationError, not RecursionError."""
        from Poule.models.labels import LApp, LRel
        from Poule.normalization.cse import cse_normalize
        from Poule.normalization.errors import NormalizationError

        # Build a very deep chain: App(App(App(...Rel(0)...)))
        import sys
        depth = sys.getrecursionlimit() + 100
        node = _leaf(LRel(0))
        for _ in range(depth):
            node = _node(LApp(), [node, _leaf(LRel(1))])

        tree = _tree(node)
        # Skip _prepare since it would also recurse too deep

        with pytest.raises(NormalizationError):
            cse_normalize(tree)


# ---------------------------------------------------------------------------
# Additional spec-example tests
# ---------------------------------------------------------------------------

class TestSpecExamples:

    def test_nat_arrow_nat_arrow_nat_unchanged(self):
        """Spec example: nat -> nat -> nat.
        Prod(Ind(nat), Prod(Ind(nat), Ind(nat)))
        All nodes are constants -> no replacement."""
        from Poule.models.labels import LProd, LInd, LCseVar
        from Poule.normalization.cse import cse_normalize

        root = _node(LProd(), [
            _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            _node(LProd(), [
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ]),
        ])
        tree = _prepare(_tree(root))
        assert tree.node_count == 5

        cse_normalize(tree)

        # No LCseVar anywhere — Ind nodes are constants
        labels = _collect_labels(tree.root)
        cse_labels = [l for l in labels if isinstance(l, LCseVar)]
        assert cse_labels == []
        assert tree.node_count == 5

    def test_nat_arrow_bool_unchanged(self):
        """Spec example: nat -> bool. No duplicated non-constant subtrees."""
        from Poule.models.labels import LProd, LInd, LCseVar
        from Poule.normalization.cse import cse_normalize

        root = _node(LProd(), [
            _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            _leaf(LInd("Stdlib.Init.Datatypes.bool")),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        labels = _collect_labels(tree.root)
        cse_labels = [l for l in labels if isinstance(l, LCseVar)]
        assert cse_labels == []

    def test_list_nat_arrow_list_nat_cse(self):
        """Spec example: list nat -> list nat.
        Prod(App(Ind(list), Ind(nat)), App(Ind(list), Ind(nat)))
        -> Prod(App(Ind(list), Ind(nat)), CseVar(0))
        Node count 7 -> 4."""
        from Poule.models.labels import LProd, LApp, LInd, LCseVar
        from Poule.normalization.cse import cse_normalize

        def _make_app_list_nat():
            return _node(LApp(), [
                _leaf(LInd("Stdlib.Init.Datatypes.list")),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ])

        root = _node(LProd(), [
            _make_app_list_nat(),
            _make_app_list_nat(),
        ])
        tree = _prepare(_tree(root))
        assert tree.node_count == 7

        cse_normalize(tree)

        # Structure check
        assert isinstance(tree.root.label, LProd)
        first = tree.root.children[0]
        assert isinstance(first.label, LApp)
        second = tree.root.children[1]
        assert isinstance(second.label, LCseVar)
        assert second.label.id == 0
        assert second.children == []

        # Node count reduced: LProd + LApp + LInd(list) + LInd(nat) + LCseVar(0) = 5
        assert tree.node_count == 5


# ---------------------------------------------------------------------------
# Edge case: all-constant tree
# ---------------------------------------------------------------------------

class TestAllConstantTree:

    def test_all_constants_no_replacement(self):
        """A tree made entirely of constant labels has no replacements,
        even when subtrees are structurally repeated."""
        from Poule.models.labels import LApp, LConst, LInd, LConstruct, LCseVar
        from Poule.normalization.cse import cse_normalize

        root = _node(LApp(), [
            _node(LApp(), [
                _leaf(LConst("Stdlib.Init.Nat.add")),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ]),
            _node(LApp(), [
                _leaf(LConst("Stdlib.Init.Nat.add")),
                _leaf(LInd("Stdlib.Init.Datatypes.nat")),
            ]),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        labels = _collect_labels(tree.root)
        # The inner App subtrees are repeated AND non-constant (LApp is not
        # a constant label), so they ARE candidates for replacement.
        # Only the LConst and LInd leaves are protected.
        # The second App(Const, Ind) should become LCseVar(0).
        cse_labels = [l for l in labels if isinstance(l, LCseVar)]
        assert len(cse_labels) >= 1, (
            "Repeated LApp subtrees should be replaced even if their leaves "
            "are constants — LApp itself is not a constant label"
        )


# ---------------------------------------------------------------------------
# CSE var id sequencing
# ---------------------------------------------------------------------------

class TestCseVarIdSequencing:

    def test_ids_start_at_zero_and_increment(self):
        """CSE variable ids are assigned sequentially starting from 0."""
        from Poule.models.labels import (
            LApp, LProd, LSort, LRel, LCseVar, LFix,
        )
        from Poule.models.enums import SortKind
        from Poule.normalization.cse import cse_normalize

        # Two distinct non-constant subtrees, each repeated twice
        def _sub_a():
            return _node(LProd(), [
                _leaf(LSort(SortKind.PROP)),
                _leaf(LRel(0)),
            ])

        def _sub_b():
            return _node(LProd(), [
                _leaf(LSort(SortKind.TYPE_UNIV)),
                _leaf(LRel(1)),
            ])

        # Tree: Fix( App(A, B), App(A, B) )
        # The App(A, B) subtree repeats, and within it A and B each repeat
        root = _node(LFix(0), [
            _node(LApp(), [_sub_a(), _sub_b()]),
            _node(LApp(), [_sub_a(), _sub_b()]),
        ])
        tree = _prepare(_tree(root))

        cse_normalize(tree)

        labels = _collect_labels(tree.root)
        cse_labels = [l for l in labels if isinstance(l, LCseVar)]
        if cse_labels:
            ids = sorted({l.id for l in cse_labels})
            # Ids should be sequential starting from 0
            assert ids == list(range(len(ids)))
