"""TDD tests for Coq expression normalization (coq-normalization spec).

Tests are written BEFORE implementation exists. They will fail with
ImportError until the production modules are created.

Covers:
- ConstrNode variants and constr_to_tree() adaptation rules
- coq_normalize() pipeline (depths, node_ids, node_count)
- NormalizationError conditions
- Determinism guarantee
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Import helpers — these will fail until implementation exists (TDD)
# ---------------------------------------------------------------------------

def _import_constr_nodes():
    from Poule.normalization.constr_node import (
        Rel, Var, Sort, Cast, Prod, Lambda, LetIn, App,
        Const, Ind, Construct, Case, Fix, CoFix, Proj, Int, Float,
    )
    return (
        Rel, Var, Sort, Cast, Prod, Lambda, LetIn, App,
        Const, Ind, Construct, Case, Fix, CoFix, Proj, Int, Float,
    )


def _import_normalize():
    from Poule.normalization.normalize import constr_to_tree, coq_normalize
    return constr_to_tree, coq_normalize


def _import_errors():
    from Poule.normalization.errors import NormalizationError
    return NormalizationError


def _import_labels():
    from Poule.models.labels import (
        LRel, LConst, LInd, LConstruct, LSort, LPrimitive,
        LApp, LAbs, LLet, LProj, LCase, LProd, LFix, LCoFix,
    )
    return (
        LRel, LConst, LInd, LConstruct, LSort, LPrimitive,
        LApp, LAbs, LLet, LProj, LCase, LProd, LFix, LCoFix,
    )


def _import_enums():
    from Poule.models.enums import SortKind
    return SortKind


def _import_tree():
    from Poule.models.tree import TreeNode, ExprTree
    return TreeNode, ExprTree


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def constr():
    """Provide all ConstrNode constructors as a namespace object."""
    (Rel, Var, Sort, Cast, Prod, Lambda, LetIn, App,
     Const, Ind, Construct, Case, Fix, CoFix, Proj, Int, Float) = _import_constr_nodes()

    class _NS:
        pass

    ns = _NS()
    ns.Rel = Rel
    ns.Var = Var
    ns.Sort = Sort
    ns.Cast = Cast
    ns.Prod = Prod
    ns.Lambda = Lambda
    ns.LetIn = LetIn
    ns.App = App
    ns.Const = Const
    ns.Ind = Ind
    ns.Construct = Construct
    ns.Case = Case
    ns.Fix = Fix
    ns.CoFix = CoFix
    ns.Proj = Proj
    ns.Int = Int
    ns.Float = Float
    return ns


@pytest.fixture
def c2t():
    """Return the constr_to_tree function."""
    constr_to_tree, _ = _import_normalize()
    return constr_to_tree


@pytest.fixture
def normalize():
    """Return the coq_normalize function."""
    _, coq_normalize = _import_normalize()
    return coq_normalize


@pytest.fixture
def labels():
    """Provide all label constructors as a namespace."""
    (LRel, LConst, LInd, LConstruct, LSort, LPrimitive,
     LApp, LAbs, LLet, LProj, LCase, LProd, LFix, LCoFix) = _import_labels()

    class _NS:
        pass

    ns = _NS()
    ns.LRel = LRel
    ns.LConst = LConst
    ns.LInd = LInd
    ns.LConstruct = LConstruct
    ns.LSort = LSort
    ns.LPrimitive = LPrimitive
    ns.LApp = LApp
    ns.LAbs = LAbs
    ns.LLet = LLet
    ns.LProj = LProj
    ns.LCase = LCase
    ns.LProd = LProd
    ns.LFix = LFix
    ns.LCoFix = LCoFix
    return ns


@pytest.fixture
def SortKind():
    return _import_enums()


# ===================================================================
# 1. Direct-mapping variants: Rel, Const, Ind
# ===================================================================

class TestDirectMappingVariants:
    """Rel → LRel, Const → LConst, Ind → LInd — leaf nodes, no adaptation."""

    def test_rel_produces_lrel(self, constr, c2t, labels):
        node = constr.Rel(3)
        result = c2t(node)
        assert result.label == labels.LRel(3)
        assert result.children == []

    def test_rel_zero(self, constr, c2t, labels):
        result = c2t(constr.Rel(0))
        assert result.label == labels.LRel(0)
        assert result.children == []

    def test_const_produces_lconst(self, constr, c2t, labels):
        node = constr.Const("Stdlib.Init.Nat.add")
        result = c2t(node)
        assert result.label == labels.LConst("Stdlib.Init.Nat.add")
        assert result.children == []

    def test_ind_produces_lind(self, constr, c2t, labels):
        node = constr.Ind("Stdlib.Init.Datatypes.nat")
        result = c2t(node)
        assert result.label == labels.LInd("Stdlib.Init.Datatypes.nat")
        assert result.children == []


# ===================================================================
# 2. Currification — App with 0, 1, 2, 3+ args
# ===================================================================

class TestCurrification:
    """App(f, args) → nested binary LApp nodes via left-fold."""

    def test_app_zero_args_returns_func_tree(self, constr, c2t, labels):
        """App(f, []) → constr_to_tree(f), no LApp wrapper."""
        node = constr.App(constr.Const("f"), [])
        result = c2t(node)
        assert result.label == labels.LConst("f")
        assert result.children == []

    def test_app_one_arg_produces_single_lapp(self, constr, c2t, labels):
        """App(f, [a]) → LApp(f, a)."""
        node = constr.App(constr.Const("f"), [constr.Rel(1)])
        result = c2t(node)
        assert result.label == labels.LApp()
        assert len(result.children) == 2
        assert result.children[0].label == labels.LConst("f")
        assert result.children[1].label == labels.LRel(1)

    def test_app_two_args_produces_nested_lapp(self, constr, c2t, labels):
        """App(f, [a1, a2]) → LApp(LApp(f, a1), a2)."""
        node = constr.App(
            constr.Const("Stdlib.Init.Nat.add"),
            [constr.Rel(1), constr.Rel(2)],
        )
        result = c2t(node)
        # Outer LApp
        assert result.label == labels.LApp()
        assert len(result.children) == 2
        # Inner LApp
        inner = result.children[0]
        assert inner.label == labels.LApp()
        assert inner.children[0].label == labels.LConst("Stdlib.Init.Nat.add")
        assert inner.children[1].label == labels.LRel(1)
        # Second arg
        assert result.children[1].label == labels.LRel(2)

    def test_app_three_args_produces_three_nested_lapps(self, constr, c2t, labels):
        """App(f, [a, b, c]) → LApp(LApp(LApp(f, a), b), c) — spec example."""
        node = constr.App(
            constr.Const("f"),
            [constr.Rel(1), constr.Rel(2), constr.Rel(3)],
        )
        result = c2t(node)
        # Outermost: LApp(_, c)
        assert result.label == labels.LApp()
        assert result.children[1].label == labels.LRel(3)
        # Middle: LApp(_, b)
        mid = result.children[0]
        assert mid.label == labels.LApp()
        assert mid.children[1].label == labels.LRel(2)
        # Innermost: LApp(f, a)
        inner = mid.children[0]
        assert inner.label == labels.LApp()
        assert inner.children[0].label == labels.LConst("f")
        assert inner.children[1].label == labels.LRel(1)

    def test_all_lapp_nodes_have_exactly_two_children(self, constr, c2t, labels):
        """Invariant: every LApp node has exactly 2 children."""
        node = constr.App(
            constr.Const("f"),
            [constr.Rel(1), constr.Rel(2), constr.Rel(3), constr.Rel(4)],
        )
        result = c2t(node)

        def check(n):
            if n.label == labels.LApp():
                assert len(n.children) == 2, "LApp must have exactly 2 children"
            for child in n.children:
                check(child)

        check(result)


# ===================================================================
# 3. Cast stripping — single, nested
# ===================================================================

class TestCastStripping:
    """Cast(term, type) → constr_to_tree(term), type discarded."""

    def test_cast_strips_to_inner_term(self, constr, c2t, labels):
        """Cast(Const(zero), Ind(nat)) → LConst(zero) — spec example."""
        node = constr.Cast(
            constr.Const("Stdlib.Init.Nat.zero"),
            constr.Ind("Stdlib.Init.Datatypes.nat"),
        )
        result = c2t(node)
        assert result.label == labels.LConst("Stdlib.Init.Nat.zero")
        assert result.children == []

    def test_nested_casts_fully_stripped(self, constr, c2t, labels):
        """Cast(Cast(Rel(0), _), _) → LRel(0)."""
        inner_cast = constr.Cast(constr.Rel(0), constr.Ind("ty"))
        outer_cast = constr.Cast(inner_cast, constr.Ind("ty2"))
        result = c2t(outer_cast)
        assert result.label == labels.LRel(0)
        assert result.children == []

    def test_cast_around_app(self, constr, c2t, labels):
        """Cast wrapping an App — cast stripped, app currified."""
        node = constr.Cast(
            constr.App(constr.Const("f"), [constr.Rel(1)]),
            constr.Ind("ty"),
        )
        result = c2t(node)
        assert result.label == labels.LApp()
        assert len(result.children) == 2


# ===================================================================
# 4. Var rejection → NormalizationError
# ===================================================================

class TestVarRejection:
    """Var(name) is rejected — it should not appear in closed kernel terms."""

    def test_var_raises_normalization_error(self, constr, c2t):
        NormalizationError = _import_errors()
        node = constr.Var("x")
        with pytest.raises(NormalizationError):
            c2t(node)

    def test_var_nested_in_app_raises(self, constr, c2t):
        NormalizationError = _import_errors()
        node = constr.App(constr.Var("x"), [constr.Rel(1)])
        with pytest.raises(NormalizationError):
            c2t(node)


# ===================================================================
# 5. Lambda → LAbs (name/type discarded, 1 child)
# ===================================================================

class TestLambda:
    """Lambda(name, type, body) → LAbs with 1 child: body."""

    def test_lambda_produces_labs_with_one_child(self, constr, c2t, labels):
        node = constr.Lambda("x", constr.Ind("nat"), constr.Rel(0))
        result = c2t(node)
        assert result.label == labels.LAbs()
        assert len(result.children) == 1
        assert result.children[0].label == labels.LRel(0)

    def test_lambda_discards_name_and_type(self, constr, c2t, labels):
        """Two lambdas with different names/types but same body produce same tree."""
        node_a = constr.Lambda("x", constr.Ind("nat"), constr.Rel(0))
        node_b = constr.Lambda("y", constr.Ind("bool"), constr.Rel(0))
        result_a = c2t(node_a)
        result_b = c2t(node_b)
        assert result_a.label == result_b.label
        assert len(result_a.children) == len(result_b.children)
        assert result_a.children[0].label == result_b.children[0].label

    def test_nested_lambda(self, constr, c2t, labels):
        """Lambda(_, _, Lambda(_, _, Rel(0))) → LAbs(LAbs(LRel(0)))."""
        inner = constr.Lambda("y", constr.Ind("nat"), constr.Rel(0))
        outer = constr.Lambda("x", constr.Ind("nat"), inner)
        result = c2t(outer)
        assert result.label == labels.LAbs()
        assert len(result.children) == 1
        inner_result = result.children[0]
        assert inner_result.label == labels.LAbs()
        assert len(inner_result.children) == 1
        assert inner_result.children[0].label == labels.LRel(0)


# ===================================================================
# 6. LetIn → LLet (2 children: value, body; name/type discarded)
# ===================================================================

class TestLetIn:
    """LetIn(name, value, type, body) → LLet with 2 children."""

    def test_letin_produces_llet_with_two_children(self, constr, c2t, labels):
        node = constr.LetIn(
            "x",
            constr.Const("Stdlib.Init.Nat.zero"),
            constr.Ind("nat"),
            constr.Rel(0),
        )
        result = c2t(node)
        assert result.label == labels.LLet()
        assert len(result.children) == 2
        # First child is value
        assert result.children[0].label == labels.LConst("Stdlib.Init.Nat.zero")
        # Second child is body
        assert result.children[1].label == labels.LRel(0)

    def test_letin_discards_name_and_type(self, constr, c2t, labels):
        """Different names/types, same value/body → same tree."""
        node_a = constr.LetIn("x", constr.Rel(1), constr.Ind("nat"), constr.Rel(0))
        node_b = constr.LetIn("y", constr.Rel(1), constr.Ind("bool"), constr.Rel(0))
        result_a = c2t(node_a)
        result_b = c2t(node_b)
        assert result_a.label == result_b.label
        assert len(result_a.children) == len(result_b.children)
        for ca, cb in zip(result_a.children, result_b.children):
            assert ca.label == cb.label


# ===================================================================
# 7. Prod → LProd (2 children: type, body; name discarded)
# ===================================================================

class TestProd:
    """Prod(name, type, body) → LProd with 2 children."""

    def test_prod_produces_lprod_with_two_children(self, constr, c2t, labels):
        node = constr.Prod(
            "x",
            constr.Ind("Stdlib.Init.Datatypes.nat"),
            constr.Ind("Stdlib.Init.Datatypes.nat"),
        )
        result = c2t(node)
        assert result.label == labels.LProd()
        assert len(result.children) == 2
        assert result.children[0].label == labels.LInd("Stdlib.Init.Datatypes.nat")
        assert result.children[1].label == labels.LInd("Stdlib.Init.Datatypes.nat")

    def test_prod_discards_name(self, constr, c2t, labels):
        node_a = constr.Prod("x", constr.Ind("nat"), constr.Rel(0))
        node_b = constr.Prod("y", constr.Ind("nat"), constr.Rel(0))
        result_a = c2t(node_a)
        result_b = c2t(node_b)
        assert result_a.label == result_b.label
        assert result_a.children[0].label == result_b.children[0].label
        assert result_a.children[1].label == result_b.children[1].label


# ===================================================================
# 8. Sort mapping — Prop, SProp, Set, Type
# ===================================================================

class TestSortMapping:
    """Sort string → LSort(SortKind) mapping."""

    def test_sort_prop(self, constr, c2t, labels, SortKind):
        result = c2t(constr.Sort("Prop"))
        assert result.label == labels.LSort(SortKind.PROP)
        assert result.children == []

    def test_sort_sprop(self, constr, c2t, labels, SortKind):
        """SProp maps to PROP, same as Prop."""
        result = c2t(constr.Sort("SProp"))
        assert result.label == labels.LSort(SortKind.PROP)
        assert result.children == []

    def test_sort_set(self, constr, c2t, labels, SortKind):
        result = c2t(constr.Sort("Set"))
        assert result.label == labels.LSort(SortKind.SET)
        assert result.children == []

    def test_sort_type(self, constr, c2t, labels, SortKind):
        result = c2t(constr.Sort("Type"))
        assert result.label == labels.LSort(SortKind.TYPE_UNIV)
        assert result.children == []


# ===================================================================
# 9. Unknown sort → NormalizationError
# ===================================================================

class TestUnknownSort:
    """An unrecognized Sort string raises NormalizationError."""

    def test_unknown_sort_raises(self, constr, c2t):
        NormalizationError = _import_errors()
        with pytest.raises(NormalizationError):
            c2t(constr.Sort("UnknownSort"))

    def test_empty_sort_string_raises(self, constr, c2t):
        NormalizationError = _import_errors()
        with pytest.raises(NormalizationError):
            c2t(constr.Sort(""))


# ===================================================================
# 10. Construct → LConstruct
# ===================================================================

class TestConstruct:
    """Construct(fqn, index) → LConstruct(fqn, index), leaf."""

    def test_construct_produces_lconstruct(self, constr, c2t, labels):
        node = constr.Construct("Stdlib.Init.Datatypes.nat", 1)
        result = c2t(node)
        assert result.label == labels.LConstruct("Stdlib.Init.Datatypes.nat", 1)
        assert result.children == []

    def test_construct_zero_index(self, constr, c2t, labels):
        node = constr.Construct("Stdlib.Init.Datatypes.nat", 0)
        result = c2t(node)
        assert result.label == labels.LConstruct("Stdlib.Init.Datatypes.nat", 0)
        assert result.children == []


# ===================================================================
# 11. Fix/CoFix → LFix/LCoFix with correct children count
# ===================================================================

class TestFix:
    """Fix(index, bodies) → LFix(index) with len(bodies) children."""

    def test_fix_single_body(self, constr, c2t, labels):
        node = constr.Fix(0, [constr.Rel(0)])
        result = c2t(node)
        assert result.label == labels.LFix(0)
        assert len(result.children) == 1

    def test_fix_multiple_bodies(self, constr, c2t, labels):
        node = constr.Fix(1, [constr.Rel(0), constr.Rel(1), constr.Rel(2)])
        result = c2t(node)
        assert result.label == labels.LFix(1)
        assert len(result.children) == 3

    def test_fix_children_are_converted(self, constr, c2t, labels):
        node = constr.Fix(0, [constr.Const("f"), constr.Rel(1)])
        result = c2t(node)
        assert result.children[0].label == labels.LConst("f")
        assert result.children[1].label == labels.LRel(1)


class TestCoFix:
    """CoFix(index, bodies) → LCoFix(index) with len(bodies) children."""

    def test_cofix_single_body(self, constr, c2t, labels):
        node = constr.CoFix(0, [constr.Rel(0)])
        result = c2t(node)
        assert result.label == labels.LCoFix(0)
        assert len(result.children) == 1

    def test_cofix_multiple_bodies(self, constr, c2t, labels):
        node = constr.CoFix(0, [constr.Rel(0), constr.Rel(1)])
        result = c2t(node)
        assert result.label == labels.LCoFix(0)
        assert len(result.children) == 2


# ===================================================================
# 12. Proj → LProj with 1 child
# ===================================================================

class TestProj:
    """Proj(name, term) → LProj(name) with 1 child."""

    def test_proj_produces_lproj_with_one_child(self, constr, c2t, labels):
        node = constr.Proj("Stdlib.Init.Datatypes.fst", constr.Rel(0))
        result = c2t(node)
        assert result.label == labels.LProj("Stdlib.Init.Datatypes.fst")
        assert len(result.children) == 1
        assert result.children[0].label == labels.LRel(0)

    def test_proj_child_is_recursively_converted(self, constr, c2t, labels):
        """Proj wrapping a complex term."""
        inner = constr.App(constr.Const("pair"), [constr.Rel(0)])
        node = constr.Proj("fst", inner)
        result = c2t(node)
        assert result.label == labels.LProj("fst")
        assert len(result.children) == 1
        assert result.children[0].label == labels.LApp()


# ===================================================================
# 13. Int/Float → LPrimitive
# ===================================================================

class TestPrimitive:
    """Int(v) → LPrimitive(v), Float(v) → LPrimitive(v)."""

    def test_int_produces_lprimitive(self, constr, c2t, labels):
        result = c2t(constr.Int(42))
        assert result.label == labels.LPrimitive(42)
        assert result.children == []

    def test_int_zero(self, constr, c2t, labels):
        result = c2t(constr.Int(0))
        assert result.label == labels.LPrimitive(0)

    def test_int_negative(self, constr, c2t, labels):
        result = c2t(constr.Int(-1))
        assert result.label == labels.LPrimitive(-1)

    def test_float_produces_lprimitive(self, constr, c2t, labels):
        result = c2t(constr.Float(3.14))
        assert result.label == labels.LPrimitive(3.14)
        assert result.children == []

    def test_float_zero(self, constr, c2t, labels):
        result = c2t(constr.Float(0.0))
        assert result.label == labels.LPrimitive(0.0)


# ===================================================================
# 14. Case → LCase
# ===================================================================

class TestCase:
    """Case(ind_name, scrutinee, branches) → LCase(ind_name) with 1+len(branches) children."""

    def test_case_with_two_branches(self, constr, c2t, labels):
        node = constr.Case(
            "Stdlib.Init.Datatypes.nat",
            constr.Rel(0),
            [constr.Rel(1), constr.Rel(2)],
        )
        result = c2t(node)
        assert result.label == labels.LCase("Stdlib.Init.Datatypes.nat")
        assert len(result.children) == 3  # 1 scrutinee + 2 branches

    def test_case_scrutinee_is_first_child(self, constr, c2t, labels):
        node = constr.Case(
            "nat",
            constr.Const("scrut"),
            [constr.Const("br1")],
        )
        result = c2t(node)
        assert result.children[0].label == labels.LConst("scrut")
        assert result.children[1].label == labels.LConst("br1")

    def test_case_zero_branches(self, constr, c2t, labels):
        """Empty type like False can have 0 branches."""
        node = constr.Case("Stdlib.Init.Logic.False", constr.Rel(0), [])
        result = c2t(node)
        assert result.label == labels.LCase("Stdlib.Init.Logic.False")
        assert len(result.children) == 1  # scrutinee only

    def test_case_many_branches(self, constr, c2t, labels):
        branches = [constr.Rel(i) for i in range(5)]
        node = constr.Case("ind", constr.Rel(99), branches)
        result = c2t(node)
        assert len(result.children) == 6  # 1 + 5


# ===================================================================
# 15. coq_normalize — ExprTree with correct node_count, depths, node_ids
# ===================================================================

class TestCoqNormalize:
    """coq_normalize(constr_node) → ExprTree with depths, node_ids, node_count."""

    def test_single_leaf(self, constr, normalize, labels):
        """Simplest case: one leaf node."""
        result = normalize(constr.Rel(0))
        assert result.node_count == 1
        assert result.root.depth == 0
        assert result.root.node_id == 0

    def test_prod_nat_nat(self, constr, normalize, labels):
        """Prod(_, nat, nat) → 3-node tree with correct metadata."""
        node = constr.Prod(
            "_",
            constr.Ind("Stdlib.Init.Datatypes.nat"),
            constr.Ind("Stdlib.Init.Datatypes.nat"),
        )
        result = normalize(node)
        assert result.node_count == 3
        # Root is LProd at depth 0
        assert result.root.label == labels.LProd()
        assert result.root.depth == 0
        assert result.root.node_id == 0
        # Children at depth 1
        left = result.root.children[0]
        right = result.root.children[1]
        assert left.depth == 1
        assert right.depth == 1
        # Pre-order node_ids: root=0, left=1, right=2
        assert left.node_id == 1
        assert right.node_id == 2

    def test_currified_app_depths_and_ids(self, constr, normalize, labels):
        """App(Nat.add, [Rel(1), Rel(2)]) — spec example as full pipeline."""
        node = constr.App(
            constr.Const("Stdlib.Init.Nat.add"),
            [constr.Rel(1), constr.Rel(2)],
        )
        result = normalize(node)
        # 5 nodes: outer LApp, inner LApp, LConst, LRel(1), LRel(2)
        assert result.node_count == 5
        # Root depth 0
        assert result.root.depth == 0
        # Pre-order: outer_app=0, inner_app=1, const=2, rel1=3, rel2=4
        assert result.root.node_id == 0

    def test_node_ids_are_sequential_preorder(self, constr, normalize, labels):
        """All node_ids form a contiguous 0..n-1 sequence in pre-order."""
        node = constr.Prod(
            "_",
            constr.App(constr.Const("f"), [constr.Rel(0)]),
            constr.Rel(1),
        )
        result = normalize(node)

        ids = []

        def collect(n):
            ids.append(n.node_id)
            for c in n.children:
                collect(c)

        collect(result.root)
        assert ids == list(range(len(ids)))
        assert len(ids) == result.node_count

    def test_depths_increase_monotonically(self, constr, normalize, labels):
        """Each child's depth is exactly parent.depth + 1."""
        node = constr.Lambda(
            "_",
            constr.Ind("nat"),
            constr.App(constr.Const("f"), [constr.Rel(0)]),
        )
        result = normalize(node)

        def check_depths(n):
            for c in n.children:
                assert c.depth == n.depth + 1
                check_depths(c)

        check_depths(result.root)
        assert result.root.depth == 0


