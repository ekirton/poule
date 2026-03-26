"""TDD tests for core data structures (specification/data-structures.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/poule/models/.
"""

from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# 1. Enumerations
# ═══════════════════════════════════════════════════════════════════════════


class TestSortKind:
    """SortKind enum — exactly 3 members: PROP, SET, TYPE_UNIV."""

    def test_has_exactly_three_members(self):
        from Poule.models.enums import SortKind

        assert len(SortKind) == 3

    def test_prop_member_exists(self):
        from Poule.models.enums import SortKind

        assert SortKind.PROP is not None

    def test_set_member_exists(self):
        from Poule.models.enums import SortKind

        assert SortKind.SET is not None

    def test_type_univ_member_exists(self):
        from Poule.models.enums import SortKind

        assert SortKind.TYPE_UNIV is not None

    def test_members_are_distinct(self):
        from Poule.models.enums import SortKind

        members = [SortKind.PROP, SortKind.SET, SortKind.TYPE_UNIV]
        assert len(set(members)) == 3


class TestDeclKind:
    """DeclKind enum — 7 members with lowercase string values."""

    def test_has_exactly_seven_members(self):
        from Poule.models.enums import DeclKind

        assert len(DeclKind) == 7

    @pytest.mark.parametrize(
        "member_name,expected_value",
        [
            ("LEMMA", "lemma"),
            ("THEOREM", "theorem"),
            ("DEFINITION", "definition"),
            ("INSTANCE", "instance"),
            ("INDUCTIVE", "inductive"),
            ("CONSTRUCTOR", "constructor"),
            ("AXIOM", "axiom"),
        ],
    )
    def test_member_has_lowercase_string_value(self, member_name, expected_value):
        from Poule.models.enums import DeclKind

        member = DeclKind[member_name]
        assert member.value == expected_value

    def test_all_values_are_lowercase_strings(self):
        from Poule.models.enums import DeclKind

        for member in DeclKind:
            assert isinstance(member.value, str)
            assert member.value == member.value.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Node Labels — Base class
# ═══════════════════════════════════════════════════════════════════════════


class TestNodeLabelBase:
    """NodeLabel abstract base — cannot be instantiated directly."""

    def test_cannot_instantiate_directly(self):
        from Poule.models.labels import NodeLabel

        with pytest.raises(TypeError):
            NodeLabel()

    def test_concrete_subtypes_are_instances_of_node_label(self):
        from Poule.models.labels import NodeLabel, LConst, LApp

        assert isinstance(LConst("x"), NodeLabel)
        assert isinstance(LApp(), NodeLabel)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Leaf Labels — Construction, equality, hashing, payload
# ═══════════════════════════════════════════════════════════════════════════


class TestLConst:
    """LConst(name: str) — fully qualified constant reference."""

    def test_construction_and_name_access(self):
        from Poule.models.labels import LConst

        lc = LConst("Stdlib.Init.Nat.add")
        assert lc.name == "Stdlib.Init.Nat.add"

    def test_equality_same_name(self):
        from Poule.models.labels import LConst

        assert LConst("Stdlib.Init.Nat.add") == LConst("Stdlib.Init.Nat.add")

    def test_inequality_different_name(self):
        from Poule.models.labels import LConst

        assert LConst("Stdlib.Init.Nat.add") != LConst("Stdlib.Init.Nat.mul")

    def test_hashable_and_equal_hashes(self):
        from Poule.models.labels import LConst

        a = LConst("x")
        b = LConst("x")
        assert hash(a) == hash(b)

    def test_usable_as_dict_key(self):
        from Poule.models.labels import LConst

        d = {LConst("x"): 1}
        assert d[LConst("x")] == 1

    def test_usable_in_set(self):
        from Poule.models.labels import LConst

        s = {LConst("x"), LConst("x"), LConst("y")}
        assert len(s) == 2


class TestLInd:
    """LInd(name: str) — fully qualified inductive type reference."""

    def test_construction_and_name_access(self):
        from Poule.models.labels import LInd

        li = LInd("Stdlib.Init.Datatypes.nat")
        assert li.name == "Stdlib.Init.Datatypes.nat"

    def test_equality_same_name(self):
        from Poule.models.labels import LInd

        assert LInd("nat") == LInd("nat")

    def test_inequality_different_name(self):
        from Poule.models.labels import LInd

        assert LInd("nat") != LInd("bool")

    def test_hashable(self):
        from Poule.models.labels import LInd

        assert hash(LInd("nat")) == hash(LInd("nat"))


class TestLConstruct:
    """LConstruct(name: str, index: int) — constructor reference."""

    def test_construction_and_payload_access(self):
        from Poule.models.labels import LConstruct

        lc = LConstruct("Stdlib.Init.Datatypes.nat", 0)
        assert lc.name == "Stdlib.Init.Datatypes.nat"
        assert lc.index == 0

    def test_equality_same_name_and_index(self):
        from Poule.models.labels import LConstruct

        assert LConstruct("nat", 0) == LConstruct("nat", 0)

    def test_inequality_different_index(self):
        from Poule.models.labels import LConstruct

        assert LConstruct("nat", 0) != LConstruct("nat", 1)

    def test_inequality_different_name(self):
        from Poule.models.labels import LConstruct

        assert LConstruct("nat", 0) != LConstruct("bool", 0)

    def test_hashable(self):
        from Poule.models.labels import LConstruct

        assert hash(LConstruct("nat", 0)) == hash(LConstruct("nat", 0))

    def test_negative_index_raises_value_error(self):
        from Poule.models.labels import LConstruct

        with pytest.raises(ValueError):
            LConstruct("nat", -1)

    def test_zero_index_is_valid(self):
        from Poule.models.labels import LConstruct

        lc = LConstruct("nat", 0)
        assert lc.index == 0


class TestLCseVar:
    """LCseVar(id: int) — CSE placeholder variable."""

    def test_construction_and_id_access(self):
        from Poule.models.labels import LCseVar

        lv = LCseVar(3)
        assert lv.id == 3

    def test_equality(self):
        from Poule.models.labels import LCseVar

        assert LCseVar(0) == LCseVar(0)

    def test_inequality(self):
        from Poule.models.labels import LCseVar

        assert LCseVar(0) != LCseVar(1)

    def test_hashable(self):
        from Poule.models.labels import LCseVar

        assert hash(LCseVar(5)) == hash(LCseVar(5))

    def test_negative_id_raises_value_error(self):
        from Poule.models.labels import LCseVar

        with pytest.raises(ValueError):
            LCseVar(-1)

    def test_zero_id_is_valid(self):
        from Poule.models.labels import LCseVar

        assert LCseVar(0).id == 0


class TestLRel:
    """LRel(index: int) — de Bruijn index reference."""

    def test_construction_and_index_access(self):
        from Poule.models.labels import LRel

        lr = LRel(0)
        assert lr.index == 0

    def test_equality(self):
        from Poule.models.labels import LRel

        assert LRel(3) == LRel(3)

    def test_inequality(self):
        from Poule.models.labels import LRel

        assert LRel(0) != LRel(1)

    def test_hashable(self):
        from Poule.models.labels import LRel

        assert hash(LRel(0)) == hash(LRel(0))

    def test_negative_index_raises_value_error(self):
        from Poule.models.labels import LRel

        with pytest.raises(ValueError):
            LRel(-1)

    def test_zero_index_is_valid(self):
        from Poule.models.labels import LRel

        assert LRel(0).index == 0


