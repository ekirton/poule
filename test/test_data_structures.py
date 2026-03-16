"""TDD tests for core data structures (specification/data-structures.md).

Tests are written BEFORE implementation. They will fail with ImportError
until the production modules exist under src/wily_rooster/models/.
"""

from __future__ import annotations

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# 1. Enumerations
# ═══════════════════════════════════════════════════════════════════════════


class TestSortKind:
    """SortKind enum — exactly 3 members: PROP, SET, TYPE_UNIV."""

    def test_has_exactly_three_members(self):
        from wily_rooster.models.enums import SortKind

        assert len(SortKind) == 3

    def test_prop_member_exists(self):
        from wily_rooster.models.enums import SortKind

        assert SortKind.PROP is not None

    def test_set_member_exists(self):
        from wily_rooster.models.enums import SortKind

        assert SortKind.SET is not None

    def test_type_univ_member_exists(self):
        from wily_rooster.models.enums import SortKind

        assert SortKind.TYPE_UNIV is not None

    def test_members_are_distinct(self):
        from wily_rooster.models.enums import SortKind

        members = [SortKind.PROP, SortKind.SET, SortKind.TYPE_UNIV]
        assert len(set(members)) == 3


class TestDeclKind:
    """DeclKind enum — 7 members with lowercase string values."""

    def test_has_exactly_seven_members(self):
        from wily_rooster.models.enums import DeclKind

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
        from wily_rooster.models.enums import DeclKind

        member = DeclKind[member_name]
        assert member.value == expected_value

    def test_all_values_are_lowercase_strings(self):
        from wily_rooster.models.enums import DeclKind

        for member in DeclKind:
            assert isinstance(member.value, str)
            assert member.value == member.value.lower()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Node Labels — Base class
# ═══════════════════════════════════════════════════════════════════════════


class TestNodeLabelBase:
    """NodeLabel abstract base — cannot be instantiated directly."""

    def test_cannot_instantiate_directly(self):
        from wily_rooster.models.labels import NodeLabel

        with pytest.raises(TypeError):
            NodeLabel()

    def test_concrete_subtypes_are_instances_of_node_label(self):
        from wily_rooster.models.labels import NodeLabel, LConst, LApp

        assert isinstance(LConst("x"), NodeLabel)
        assert isinstance(LApp(), NodeLabel)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Leaf Labels — Construction, equality, hashing, payload
# ═══════════════════════════════════════════════════════════════════════════


class TestLConst:
    """LConst(name: str) — fully qualified constant reference."""

    def test_construction_and_name_access(self):
        from wily_rooster.models.labels import LConst

        lc = LConst("Coq.Init.Nat.add")
        assert lc.name == "Coq.Init.Nat.add"

    def test_equality_same_name(self):
        from wily_rooster.models.labels import LConst

        assert LConst("Coq.Init.Nat.add") == LConst("Coq.Init.Nat.add")

    def test_inequality_different_name(self):
        from wily_rooster.models.labels import LConst

        assert LConst("Coq.Init.Nat.add") != LConst("Coq.Init.Nat.mul")

    def test_hashable_and_equal_hashes(self):
        from wily_rooster.models.labels import LConst

        a = LConst("x")
        b = LConst("x")
        assert hash(a) == hash(b)

    def test_usable_as_dict_key(self):
        from wily_rooster.models.labels import LConst

        d = {LConst("x"): 1}
        assert d[LConst("x")] == 1

    def test_usable_in_set(self):
        from wily_rooster.models.labels import LConst

        s = {LConst("x"), LConst("x"), LConst("y")}
        assert len(s) == 2


class TestLInd:
    """LInd(name: str) — fully qualified inductive type reference."""

    def test_construction_and_name_access(self):
        from wily_rooster.models.labels import LInd

        li = LInd("Coq.Init.Datatypes.nat")
        assert li.name == "Coq.Init.Datatypes.nat"

    def test_equality_same_name(self):
        from wily_rooster.models.labels import LInd

        assert LInd("nat") == LInd("nat")

    def test_inequality_different_name(self):
        from wily_rooster.models.labels import LInd

        assert LInd("nat") != LInd("bool")

    def test_hashable(self):
        from wily_rooster.models.labels import LInd

        assert hash(LInd("nat")) == hash(LInd("nat"))


