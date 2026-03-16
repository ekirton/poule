"""Coq expression normalization: constr_to_tree and coq_normalize."""

from __future__ import annotations

from functools import reduce

from wily_rooster.models.enums import SortKind
from wily_rooster.models.labels import (
    LAbs,
    LApp,
    LCase,
    LCoFix,
    LConst,
    LConstruct,
    LFix,
    LInd,
    LLet,
    LPrimitive,
    LProj,
    LProd,
    LRel,
    LSort,
)
from wily_rooster.models.tree import (
    ExprTree,
    TreeNode,
    assign_node_ids,
    node_count,
    recompute_depths,
)
from wily_rooster.normalization.constr_node import (
    App,
    Case,
    Cast,
    CoFix,
    Const,
    Construct,
    Fix,
    Float,
    Ind,
    Int,
    Lambda,
    LetIn,
    Prod,
    Proj,
    Rel,
    Sort,
    Var,
)
from wily_rooster.normalization.errors import NormalizationError

_SORT_MAP = {
    "Prop": SortKind.PROP,
    "SProp": SortKind.PROP,
    "Set": SortKind.SET,
    "Type": SortKind.TYPE_UNIV,
}


def constr_to_tree(node: object) -> TreeNode:
    """Convert a ConstrNode to a TreeNode, applying all adaptation rules.

    Raises NormalizationError on Var nodes, unknown sorts, or recursion overflow.
    """
    try:
        return _convert(node)
    except RecursionError:
        raise NormalizationError(
            declaration_name="<unknown>",
            message="Recursion depth exceeded during constr_to_tree",
        )


def _convert(node: object) -> TreeNode:
    if isinstance(node, Rel):
        return TreeNode(label=LRel(node.n), children=[])

    if isinstance(node, Var):
        raise NormalizationError(
            declaration_name="<unknown>",
            message=f"Var node encountered: {node.name}",
        )

    if isinstance(node, Sort):
        kind = _SORT_MAP.get(node.sort)
        if kind is None:
            raise NormalizationError(
                declaration_name="<unknown>",
                message=f"Unknown sort: {node.sort!r}",
            )
        return TreeNode(label=LSort(kind), children=[])

    if isinstance(node, Cast):
        return _convert(node.term)

    if isinstance(node, Prod):
        return TreeNode(
            label=LProd(),
            children=[_convert(node.type), _convert(node.body)],
        )

    if isinstance(node, Lambda):
        return TreeNode(label=LAbs(), children=[_convert(node.body)])

    if isinstance(node, LetIn):
        return TreeNode(
            label=LLet(),
            children=[_convert(node.value), _convert(node.body)],
        )

    if isinstance(node, App):
        if not node.args:
            return _convert(node.func)
        # Currify: left-fold into nested binary LApp
        func_tree = _convert(node.func)
        return reduce(
            lambda acc, arg: TreeNode(label=LApp(), children=[acc, _convert(arg)]),
            node.args,
            func_tree,
        )

    if isinstance(node, Const):
        return TreeNode(label=LConst(node.fqn), children=[])

    if isinstance(node, Ind):
        return TreeNode(label=LInd(node.fqn), children=[])

    if isinstance(node, Construct):
        return TreeNode(label=LConstruct(node.fqn, node.index), children=[])

    if isinstance(node, Case):
        children = [_convert(node.scrutinee)] + [_convert(b) for b in node.branches]
        return TreeNode(label=LCase(node.ind_name), children=children)

    if isinstance(node, Fix):
        children = [_convert(b) for b in node.bodies]
        return TreeNode(label=LFix(node.index), children=children)

    if isinstance(node, CoFix):
        children = [_convert(b) for b in node.bodies]
        return TreeNode(label=LCoFix(node.index), children=children)

    if isinstance(node, Proj):
        return TreeNode(label=LProj(node.name), children=[_convert(node.term)])

    if isinstance(node, Int):
        return TreeNode(label=LPrimitive(node.value), children=[])

    if isinstance(node, Float):
        return TreeNode(label=LPrimitive(node.value), children=[])

    raise NormalizationError(
        declaration_name="<unknown>",
        message=f"Unknown ConstrNode type: {type(node).__name__}",
    )


def coq_normalize(constr_node: object) -> ExprTree:
    """Full normalization pipeline: constr_to_tree -> recompute_depths -> assign_node_ids."""
    root = constr_to_tree(constr_node)
    tree = ExprTree(root=root, node_count=node_count(root))
    recompute_depths(tree)
    assign_node_ids(tree)
    return tree