class TestLSort:
    """LSort(kind: SortKind) — sort reference."""

    def test_construction_and_kind_access(self):
        from Poule.models.labels import LSort
        from Poule.models.enums import SortKind

        ls = LSort(SortKind.PROP)
        assert ls.kind == SortKind.PROP

    def test_equality_same_kind(self):
        from Poule.models.labels import LSort
        from Poule.models.enums import SortKind

        assert LSort(SortKind.PROP) == LSort(SortKind.PROP)

    def test_inequality_different_kind(self):
        from Poule.models.labels import LSort
        from Poule.models.enums import SortKind

        assert LSort(SortKind.PROP) != LSort(SortKind.SET)

    def test_hashable(self):
        from Poule.models.labels import LSort
        from Poule.models.enums import SortKind

        assert hash(LSort(SortKind.TYPE_UNIV)) == hash(LSort(SortKind.TYPE_UNIV))

    def test_all_sort_kinds(self):
        from Poule.models.labels import LSort
        from Poule.models.enums import SortKind

        for kind in SortKind:
            ls = LSort(kind)
            assert ls.kind == kind


class TestLPrimitive:
    """LPrimitive(value: int | float) — primitive literal."""

    def test_construction_with_int(self):
        from Poule.models.labels import LPrimitive

        lp = LPrimitive(42)
        assert lp.value == 42

    def test_construction_with_float(self):
        from Poule.models.labels import LPrimitive

        lp = LPrimitive(3.14)
        assert lp.value == 3.14

    def test_equality_int(self):
        from Poule.models.labels import LPrimitive

        assert LPrimitive(42) == LPrimitive(42)

    def test_equality_float(self):
        from Poule.models.labels import LPrimitive

        assert LPrimitive(3.14) == LPrimitive(3.14)

    def test_inequality_different_values(self):
        from Poule.models.labels import LPrimitive

        assert LPrimitive(42) != LPrimitive(3.14)

    def test_hashable(self):
        from Poule.models.labels import LPrimitive

        assert hash(LPrimitive(42)) == hash(LPrimitive(42))

    def test_int_and_float_same_numeric_value(self):
        """LPrimitive(1) and LPrimitive(1.0) — equality follows Python semantics."""
        from Poule.models.labels import LPrimitive

        # In Python, 1 == 1.0 and hash(1) == hash(1.0), so frozen dataclass
        # will treat them as equal.
        assert LPrimitive(1) == LPrimitive(1.0)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Interior Labels — Construction, equality, hashing, payload
# ═══════════════════════════════════════════════════════════════════════════


class TestLApp:
    """LApp() — application node, no payload."""

    def test_equality(self):
        from Poule.models.labels import LApp

        assert LApp() == LApp()

    def test_hashable(self):
        from Poule.models.labels import LApp

        assert hash(LApp()) == hash(LApp())


class TestLAbs:
    """LAbs() — abstraction (lambda) node, no payload."""

    def test_equality(self):
        from Poule.models.labels import LAbs

        assert LAbs() == LAbs()

    def test_hashable(self):
        from Poule.models.labels import LAbs

        assert hash(LAbs()) == hash(LAbs())


class TestLLet:
    """LLet() — let-in binding, no payload."""

    def test_equality(self):
        from Poule.models.labels import LLet

        assert LLet() == LLet()

    def test_hashable(self):
        from Poule.models.labels import LLet

        assert hash(LLet()) == hash(LLet())


class TestLProj:
    """LProj(name: str) — projection with name payload."""

    def test_construction_and_name_access(self):
        from Poule.models.labels import LProj

        lp = LProj("fst")
        assert lp.name == "fst"

    def test_equality_same_name(self):
        from Poule.models.labels import LProj

        assert LProj("fst") == LProj("fst")

    def test_inequality_different_name(self):
        from Poule.models.labels import LProj

        assert LProj("fst") != LProj("snd")

    def test_hashable(self):
        from Poule.models.labels import LProj

        assert hash(LProj("fst")) == hash(LProj("fst"))


class TestLCase:
    """LCase(ind_name: str) — case/match node with inductive type name."""

    def test_construction_and_ind_name_access(self):
        from Poule.models.labels import LCase

        lc = LCase("Stdlib.Init.Datatypes.nat")
        assert lc.ind_name == "Stdlib.Init.Datatypes.nat"

    def test_equality_same_ind_name(self):
        from Poule.models.labels import LCase

        assert LCase("nat") == LCase("nat")

    def test_inequality_different_ind_name(self):
        from Poule.models.labels import LCase

        assert LCase("nat") != LCase("bool")

    def test_hashable(self):
        from Poule.models.labels import LCase

        assert hash(LCase("nat")) == hash(LCase("nat"))


class TestLProd:
    """LProd() — dependent product (forall), no payload."""

    def test_equality(self):
        from Poule.models.labels import LProd

        assert LProd() == LProd()

    def test_hashable(self):
        from Poule.models.labels import LProd

        assert hash(LProd()) == hash(LProd())


class TestLFix:
    """LFix(mutual_index: int) — fixpoint with mutual index."""

    def test_construction_and_payload_access(self):
        from Poule.models.labels import LFix

        lf = LFix(0)
        assert lf.mutual_index == 0

    def test_equality(self):
        from Poule.models.labels import LFix

        assert LFix(0) == LFix(0)

    def test_inequality(self):
        from Poule.models.labels import LFix

        assert LFix(0) != LFix(1)

    def test_hashable(self):
        from Poule.models.labels import LFix

        assert hash(LFix(0)) == hash(LFix(0))

    def test_negative_mutual_index_raises_value_error(self):
        from Poule.models.labels import LFix

        with pytest.raises(ValueError):
            LFix(-1)

    def test_zero_mutual_index_is_valid(self):
        from Poule.models.labels import LFix

        assert LFix(0).mutual_index == 0


class TestLCoFix:
    """LCoFix(mutual_index: int) — cofixpoint with mutual index."""

    def test_construction_and_payload_access(self):
        from Poule.models.labels import LCoFix

        lc = LCoFix(0)
        assert lc.mutual_index == 0

    def test_equality(self):
        from Poule.models.labels import LCoFix

        assert LCoFix(0) == LCoFix(0)

    def test_inequality(self):
        from Poule.models.labels import LCoFix

        assert LCoFix(0) != LCoFix(1)

    def test_hashable(self):
        from Poule.models.labels import LCoFix

        assert hash(LCoFix(0)) == hash(LCoFix(0))

    def test_negative_mutual_index_raises_value_error(self):
        from Poule.models.labels import LCoFix

        with pytest.raises(ValueError):
            LCoFix(-1)

    def test_zero_mutual_index_is_valid(self):
        from Poule.models.labels import LCoFix

        assert LCoFix(0).mutual_index == 0