class TestLConstruct:
    """LConstruct(name: str, index: int) — constructor reference."""

    def test_construction_and_payload_access(self):
        from wily_rooster.models.labels import LConstruct

        lc = LConstruct("Coq.Init.Datatypes.nat", 0)
        assert lc.name == "Coq.Init.Datatypes.nat"
        assert lc.index == 0

    def test_equality_same_name_and_index(self):
        from wily_rooster.models.labels import LConstruct

        assert LConstruct("nat", 0) == LConstruct("nat", 0)

    def test_inequality_different_index(self):
        from wily_rooster.models.labels import LConstruct

        assert LConstruct("nat", 0) != LConstruct("nat", 1)

    def test_inequality_different_name(self):
        from wily_rooster.models.labels import LConstruct

        assert LConstruct("nat", 0) != LConstruct("bool", 0)

    def test_hashable(self):
        from wily_rooster.models.labels import LConstruct

        assert hash(LConstruct("nat", 0)) == hash(LConstruct("nat", 0))

    def test_negative_index_raises_value_error(self):
        from wily_rooster.models.labels import LConstruct

        with pytest.raises(ValueError):
            LConstruct("nat", -1)

    def test_zero_index_is_valid(self):
        from wily_rooster.models.labels import LConstruct

        lc = LConstruct("nat", 0)
        assert lc.index == 0


class TestLCseVar:
    """LCseVar(id: int) — CSE placeholder variable."""

    def test_construction_and_id_access(self):
        from wily_rooster.models.labels import LCseVar

        lv = LCseVar(3)
        assert lv.id == 3

    def test_equality(self):
        from wily_rooster.models.labels import LCseVar

        assert LCseVar(0) == LCseVar(0)

    def test_inequality(self):
        from wily_rooster.models.labels import LCseVar

        assert LCseVar(0) != LCseVar(1)

    def test_hashable(self):
        from wily_rooster.models.labels import LCseVar

        assert hash(LCseVar(5)) == hash(LCseVar(5))

    def test_negative_id_raises_value_error(self):
        from wily_rooster.models.labels import LCseVar

        with pytest.raises(ValueError):
            LCseVar(-1)

    def test_zero_id_is_valid(self):
        from wily_rooster.models.labels import LCseVar

        assert LCseVar(0).id == 0


class TestLRel:
    """LRel(index: int) — de Bruijn index reference."""

    def test_construction_and_index_access(self):
        from wily_rooster.models.labels import LRel

        lr = LRel(0)
        assert lr.index == 0

    def test_equality(self):
        from wily_rooster.models.labels import LRel

        assert LRel(3) == LRel(3)

    def test_inequality(self):
        from wily_rooster.models.labels import LRel

        assert LRel(0) != LRel(1)

    def test_hashable(self):
        from wily_rooster.models.labels import LRel

        assert hash(LRel(0)) == hash(LRel(0))

    def test_negative_index_raises_value_error(self):
        from wily_rooster.models.labels import LRel

        with pytest.raises(ValueError):
            LRel(-1)

    def test_zero_index_is_valid(self):
        from wily_rooster.models.labels import LRel

        assert LRel(0).index == 0


class TestLSort:
    """LSort(kind: SortKind) — sort reference."""

    def test_construction_and_kind_access(self):
        from wily_rooster.models.labels import LSort
        from wily_rooster.models.enums import SortKind

        ls = LSort(SortKind.PROP)
        assert ls.kind == SortKind.PROP

    def test_equality_same_kind(self):
        from wily_rooster.models.labels import LSort
        from wily_rooster.models.enums import SortKind

        assert LSort(SortKind.PROP) == LSort(SortKind.PROP)

    def test_inequality_different_kind(self):
        from wily_rooster.models.labels import LSort
        from wily_rooster.models.enums import SortKind

        assert LSort(SortKind.PROP) != LSort(SortKind.SET)

    def test_hashable(self):
        from wily_rooster.models.labels import LSort
        from wily_rooster.models.enums import SortKind

        assert hash(LSort(SortKind.TYPE_UNIV)) == hash(LSort(SortKind.TYPE_UNIV))

    def test_all_sort_kinds(self):
        from wily_rooster.models.labels import LSort
        from wily_rooster.models.enums import SortKind

        for kind in SortKind:
            ls = LSort(kind)
            assert ls.kind == kind


