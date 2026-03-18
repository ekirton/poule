"""Shared test fixtures and tree-building helpers for poule tests.

These helpers construct expression trees without importing production code,
following TDD practice — tests are written before the implementation exists.
The fixtures define the expected API surface that implementation must satisfy.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Tree-building helpers (mirror the data-structures spec API)
# ---------------------------------------------------------------------------
# These import from the package that WILL be implemented.  Tests will fail
# with ImportError until the production modules exist — that's TDD.

@pytest.fixture
def make_leaf():
    """Return a factory that creates a leaf TreeNode with no children."""
    from poule.models.tree import TreeNode

    def _make(label):
        return TreeNode(label=label, children=[])

    return _make


@pytest.fixture
def make_node():
    """Return a factory that creates a TreeNode with children."""
    from poule.models.tree import TreeNode

    def _make(label, children):
        return TreeNode(label=label, children=children)

    return _make


@pytest.fixture
def make_tree():
    """Return a factory that creates an ExprTree from a root node."""
    from poule.models.tree import ExprTree, node_count as _nc

    def _make(root):
        return ExprTree(root=root, node_count=_nc(root))

    return _make


@pytest.fixture
def sample_prod_tree():
    """LProd(LSort(PROP), LRel(0)) — a simple 3-node tree."""
    from poule.models.labels import LProd, LSort, LRel
    from poule.models.enums import SortKind
    from poule.models.tree import TreeNode, ExprTree

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
    from poule.models.labels import LApp, LConst, LRel
    from poule.models.tree import TreeNode, ExprTree

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


# ---------------------------------------------------------------------------
# Contract-test fixtures (requires_coq marker)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def coq_test_file(tmp_path_factory):
    """Copy examples/test.v to a temp dir and return the absolute path.

    Session-scoped so the file is created once and shared across all
    contract tests that need a Coq source file.
    """
    src = _PROJECT_ROOT / "examples" / "test.v"
    dest = tmp_path_factory.mktemp("coq") / "test.v"
    shutil.copy2(src, dest)
    return dest


@pytest.fixture(scope="session")
def test_fixture_db(tmp_path_factory):
    """Generate a minimal index database matching the storage schema.

    Returns the absolute path to the SQLite file.
    """
    db_path = tmp_path_factory.mktemp("db") / "test_fixture.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE declarations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            module TEXT NOT NULL,
            kind TEXT NOT NULL,
            statement TEXT NOT NULL,
            type_expr TEXT,
            constr_tree BLOB,
            node_count INTEGER NOT NULL CHECK(node_count > 0),
            symbol_set TEXT NOT NULL
        );
        CREATE TABLE dependencies (
            src INTEGER NOT NULL REFERENCES declarations(id) ON DELETE CASCADE,
            dst INTEGER NOT NULL REFERENCES declarations(id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            PRIMARY KEY (src, dst, relation)
        );
        CREATE TABLE wl_vectors (
            decl_id INTEGER NOT NULL REFERENCES declarations(id) ON DELETE CASCADE,
            h INTEGER NOT NULL,
            histogram TEXT NOT NULL,
            PRIMARY KEY (decl_id, h)
        );
        CREATE TABLE symbol_freq (
            symbol TEXT PRIMARY KEY,
            freq INTEGER NOT NULL CHECK(freq > 0)
        );
        CREATE TABLE index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE declarations_fts USING fts5(
            name, statement, module,
            content=declarations, content_rowid=id,
            tokenize='porter unicode61'
        );
    """)
    meta = {
        "schema_version": "1",
        "coq_version": "8.19.2",
        "mathcomp_version": "2.2.0",
        "created_at": "2025-01-15T10:30:00Z",
    }
    conn.executemany(
        "INSERT INTO index_meta (key, value) VALUES (?, ?)", meta.items(),
    )
    decls = [
        (1, "Coq.Arith.Plus.add_comm", "Coq.Arith.Plus", "lemma",
         "forall n m : nat, n + m = m + n",
         "forall n m : nat, n + m = m + n",
         None, 5, json.dumps(["Nat.add", "eq"])),
        (2, "Coq.Arith.Plus.add_assoc", "Coq.Arith.Plus", "lemma",
         "forall n m p : nat, n + (m + p) = n + m + p",
         "forall n m p : nat, n + (m + p) = n + m + p",
         None, 7, json.dumps(["Nat.add", "eq"])),
        (3, "Coq.Init.Nat.add", "Coq.Init.Nat", "definition",
         "fix add (n m : nat) : nat := match n with | O => m | S p => S (add p m) end",
         "nat -> nat -> nat",
         None, 6, json.dumps(["nat", "O", "S"])),
        (4, "Coq.Init.Nat.nat", "Coq.Init.Nat", "inductive",
         "Inductive nat : Set := O : nat | S : nat -> nat.",
         "Set",
         None, 3, json.dumps(["Set"])),
        (5, "Coq.Init.Datatypes.bool", "Coq.Init.Datatypes", "inductive",
         "Inductive bool : Set := true : bool | false : bool.",
         "Set",
         None, 3, json.dumps(["Set"])),
    ]
    conn.executemany(
        "INSERT INTO declarations"
        " (id, name, module, kind, statement, type_expr,"
        "  constr_tree, node_count, symbol_set)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        decls,
    )
    deps = [
        (1, 3, "uses"),
        (2, 3, "uses"),
        (3, 4, "uses"),
    ]
    conn.executemany(
        "INSERT INTO dependencies (src, dst, relation) VALUES (?, ?, ?)", deps,
    )
    conn.executescript(
        "INSERT INTO declarations_fts(declarations_fts) VALUES('rebuild');"
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture(scope="session")
def test_fixture_dot(tmp_path_factory):
    """Generate a minimal coq-dpdgraph DOT fixture.

    Returns the absolute path to the .dot file.
    """
    dot_path = tmp_path_factory.mktemp("dot") / "test_fixture.dot"
    dot_path.write_text(
        'digraph dependencies {\n'
        '  "Coq.Arith.Plus.add_comm" -> "Coq.Init.Nat.add";\n'
        '  "Coq.Arith.Plus.add_assoc" -> "Coq.Init.Nat.add";\n'
        '  "Coq.Init.Nat.add" -> "Coq.Init.Nat.nat";\n'
        '  "Coq.Init.Nat.nat" -> "Coq.Init.Datatypes.O";\n'
        '  "Coq.Init.Nat.nat" -> "Coq.Init.Datatypes.S";\n'
        '}\n'
    )
    return dot_path