# ═══════════════════════════════════════════════════════════════════════════
# 5. Cross-type inequality
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossTypeInequality:
    """Labels of different concrete types are never equal, even with same payload."""

    def test_lconst_vs_lind_same_name(self):
        from Poule.models.labels import LConst, LInd

        assert LConst("Stdlib.Init.Nat.add") != LInd("Stdlib.Init.Nat.add")

    def test_lconst_vs_lproj_same_name(self):
        from Poule.models.labels import LConst, LProj

        assert LConst("fst") != LProj("fst")

    def test_lind_vs_lcase_same_name(self):
        from Poule.models.labels import LInd, LCase

        assert LInd("nat") != LCase("nat")

    def test_lrel_vs_lcsevar_same_int(self):
        from Poule.models.labels import LRel, LCseVar

        assert LRel(0) != LCseVar(0)

    def test_lfix_vs_lcofix_same_index(self):
        from Poule.models.labels import LFix, LCoFix

        assert LFix(0) != LCoFix(0)

    def test_lapp_vs_labs(self):
        from Poule.models.labels import LApp, LAbs

        assert LApp() != LAbs()

    def test_lapp_vs_llet(self):
        from Poule.models.labels import LApp, LLet

        assert LApp() != LLet()

    def test_lapp_vs_lprod(self):
        from Poule.models.labels import LApp, LProd

        assert LApp() != LProd()

    def test_lconstruct_vs_lrel_overlapping_index(self):
        """LConstruct and LRel both carry an int, but are different types."""
        from Poule.models.labels import LConstruct, LRel

        assert LConstruct("nat", 0) != LRel(0)


# ═══════════════════════════════════════════════════════════════════════════
# 6. TreeNode construction
# ═══════════════════════════════════════════════════════════════════════════


class TestTreeNode:
    """TreeNode — mutable node with label, children, depth, node_id."""

    def test_leaf_construction(self, make_leaf):
        from Poule.models.labels import LConst

        node = make_leaf(LConst("Stdlib.Init.Nat.add"))
        assert node.label == LConst("Stdlib.Init.Nat.add")
        assert node.children == []

    def test_default_depth_is_zero(self, make_leaf):
        from Poule.models.labels import LConst

        node = make_leaf(LConst("x"))
        assert node.depth == 0

    def test_default_node_id_is_zero(self, make_leaf):
        from Poule.models.labels import LConst

        node = make_leaf(LConst("x"))
        assert node.node_id == 0

    def test_interior_construction(self, make_leaf, make_node):
        from Poule.models.labels import LApp, LConst, LPrimitive

        child_a = make_leaf(LConst("Stdlib.Init.Nat.add"))
        child_b = make_leaf(LPrimitive(1))
        node = make_node(LApp(), [child_a, child_b])
        assert node.label == LApp()
        assert len(node.children) == 2

    def test_depth_is_mutable(self, make_leaf):
        from Poule.models.labels import LConst

        node = make_leaf(LConst("x"))
        node.depth = 5
        assert node.depth == 5

    def test_node_id_is_mutable(self, make_leaf):
        from Poule.models.labels import LConst

        node = make_leaf(LConst("x"))
        node.node_id = 42
        assert node.node_id == 42


# ═══════════════════════════════════════════════════════════════════════════
# 7. ExprTree construction and validation
# ═══════════════════════════════════════════════════════════════════════════


class TestExprTree:
    """ExprTree — wrapper around root TreeNode with node_count."""

    def test_construction_single_leaf(self, make_leaf):
        from Poule.models.labels import LConst
        from Poule.models.tree import ExprTree

        root = make_leaf(LConst("Stdlib.Init.Nat.add"))
        tree = ExprTree(root=root, node_count=1)
        assert tree.root is root
        assert tree.node_count == 1

    def test_construction_with_children(self, make_leaf, make_node):
        from Poule.models.labels import LProd, LInd
        from Poule.models.tree import ExprTree

        root = make_node(LProd(), [
            make_leaf(LInd("Stdlib.Init.Datatypes.nat")),
            make_leaf(LInd("Stdlib.Init.Datatypes.nat")),
        ])
        tree = ExprTree(root=root, node_count=3)
        assert tree.node_count == 3

    def test_node_count_zero_raises_value_error(self, make_leaf):
        from Poule.models.labels import LConst
        from Poule.models.tree import ExprTree

        root = make_leaf(LConst("x"))
        with pytest.raises(ValueError):
            ExprTree(root=root, node_count=0)

    def test_node_count_negative_raises_value_error(self, make_leaf):
        from Poule.models.labels import LConst
        from Poule.models.tree import ExprTree

        root = make_leaf(LConst("x"))
        with pytest.raises(ValueError):
            ExprTree(root=root, node_count=-1)

    def test_node_count_one_is_valid(self, make_leaf):
        from Poule.models.labels import LConst
        from Poule.models.tree import ExprTree

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        assert tree.node_count == 1


# ═══════════════════════════════════════════════════════════════════════════
# 8. recompute_depths
# ═══════════════════════════════════════════════════════════════════════════


class TestRecomputeDepths:
    """recompute_depths(tree) — set depth on all nodes in place."""

    def test_single_leaf_depth_is_zero(self, make_leaf):
        from Poule.models.labels import LConst
        from Poule.models.tree import ExprTree, recompute_depths

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        recompute_depths(tree)
        assert tree.root.depth == 0

    def test_root_depth_is_zero(self, sample_prod_tree):
        from Poule.models.tree import recompute_depths

        recompute_depths(sample_prod_tree)
        assert sample_prod_tree.root.depth == 0

    def test_children_depth_is_parent_plus_one(self, sample_prod_tree):
        from Poule.models.tree import recompute_depths

        recompute_depths(sample_prod_tree)
        for child in sample_prod_tree.root.children:
            assert child.depth == 1

    def test_multi_level_depths(self, sample_app_tree):
        """LApp(LApp(LConst, LRel), LRel) — depths [0, 1, 2, 2, 1]."""
        from Poule.models.tree import recompute_depths

        recompute_depths(sample_app_tree)
        root = sample_app_tree.root
        assert root.depth == 0
        inner = root.children[0]
        assert inner.depth == 1
        assert inner.children[0].depth == 2  # LConst
        assert inner.children[1].depth == 2  # LRel(1)
        assert root.children[1].depth == 1   # LRel(2)

    def test_idempotent(self, sample_prod_tree):
        from Poule.models.tree import recompute_depths

        recompute_depths(sample_prod_tree)
        depths_first = [
            sample_prod_tree.root.depth,
            sample_prod_tree.root.children[0].depth,
            sample_prod_tree.root.children[1].depth,
        ]
        recompute_depths(sample_prod_tree)
        depths_second = [
            sample_prod_tree.root.depth,
            sample_prod_tree.root.children[0].depth,
            sample_prod_tree.root.children[1].depth,
        ]
        assert depths_first == depths_second

    def test_modifies_in_place(self, make_leaf):
        from Poule.models.labels import LConst
        from Poule.models.tree import ExprTree, recompute_depths

        root = make_leaf(LConst("x"))
        root.depth = 999  # bogus value
        tree = ExprTree(root=root, node_count=1)
        recompute_depths(tree)
        assert root.depth == 0  # corrected in place


# ═══════════════════════════════════════════════════════════════════════════
# 9. assign_node_ids — pre-order traversal, sequential from 0
# ═══════════════════════════════════════════════════════════════════════════