class TestLPrimitive:
    """LPrimitive(value: int | float) — primitive literal."""

    def test_construction_with_int(self):
        from wily_rooster.models.labels import LPrimitive

        lp = LPrimitive(42)
        assert lp.value == 42

    def test_construction_with_float(self):
        from wily_rooster.models.labels import LPrimitive

        lp = LPrimitive(3.14)
        assert lp.value == 3.14

    def test_equality_int(self):
        from wily_rooster.models.labels import LPrimitive

        assert LPrimitive(42) == LPrimitive(42)

    def test_equality_float(self):
        from wily_rooster.models.labels import LPrimitive

        assert LPrimitive(3.14) == LPrimitive(3.14)

    def test_inequality_different_values(self):
        from wily_rooster.models.labels import LPrimitive

        assert LPrimitive(42) != LPrimitive(3.14)

    def test_hashable(self):
        from wily_rooster.models.labels import LPrimitive

        assert hash(LPrimitive(42)) == hash(LPrimitive(42))

    def test_int_and_float_same_numeric_value(self):
        """LPrimitive(1) and LPrimitive(1.0) — equality follows Python semantics."""
        from wily_rooster.models.labels import LPrimitive

        # In Python, 1 == 1.0 and hash(1) == hash(1.0), so frozen dataclass
        # will treat them as equal.
        assert LPrimitive(1) == LPrimitive(1.0)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Interior Labels — Construction, equality, hashing, payload
# ═══════════════════════════════════════════════════════════════════════════


class TestLApp:
    """LApp() — application node, no payload."""

    def test_construction(self):
        from wily_rooster.models.labels import LApp

        la = LApp()
        assert la is not None

    def test_equality(self):
        from wily_rooster.models.labels import LApp

        assert LApp() == LApp()

    def test_hashable(self):
        from wily_rooster.models.labels import LApp

        assert hash(LApp()) == hash(LApp())


class TestLAbs:
    """LAbs() — abstraction (lambda) node, no payload."""

    def test_construction(self):
        from wily_rooster.models.labels import LAbs

        assert LAbs() is not None

    def test_equality(self):
        from wily_rooster.models.labels import LAbs

        assert LAbs() == LAbs()

    def test_hashable(self):
        from wily_rooster.models.labels import LAbs

        assert hash(LAbs()) == hash(LAbs())


class TestLLet:
    """LLet() — let-in binding, no payload."""

    def test_construction(self):
        from wily_rooster.models.labels import LLet

        assert LLet() is not None

    def test_equality(self):
        from wily_rooster.models.labels import LLet

        assert LLet() == LLet()

    def test_hashable(self):
        from wily_rooster.models.labels import LLet

        assert hash(LLet()) == hash(LLet())


class TestLProj:
    """LProj(name: str) — projection with name payload."""

    def test_construction_and_name_access(self):
        from wily_rooster.models.labels import LProj

        lp = LProj("fst")
        assert lp.name == "fst"

    def test_equality_same_name(self):
        from wily_rooster.models.labels import LProj

        assert LProj("fst") == LProj("fst")

    def test_inequality_different_name(self):
        from wily_rooster.models.labels import LProj

        assert LProj("fst") != LProj("snd")

    def test_hashable(self):
        from wily_rooster.models.labels import LProj

        assert hash(LProj("fst")) == hash(LProj("fst"))


class TestLCase:
    """LCase(ind_name: str) — case/match node with inductive type name."""

    def test_construction_and_ind_name_access(self):
        from wily_rooster.models.labels import LCase

        lc = LCase("Coq.Init.Datatypes.nat")
        assert lc.ind_name == "Coq.Init.Datatypes.nat"

    def test_equality_same_ind_name(self):
        from wily_rooster.models.labels import LCase

        assert LCase("nat") == LCase("nat")

    def test_inequality_different_ind_name(self):
        from wily_rooster.models.labels import LCase

        assert LCase("nat") != LCase("bool")

    def test_hashable(self):
        from wily_rooster.models.labels import LCase

        assert hash(LCase("nat")) == hash(LCase("nat"))