# ===================================================================
# 16. Determinism — same input → same output
# ===================================================================

class TestDeterminism:
    """constr_to_tree is deterministic: same input always produces same output."""

    def test_same_input_same_output(self, constr, c2t, labels):
        node = constr.App(
            constr.Const("Stdlib.Init.Nat.add"),
            [constr.Rel(1), constr.Rel(2)],
        )
        result_a = c2t(node)
        result_b = c2t(node)
        assert _tree_equal(result_a, result_b)

    def test_normalize_deterministic(self, constr, normalize, labels):
        node = constr.Prod(
            "x",
            constr.Ind("Stdlib.Init.Datatypes.nat"),
            constr.App(constr.Const("f"), [constr.Rel(0), constr.Rel(1)]),
        )
        result_a = normalize(node)
        result_b = normalize(node)
        assert result_a.node_count == result_b.node_count
        assert _tree_equal(result_a.root, result_b.root)


# ===================================================================
# Error conditions
# ===================================================================

class TestNormalizationError:
    """NormalizationError carries declaration_name and message."""

    def test_error_has_declaration_name(self):
        NormalizationError = _import_errors()
        err = NormalizationError(declaration_name="my_lemma", message="bad input")
        assert err.declaration_name == "my_lemma"
        assert err.message == "bad input"

    def test_error_is_exception(self):
        NormalizationError = _import_errors()
        assert issubclass(NormalizationError, Exception)