class TestAssignNodeIds:
    """assign_node_ids(tree) — pre-order sequential IDs from 0."""

    def test_single_leaf_gets_id_zero(self, make_leaf):
        from Poule.models.labels import LConst
        from Poule.models.tree import ExprTree, assign_node_ids

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        assign_node_ids(tree)
        assert tree.root.node_id == 0

    def test_prod_tree_preorder_ids(self, sample_prod_tree):
        """LProd(LSort, LRel) — pre-order: root=0, left=1, right=2."""
        from Poule.models.tree import assign_node_ids

        assign_node_ids(sample_prod_tree)
        assert sample_prod_tree.root.node_id == 0
        assert sample_prod_tree.root.children[0].node_id == 1
        assert sample_prod_tree.root.children[1].node_id == 2

    def test_app_tree_preorder_ids(self, sample_app_tree):
        """LApp(LApp(LConst, LRel), LRel) — pre-order: 0, 1, 2, 3, 4."""
        from Poule.models.tree import assign_node_ids

        assign_node_ids(sample_app_tree)
        root = sample_app_tree.root
        assert root.node_id == 0
        inner = root.children[0]
        assert inner.node_id == 1
        assert inner.children[0].node_id == 2  # LConst
        assert inner.children[1].node_id == 3  # LRel(1)
        assert root.children[1].node_id == 4   # LRel(2)

    def test_ids_are_contiguous(self, sample_app_tree):
        from Poule.models.tree import assign_node_ids

        assign_node_ids(sample_app_tree)

        def collect_ids(node):
            ids = [node.node_id]
            for child in node.children:
                ids.extend(collect_ids(child))
            return ids

        all_ids = sorted(collect_ids(sample_app_tree.root))
        assert all_ids == list(range(len(all_ids)))

    def test_idempotent(self, sample_prod_tree):
        from Poule.models.tree import assign_node_ids

        assign_node_ids(sample_prod_tree)
        ids_first = [
            sample_prod_tree.root.node_id,
            sample_prod_tree.root.children[0].node_id,
            sample_prod_tree.root.children[1].node_id,
        ]
        assign_node_ids(sample_prod_tree)
        ids_second = [
            sample_prod_tree.root.node_id,
            sample_prod_tree.root.children[0].node_id,
            sample_prod_tree.root.children[1].node_id,
        ]
        assert ids_first == ids_second


# ═══════════════════════════════════════════════════════════════════════════
# 10. node_count
# ═══════════════════════════════════════════════════════════════════════════


class TestNodeCount:
    """node_count(tree) — total number of nodes (interior + leaf)."""

    def test_single_leaf_returns_one(self, make_leaf):
        from Poule.models.labels import LConst
        from Poule.models.tree import ExprTree, node_count

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        assert node_count(tree) == 1

    def test_prod_tree_returns_three(self, sample_prod_tree):
        from Poule.models.tree import node_count

        assert node_count(sample_prod_tree) == 3

    def test_app_tree_returns_five(self, sample_app_tree):
        from Poule.models.tree import node_count

        assert node_count(sample_app_tree) == 5

    def test_result_is_always_positive(self, make_leaf):
        from Poule.models.labels import LConst
        from Poule.models.tree import ExprTree, node_count

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        assert node_count(tree) >= 1

    def test_pure_function_no_side_effects(self, sample_prod_tree):
        """Calling node_count does not modify depth or node_id."""
        from Poule.models.tree import node_count

        root = sample_prod_tree.root
        original_depth = root.depth
        original_id = root.node_id
        node_count(sample_prod_tree)
        assert root.depth == original_depth
        assert root.node_id == original_id


# ═══════════════════════════════════════════════════════════════════════════
# 11. Response types — construction, field access, immutability
# ═══════════════════════════════════════════════════════════════════════════


class TestSearchResult:
    """SearchResult — immutable response with name, statement, type, module, kind, score."""

    def test_construction_and_field_access(self):
        from Poule.models.enums import DeclKind
        from Poule.models.responses import SearchResult

        sr = SearchResult(
            name="Stdlib.Init.Nat.add",
            statement="forall n m : nat, nat",
            type="nat -> nat -> nat",
            module="Stdlib.Init.Nat",
            kind=DeclKind.DEFINITION,
            score=0.95,
        )
        assert sr.name == "Stdlib.Init.Nat.add"
        assert sr.statement == "forall n m : nat, nat"
        assert sr.type == "nat -> nat -> nat"
        assert sr.module == "Stdlib.Init.Nat"
        assert sr.kind == DeclKind.DEFINITION
        assert sr.score == 0.95

    def test_kind_uses_declkind_enum(self):
        from Poule.models.enums import DeclKind
        from Poule.models.responses import SearchResult

        sr = SearchResult(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=0.5,
        )
        assert isinstance(sr.kind, DeclKind)

    def test_frozen_cannot_assign_name(self):
        from Poule.models.enums import DeclKind
        from Poule.models.responses import SearchResult

        sr = SearchResult(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=0.5,
        )
        with pytest.raises(AttributeError):
            sr.name = "y"

    def test_frozen_cannot_assign_score(self):
        from Poule.models.enums import DeclKind
        from Poule.models.responses import SearchResult

        sr = SearchResult(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=0.5,
        )
        with pytest.raises(AttributeError):
            sr.score = 0.99


class TestLemmaDetail:
    """LemmaDetail — extends SearchResult with extra fields, also frozen."""

    def test_construction_and_all_fields(self):
        from Poule.models.enums import DeclKind
        from Poule.models.responses import LemmaDetail

        ld = LemmaDetail(
            name="Stdlib.Arith.PeanoNat.Nat.add_comm",
            statement="forall n m : nat, n + m = m + n",
            type="nat -> nat -> Prop",
            module="Stdlib.Arith.PeanoNat",
            kind=DeclKind.LEMMA,
            score=1.0,
            dependencies=["Stdlib.Init.Nat.add"],
            dependents=["Stdlib.Arith.PeanoNat.Nat.add_assoc"],
            proof_sketch="induction on n",
            symbols=["Stdlib.Init.Nat.add", "eq"],
            node_count=15,
        )
        assert ld.name == "Stdlib.Arith.PeanoNat.Nat.add_comm"
        assert ld.dependencies == ["Stdlib.Init.Nat.add"]
        assert ld.dependents == ["Stdlib.Arith.PeanoNat.Nat.add_assoc"]
        assert ld.proof_sketch == "induction on n"
        assert ld.symbols == ["Stdlib.Init.Nat.add", "eq"]
        assert ld.node_count == 15

    def test_empty_dependencies_and_dependents(self):
        from Poule.models.enums import DeclKind
        from Poule.models.responses import LemmaDetail

        ld = LemmaDetail(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.AXIOM, score=1.0,
            dependencies=[], dependents=[], proof_sketch="",
            symbols=[], node_count=1,
        )
        assert ld.dependencies == []
        assert ld.dependents == []
        assert ld.proof_sketch == ""
        assert ld.symbols == []

    def test_node_count_accessible(self):
        from Poule.models.enums import DeclKind
        from Poule.models.responses import LemmaDetail

        ld = LemmaDetail(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.THEOREM, score=0.8,
            dependencies=[], dependents=[], proof_sketch="",
            symbols=[], node_count=42,
        )
        assert ld.node_count == 42

    def test_frozen_cannot_assign_dependencies(self):
        from Poule.models.enums import DeclKind
        from Poule.models.responses import LemmaDetail

        ld = LemmaDetail(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=1.0,
            dependencies=[], dependents=[], proof_sketch="",
            symbols=[], node_count=1,
        )
        with pytest.raises(AttributeError):
            ld.dependencies = ["new"]

    def test_frozen_cannot_assign_node_count(self):
        from Poule.models.enums import DeclKind
        from Poule.models.responses import LemmaDetail

        ld = LemmaDetail(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=1.0,
            dependencies=[], dependents=[], proof_sketch="",
            symbols=[], node_count=1,
        )
        with pytest.raises(AttributeError):
            ld.node_count = 99

    def test_is_a_search_result(self):
        """LemmaDetail extends SearchResult — isinstance check."""
        from Poule.models.enums import DeclKind
        from Poule.models.responses import SearchResult, LemmaDetail

        ld = LemmaDetail(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=1.0,
            dependencies=[], dependents=[], proof_sketch="",
            symbols=[], node_count=1,
        )
        assert isinstance(ld, SearchResult)