class TestLProd:
    """LProd() — dependent product (forall), no payload."""

    def test_construction(self):
        from wily_rooster.models.labels import LProd

        assert LProd() is not None

    def test_equality(self):
        from wily_rooster.models.labels import LProd

        assert LProd() == LProd()

    def test_hashable(self):
        from wily_rooster.models.labels import LProd

        assert hash(LProd()) == hash(LProd())


class TestLFix:
    """LFix(mutual_index: int) — fixpoint with mutual index."""

    def test_construction_and_payload_access(self):
        from wily_rooster.models.labels import LFix

        lf = LFix(0)
        assert lf.mutual_index == 0

    def test_equality(self):
        from wily_rooster.models.labels import LFix

        assert LFix(0) == LFix(0)

    def test_inequality(self):
        from wily_rooster.models.labels import LFix

        assert LFix(0) != LFix(1)

    def test_hashable(self):
        from wily_rooster.models.labels import LFix

        assert hash(LFix(0)) == hash(LFix(0))

    def test_negative_mutual_index_raises_value_error(self):
        from wily_rooster.models.labels import LFix

        with pytest.raises(ValueError):
            LFix(-1)

    def test_zero_mutual_index_is_valid(self):
        from wily_rooster.models.labels import LFix

        assert LFix(0).mutual_index == 0


class TestLCoFix:
    """LCoFix(mutual_index: int) — cofixpoint with mutual index."""

    def test_construction_and_payload_access(self):
        from wily_rooster.models.labels import LCoFix

        lc = LCoFix(0)
        assert lc.mutual_index == 0

    def test_equality(self):
        from wily_rooster.models.labels import LCoFix

        assert LCoFix(0) == LCoFix(0)

    def test_inequality(self):
        from wily_rooster.models.labels import LCoFix

        assert LCoFix(0) != LCoFix(1)

    def test_hashable(self):
        from wily_rooster.models.labels import LCoFix

        assert hash(LCoFix(0)) == hash(LCoFix(0))

    def test_negative_mutual_index_raises_value_error(self):
        from wily_rooster.models.labels import LCoFix

        with pytest.raises(ValueError):
            LCoFix(-1)

    def test_zero_mutual_index_is_valid(self):
        from wily_rooster.models.labels import LCoFix

        assert LCoFix(0).mutual_index == 0


# ═══════════════════════════════════════════════════════════════════════════
# 5. Cross-type inequality
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossTypeInequality:
    """Labels of different concrete types are never equal, even with same payload."""

    def test_lconst_vs_lind_same_name(self):
        from wily_rooster.models.labels import LConst, LInd

        assert LConst("Coq.Init.Nat.add") != LInd("Coq.Init.Nat.add")

    def test_lconst_vs_lproj_same_name(self):
        from wily_rooster.models.labels import LConst, LProj

        assert LConst("fst") != LProj("fst")

    def test_lind_vs_lcase_same_name(self):
        from wily_rooster.models.labels import LInd, LCase

        assert LInd("nat") != LCase("nat")

    def test_lrel_vs_lcsevar_same_int(self):
        from wily_rooster.models.labels import LRel, LCseVar

        assert LRel(0) != LCseVar(0)

    def test_lfix_vs_lcofix_same_index(self):
        from wily_rooster.models.labels import LFix, LCoFix

        assert LFix(0) != LCoFix(0)

    def test_lapp_vs_labs(self):
        from wily_rooster.models.labels import LApp, LAbs

        assert LApp() != LAbs()

    def test_lapp_vs_llet(self):
        from wily_rooster.models.labels import LApp, LLet

        assert LApp() != LLet()

    def test_lapp_vs_lprod(self):
        from wily_rooster.models.labels import LApp, LProd

        assert LApp() != LProd()

    def test_lconstruct_vs_lrel_overlapping_index(self):
        """LConstruct and LRel both carry an int, but are different types."""
        from wily_rooster.models.labels import LConstruct, LRel

        assert LConstruct("nat", 0) != LRel(0)


# ═══════════════════════════════════════════════════════════════════════════
# 6. TreeNode construction
# ═══════════════════════════════════════════════════════════════════════════


