"""Shared test fixtures and tree-building helpers for wily-rooster tests.

These helpers construct expression trees without importing production code,
following TDD practice — tests are written before the implementation exists.
The fixtures define the expected API surface that implementation must satisfy.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Tree-building helpers (mirror the data-structures spec API)
# ---------------------------------------------------------------------------
# These import from the package that WILL be implemented.  Tests will fail
# with ImportError until the production modules exist — that's TDD.

@pytest.fixture
def make_leaf():
    """Return a factory that creates a leaf TreeNode with no children."""
    from wily_rooster.models.tree import TreeNode

    def _make(label):
        return TreeNode(label=label, children=[])

    return _make


@pytest.fixture
def make_node():
    """Return a factory that creates a TreeNode with children."""
    from wily_rooster.models.tree import TreeNode

    def _make(label, children):
        return TreeNode(label=label, children=children)

    return _make


@pytest.fixture
def make_tree():
    """Return a factory that creates an ExprTree from a root node."""
    from wily_rooster.models.tree import ExprTree, node_count as _nc

    def _make(root):
        return ExprTree(root=root, node_count=_nc(root))

    return _make


@pytest.fixture
def sample_prod_tree():
    """LProd(LSort(PROP), LRel(0)) — a simple 3-node tree."""
    from wily_rooster.models.labels import LProd, LSort, LRel
    from wily_rooster.models.enums import SortKind
    from wily_rooster.models.tree import TreeNode, ExprTree

    root = TreeNode(
        label=LProd(),
        children=[
            TreeNode(label=LSort(SortKind.PROP), children=[]),
            TreeNode(label=LRel(0), children=[]),
        ],
    )
    return ExprTree(root=root, node_count=3)


@pytest.fixture
def sample_app_tree():
    """LApp(LApp(LConst(Nat.add), LRel(1)), LRel(2)) — currified application, 5 nodes."""
    from wily_rooster.models.labels import LApp, LConst, LRel
    from wily_rooster.models.tree import TreeNode, ExprTree

    inner = TreeNode(
        label=LApp(),
        children=[
            TreeNode(label=LConst("Coq.Init.Nat.add"), children=[]),
            TreeNode(label=LRel(1), children=[]),
        ],
    )
    root = TreeNode(
        label=LApp(),
        children=[
            inner,
            TreeNode(label=LRel(2), children=[]),
        ],
    )
    return ExprTree(root=root, node_count=5)


@pytest.fixture
def tmp_db_path(tmp_path):
    """Return a temporary path for a SQLite database file."""
    return tmp_path / "test_index.db"