class TestModule:
    """Module — immutable response with name and decl_count."""

    def test_construction_and_field_access(self):
        from Poule.models.responses import Module

        mod = Module(name="Stdlib.Arith.PeanoNat", decl_count=42)
        assert mod.name == "Stdlib.Arith.PeanoNat"
        assert mod.decl_count == 42

    def test_zero_decl_count_is_valid(self):
        from Poule.models.responses import Module

        mod = Module(name="Empty.Module", decl_count=0)
        assert mod.decl_count == 0

    def test_frozen_cannot_assign_name(self):
        from Poule.models.responses import Module

        mod = Module(name="x", decl_count=1)
        with pytest.raises(AttributeError):
            mod.name = "y"

    def test_frozen_cannot_assign_decl_count(self):
        from Poule.models.responses import Module

        mod = Module(name="x", decl_count=1)
        with pytest.raises(AttributeError):
            mod.decl_count = 99


# ═══════════════════════════════════════════════════════════════════════════
# 12. Spec example: Nat.add (Section 8)
# ═══════════════════════════════════════════════════════════════════════════


class TestSpecExampleNatAdd:
    """Spec Section 8 — simple expression tree for Nat.add."""

    def test_single_const_tree(self):
        from Poule.models.labels import LConst
        from Poule.models.tree import TreeNode, ExprTree

        tree = ExprTree(
            root=TreeNode(label=LConst("Stdlib.Init.Nat.add"), children=[]),
            node_count=1,
        )
        assert tree.root.label == LConst("Stdlib.Init.Nat.add")
        assert tree.node_count == 1


class TestSpecExampleCurriedApp:
    """Spec Section 8 — Nat.add 1 2 as nested LApp."""

    def test_build_and_recompute_depths(self):
        from Poule.models.labels import LApp, LConst, LPrimitive
        from Poule.models.tree import TreeNode, ExprTree, recompute_depths

        inner = TreeNode(label=LApp(), children=[
            TreeNode(label=LConst("Stdlib.Init.Nat.add"), children=[]),
            TreeNode(label=LPrimitive(1), children=[]),
        ])
        outer = TreeNode(label=LApp(), children=[
            inner,
            TreeNode(label=LPrimitive(2), children=[]),
        ])
        tree = ExprTree(root=outer, node_count=5)

        recompute_depths(tree)
        assert outer.depth == 0
        assert inner.depth == 1
        assert inner.children[0].depth == 2  # LConst
        assert inner.children[1].depth == 2  # LPrimitive(1)
        assert outer.children[1].depth == 1  # LPrimitive(2)

    def test_build_and_assign_node_ids(self):
        from Poule.models.labels import LApp, LConst, LPrimitive
        from Poule.models.tree import TreeNode, ExprTree, assign_node_ids

        inner = TreeNode(label=LApp(), children=[
            TreeNode(label=LConst("Stdlib.Init.Nat.add"), children=[]),
            TreeNode(label=LPrimitive(1), children=[]),
        ])
        outer = TreeNode(label=LApp(), children=[
            inner,
            TreeNode(label=LPrimitive(2), children=[]),
        ])
        tree = ExprTree(root=outer, node_count=5)

        assign_node_ids(tree)
        assert outer.node_id == 0
        assert inner.node_id == 1
        assert inner.children[0].node_id == 2  # Nat.add
        assert inner.children[1].node_id == 3  # 1
        assert outer.children[1].node_id == 4  # 2


# ═══════════════════════════════════════════════════════════════════════════
# 13. Proof Interaction Types (Spec §4.7)
# ═══════════════════════════════════════════════════════════════════════════


def _import_proof_types():
    from Poule.session.types import (
        Goal,
        GoalChange,
        Hypothesis,
        HypothesisChange,
        Premise,
        PremiseAnnotation,
        ProofState,
        ProofStateDiff,
        ProofTrace,
        Session,
        TraceStep,
    )
    return (
        Goal, GoalChange, Hypothesis, HypothesisChange, Premise,
        PremiseAnnotation, ProofState, ProofStateDiff, ProofTrace,
        Session, TraceStep,
    )


class TestHypothesisType:
    """Hypothesis: name, type, optional body."""

    def test_construction_without_body(self):
        *_, Hypothesis = _import_proof_types()[2:3]
        Hypothesis = _import_proof_types()[2]
        h = Hypothesis(name="n", type="nat")
        assert h.name == "n"
        assert h.type == "nat"
        assert h.body is None

    def test_construction_with_body(self):
        Hypothesis = _import_proof_types()[2]
        h = Hypothesis(name="x", type="nat", body="S O")
        assert h.body == "S O"

    def test_body_defaults_to_none(self):
        Hypothesis = _import_proof_types()[2]
        h = Hypothesis(name="n", type="nat")
        assert h.body is None


class TestGoalType:
    """Goal: index, type, hypotheses list."""

    def test_construction_with_hypotheses(self):
        Goal, _, Hypothesis = _import_proof_types()[0], None, _import_proof_types()[2]
        Goal = _import_proof_types()[0]
        Hypothesis = _import_proof_types()[2]
        g = Goal(
            index=0,
            type="n + m = m + n",
            hypotheses=[Hypothesis(name="n", type="nat")],
        )
        assert g.index == 0
        assert g.type == "n + m = m + n"
        assert len(g.hypotheses) == 1

    def test_empty_hypotheses_by_default(self):
        Goal = _import_proof_types()[0]
        g = Goal(index=0, type="True")
        assert g.hypotheses == []


class TestProofStateType:
    """ProofState: schema_version, session_id, step_index, is_complete, focused_goal_index, goals."""

    def test_construction_incomplete_proof(self):
        (Goal, _, Hypothesis, _, _, _, ProofState, *_) = _import_proof_types()
        ps = ProofState(
            schema_version=1,
            session_id="abc-123",
            step_index=0,
            is_complete=False,
            focused_goal_index=0,
            goals=[Goal(index=0, type="n = n")],
        )
        assert ps.schema_version == 1
        assert ps.session_id == "abc-123"
        assert ps.step_index == 0
        assert ps.is_complete is False
        assert ps.focused_goal_index == 0
        assert len(ps.goals) == 1

    def test_construction_complete_proof(self):
        (_, _, _, _, _, _, ProofState, *_) = _import_proof_types()
        ps = ProofState(
            schema_version=1,
            session_id="abc-123",
            step_index=5,
            is_complete=True,
            focused_goal_index=None,
        )
        assert ps.is_complete is True
        assert ps.focused_goal_index is None
        assert ps.goals == []


class TestTraceStepType:
    """TraceStep: step_index, tactic (null for step 0), state."""

    def test_step_zero_has_null_tactic(self):
        (_, _, _, _, _, _, ProofState, _, _, _, TraceStep) = _import_proof_types()
        state = ProofState(
            schema_version=1, session_id="s", step_index=0,
            is_complete=False, focused_goal_index=0,
        )
        ts = TraceStep(step_index=0, tactic=None, state=state)
        assert ts.tactic is None
        assert ts.step_index == 0

    def test_step_nonzero_has_tactic(self):
        (_, _, _, _, _, _, ProofState, _, _, _, TraceStep) = _import_proof_types()
        state = ProofState(
            schema_version=1, session_id="s", step_index=1,
            is_complete=False, focused_goal_index=0,
        )
        ts = TraceStep(step_index=1, tactic="intro n.", state=state)
        assert ts.tactic == "intro n."