class TestTreeNode:
    """TreeNode — mutable node with label, children, depth, node_id."""

    def test_leaf_construction(self, make_leaf):
        from wily_rooster.models.labels import LConst

        node = make_leaf(LConst("Coq.Init.Nat.add"))
        assert node.label == LConst("Coq.Init.Nat.add")
        assert node.children == []

    def test_default_depth_is_zero(self, make_leaf):
        from wily_rooster.models.labels import LConst

        node = make_leaf(LConst("x"))
        assert node.depth == 0

    def test_default_node_id_is_zero(self, make_leaf):
        from wily_rooster.models.labels import LConst

        node = make_leaf(LConst("x"))
        assert node.node_id == 0

    def test_interior_construction(self, make_leaf, make_node):
        from wily_rooster.models.labels import LApp, LConst, LPrimitive

        child_a = make_leaf(LConst("Coq.Init.Nat.add"))
        child_b = make_leaf(LPrimitive(1))
        node = make_node(LApp(), [child_a, child_b])
        assert node.label == LApp()
        assert len(node.children) == 2

    def test_depth_is_mutable(self, make_leaf):
        from wily_rooster.models.labels import LConst

        node = make_leaf(LConst("x"))
        node.depth = 5
        assert node.depth == 5

    def test_node_id_is_mutable(self, make_leaf):
        from wily_rooster.models.labels import LConst

        node = make_leaf(LConst("x"))
        node.node_id = 42
        assert node.node_id == 42


# ═══════════════════════════════════════════════════════════════════════════
# 7. ExprTree construction and validation
# ═══════════════════════════════════════════════════════════════════════════


class TestExprTree:
    """ExprTree — wrapper around root TreeNode with node_count."""

    def test_construction_single_leaf(self, make_leaf):
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import ExprTree

        root = make_leaf(LConst("Coq.Init.Nat.add"))
        tree = ExprTree(root=root, node_count=1)
        assert tree.root is root
        assert tree.node_count == 1

    def test_construction_with_children(self, make_leaf, make_node):
        from wily_rooster.models.labels import LProd, LInd
        from wily_rooster.models.tree import ExprTree

        root = make_node(LProd(), [
            make_leaf(LInd("Coq.Init.Datatypes.nat")),
            make_leaf(LInd("Coq.Init.Datatypes.nat")),
        ])
        tree = ExprTree(root=root, node_count=3)
        assert tree.node_count == 3

    def test_node_count_zero_raises_value_error(self, make_leaf):
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import ExprTree

        root = make_leaf(LConst("x"))
        with pytest.raises(ValueError):
            ExprTree(root=root, node_count=0)

    def test_node_count_negative_raises_value_error(self, make_leaf):
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import ExprTree

        root = make_leaf(LConst("x"))
        with pytest.raises(ValueError):
            ExprTree(root=root, node_count=-1)

    def test_node_count_one_is_valid(self, make_leaf):
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import ExprTree

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        assert tree.node_count == 1


# ═══════════════════════════════════════════════════════════════════════════
# 8. recompute_depths
# ═══════════════════════════════════════════════════════════════════════════


class TestRecomputeDepths:
    """recompute_depths(tree) — set depth on all nodes in place."""

    def test_single_leaf_depth_is_zero(self, make_leaf):
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import ExprTree, recompute_depths

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        recompute_depths(tree)
        assert tree.root.depth == 0

    def test_root_depth_is_zero(self, sample_prod_tree):
        from wily_rooster.models.tree import recompute_depths

        recompute_depths(sample_prod_tree)
        assert sample_prod_tree.root.depth == 0

    def test_children_depth_is_parent_plus_one(self, sample_prod_tree):
        from wily_rooster.models.tree import recompute_depths

        recompute_depths(sample_prod_tree)
        for child in sample_prod_tree.root.children:
            assert child.depth == 1

    def test_multi_level_depths(self, sample_app_tree):
        """LApp(LApp(LConst, LRel), LRel) — depths [0, 1, 2, 2, 1]."""
        from wily_rooster.models.tree import recompute_depths

        recompute_depths(sample_app_tree)
        root = sample_app_tree.root
        assert root.depth == 0
        inner = root.children[0]
        assert inner.depth == 1
        assert inner.children[0].depth == 2  # LConst
        assert inner.children[1].depth == 2  # LRel(1)
        assert root.children[1].depth == 1   # LRel(2)

    def test_idempotent(self, sample_prod_tree):
        from wily_rooster.models.tree import recompute_depths

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
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import ExprTree, recompute_depths

        root = make_leaf(LConst("x"))
        root.depth = 999  # bogus value
        tree = ExprTree(root=root, node_count=1)
        recompute_depths(tree)
        assert root.depth == 0  # corrected in place

    def test_returns_none(self, sample_prod_tree):
        from wily_rooster.models.tree import recompute_depths

        result = recompute_depths(sample_prod_tree)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# 9. assign_node_ids — pre-order traversal, sequential from 0