class TestRecursionErrorHandling:
    """RecursionError during conversion → NormalizationError."""

    def test_deeply_nested_term_raises_normalization_error(self, constr, c2t):
        """A term deeper than Python's recursion limit raises NormalizationError."""
        NormalizationError = _import_errors()
        # Build a deeply nested Cast chain that will exceed recursion limits
        node = constr.Rel(0)
        for _ in range(2000):
            node = constr.Cast(node, constr.Ind("ty"))
        with pytest.raises(NormalizationError):
            c2t(node)


# ===================================================================
# Combined / integration-level tests
# ===================================================================

class TestCombinedTransforms:
    """Tests exercising multiple adaptation rules in a single tree."""

    def test_cast_inside_app(self, constr, c2t, labels):
        """App(Cast(f, _), [a]) → cast stripped, then currified."""
        node = constr.App(
            constr.Cast(constr.Const("f"), constr.Ind("ty")),
            [constr.Rel(0)],
        )
        result = c2t(node)
        assert result.label == labels.LApp()
        assert result.children[0].label == labels.LConst("f")
        assert result.children[1].label == labels.LRel(0)

    def test_lambda_with_app_body(self, constr, c2t, labels):
        """Lambda(_, _, App(f, [a])) → LAbs with 1 child that is LApp."""
        node = constr.Lambda(
            "x",
            constr.Ind("nat"),
            constr.App(constr.Const("f"), [constr.Rel(0)]),
        )
        result = c2t(node)
        assert result.label == labels.LAbs()
        assert len(result.children) == 1
        body = result.children[0]
        assert body.label == labels.LApp()
        assert len(body.children) == 2

    def test_fix_with_lambda_bodies(self, constr, c2t, labels):
        """Fix containing Lambda bodies — both transforms applied."""
        body1 = constr.Lambda("f", constr.Ind("nat"), constr.Rel(0))
        body2 = constr.Lambda("g", constr.Ind("bool"), constr.Rel(1))
        node = constr.Fix(0, [body1, body2])
        result = c2t(node)
        assert result.label == labels.LFix(0)
        assert len(result.children) == 2
        assert result.children[0].label == labels.LAbs()
        assert result.children[1].label == labels.LAbs()

    def test_case_with_complex_branches(self, constr, c2t, labels):
        """Case where scrutinee and branches are non-trivial terms."""
        scrutinee = constr.App(constr.Const("match_val"), [constr.Rel(0)])
        branch0 = constr.Const("Stdlib.Init.Nat.zero")
        branch1 = constr.Lambda("n", constr.Ind("nat"), constr.Rel(0))
        node = constr.Case("Stdlib.Init.Datatypes.nat", scrutinee, [branch0, branch1])
        result = c2t(node)
        assert result.label == labels.LCase("Stdlib.Init.Datatypes.nat")
        assert len(result.children) == 3
        # Scrutinee is an App
        assert result.children[0].label == labels.LApp()
        # Branch 0 is a leaf
        assert result.children[1].label == labels.LConst("Stdlib.Init.Nat.zero")
        # Branch 1 is LAbs
        assert result.children[2].label == labels.LAbs()

    def test_full_pipeline_s_s_o(self, constr, normalize, labels):
        """S (S O) — spec example: App(S, [App(S, [O])]) = 5 nodes after currification."""
        O = constr.Construct("Stdlib.Init.Datatypes.nat", 0)
        S_inner = constr.Construct("Stdlib.Init.Datatypes.nat", 1)
        S_outer = constr.Construct("Stdlib.Init.Datatypes.nat", 1)
        inner_app = constr.App(S_inner, [O])
        outer_app = constr.App(S_outer, [inner_app])
        result = normalize(outer_app)
        assert result.node_count == 5
        # Structure: LApp(S, LApp(S, O))
        root = result.root
        assert root.label == labels.LApp()
        assert root.children[0].label == labels.LConstruct("Stdlib.Init.Datatypes.nat", 1)
        inner = root.children[1]
        assert inner.label == labels.LApp()
        assert inner.children[0].label == labels.LConstruct("Stdlib.Init.Datatypes.nat", 1)
        assert inner.children[1].label == labels.LConstruct("Stdlib.Init.Datatypes.nat", 0)


# ===================================================================
# Helpers
# ===================================================================

def _tree_equal(a, b) -> bool:
    """Recursively compare two TreeNodes for structural + label equality."""
    if a.label != b.label:
        return False
    if len(a.children) != len(b.children):
        return False
    return all(_tree_equal(ca, cb) for ca, cb in zip(a.children, b.children))