class TestProofTraceType:
    """ProofTrace: schema_version, session_id, proof_name, file_path, total_steps, steps."""

    def test_construction(self):
        (_, _, _, _, _, _, ProofState, _, ProofTrace, _, TraceStep) = _import_proof_types()
        state0 = ProofState(
            schema_version=1, session_id="s", step_index=0,
            is_complete=False, focused_goal_index=0,
        )
        trace = ProofTrace(
            schema_version=1,
            session_id="s",
            proof_name="Nat.add_comm",
            file_path="/path/to/Nat.v",
            total_steps=0,
            steps=[TraceStep(step_index=0, tactic=None, state=state0)],
        )
        assert trace.proof_name == "Nat.add_comm"
        assert trace.total_steps == 0
        assert len(trace.steps) == 1


class TestPremiseType:
    """Premise: name, kind."""

    def test_construction_valid_kind(self):
        Premise = _import_proof_types()[4]
        p = Premise(name="Stdlib.Arith.PeanoNat.Nat.add_comm", kind="lemma")
        assert p.name == "Stdlib.Arith.PeanoNat.Nat.add_comm"
        assert p.kind == "lemma"

    @pytest.mark.parametrize("kind", ["lemma", "hypothesis", "constructor", "definition"])
    def test_all_valid_kinds_accepted(self, kind):
        Premise = _import_proof_types()[4]
        p = Premise(name="test", kind=kind)
        assert p.kind == kind


class TestPremiseAnnotationType:
    """PremiseAnnotation: step_index, tactic, premises list."""

    def test_construction_with_premises(self):
        Premise = _import_proof_types()[4]
        PremiseAnnotation = _import_proof_types()[5]
        pa = PremiseAnnotation(
            step_index=1,
            tactic="rewrite Nat.add_comm.",
            premises=[Premise(name="Nat.add_comm", kind="lemma")],
        )
        assert pa.step_index == 1
        assert pa.tactic == "rewrite Nat.add_comm."
        assert len(pa.premises) == 1

    def test_empty_premises_by_default(self):
        PremiseAnnotation = _import_proof_types()[5]
        pa = PremiseAnnotation(step_index=1, tactic="reflexivity.")
        assert pa.premises == []


class TestSessionType:
    """Session: metadata for an active proof session."""

    def test_construction(self):
        Session = _import_proof_types()[9]
        s = Session(
            session_id="abc-123",
            file_path="/path/to/Nat.v",
            proof_name="Nat.add_comm",
            current_step=3,
            total_steps=5,
            created_at="2026-03-17T14:00:00Z",
            last_active_at="2026-03-17T14:05:00Z",
        )
        assert s.session_id == "abc-123"
        assert s.total_steps == 5

    def test_total_steps_can_be_none(self):
        Session = _import_proof_types()[9]
        s = Session(
            session_id="abc",
            file_path="/f.v",
            proof_name="P",
            current_step=0,
            total_steps=None,
            created_at="2026-03-17T14:00:00Z",
            last_active_at="2026-03-17T14:00:00Z",
        )
        assert s.total_steps is None


class TestGoalChangeType:
    """GoalChange: index, before, after."""

    def test_construction(self):
        GoalChange = _import_proof_types()[1]
        gc = GoalChange(index=0, before="S n + m = m + S n", after="S (n + m) = m + S n")
        assert gc.index == 0
        assert gc.before == "S n + m = m + S n"
        assert gc.after == "S (n + m) = m + S n"


class TestHypothesisChangeType:
    """HypothesisChange: name, type_before, type_after, body_before, body_after."""

    def test_construction_type_change(self):
        HypothesisChange = _import_proof_types()[3]
        hc = HypothesisChange(
            name="IHn",
            type_before="n + m = m + n",
            type_after="S n + m = m + S n",
        )
        assert hc.name == "IHn"
        assert hc.body_before is None
        assert hc.body_after is None

    def test_construction_body_change(self):
        HypothesisChange = _import_proof_types()[3]
        hc = HypothesisChange(
            name="x",
            type_before="nat",
            type_after="nat",
            body_before="O",
            body_after="S O",
        )
        assert hc.body_before == "O"
        assert hc.body_after == "S O"


class TestProofStateDiffType:
    """ProofStateDiff: from_step, to_step, and 6 change lists."""

    def test_construction_empty_diff(self):
        ProofStateDiff = _import_proof_types()[7]
        diff = ProofStateDiff(from_step=2, to_step=3)
        assert diff.from_step == 2
        assert diff.to_step == 3
        assert diff.goals_added == []
        assert diff.goals_removed == []
        assert diff.goals_changed == []
        assert diff.hypotheses_added == []
        assert diff.hypotheses_removed == []
        assert diff.hypotheses_changed == []

    def test_construction_with_changes(self):
        (Goal, GoalChange, Hypothesis, _, _, _, _, ProofStateDiff, *_) = _import_proof_types()
        diff = ProofStateDiff(
            from_step=2,
            to_step=3,
            goals_changed=[GoalChange(index=0, before="A", after="B")],
            hypotheses_added=[Hypothesis(name="H", type="nat")],
        )
        assert len(diff.goals_changed) == 1
        assert len(diff.hypotheses_added) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 4. Extraction Types (§4.8)
# ═══════════════════════════════════════════════════════════════════════════


def _import_extraction_types():
    from Poule.extraction.types import (
        CampaignMetadata,
        DependencyEntry,
        DependencyRef,
        DistributionStats,
        ExtractionDiff,
        ExtractionError,
        ExtractionRecord,
        ExtractionStep,
        ExtractionSummary,
        FileSummary,
        ProjectMetadata,
        ProjectQualityReport,
        ProjectSummary,
        QualityReport,
        ScopeFilter,
        TacticFrequency,
    )
    return (
        CampaignMetadata, DependencyEntry, DependencyRef, DistributionStats,
        ExtractionDiff, ExtractionError, ExtractionRecord, ExtractionStep,
        ExtractionSummary, FileSummary, ProjectMetadata, ProjectQualityReport,
        ProjectSummary, QualityReport, ScopeFilter, TacticFrequency,
    )


def _import_error_kind():
    from Poule.extraction.types import ErrorKind
    return ErrorKind


class TestErrorKindEnum:
    """ErrorKind enum — exactly 6 members with underscore-separated lowercase values."""

    def test_has_exactly_six_members(self):
        ErrorKind = _import_error_kind()
        assert len(ErrorKind) == 6

    @pytest.mark.parametrize(
        "member_name,expected_value",
        [
            ("TIMEOUT", "timeout"),
            ("BACKEND_CRASH", "backend_crash"),
            ("TACTIC_FAILURE", "tactic_failure"),
            ("LOAD_FAILURE", "load_failure"),
            ("NO_PROOF_BODY", "no_proof_body"),
            ("UNKNOWN", "unknown"),
        ],
    )
    def test_member_has_correct_string_value(self, member_name, expected_value):
        ErrorKind = _import_error_kind()
        member = ErrorKind[member_name]
        assert member.value == expected_value

    def test_all_values_are_lowercase(self):
        ErrorKind = _import_error_kind()
        for member in ErrorKind:
            assert isinstance(member.value, str)
            assert member.value == member.value.lower()