# ═══════════════════════════════════════════════════════════════════════════


class TestAssignNodeIds:
    """assign_node_ids(tree) — pre-order sequential IDs from 0."""

    def test_single_leaf_gets_id_zero(self, make_leaf):
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import ExprTree, assign_node_ids

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        assign_node_ids(tree)
        assert tree.root.node_id == 0

    def test_prod_tree_preorder_ids(self, sample_prod_tree):
        """LProd(LSort, LRel) — pre-order: root=0, left=1, right=2."""
        from wily_rooster.models.tree import assign_node_ids

        assign_node_ids(sample_prod_tree)
        assert sample_prod_tree.root.node_id == 0
        assert sample_prod_tree.root.children[0].node_id == 1
        assert sample_prod_tree.root.children[1].node_id == 2

    def test_app_tree_preorder_ids(self, sample_app_tree):
        """LApp(LApp(LConst, LRel), LRel) — pre-order: 0, 1, 2, 3, 4."""
        from wily_rooster.models.tree import assign_node_ids

        assign_node_ids(sample_app_tree)
        root = sample_app_tree.root
        assert root.node_id == 0
        inner = root.children[0]
        assert inner.node_id == 1
        assert inner.children[0].node_id == 2  # LConst
        assert inner.children[1].node_id == 3  # LRel(1)
        assert root.children[1].node_id == 4   # LRel(2)

    def test_ids_are_contiguous(self, sample_app_tree):
        from wily_rooster.models.tree import assign_node_ids

        assign_node_ids(sample_app_tree)

        def collect_ids(node):
            ids = [node.node_id]
            for child in node.children:
                ids.extend(collect_ids(child))
            return ids

        all_ids = sorted(collect_ids(sample_app_tree.root))
        assert all_ids == list(range(len(all_ids)))

    def test_idempotent(self, sample_prod_tree):
        from wily_rooster.models.tree import assign_node_ids

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

    def test_returns_none(self, sample_prod_tree):
        from wily_rooster.models.tree import assign_node_ids

        result = assign_node_ids(sample_prod_tree)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# 10. node_count
# ═══════════════════════════════════════════════════════════════════════════


class TestNodeCount:
    """node_count(tree) — total number of nodes (interior + leaf)."""

    def test_single_leaf_returns_one(self, make_leaf):
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import ExprTree, node_count

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        assert node_count(tree) == 1

    def test_prod_tree_returns_three(self, sample_prod_tree):
        from wily_rooster.models.tree import node_count

        assert node_count(sample_prod_tree) == 3

    def test_app_tree_returns_five(self, sample_app_tree):
        from wily_rooster.models.tree import node_count

        assert node_count(sample_app_tree) == 5

    def test_result_is_always_positive(self, make_leaf):
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import ExprTree, node_count

        root = make_leaf(LConst("x"))
        tree = ExprTree(root=root, node_count=1)
        assert node_count(tree) >= 1

    def test_pure_function_no_side_effects(self, sample_prod_tree):
        """Calling node_count does not modify depth or node_id."""
        from wily_rooster.models.tree import node_count

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
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import SearchResult

        sr = SearchResult(
            name="Coq.Init.Nat.add",
            statement="forall n m : nat, nat",
            type="nat -> nat -> nat",
            module="Coq.Init.Nat",
            kind=DeclKind.DEFINITION,
            score=0.95,
        )
        assert sr.name == "Coq.Init.Nat.add"
        assert sr.statement == "forall n m : nat, nat"
        assert sr.type == "nat -> nat -> nat"
        assert sr.module == "Coq.Init.Nat"
        assert sr.kind == DeclKind.DEFINITION
        assert sr.score == 0.95

    def test_kind_uses_declkind_enum(self):
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import SearchResult

        sr = SearchResult(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=0.5,
        )
        assert isinstance(sr.kind, DeclKind)

    def test_frozen_cannot_assign_name(self):
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import SearchResult

        sr = SearchResult(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=0.5,
        )
        with pytest.raises(AttributeError):
            sr.name = "y"

    def test_frozen_cannot_assign_score(self):
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import SearchResult

        sr = SearchResult(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=0.5,
        )
        with pytest.raises(AttributeError):
            sr.score = 0.99


