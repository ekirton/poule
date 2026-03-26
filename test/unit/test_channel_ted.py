"""TDD tests for the TED fine-ranking channel.

Tests are written BEFORE implementation exists. They will fail with ImportError
until the production modules in src/poule/channels/ted.py are implemented.

Specification: specification/channel-ted.md
Architecture:  doc/architecture/retrieval-pipeline.md
Data model:    doc/architecture/data-models/expression-tree.md
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers — build trees from model types (not yet implemented)
# ---------------------------------------------------------------------------

def _make_leaf(label):
    from Poule.models.tree import TreeNode
    return TreeNode(label=label, children=[])


def _make_node(label, children):
    from Poule.models.tree import TreeNode
    return TreeNode(label=label, children=children)


def _make_tree(root):
    from Poule.models.tree import ExprTree, node_count as _nc
    return ExprTree(root=root, node_count=_nc(root))


def _prepare_tree(root):
    """Build an ExprTree from a root node, then run recompute_depths and
    assign_node_ids as required by the TED spec."""
    from Poule.models.tree import recompute_depths, assign_node_ids
    tree = _make_tree(root)
    recompute_depths(tree)
    assign_node_ids(tree)
    return tree


# ---------------------------------------------------------------------------
# Label constructors — shortcuts
# ---------------------------------------------------------------------------

def _labs():
    from Poule.models.labels import LAbs
    return LAbs()


def _lprod():
    from Poule.models.labels import LProd
    return LProd()


def _llet():
    from Poule.models.labels import LLet
    return LLet()


def _lapp():
    from Poule.models.labels import LApp
    return LApp()


def _lconst(name="Stdlib.Init.Nat.add"):
    from Poule.models.labels import LConst
    return LConst(name)


def _lind(name="Stdlib.Init.Datatypes.nat"):
    from Poule.models.labels import LInd
    return LInd(name)


def _lconstruct(name="Stdlib.Init.Datatypes.nat", idx=0):
    from Poule.models.labels import LConstruct
    return LConstruct(name, idx)


def _lrel(n=0):
    from Poule.models.labels import LRel
    return LRel(n)


def _lcsevar(n=0):
    from Poule.models.labels import LCseVar
    return LCseVar(n)


def _lsort(kind=None):
    from Poule.models.labels import LSort
    from Poule.models.enums import SortKind
    return LSort(kind or SortKind.PROP)


def _lcase(name="Stdlib.Init.Datatypes.nat"):
    from Poule.models.labels import LCase
    return LCase(name)


def _lfix(idx=0):
    from Poule.models.labels import LFix
    return LFix(idx)


def _lcofix(idx=0):
    from Poule.models.labels import LCoFix
    return LCoFix(idx)


def _lproj(name="proj"):
    from Poule.models.labels import LProj
    return LProj(name)


def _lprimitive(val=42):
    from Poule.models.labels import LPrimitive
    return LPrimitive(val)


# ===================================================================
# rename_cost tests
# ===================================================================

class TestRenameCost:
    """Spec § 4.1 — rename_cost(label_a, label_b)."""

    def test_identical_labels_return_zero(self):
        """Identical labels → 0.0."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lconst("a"), _lconst("a")) == 0.0

    def test_identical_labels_interior(self):
        """Identical interior labels → 0.0."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lapp(), _lapp()) == 0.0

    def test_same_category_binder_labs_lprod(self):
        """LAbs vs LProd (both Binder) → 0.5."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_labs(), _lprod()) == 0.5

    def test_same_category_binder_labs_llet(self):
        """LAbs vs LLet (both Binder) → 0.5."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_labs(), _llet()) == 0.5

    def test_cross_category_labs_lapp(self):
        """LAbs (Binder) vs LApp (Application) → 1.0."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_labs(), _lapp()) == 1.0

    def test_same_category_constant_ref(self):
        """LConst vs LInd (both ConstantRef) → 0.5."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lconst("a"), _lind("b")) == 0.5

    def test_same_category_constant_ref_construct(self):
        """LConst vs LConstruct (both ConstantRef) → 0.5."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lconst("a"), _lconstruct("b", 0)) == 0.5

    def test_same_category_variable(self):
        """LRel vs LCseVar (both Variable) → 0.5."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lrel(0), _lcsevar(0)) == 0.5

    def test_cross_category_sort_vs_primitive(self):
        """LSort (Sort) vs LPrimitive (Primitive) → 1.0."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lsort(), _lprimitive()) == 1.0

    def test_same_category_control(self):
        """LCase vs LFix (both Control) → 0.5."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lcase(), _lfix()) == 0.5

    def test_same_category_control_fix_cofix(self):
        """LFix vs LCoFix (both Control) → 0.5."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lfix(), _lcofix()) == 0.5

    def test_cross_category_const_vs_rel(self):
        """LConst (ConstantRef) vs LRel (Variable) → 1.0."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lconst("a"), _lrel(0)) == 1.0

    def test_cross_category_app_vs_case(self):
        """LApp (Application) vs LCase (Control) → 1.0."""
        from Poule.channels.ted import rename_cost
        assert rename_cost(_lapp(), _lcase()) == 1.0

    def test_rename_cost_symmetry(self):
        """rename_cost(a, b) == rename_cost(b, a) for all tested pairs."""
        from Poule.channels.ted import rename_cost
        pairs = [
            (_labs(), _lprod()),
            (_lconst("a"), _lind("b")),
            (_labs(), _lapp()),
            (_lsort(), _lprimitive()),
            (_lrel(0), _lcsevar(1)),
        ]
        for a, b in pairs:
            assert rename_cost(a, b) == rename_cost(b, a), (
                f"rename_cost not symmetric for {a!r}, {b!r}"
            )


# ===================================================================
# ted (tree edit distance) tests
# ===================================================================

class TestTed:
    """Spec § 4.2 — ted(tree_a, tree_b) using Zhang-Shasha."""

    def test_identical_single_node_trees(self):
        """Identical single-node trees → 0.0."""
        from Poule.channels.ted import ted
        tree_a = _prepare_tree(_make_leaf(_lconst("a")))
        tree_b = _prepare_tree(_make_leaf(_lconst("a")))
        assert ted(tree_a, tree_b) == 0.0

    def test_identical_multi_node_trees(self):
        """Identical multi-node trees → 0.0."""
        from Poule.channels.ted import ted

        def build():
            return _prepare_tree(
                _make_node(_lprod(), [
                    _make_leaf(_lsort()),
                    _make_leaf(_lrel(0)),
                ])
            )

        assert ted(build(), build()) == 0.0

    def test_single_node_vs_empty(self):
        """Single node vs empty tree → 1.0 (one insert).

        An 'empty tree' is modelled as None / zero-node, resulting in cost
        equal to one insert = 1.0.
        """
        from Poule.channels.ted import ted
        from Poule.models.tree import ExprTree

        tree_a = _prepare_tree(_make_leaf(_lconst("a")))
        # Empty tree represented per data model (root=None or node_count=0).
        # The exact representation depends on implementation; we create the
        # minimal valid empty ExprTree.
        tree_b = ExprTree(root=None, node_count=0)
        assert ted(tree_a, tree_b) == 1.0

    def test_same_category_rename(self):
        """Trees differing by one same-category rename → 0.5.

        Spec § 7 example: LAbs root vs LProd root, identical children.
        """
        from Poule.channels.ted import ted

        tree_a = _prepare_tree(
            _make_node(_labs(), [_make_leaf(_lrel(0))])
        )
        tree_b = _prepare_tree(
            _make_node(_lprod(), [_make_leaf(_lrel(0))])
        )
        assert ted(tree_a, tree_b) == 0.5

    def test_cross_category_rename(self):
        """Trees differing by one cross-category rename → 1.0.

        LProd (Binder) root vs LApp (Application) root, same children.
        """
        from Poule.channels.ted import ted

        tree_a = _prepare_tree(
            _make_node(_lprod(), [
                _make_leaf(_lrel(0)),
                _make_leaf(_lrel(1)),
            ])
        )
        tree_b = _prepare_tree(
            _make_node(_lapp(), [
                _make_leaf(_lrel(0)),
                _make_leaf(_lrel(1)),
            ])
        )
        assert ted(tree_a, tree_b) == 1.0

    def test_completely_different_trees(self):
        """Completely different trees → sum of deletes + inserts.

        tree_a: 3 nodes (all ConstantRef), tree_b: 2 nodes (all Variable).
        Cheapest edit: delete all of A (3 * 1.0) + insert all of B (2 * 1.0)
        = 5.0. But the algorithm may find a cheaper mapping via cross-category
        renames. With completely different categories the rename cost is 1.0,
        which equals delete+insert for a single node (1.0 + 1.0 = 2.0 vs
        rename 1.0), so renames are preferred where possible.

        tree_a: LConst root, children [LInd, LInd]  — 3 nodes
        tree_b: LRel(0)  — 1 node

        Optimal: rename root LConst→LRel = 1.0, delete two children = 2 * 1.0 = 2.0
        Total = 3.0
        """
        from Poule.channels.ted import ted

        tree_a = _prepare_tree(
            _make_node(_lcase(), [
                _make_leaf(_lind("a")),
                _make_leaf(_lind("b")),
            ])
        )
        tree_b = _prepare_tree(_make_leaf(_lrel(0)))
        # Optimal: rename LCase→LRel (cross-category) = 1.0, delete 2 children = 2.0
        assert ted(tree_a, tree_b) == 3.0

    def test_symmetry(self):
        """ted(a, b) == ted(b, a) for asymmetric trees."""
        from Poule.channels.ted import ted

        tree_a = _prepare_tree(
            _make_node(_lprod(), [
                _make_leaf(_lsort()),
                _make_node(_labs(), [_make_leaf(_lrel(0))]),
            ])
        )
        tree_b = _prepare_tree(
            _make_node(_lapp(), [
                _make_leaf(_lconst("f")),
                _make_leaf(_lrel(1)),
            ])
        )
        assert ted(tree_a, tree_b) == ted(tree_b, tree_a)

    def test_spec_example_same_category_rename(self):
        """Spec § 7 example: LAbs root vs LProd root, one identical child.

        tree_a: LAbs(child), tree_b: LProd(child) → ted = 0.5.
        """
        from Poule.channels.ted import ted

        child = _make_leaf(_lrel(0))
        tree_a = _prepare_tree(_make_node(_labs(), [_make_leaf(_lrel(0))]))
        tree_b = _prepare_tree(_make_node(_lprod(), [_make_leaf(_lrel(0))]))
        assert ted(tree_a, tree_b) == 0.5


# ===================================================================
# ted_similarity tests
# ===================================================================

class TestTedSimilarity:
    """Spec § 4.3 — ted_similarity(tree_a, tree_b)."""

    def test_identical_trees_return_one(self):
        """Identical trees → 1.0."""
        from Poule.channels.ted import ted_similarity

        tree = _prepare_tree(
            _make_node(_lprod(), [
                _make_leaf(_lsort()),
                _make_leaf(_lrel(0)),
            ])
        )
        # Build a second identical copy.
        tree2 = _prepare_tree(
            _make_node(_lprod(), [
                _make_leaf(_lsort()),
                _make_leaf(_lrel(0)),
            ])
        )
        assert ted_similarity(tree, tree2) == 1.0

    def test_completely_different_5_node_trees(self):
        """Completely different 5-node trees → 0.0.

        Spec § 7 example: tree_a has 5 nodes, tree_b has 5 nodes,
        all labels differ across categories.
        ted = 5.0 (delete all of A, insert all of B — or equivalent renames,
        each costing 1.0 cross-category).
        similarity = max(0.0, 1.0 - 5.0 / 5) = 0.0.
        """
        from Poule.channels.ted import ted_similarity

        # tree_a: 5 ConstantRef nodes
        tree_a = _prepare_tree(
            _make_node(_lcase("t"), [
                _make_leaf(_lind("a")),
                _make_node(_lcase("u"), [
                    _make_leaf(_lind("b")),
                    _make_leaf(_lind("c")),
                ]),
            ])
        )
        # tree_b: 5 Variable/Sort/Primitive nodes (all cross-category from above)
        tree_b = _prepare_tree(
            _make_node(_labs(), [
                _make_node(_labs(), [
                    _make_node(_labs(), [
                        _make_node(_labs(), [
                            _make_leaf(_lrel(0)),
                        ]),
                    ]),
                ]),
            ])
        )
        result = ted_similarity(tree_a, tree_b)
        assert result == 0.0

    def test_clamping_never_negative(self):
        """Similarity is clamped to 0.0, never negative.

        When ted > max(node_count_a, node_count_b) the raw formula would be
        negative. The result must be 0.0.
        """
        from Poule.channels.ted import ted_similarity

        # A large tree vs a small completely different tree.
        # ted could exceed max(nc_a, nc_b) if cross-category costs pile up.
        tree_a = _prepare_tree(
            _make_node(_lcase("t"), [
                _make_leaf(_lind("a")),
                _make_leaf(_lind("b")),
                _make_leaf(_lind("c")),
                _make_leaf(_lind("d")),
            ])
        )
        tree_b = _prepare_tree(_make_leaf(_lrel(0)))
        result = ted_similarity(tree_a, tree_b)
        assert result >= 0.0

    def test_partial_match(self):
        """Partial match between trees gives value in (0.0, 1.0).

        tree_a: LProd(LSort, LRel(0))  — 3 nodes
        tree_b: LProd(LSort, LConst)   — 3 nodes

        Only the third node differs: LRel (Variable) vs LConst (ConstantRef)
        → cross-category rename = 1.0.
        ted = 1.0, max_nc = 3.
        similarity = 1.0 - 1.0/3 ≈ 0.6667.
        """
        from Poule.channels.ted import ted_similarity

        tree_a = _prepare_tree(
            _make_node(_lprod(), [
                _make_leaf(_lsort()),
                _make_leaf(_lrel(0)),
            ])
        )
        tree_b = _prepare_tree(
            _make_node(_lprod(), [
                _make_leaf(_lsort()),
                _make_leaf(_lconst("f")),
            ])
        )
        result = ted_similarity(tree_a, tree_b)
        assert result == pytest.approx(1.0 - 1.0 / 3, abs=1e-9)

    def test_self_similarity(self):
        """Self-similarity: ted_similarity(T, T) == 1.0 for varied shapes."""
        from Poule.channels.ted import ted_similarity

        trees = [
            _prepare_tree(_make_leaf(_lconst("a"))),
            _prepare_tree(
                _make_node(_lapp(), [
                    _make_leaf(_lconst("f")),
                    _make_leaf(_lrel(0)),
                ])
            ),
            _prepare_tree(
                _make_node(_lprod(), [
                    _make_leaf(_lsort()),
                    _make_node(_labs(), [_make_leaf(_lrel(0))]),
                ])
            ),
        ]
        for t in trees:
            assert ted_similarity(t, t) == 1.0

    def test_similarity_in_unit_range(self):
        """Result is always in [0.0, 1.0]."""
        from Poule.channels.ted import ted_similarity

        tree_a = _prepare_tree(
            _make_node(_lapp(), [
                _make_leaf(_lconst("f")),
                _make_leaf(_lrel(0)),
            ])
        )
        tree_b = _prepare_tree(
            _make_node(_lprod(), [
                _make_leaf(_lsort()),
                _make_leaf(_lind("nat")),
            ])
        )
        result = ted_similarity(tree_a, tree_b)
        assert 0.0 <= result <= 1.0

    def test_symmetry(self):
        """ted_similarity(a, b) == ted_similarity(b, a)."""
        from Poule.channels.ted import ted_similarity

        tree_a = _prepare_tree(
            _make_node(_lprod(), [
                _make_leaf(_lsort()),
                _make_leaf(_lrel(0)),
            ])
        )
        tree_b = _prepare_tree(
            _make_node(_lapp(), [
                _make_leaf(_lconst("f")),
                _make_leaf(_lrel(1)),
            ])
        )
        assert ted_similarity(tree_a, tree_b) == ted_similarity(tree_b, tree_a)