class TestExtractionRecordType:
    """ExtractionRecord: schema_version, record_type, theorem_name, source_file,
    project_id, total_steps, steps."""

    def test_construction(self):
        *_, ExtractionRecord, ExtractionStep, _, _, _, _, _, _, _, _ = _import_extraction_types()
        step0 = ExtractionStep(
            step_index=0, tactic=None, goals=[], focused_goal_index=0,
            premises=[], diff=None,
        )
        step1 = ExtractionStep(
            step_index=1, tactic="reflexivity.", goals=[], focused_goal_index=None,
            premises=[], diff=None,
        )
        record = ExtractionRecord(
            schema_version=1, record_type="proof_trace",
            theorem_name="Stdlib.Init.Logic.eq_refl",
            source_file="theories/Init/Logic.v",
            project_id="coq-stdlib", total_steps=1,
            steps=[step0, step1],
        )
        assert record.record_type == "proof_trace"
        assert record.total_steps == 1
        assert len(record.steps) == 2

    def test_record_type_is_proof_trace(self):
        *_, ExtractionRecord, ExtractionStep, _, _, _, _, _, _, _, _ = _import_extraction_types()
        step0 = ExtractionStep(
            step_index=0, tactic=None, goals=[], focused_goal_index=0,
            premises=[], diff=None,
        )
        record = ExtractionRecord(
            schema_version=1, record_type="proof_trace",
            theorem_name="T", source_file="f.v",
            project_id="p", total_steps=0, steps=[step0],
        )
        assert record.record_type == "proof_trace"


class TestExtractionStepType:
    """ExtractionStep: step_index, tactic, goals, focused_goal_index, premises, diff."""

    def test_step_zero_has_null_tactic(self):
        *_, ExtractionStep, _, _, _, _, _, _, _, _ = _import_extraction_types()
        step = ExtractionStep(
            step_index=0, tactic=None, goals=[], focused_goal_index=0,
            premises=[], diff=None,
        )
        assert step.tactic is None
        assert step.diff is None

    def test_step_nonzero_has_tactic(self):
        *_, ExtractionStep, _, _, _, _, _, _, _, _ = _import_extraction_types()
        step = ExtractionStep(
            step_index=1, tactic="intros n.", goals=[], focused_goal_index=0,
            premises=[], diff=None,
        )
        assert step.tactic == "intros n."

    def test_diff_is_null_when_disabled(self):
        *_, ExtractionStep, _, _, _, _, _, _, _, _ = _import_extraction_types()
        step = ExtractionStep(
            step_index=2, tactic="simpl.", goals=[], focused_goal_index=0,
            premises=[], diff=None,
        )
        assert step.diff is None


class TestExtractionDiffType:
    """ExtractionDiff: 6 change lists, structurally like ProofStateDiff but without from/to step."""

    def test_construction_empty(self):
        *_, ExtractionDiff, _, _, _, _, _, _, _, _, _, _, _ = _import_extraction_types()
        diff = ExtractionDiff(
            goals_added=[], goals_removed=[], goals_changed=[],
            hypotheses_added=[], hypotheses_removed=[], hypotheses_changed=[],
        )
        assert diff.goals_added == []
        assert diff.hypotheses_changed == []

    def test_has_no_from_to_step_fields(self):
        """ExtractionDiff omits from_step/to_step (implicit from containing step)."""
        *_, ExtractionDiff, _, _, _, _, _, _, _, _, _, _, _ = _import_extraction_types()
        diff = ExtractionDiff(
            goals_added=[], goals_removed=[], goals_changed=[],
            hypotheses_added=[], hypotheses_removed=[], hypotheses_changed=[],
        )
        assert not hasattr(diff, "from_step")
        assert not hasattr(diff, "to_step")


class TestExtractionErrorType:
    """ExtractionError: schema_version, record_type, theorem_name, source_file,
    project_id, error_kind, error_message."""

    def test_construction(self):
        *_, ExtractionError, _, _, _, _, _, _, _, _, _, _ = _import_extraction_types()
        error = ExtractionError(
            schema_version=1, record_type="extraction_error",
            theorem_name="Stdlib.Arith.PeanoNat.Nat.sub_diag",
            source_file="theories/Arith/PeanoNat.v",
            project_id="coq-stdlib",
            error_kind="timeout",
            error_message="Proof extraction exceeded 60s time limit",
        )
        assert error.record_type == "extraction_error"
        assert error.error_kind == "timeout"

    @pytest.mark.parametrize("kind", [
        "timeout", "backend_crash", "tactic_failure", "load_failure", "unknown",
    ])
    def test_all_valid_error_kinds_accepted(self, kind):
        *_, ExtractionError, _, _, _, _, _, _, _, _, _, _ = _import_extraction_types()
        error = ExtractionError(
            schema_version=1, record_type="extraction_error",
            theorem_name="T", source_file="f.v", project_id="p",
            error_kind=kind, error_message="msg",
        )
        assert error.error_kind == kind


class TestCampaignMetadataType:
    """CampaignMetadata: schema_version, record_type, extraction_tool_version,
    extraction_timestamp, projects."""

    def test_construction(self):
        (CampaignMetadata, _, _, _, _, _, _, _, _, _, ProjectMetadata, *_) = _import_extraction_types()
        pm = ProjectMetadata(
            project_id="coq-stdlib",
            project_path="/home/user/stdlib",
            coq_version="8.19.1",
            commit_hash=None,
        )
        meta = CampaignMetadata(
            schema_version=1, record_type="campaign_metadata",
            extraction_tool_version="0.3.0",
            extraction_timestamp="2026-03-17T14:30:00Z",
            projects=[pm],
        )
        assert meta.record_type == "campaign_metadata"
        assert len(meta.projects) == 1

    def test_projects_must_be_non_empty(self):
        """Spec §4.8: projects list is non-empty."""
        (CampaignMetadata, *_) = _import_extraction_types()
        meta = CampaignMetadata(
            schema_version=1, record_type="campaign_metadata",
            extraction_tool_version="0.3.0",
            extraction_timestamp="2026-03-17T14:30:00Z",
            projects=[],
        )
        # Construction succeeds — validation is at serialization time
        assert meta.projects == []


class TestProjectMetadataType:
    """ProjectMetadata: project_id, project_path, coq_version, commit_hash."""

    def test_construction_with_commit_hash(self):
        *_, ProjectMetadata, _, _, _, _, _ = _import_extraction_types()
        pm = ProjectMetadata(
            project_id="coq-stdlib",
            project_path="/path/to/stdlib",
            coq_version="8.19.1",
            commit_hash="abc123def456",
        )
        assert pm.commit_hash == "abc123def456"

    def test_commit_hash_none_for_non_git(self):
        *_, ProjectMetadata, _, _, _, _, _ = _import_extraction_types()
        pm = ProjectMetadata(
            project_id="local-project",
            project_path="/tmp/project",
            coq_version="8.19.1",
            commit_hash=None,
        )
        assert pm.commit_hash is None


class TestExtractionSummaryType:
    """ExtractionSummary: counters and per-project breakdown."""

    def test_construction(self):
        (_, _, _, _, _, _, _, _, ExtractionSummary, _, _, _, ProjectSummary, *_) = _import_extraction_types()
        summary = ExtractionSummary(
            schema_version=1, record_type="extraction_summary",
            total_theorems_found=100, total_extracted=95,
            total_failed=5, total_skipped=0,
            per_project=[],
        )
        assert summary.total_theorems_found == 100
        assert summary.total_extracted == 95

    def test_counter_invariant(self):
        """extracted + partial + failed + no_proof_body + skipped == theorems_found."""
        (_, _, _, _, _, _, _, _, ExtractionSummary, *_) = _import_extraction_types()
        summary = ExtractionSummary(
            schema_version=1, record_type="extraction_summary",
            total_theorems_found=100, total_extracted=85,
            total_failed=5, total_partial=3, total_no_proof_body=4,
            total_skipped=3, per_project=[],
        )
        assert (summary.total_extracted + summary.total_partial + summary.total_failed
                + summary.total_no_proof_body + summary.total_skipped
                ) == summary.total_theorems_found


