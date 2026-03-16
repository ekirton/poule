"""TreeNode, ExprTree, and tree utility functions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from wily_rooster.models.labels import NodeLabel


@dataclass
class TreeNode:
    """A mutable node in an expression tree."""

    label: NodeLabel
    children: list[TreeNode]
    depth: int = 0
    node_id: int = 0


@dataclass
class ExprTree:
    """Wrapper around a root TreeNode with a node count."""

    root: TreeNode
    node_count: int

    def __post_init__(self) -> None:
        if self.root is not None and self.node_count < 1:
            raise ValueError("node count must be positive")


def recompute_depths(tree: ExprTree) -> None:
    """Set depth on all nodes: root=0, each child=parent.depth+1. Mutates in place."""

    def _walk(node: TreeNode, depth: int) -> None:
        node.depth = depth
        for child in node.children:
            _walk(child, depth + 1)

    _walk(tree.root, 0)


def assign_node_ids(tree: ExprTree) -> None:
    """Assign sequential pre-order IDs starting from 0. Mutates in place."""

    counter = [0]

    def _walk(node: TreeNode) -> None:
        node.node_id = counter[0]
        counter[0] += 1
        for child in node.children:
            _walk(child)

    _walk(tree.root)


def node_count(tree_or_node: Union[ExprTree, TreeNode]) -> int:
    """Return total number of nodes (interior + leaf).

    Accepts either an ExprTree or a TreeNode for flexibility.
    Uses an iterative approach to avoid recursion limits on deep trees.
    """
    if isinstance(tree_or_node, ExprTree):
        root = tree_or_node.root
    else:
        root = tree_or_node

    count = 0
    stack = [root]
    while stack:
        node = stack.pop()
        count += 1
        stack.extend(node.children)
    return count