class TestLemmaDetail:
    """LemmaDetail — extends SearchResult with extra fields, also frozen."""

    def test_construction_and_all_fields(self):
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import LemmaDetail

        ld = LemmaDetail(
            name="Coq.Arith.PeanoNat.Nat.add_comm",
            statement="forall n m : nat, n + m = m + n",
            type="nat -> nat -> Prop",
            module="Coq.Arith.PeanoNat",
            kind=DeclKind.LEMMA,
            score=1.0,
            dependencies=["Coq.Init.Nat.add"],
            dependents=["Coq.Arith.PeanoNat.Nat.add_assoc"],
            proof_sketch="induction on n",
            symbols=["Coq.Init.Nat.add", "eq"],
            node_count=15,
        )
        assert ld.name == "Coq.Arith.PeanoNat.Nat.add_comm"
        assert ld.dependencies == ["Coq.Init.Nat.add"]
        assert ld.dependents == ["Coq.Arith.PeanoNat.Nat.add_assoc"]
        assert ld.proof_sketch == "induction on n"
        assert ld.symbols == ["Coq.Init.Nat.add", "eq"]
        assert ld.node_count == 15

    def test_empty_dependencies_and_dependents(self):
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import LemmaDetail

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
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import LemmaDetail

        ld = LemmaDetail(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.THEOREM, score=0.8,
            dependencies=[], dependents=[], proof_sketch="",
            symbols=[], node_count=42,
        )
        assert ld.node_count == 42

    def test_frozen_cannot_assign_dependencies(self):
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import LemmaDetail

        ld = LemmaDetail(
            name="x", statement="s", type="t", module="m",
            kind=DeclKind.LEMMA, score=1.0,
            dependencies=[], dependents=[], proof_sketch="",
            symbols=[], node_count=1,
        )
        with pytest.raises(AttributeError):
            ld.dependencies = ["new"]

    def test_frozen_cannot_assign_node_count(self):
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import LemmaDetail

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
        from wily_rooster.models.enums import DeclKind
        from wily_rooster.models.responses import SearchResult, LemmaDetail

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
        from wily_rooster.models.responses import Module

        mod = Module(name="Coq.Arith.PeanoNat", decl_count=42)
        assert mod.name == "Coq.Arith.PeanoNat"
        assert mod.decl_count == 42

    def test_zero_decl_count_is_valid(self):
        from wily_rooster.models.responses import Module

        mod = Module(name="Empty.Module", decl_count=0)
        assert mod.decl_count == 0

    def test_frozen_cannot_assign_name(self):
        from wily_rooster.models.responses import Module

        mod = Module(name="x", decl_count=1)
        with pytest.raises(AttributeError):
            mod.name = "y"

    def test_frozen_cannot_assign_decl_count(self):
        from wily_rooster.models.responses import Module

        mod = Module(name="x", decl_count=1)
        with pytest.raises(AttributeError):
            mod.decl_count = 99


# ═══════════════════════════════════════════════════════════════════════════
# 12. Label immutability (frozen dataclass)
# ═══════════════════════════════════════════════════════════════════════════