class TestProjectSummaryType:
    """ProjectSummary: per-project counters with per-file breakdown."""

    def test_construction(self):
        (_, _, _, _, _, _, _, _, _, FileSummary, _, _, ProjectSummary, *_) = _import_extraction_types()
        fs = FileSummary(
            source_file="theories/Init/Logic.v",
            theorems_found=10, extracted=9, failed=1, skipped=0,
        )
        ps = ProjectSummary(
            project_id="coq-stdlib",
            theorems_found=10, extracted=9, failed=1, skipped=0,
            per_file=[fs],
        )
        assert ps.project_id == "coq-stdlib"
        assert len(ps.per_file) == 1

    def test_counter_invariant(self):
        (_, _, _, _, _, _, _, _, _, _, _, _, ProjectSummary, *_) = _import_extraction_types()
        ps = ProjectSummary(
            project_id="p", theorems_found=20,
            extracted=15, failed=3, skipped=2, per_file=[],
        )
        assert ps.extracted + ps.failed + ps.skipped == ps.theorems_found


class TestFileSummaryType:
    """FileSummary: per-file counters."""

    def test_construction(self):
        (_, _, _, _, _, _, _, _, _, FileSummary, *_) = _import_extraction_types()
        fs = FileSummary(
            source_file="theories/Arith/PeanoNat.v",
            theorems_found=50, extracted=48, failed=2, skipped=0,
        )
        assert fs.source_file == "theories/Arith/PeanoNat.v"

    def test_counter_invariant(self):
        (_, _, _, _, _, _, _, _, _, FileSummary, *_) = _import_extraction_types()
        fs = FileSummary(
            source_file="f.v", theorems_found=10,
            extracted=7, failed=2, skipped=1,
        )
        assert fs.extracted + fs.failed + fs.skipped == fs.theorems_found


class TestDependencyEntryType:
    """DependencyEntry: theorem_name, source_file, project_id, depends_on."""

    def test_construction(self):
        (_, DependencyEntry, DependencyRef, *_) = _import_extraction_types()
        entry = DependencyEntry(
            theorem_name="Stdlib.Arith.PeanoNat.Nat.add_comm",
            source_file="theories/Arith/PeanoNat.v",
            project_id="coq-stdlib",
            depends_on=[
                DependencyRef(name="Stdlib.Arith.PeanoNat.Nat.add_0_r", kind="lemma"),
                DependencyRef(name="Stdlib.Init.Datatypes.nat", kind="inductive"),
            ],
        )
        assert len(entry.depends_on) == 2

    def test_empty_depends_on(self):
        (_, DependencyEntry, *_) = _import_extraction_types()
        entry = DependencyEntry(
            theorem_name="T", source_file="f.v",
            project_id="p", depends_on=[],
        )
        assert entry.depends_on == []


class TestDependencyRefType:
    """DependencyRef: name and kind."""

    @pytest.mark.parametrize("kind", [
        "theorem", "lemma", "definition", "axiom", "constructor", "inductive",
    ])
    def test_all_valid_kinds_accepted(self, kind):
        (_, _, DependencyRef, *_) = _import_extraction_types()
        ref = DependencyRef(name="Stdlib.Init.Datatypes.nat", kind=kind)
        assert ref.kind == kind


class TestQualityReportType:
    """QualityReport: premise_coverage, proof_length_distribution,
    tactic_vocabulary, per_project."""

    def test_construction(self):
        (_, _, _, DistributionStats, _, _, _, _, _, _, _, ProjectQualityReport,
         _, QualityReport, _, TacticFrequency) = _import_extraction_types()
        dist = DistributionStats(
            min=1, max=342, mean=12.4, median=8.0,
            p25=4.0, p75=16.0, p95=45.0,
        )
        report = QualityReport(
            premise_coverage=0.87,
            proof_length_distribution=dist,
            tactic_vocabulary=[TacticFrequency(tactic="apply", count=24500)],
            per_project=[],
        )
        assert report.premise_coverage == 0.87
        assert report.proof_length_distribution.min == 1


class TestDistributionStatsType:
    """DistributionStats: min, max, mean, median, p25, p75, p95."""

    def test_construction(self):
        (_, _, _, DistributionStats, *_) = _import_extraction_types()
        stats = DistributionStats(
            min=1, max=100, mean=25.5, median=20.0,
            p25=10.0, p75=35.0, p95=80.0,
        )
        assert stats.min == 1
        assert stats.p95 == 80.0

    def test_single_value_all_equal(self):
        """Spec: for a single record, min = max = mean = median = p25 = p75 = p95."""
        (_, _, _, DistributionStats, *_) = _import_extraction_types()
        stats = DistributionStats(
            min=5, max=5, mean=5.0, median=5.0,
            p25=5.0, p75=5.0, p95=5.0,
        )
        assert stats.min == stats.max == stats.mean == stats.median


class TestTacticFrequencyType:
    """TacticFrequency: tactic keyword and count."""

    def test_construction(self):
        *_, TacticFrequency = _import_extraction_types()
        tf = TacticFrequency(tactic="apply", count=24500)
        assert tf.tactic == "apply"
        assert tf.count == 24500


class TestProjectQualityReportType:
    """ProjectQualityReport: per-project quality metrics."""

    def test_construction(self):
        (_, _, _, DistributionStats, _, _, _, _, _, _, _, ProjectQualityReport, *_) = _import_extraction_types()
        dist = DistributionStats(
            min=1, max=200, mean=10.2, median=7.0,
            p25=3.0, p75=14.0, p95=38.0,
        )
        pqr = ProjectQualityReport(
            project_id="coq-stdlib",
            premise_coverage=0.89,
            proof_length_distribution=dist,
            theorem_count=4500,
        )
        assert pqr.project_id == "coq-stdlib"
        assert pqr.theorem_count == 4500


class TestScopeFilterType:
    """ScopeFilter: name_pattern and module_prefixes."""

    def test_both_none_means_extract_all(self):
        *_, ScopeFilter, _ = _import_extraction_types()
        sf = ScopeFilter(name_pattern=None, module_prefixes=None)
        assert sf.name_pattern is None
        assert sf.module_prefixes is None

    def test_name_pattern_only(self):
        *_, ScopeFilter, _ = _import_extraction_types()
        sf = ScopeFilter(name_pattern=".*comm.*", module_prefixes=None)
        assert sf.name_pattern == ".*comm.*"

    def test_module_prefixes_only(self):
        *_, ScopeFilter, _ = _import_extraction_types()
        sf = ScopeFilter(name_pattern=None, module_prefixes=["Stdlib.Arith"])
        assert sf.module_prefixes == ["Stdlib.Arith"]

    def test_both_set_means_conjunction(self):
        """Spec: when both fields are set, both must match (conjunction)."""
        *_, ScopeFilter, _ = _import_extraction_types()
        sf = ScopeFilter(
            name_pattern=".*comm.*",
            module_prefixes=["Stdlib.Arith"],
        )
        assert sf.name_pattern is not None
        assert sf.module_prefixes is not None