class TestLabelImmutability:
    """All node labels are frozen — field assignment raises an error."""

    def test_lconst_frozen(self):
        from wily_rooster.models.labels import LConst

        lc = LConst("x")
        with pytest.raises(AttributeError):
            lc.name = "y"

    def test_lind_frozen(self):
        from wily_rooster.models.labels import LInd

        li = LInd("x")
        with pytest.raises(AttributeError):
            li.name = "y"

    def test_lconstruct_frozen(self):
        from wily_rooster.models.labels import LConstruct

        lc = LConstruct("x", 0)
        with pytest.raises(AttributeError):
            lc.index = 1

    def test_lcsevar_frozen(self):
        from wily_rooster.models.labels import LCseVar

        lv = LCseVar(0)
        with pytest.raises(AttributeError):
            lv.id = 1

    def test_lrel_frozen(self):
        from wily_rooster.models.labels import LRel

        lr = LRel(0)
        with pytest.raises(AttributeError):
            lr.index = 1

    def test_lsort_frozen(self):
        from wily_rooster.models.labels import LSort
        from wily_rooster.models.enums import SortKind

        ls = LSort(SortKind.PROP)
        with pytest.raises(AttributeError):
            ls.kind = SortKind.SET

    def test_lprimitive_frozen(self):
        from wily_rooster.models.labels import LPrimitive

        lp = LPrimitive(42)
        with pytest.raises(AttributeError):
            lp.value = 99

    def test_lproj_frozen(self):
        from wily_rooster.models.labels import LProj

        lp = LProj("fst")
        with pytest.raises(AttributeError):
            lp.name = "snd"

    def test_lcase_frozen(self):
        from wily_rooster.models.labels import LCase

        lc = LCase("nat")
        with pytest.raises(AttributeError):
            lc.ind_name = "bool"

    def test_lfix_frozen(self):
        from wily_rooster.models.labels import LFix

        lf = LFix(0)
        with pytest.raises(AttributeError):
            lf.mutual_index = 1

    def test_lcofix_frozen(self):
        from wily_rooster.models.labels import LCoFix

        lc = LCoFix(0)
        with pytest.raises(AttributeError):
            lc.mutual_index = 1


# ═══════════════════════════════════════════════════════════════════════════
# 13. Spec example: Nat.add (Section 8)
# ═══════════════════════════════════════════════════════════════════════════


class TestSpecExampleNatAdd:
    """Spec Section 8 — simple expression tree for Nat.add."""

    def test_single_const_tree(self):
        from wily_rooster.models.labels import LConst
        from wily_rooster.models.tree import TreeNode, ExprTree

        tree = ExprTree(
            root=TreeNode(label=LConst("Coq.Init.Nat.add"), children=[]),
            node_count=1,
        )
        assert tree.root.label == LConst("Coq.Init.Nat.add")
        assert tree.node_count == 1


class TestSpecExampleCurriedApp:
    """Spec Section 8 — Nat.add 1 2 as nested LApp."""

    def test_build_and_recompute_depths(self):
        from wily_rooster.models.labels import LApp, LConst, LPrimitive
        from wily_rooster.models.tree import TreeNode, ExprTree, recompute_depths

        inner = TreeNode(label=LApp(), children=[
            TreeNode(label=LConst("Coq.Init.Nat.add"), children=[]),
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
        from wily_rooster.models.labels import LApp, LConst, LPrimitive
        from wily_rooster.models.tree import TreeNode, ExprTree, assign_node_ids

        inner = TreeNode(label=LApp(), children=[
            TreeNode(label=LConst("Coq.Init.Nat.add"), children=[]),
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


class TestSpecExampleEquality:
    """Spec Section 8 — equality semantics examples."""

    def test_same_lconst_equal(self):
        from wily_rooster.models.labels import LConst

        assert LConst("Coq.Init.Nat.add") == LConst("Coq.Init.Nat.add")

    def test_lconst_vs_lind_not_equal(self):
        from wily_rooster.models.labels import LConst, LInd

        assert LConst("Coq.Init.Nat.add") != LInd("Coq.Init.Nat.add")

    def test_same_lsort_equal(self):
        from wily_rooster.models.labels import LSort
        from wily_rooster.models.enums import SortKind

        assert LSort(SortKind.PROP) == LSort(SortKind.PROP)

    def test_same_lconst_same_hash(self):
        from wily_rooster.models.labels import LConst

        assert hash(LConst("x")) == hash(LConst("x"))
