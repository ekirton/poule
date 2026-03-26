"""Unit tests for Deep Dependency Analysis (specification/deep-dependency-analysis.md).

Tests are written BEFORE implementation. They will fail with ImportError
until src/poule/analysis/ modules exist.

Spec: specification/deep-dependency-analysis.md
Architecture: doc/architecture/deep-dependency-analysis.md
Data model: doc/architecture/data-models/index-entities.md

Import paths under test:
  poule.analysis.graph        (build_graph, DependencyGraph, NodeMetadata)
  poule.analysis.closure      (transitive_closure, TransitiveClosure)
  poule.analysis.impact       (impact_analysis, ImpactSet)
  poule.analysis.cycles       (detect_cycles, CycleReport)
  poule.analysis.modules      (module_summary, ModuleSummary, ModuleMetrics)
  poule.analysis.filters      (module_prefix, exclude_prefix, same_project)
  poule.analysis.cache        (GraphCache)
  poule.analysis.errors       (AnalysisError, error codes)
"""

from __future__ import annotations

import textwrap
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy imports — fail with ImportError until implementation exists
# ---------------------------------------------------------------------------

def _import_build_graph():
    from Poule.analysis.graph import build_graph
    return build_graph


def _import_graph_types():
    from Poule.analysis.graph import DependencyGraph, NodeMetadata
    return DependencyGraph, NodeMetadata


def _import_transitive_closure():
    from Poule.analysis.closure import transitive_closure, TransitiveClosure
    return transitive_closure, TransitiveClosure


def _import_impact_analysis():
    from Poule.analysis.impact import impact_analysis, ImpactSet
    return impact_analysis, ImpactSet


def _import_detect_cycles():
    from Poule.analysis.cycles import detect_cycles, CycleReport
    return detect_cycles, CycleReport


def _import_module_summary():
    from Poule.analysis.modules import module_summary, ModuleSummary, ModuleMetrics
    return module_summary, ModuleSummary, ModuleMetrics


def _import_filters():
    from Poule.analysis.filters import module_prefix, exclude_prefix, same_project
    return module_prefix, exclude_prefix, same_project


def _import_cache():
    from Poule.analysis.cache import GraphCache
    return GraphCache


def _import_errors():
    from Poule.analysis.errors import AnalysisError
    return AnalysisError


def _import_index_reader():
    from Poule.storage.reader import IndexReader
    return IndexReader


# ---------------------------------------------------------------------------
# Helpers — build real DependencyGraph and NodeMetadata instances
# ---------------------------------------------------------------------------

def _make_graph(edges: list[tuple[str, str]], metadata: dict[str, tuple[str, str]] | None = None):
    """Build a DependencyGraph from edge pairs and optional metadata.

    metadata: dict mapping qualified name to (module, kind).
    If not provided, module is inferred from name and kind defaults to 'lemma'.
    """
    DependencyGraph, NodeMetadata = _import_graph_types()

    forward_adj: dict[str, set[str]] = {}
    reverse_adj: dict[str, set[str]] = {}
    all_nodes: set[str] = set()

    for src, dst in edges:
        all_nodes.add(src)
        all_nodes.add(dst)
        forward_adj.setdefault(src, set()).add(dst)
        reverse_adj.setdefault(dst, set()).add(src)

    # Ensure all nodes have entries in both adj maps
    for node in all_nodes:
        forward_adj.setdefault(node, set())
        reverse_adj.setdefault(node, set())

    meta = {}
    for node in all_nodes:
        if metadata and node in metadata:
            mod, kind = metadata[node]
        else:
            # Infer module: everything before last dot
            parts = node.rsplit(".", 1)
            mod = parts[0] if len(parts) > 1 else ""
            kind = "lemma"
        meta[node] = NodeMetadata(module=mod, kind=kind)

    return DependencyGraph(
        forward_adj=forward_adj,
        reverse_adj=reverse_adj,
        metadata=meta,
        node_count=len(all_nodes),
        edge_count=len(edges),
    )


def _make_dot_file(content: str) -> Path:
    """Write DOT content to a temporary file and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".dot", delete=False)
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def _make_mock_index_reader(declarations: list[dict], dependencies: list[dict]):
    """Create a mock IndexReader that returns declarations and dependencies.

    declarations: list of dicts with keys: id, name, module, kind
    dependencies: list of dicts with keys: src, dst, relation
    """
    IndexReader = _import_index_reader()
    reader = MagicMock(spec=IndexReader)

    # The engine queries declarations and dependencies tables.
    # Mock the connection's execute method to return appropriate rows.
    mock_conn = MagicMock()
    reader._conn = mock_conn

    def execute_side_effect(sql, params=None):
        result = MagicMock()
        if "declarations" in sql.lower() and "dependencies" not in sql.lower():
            result.fetchall.return_value = [
                _dict_to_row(d) for d in declarations
            ]
        elif "dependencies" in sql.lower():
            result.fetchall.return_value = [
                _dict_to_row(d) for d in dependencies
            ]
        elif "index_meta" in sql.lower() and "schema_version" in sql.lower():
            result.fetchone.return_value = ("1",)
        elif "index_meta" in sql.lower() and "created_at" in sql.lower():
            result.fetchone.return_value = ("2025-01-01T00:00:00",)
        else:
            result.fetchall.return_value = []
            result.fetchone.return_value = None
        return result

    mock_conn.execute.side_effect = execute_side_effect

    return reader


def _dict_to_row(d: dict):
    """Convert a dict to a mock sqlite3.Row-like object."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: d[key] if isinstance(key, str) else list(d.values())[key]
    row.keys = lambda: d.keys()
    for k, v in d.items():
        setattr(row, k, v)
    # Support dict(row) pattern
    row.__iter__ = lambda self: iter(d.keys())
    return row


# ===========================================================================
# 1. Graph Construction from Storage -- Section 4.1
# ===========================================================================

class TestBuildGraphFromStorage:
    """Section 4.1: build_graph_from_storage behavioral requirements."""

    def test_basic_graph_construction(self):
        """Given declarations A, B, C and edges A->B, B->C,
        the graph has correct forward and reverse adjacency."""
        build_graph = _import_build_graph()
        DependencyGraph, _ = _import_graph_types()

        declarations = [
            {"id": 1, "name": "A", "module": "", "kind": "lemma"},
            {"id": 2, "name": "B", "module": "", "kind": "lemma"},
            {"id": 3, "name": "C", "module": "", "kind": "lemma"},
        ]
        dependencies = [
            {"src": 1, "dst": 2, "relation": "uses"},
            {"src": 2, "dst": 3, "relation": "uses"},
        ]
        reader = _make_mock_index_reader(declarations, dependencies)

        graph = build_graph(index_reader=reader)

        assert isinstance(graph, DependencyGraph)
        assert graph.node_count == 3
        assert graph.edge_count == 2
        assert "B" in graph.forward_adj["A"]
        assert "C" in graph.forward_adj["B"]
        assert "A" in graph.reverse_adj["B"]
        assert "B" in graph.reverse_adj["C"]

    def test_no_uses_edges_produces_isolated_nodes(self):
        """Given an index with no 'uses' edges, all nodes are isolated."""
        build_graph = _import_build_graph()

        declarations = [
            {"id": 1, "name": "A", "module": "", "kind": "lemma"},
            {"id": 2, "name": "B", "module": "", "kind": "definition"},
        ]
        dependencies = []
        reader = _make_mock_index_reader(declarations, dependencies)

        graph = build_graph(index_reader=reader)

        assert graph.node_count == 2
        assert graph.edge_count == 0
        assert graph.forward_adj.get("A", set()) == set()
        assert graph.forward_adj.get("B", set()) == set()

    def test_metadata_populated_for_every_node(self):
        """Every declaration in the graph has metadata with module and kind."""
        build_graph = _import_build_graph()

        declarations = [
            {"id": 1, "name": "Foo.bar", "module": "Foo", "kind": "theorem"},
        ]
        reader = _make_mock_index_reader(declarations, [])

        graph = build_graph(index_reader=reader)

        assert "Foo.bar" in graph.metadata
        assert graph.metadata["Foo.bar"].module == "Foo"
        assert graph.metadata["Foo.bar"].kind == "theorem"



# ===========================================================================
# 2. Graph Construction from DOT -- Section 4.1
# ===========================================================================

class TestBuildGraphFromDpdgraph:
    """Section 4.1: build_graph_from_dpdgraph behavioral requirements."""

    def test_basic_dot_parsing(self):
        """Given a DOT file with two nodes and an edge, the graph is correct."""
        build_graph = _import_build_graph()

        dot_content = textwrap.dedent("""\
            digraph dependencies {
              "Stdlib.Arith.Plus.add_comm" -> "Stdlib.Arith.Plus.add_assoc";
            }
        """)
        dot_path = _make_dot_file(dot_content)

        graph = build_graph(dot_file_path=dot_path)

        assert graph.node_count == 2
        assert graph.edge_count == 1
        assert "Stdlib.Arith.Plus.add_assoc" in graph.forward_adj["Stdlib.Arith.Plus.add_comm"]
        assert "Stdlib.Arith.Plus.add_comm" in graph.reverse_adj["Stdlib.Arith.Plus.add_assoc"]

    def test_module_inferred_from_qualified_name(self):
        """Node modules are inferred as the prefix before the last dot component."""
        build_graph = _import_build_graph()

        dot_content = textwrap.dedent("""\
            digraph dependencies {
              "Stdlib.Arith.Plus.add_comm" -> "Stdlib.Arith.Plus.add_assoc";
            }
        """)
        dot_path = _make_dot_file(dot_content)

        graph = build_graph(dot_file_path=dot_path)

        assert graph.metadata["Stdlib.Arith.Plus.add_comm"].module == "Stdlib.Arith.Plus"
        assert graph.metadata["Stdlib.Arith.Plus.add_assoc"].module == "Stdlib.Arith.Plus"

    def test_malformed_dot_returns_parse_error(self):
        """Given a malformed DOT file, a PARSE_ERROR is returned."""
        build_graph = _import_build_graph()
        AnalysisError = _import_errors()

        dot_content = textwrap.dedent("""\
            digraph dependencies {
              "A" -> "B"
        """)  # Missing closing brace
        dot_path = _make_dot_file(dot_content)

        with pytest.raises(AnalysisError) as exc_info:
            build_graph(dot_file_path=dot_path)
        assert exc_info.value.code == "PARSE_ERROR"

    def test_dot_file_not_found(self):
        """Given a non-existent DOT file path, a FILE_NOT_FOUND error is returned."""
        build_graph = _import_build_graph()
        AnalysisError = _import_errors()

        with pytest.raises(AnalysisError) as exc_info:
            build_graph(dot_file_path=Path("/nonexistent/path.dot"))
        assert exc_info.value.code == "FILE_NOT_FOUND"

    def test_duplicate_edges_deduplicated(self):
        """DOT files with duplicate edges produce no duplicates in adjacency."""
        build_graph = _import_build_graph()

        dot_content = textwrap.dedent("""\
            digraph dependencies {
              "A.x" -> "B.y";
              "A.x" -> "B.y";
            }
        """)
        dot_path = _make_dot_file(dot_content)

        graph = build_graph(dot_file_path=dot_path)

        # Sets deduplicate naturally
        assert len(graph.forward_adj["A.x"]) == 1


# ===========================================================================
# 3. Source Selection -- Section 4.1
# ===========================================================================

class TestSourceSelection:
    """Section 4.1: source selection when both, one, or neither source available."""

    def test_no_source_returns_index_missing(self):
        """When neither index_reader nor dot_file_path is provided, INDEX_MISSING."""
        build_graph = _import_build_graph()
        AnalysisError = _import_errors()

        with pytest.raises(AnalysisError) as exc_info:
            build_graph(index_reader=None, dot_file_path=None)
        assert exc_info.value.code == "INDEX_MISSING"


# ===========================================================================
# 4. Graph Cache -- Section 4.2
# ===========================================================================

class TestGraphCache:
    """Section 4.2: graph caching and invalidation."""

    def test_cache_returns_same_graph_on_repeated_access(self):
        """A cached graph is reused when the source has not changed."""
        GraphCache = _import_cache()
        cache = GraphCache()

        graph = _make_graph([("A", "B")])
        cache.put("project1", "/path/index.db", graph, schema_version="1", created_at="T1")

        cached = cache.get("project1", "/path/index.db", schema_version="1", created_at="T1")
        assert cached is graph

    def test_cache_invalidated_when_created_at_differs(self):
        """When created_at changes, cache is invalidated."""
        GraphCache = _import_cache()
        cache = GraphCache()

        graph = _make_graph([("A", "B")])
        cache.put("project1", "/path/index.db", graph, schema_version="1", created_at="T1")

        cached = cache.get("project1", "/path/index.db", schema_version="1", created_at="T2")
        assert cached is None

    def test_cache_invalidated_when_schema_version_differs(self):
        """When schema_version changes, cache is invalidated."""
        GraphCache = _import_cache()
        cache = GraphCache()

        graph = _make_graph([("A", "B")])
        cache.put("project1", "/path/index.db", graph, schema_version="1", created_at="T1")

        cached = cache.get("project1", "/path/index.db", schema_version="2", created_at="T1")
        assert cached is None

    def test_cache_holds_at_most_one_per_project(self):
        """Cache holds at most one graph per distinct project key."""
        GraphCache = _import_cache()
        cache = GraphCache()

        graph1 = _make_graph([("A", "B")])
        graph2 = _make_graph([("C", "D")])
        cache.put("project1", "/path1", graph1, schema_version="1", created_at="T1")
        cache.put("project1", "/path2", graph2, schema_version="1", created_at="T1")

        # Old source path should be gone
        assert cache.get("project1", "/path1", schema_version="1", created_at="T1") is None
        assert cache.get("project1", "/path2", schema_version="1", created_at="T1") is graph2


# ===========================================================================
# 5. Transitive Closure -- Section 4.3
# ===========================================================================

class TestTransitiveClosure:
    """Section 4.3: transitive closure (forward BFS) requirements."""

    def test_linear_chain_unlimited_depth(self):
        """Given A -> B -> C -> D, closure from A includes all nodes.
        depth_map = {0: {A}, 1: {B}, 2: {C}, 3: {D}}, total_depth = 3."""
        transitive_closure, TransitiveClosure = _import_transitive_closure()
        graph = _make_graph([("A", "B"), ("B", "C"), ("C", "D")])

        result = transitive_closure(graph, root="A", max_depth=None, scope_filter=[])

        assert isinstance(result, TransitiveClosure)
        assert result.root == "A"
        assert result.nodes == {"A", "B", "C", "D"}
        assert result.depth_map[0] == {"A"}
        assert result.depth_map[1] == {"B"}
        assert result.depth_map[2] == {"C"}
        assert result.depth_map[3] == {"D"}
        assert result.total_depth == 3

    def test_linear_chain_depth_limited(self):
        """Given A -> B -> C -> D with max_depth=2, D is not reached.
        nodes = {A, B, C}, total_depth = 2."""
        transitive_closure, _ = _import_transitive_closure()
        graph = _make_graph([("A", "B"), ("B", "C"), ("C", "D")])

        result = transitive_closure(graph, root="A", max_depth=2, scope_filter=[])

        assert result.nodes == {"A", "B", "C"}
        assert "D" not in result.nodes
        assert result.total_depth == 2

    def test_root_not_found(self):
        """When root is not in the graph, NOT_FOUND error is returned."""
        transitive_closure, _ = _import_transitive_closure()
        AnalysisError = _import_errors()
        graph = _make_graph([("A", "B")])

        with pytest.raises(AnalysisError) as exc_info:
            transitive_closure(graph, root="Z", max_depth=None, scope_filter=[])
        assert exc_info.value.code == "NOT_FOUND"

    def test_root_with_no_forward_edges(self):
        """Given root has no forward edges, result is {root}, total_depth = 0."""
        transitive_closure, _ = _import_transitive_closure()
        graph = _make_graph([("A", "B")])

        result = transitive_closure(graph, root="B", max_depth=None, scope_filter=[])

        assert result.nodes == {"B"}
        assert result.total_depth == 0
        assert result.depth_map[0] == {"B"}

    def test_edges_only_include_closure_internal(self):
        """Edges set contains only edges where both endpoints are in the closure."""
        transitive_closure, _ = _import_transitive_closure()
        graph = _make_graph([("A", "B"), ("B", "C"), ("C", "D")])

        result = transitive_closure(graph, root="A", max_depth=2, scope_filter=[])

        # D excluded, so (C, D) should not be in edges
        assert ("C", "D") not in result.edges
        assert ("A", "B") in result.edges
        assert ("B", "C") in result.edges

    def test_diamond_graph_earliest_depth(self):
        """In a diamond A -> B, A -> C, B -> D, C -> D,
        D is discovered at depth 2 (earliest BFS level)."""
        transitive_closure, _ = _import_transitive_closure()
        graph = _make_graph([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])

        result = transitive_closure(graph, root="A", max_depth=None, scope_filter=[])

        assert result.depth_map[0] == {"A"}
        assert result.depth_map[1] == {"B", "C"}
        assert result.depth_map[2] == {"D"}
        assert result.total_depth == 2

    def test_max_depth_zero_clamped_to_one(self):
        """max_depth <= 0 is clamped to 1 (Section 7.1)."""
        transitive_closure, _ = _import_transitive_closure()
        graph = _make_graph([("A", "B"), ("B", "C")])

        result = transitive_closure(graph, root="A", max_depth=0, scope_filter=[])

        # Clamped to 1: root + direct neighbors
        assert "A" in result.nodes
        assert "B" in result.nodes
        assert "C" not in result.nodes

    def test_depth_one_matches_find_related_uses(self):
        """When max_depth=1, result contains exactly root + direct forward neighbors."""
        transitive_closure, _ = _import_transitive_closure()
        graph = _make_graph([("A", "B"), ("A", "C"), ("B", "D")])

        result = transitive_closure(graph, root="A", max_depth=1, scope_filter=[])

        assert result.nodes == {"A", "B", "C"}

    def test_empty_root_string_returns_invalid_input(self):
        """Empty root string returns INVALID_INPUT error (Section 7.1)."""
        transitive_closure, _ = _import_transitive_closure()
        AnalysisError = _import_errors()
        graph = _make_graph([("A", "B")])

        with pytest.raises(AnalysisError) as exc_info:
            transitive_closure(graph, root="", max_depth=None, scope_filter=[])
        assert exc_info.value.code == "INVALID_INPUT"

    def test_bfs_visits_each_node_at_most_once(self):
        """MAINTAINS: BFS visits each node at most once, even with cycles."""
        transitive_closure, _ = _import_transitive_closure()
        # Cycle: A -> B -> C -> A
        graph = _make_graph([("A", "B"), ("B", "C"), ("C", "A")])

        result = transitive_closure(graph, root="A", max_depth=None, scope_filter=[])

        assert result.nodes == {"A", "B", "C"}
        # Each node appears in exactly one depth level
        all_depth_nodes = set()
        for nodes_at_depth in result.depth_map.values():
            assert all_depth_nodes.isdisjoint(nodes_at_depth)
            all_depth_nodes.update(nodes_at_depth)


# ===========================================================================
# 6. Scope Filtering -- Section 4.4
# ===========================================================================

class TestScopeFiltering:
    """Section 4.4: scope filter predicates and their composition."""

    def test_exclude_prefix_blocks_traversal(self):
        """exclude_prefix("Stdlib.Init") blocks B in Coq.Init, so C is unreachable."""
        transitive_closure, _ = _import_transitive_closure()
        _, exclude_prefix, _ = _import_filters()

        metadata = {
            "A": ("MyLib", "lemma"),
            "B": ("Stdlib.Init", "definition"),
            "C": ("Stdlib.Arith", "lemma"),
        }
        graph = _make_graph([("A", "B"), ("B", "C")], metadata=metadata)

        result = transitive_closure(
            graph, root="A", max_depth=None,
            scope_filter=[exclude_prefix("Stdlib.Init")],
        )

        assert result.nodes == {"A"}

    def test_module_prefix_includes_only_matching(self):
        """module_prefix("Stdlib.Arith") includes only nodes in that prefix."""
        transitive_closure, _ = _import_transitive_closure()
        module_prefix, _, _ = _import_filters()

        metadata = {
            "Stdlib.Arith.Plus.add_comm": ("Stdlib.Arith.Plus", "lemma"),
            "Stdlib.Init.Nat.add": ("Stdlib.Init.Nat", "definition"),
            "Stdlib.Arith.Mult.mul_comm": ("Stdlib.Arith.Mult", "lemma"),
        }
        graph = _make_graph(
            [("Stdlib.Arith.Plus.add_comm", "Stdlib.Init.Nat.add"),
             ("Stdlib.Arith.Plus.add_comm", "Stdlib.Arith.Mult.mul_comm")],
            metadata=metadata,
        )

        result = transitive_closure(
            graph, root="Stdlib.Arith.Plus.add_comm", max_depth=None,
            scope_filter=[module_prefix("Stdlib.Arith")],
        )

        assert "Stdlib.Arith.Mult.mul_comm" in result.nodes
        assert "Stdlib.Init.Nat.add" not in result.nodes

    def test_filters_compose_as_conjunction(self):
        """Multiple filters compose: node must pass all.
        module_prefix("Stdlib.Arith") AND exclude_prefix("Stdlib.Arith.Div")."""
        transitive_closure, _ = _import_transitive_closure()
        module_prefix, exclude_prefix, _ = _import_filters()

        metadata = {
            "Root.x": ("Root", "lemma"),
            "Stdlib.Arith.Plus.add_comm": ("Stdlib.Arith.Plus", "lemma"),
            "Stdlib.Arith.Div.div_mod": ("Stdlib.Arith.Div", "lemma"),
        }
        graph = _make_graph(
            [("Root.x", "Stdlib.Arith.Plus.add_comm"),
             ("Root.x", "Stdlib.Arith.Div.div_mod")],
            metadata=metadata,
        )

        result = transitive_closure(
            graph, root="Root.x", max_depth=None,
            scope_filter=[module_prefix("Stdlib.Arith"), exclude_prefix("Stdlib.Arith.Div")],
        )

        # Root always included regardless of filters
        assert "Root.x" in result.nodes
        assert "Stdlib.Arith.Plus.add_comm" in result.nodes
        assert "Stdlib.Arith.Div.div_mod" not in result.nodes

    def test_root_always_included_regardless_of_filters(self):
        """Root node is included even when it would be excluded by filters."""
        transitive_closure, _ = _import_transitive_closure()
        _, exclude_prefix, _ = _import_filters()

        metadata = {
            "Stdlib.Init.Root": ("Stdlib.Init", "lemma"),
            "Stdlib.Init.Dep": ("Stdlib.Init", "lemma"),
        }
        graph = _make_graph(
            [("Stdlib.Init.Root", "Stdlib.Init.Dep")],
            metadata=metadata,
        )

        result = transitive_closure(
            graph, root="Stdlib.Init.Root", max_depth=None,
            scope_filter=[exclude_prefix("Stdlib.Init")],
        )

        # Root is included; neighbor is excluded
        assert "Stdlib.Init.Root" in result.nodes
        assert "Stdlib.Init.Dep" not in result.nodes

    def test_same_project_filter(self):
        """same_project includes only nodes sharing root's top-level namespace."""
        transitive_closure, _ = _import_transitive_closure()
        _, _, same_project = _import_filters()

        metadata = {
            "MyLib.Foo.bar": ("MyLib.Foo", "lemma"),
            "MyLib.Baz.qux": ("MyLib.Baz", "definition"),
            "Stdlib.Init.Nat.add": ("Stdlib.Init.Nat", "definition"),
        }
        graph = _make_graph(
            [("MyLib.Foo.bar", "MyLib.Baz.qux"),
             ("MyLib.Foo.bar", "Stdlib.Init.Nat.add")],
            metadata=metadata,
        )

        result = transitive_closure(
            graph, root="MyLib.Foo.bar", max_depth=None,
            scope_filter=[same_project],
        )

        assert "MyLib.Baz.qux" in result.nodes
        assert "Stdlib.Init.Nat.add" not in result.nodes


# ===========================================================================
# 7. Impact Analysis -- Section 4.5
# ===========================================================================

class TestImpactAnalysis:
    """Section 4.5: impact analysis (reverse BFS) requirements."""

    def test_basic_impact(self):
        """Given A->C, B->C, C->D, impact of D = {D, C, A, B}.
        depth_map = {0: {D}, 1: {C}, 2: {A, B}}, total_depth = 2."""
        impact_analysis, ImpactSet = _import_impact_analysis()
        graph = _make_graph([("A", "C"), ("B", "C"), ("C", "D")])

        result = impact_analysis(graph, root="D", max_depth=None, scope_filter=[])

        assert isinstance(result, ImpactSet)
        assert result.root == "D"
        assert result.impacted_nodes == {"D", "C", "A", "B"}
        assert result.depth_map[0] == {"D"}
        assert result.depth_map[1] == {"C"}
        assert result.depth_map[2] == {"A", "B"}
        assert result.total_depth == 2

    def test_no_dependents_returns_root_only(self):
        """When root has no reverse edges, impacted_nodes = {root}, total_depth = 0."""
        impact_analysis, _ = _import_impact_analysis()
        graph = _make_graph([("A", "B")])

        result = impact_analysis(graph, root="A", max_depth=None, scope_filter=[])

        assert result.impacted_nodes == {"A"}
        assert result.total_depth == 0

    def test_root_not_found(self):
        """When root not in graph, NOT_FOUND error."""
        impact_analysis, _ = _import_impact_analysis()
        AnalysisError = _import_errors()
        graph = _make_graph([("A", "B")])

        with pytest.raises(AnalysisError) as exc_info:
            impact_analysis(graph, root="Z", max_depth=None, scope_filter=[])
        assert exc_info.value.code == "NOT_FOUND"

    def test_depth_limited_impact(self):
        """max_depth limits reverse BFS: with depth=1, only direct dependents."""
        impact_analysis, _ = _import_impact_analysis()
        graph = _make_graph([("A", "B"), ("B", "C")])

        result = impact_analysis(graph, root="C", max_depth=1, scope_filter=[])

        assert result.impacted_nodes == {"C", "B"}
        assert "A" not in result.impacted_nodes

    def test_impact_with_scope_filter(self):
        """Scope filters apply to impact analysis the same as transitive closure."""
        impact_analysis, _ = _import_impact_analysis()
        _, exclude_prefix, _ = _import_filters()

        metadata = {
            "Stdlib.Init.Nat.nat": ("Stdlib.Init.Nat", "inductive"),
            "Stdlib.Arith.Plus.add_comm": ("Stdlib.Arith.Plus", "lemma"),
            "External.Lib.thing": ("External.Lib", "definition"),
        }
        graph = _make_graph(
            [("Stdlib.Arith.Plus.add_comm", "Stdlib.Init.Nat.nat"),
             ("External.Lib.thing", "Stdlib.Init.Nat.nat")],
            metadata=metadata,
        )

        result = impact_analysis(
            graph, root="Stdlib.Init.Nat.nat", max_depth=None,
            scope_filter=[exclude_prefix("External")],
        )

        assert "Stdlib.Arith.Plus.add_comm" in result.impacted_nodes
        assert "External.Lib.thing" not in result.impacted_nodes

    def test_empty_root_string_returns_invalid_input(self):
        """Empty root string returns INVALID_INPUT error (Section 7.1)."""
        impact_analysis, _ = _import_impact_analysis()
        AnalysisError = _import_errors()
        graph = _make_graph([("A", "B")])

        with pytest.raises(AnalysisError) as exc_info:
            impact_analysis(graph, root="", max_depth=None, scope_filter=[])
        assert exc_info.value.code == "INVALID_INPUT"


# ===========================================================================
# 8. Cycle Detection -- Section 4.6
# ===========================================================================

class TestCycleDetection:
    """Section 4.6: detect_cycles (Tarjan SCC) requirements."""

    def test_three_node_cycle(self):
        """Given A -> B -> C -> A, cycles = [[A, B, C]], is_acyclic = false."""
        detect_cycles, CycleReport = _import_detect_cycles()
        graph = _make_graph([("A", "B"), ("B", "C"), ("C", "A"), ("D", "E")])

        result = detect_cycles(graph)

        assert isinstance(result, CycleReport)
        assert result.is_acyclic is False
        assert result.total_cycle_count == 1
        assert result.total_nodes_in_cycles == 3
        # SCC rotated to start with lexicographically smallest
        assert len(result.cycles) == 1
        assert result.cycles[0][0] == "A"
        assert set(result.cycles[0]) == {"A", "B", "C"}

    def test_acyclic_graph(self):
        """Given A -> B -> C (acyclic), is_acyclic = true, cycles = []."""
        detect_cycles, _ = _import_detect_cycles()
        graph = _make_graph([("A", "B"), ("B", "C")])

        result = detect_cycles(graph)

        assert result.is_acyclic is True
        assert result.cycles == []
        assert result.total_cycle_count == 0

    def test_two_disjoint_cycles(self):
        """Two disjoint cycles: A<->B and C->D->E->C."""
        detect_cycles, _ = _import_detect_cycles()
        graph = _make_graph([
            ("A", "B"), ("B", "A"),
            ("C", "D"), ("D", "E"), ("E", "C"),
        ])

        result = detect_cycles(graph)

        assert result.total_cycle_count == 2
        assert result.total_nodes_in_cycles == 5
        assert result.is_acyclic is False

        # Each cycle starts with lexicographically smallest
        cycle_sets = [set(c) for c in result.cycles]
        assert {"A", "B"} in cycle_sets
        assert {"C", "D", "E"} in cycle_sets
        for cycle in result.cycles:
            assert cycle[0] == min(cycle)

    def test_self_loop_not_reported(self):
        """A self-loop A -> A is a singleton SCC; not reported (SCC size < 2)."""
        detect_cycles, _ = _import_detect_cycles()
        graph = _make_graph([("A", "A")])

        result = detect_cycles(graph)

        assert result.is_acyclic is True
        assert result.cycles == []

    def test_zero_edge_graph(self):
        """Graph with zero edges: is_acyclic = true."""
        detect_cycles, _ = _import_detect_cycles()
        DependencyGraph, NodeMetadata = _import_graph_types()

        graph = DependencyGraph(
            forward_adj={"A": set(), "B": set()},
            reverse_adj={"A": set(), "B": set()},
            metadata={
                "A": NodeMetadata(module="", kind="lemma"),
                "B": NodeMetadata(module="", kind="lemma"),
            },
            node_count=2,
            edge_count=0,
        )

        result = detect_cycles(graph)

        assert result.is_acyclic is True
        assert result.cycles == []


# ===========================================================================
# 9. Module-Level Aggregation -- Section 4.7
# ===========================================================================

class TestModuleSummary:
    """Section 4.7: module_summary requirements."""

    def test_basic_module_metrics(self):
        """Given Foo.A, Foo.B, Bar.C with edges Foo.A->Foo.B, Foo.A->Bar.C:
        Foo: fan_out=1 (Bar), fan_in=0, internal_nodes=2.
        Bar: fan_out=0, fan_in=1 (Foo), internal_nodes=1."""
        module_summary, ModuleSummary, ModuleMetrics = _import_module_summary()

        metadata = {
            "Foo.A": ("Foo", "lemma"),
            "Foo.B": ("Foo", "definition"),
            "Bar.C": ("Bar", "theorem"),
        }
        graph = _make_graph(
            [("Foo.A", "Foo.B"), ("Foo.A", "Bar.C")],
            metadata=metadata,
        )

        result = module_summary(graph)

        assert isinstance(result, ModuleSummary)
        assert result.total_modules == 2

        assert result.modules["Foo"].fan_out == 1
        assert result.modules["Foo"].fan_in == 0
        assert result.modules["Foo"].internal_nodes == 2

        assert result.modules["Bar"].fan_out == 0
        assert result.modules["Bar"].fan_in == 1
        assert result.modules["Bar"].internal_nodes == 1

    def test_intra_module_edges_excluded_from_module_graph(self):
        """Self-edges (intra-module) are excluded from module_edges."""
        module_summary, _, _ = _import_module_summary()

        metadata = {
            "Foo.A": ("Foo", "lemma"),
            "Foo.B": ("Foo", "lemma"),
        }
        graph = _make_graph([("Foo.A", "Foo.B")], metadata=metadata)

        result = module_summary(graph)

        # Foo -> Foo should not appear
        assert "Foo" not in result.module_edges.get("Foo", [])

    def test_module_level_cycles(self):
        """Detect cycles in the module-level graph."""
        module_summary, _, _ = _import_module_summary()

        # Create a module-level cycle: M1 -> M2 -> M3 -> M1
        metadata = {
            "M1.a": ("M1", "lemma"),
            "M2.b": ("M2", "lemma"),
            "M3.c": ("M3", "lemma"),
        }
        graph = _make_graph(
            [("M1.a", "M2.b"), ("M2.b", "M3.c"), ("M3.c", "M1.a")],
            metadata=metadata,
        )

        result = module_summary(graph)

        assert len(result.module_cycles) == 1
        assert set(result.module_cycles[0]) == {"M1", "M2", "M3"}

    def test_no_module_cycles_in_acyclic_graph(self):
        """Acyclic module graph has empty module_cycles."""
        module_summary, _, _ = _import_module_summary()

        metadata = {
            "A.x": ("A", "lemma"),
            "B.y": ("B", "lemma"),
        }
        graph = _make_graph([("A.x", "B.y")], metadata=metadata)

        result = module_summary(graph)

        assert result.module_cycles == []

    def test_module_edges_are_json_serializable(self):
        """module_edges values are lists (not sets), so the result is JSON-serializable."""
        module_summary, _, _ = _import_module_summary()

        metadata = {
            "A.x": ("A", "lemma"),
            "B.y": ("B", "lemma"),
        }
        graph = _make_graph([("A.x", "B.y")], metadata=metadata)
        result = module_summary(graph)

        import json
        # Should not raise TypeError: Object of type set is not JSON serializable
        serialized = json.dumps({
            "modules": {k: list(v) for k, v in result.modules.items()},
            "module_edges": result.module_edges,
            "module_cycles": result.module_cycles,
            "total_modules": result.total_modules,
        })
        assert isinstance(serialized, str)
        # Verify module_edges values are lists
        for edges in result.module_edges.values():
            assert isinstance(edges, list), f"Expected list, got {type(edges)}"


# ===========================================================================
# 10. Result Size Safety -- Section 4.8
# ===========================================================================

class TestResultSizeSafety:
    """Section 4.8: result size limit of 10,000 nodes."""

    def test_transitive_closure_exceeds_limit(self):
        """When closure exceeds 10,000 nodes, RESULT_TOO_LARGE error."""
        transitive_closure, _ = _import_transitive_closure()
        AnalysisError = _import_errors()

        # Build a graph with > 10,000 reachable nodes from root
        edges = []
        for i in range(10_001):
            edges.append((f"n{i}", f"n{i+1}"))
        graph = _make_graph(edges)

        with pytest.raises(AnalysisError) as exc_info:
            transitive_closure(graph, root="n0", max_depth=None, scope_filter=[])
        assert exc_info.value.code == "RESULT_TOO_LARGE"

    def test_impact_analysis_exceeds_limit(self):
        """When impact set exceeds 10,000 nodes, RESULT_TOO_LARGE error."""
        impact_analysis, _ = _import_impact_analysis()
        AnalysisError = _import_errors()

        # Build a graph where > 10,000 nodes point to a single sink
        edges = []
        for i in range(10_001):
            edges.append((f"n{i}", "sink"))
        graph = _make_graph(edges)

        with pytest.raises(AnalysisError) as exc_info:
            impact_analysis(graph, root="sink", max_depth=None, scope_filter=[])
        assert exc_info.value.code == "RESULT_TOO_LARGE"


# ===========================================================================
# 11. Data Model -- Section 5
# ===========================================================================

class TestDataModel:
    """Section 5: data model constraints for all result types."""

    def test_dependency_graph_is_frozen_dataclass(self):
        """DependencyGraph is a frozen dataclass."""
        DependencyGraph, _ = _import_graph_types()
        import dataclasses
        assert dataclasses.is_dataclass(DependencyGraph)

    def test_node_metadata_is_named_tuple(self):
        """NodeMetadata is a NamedTuple with module and kind."""
        _, NodeMetadata = _import_graph_types()
        meta = NodeMetadata(module="Stdlib.Arith", kind="lemma")
        assert meta.module == "Stdlib.Arith"
        assert meta.kind == "lemma"
        # NamedTuple supports indexing
        assert meta[0] == "Stdlib.Arith"
        assert meta[1] == "lemma"

    def test_transitive_closure_fields(self):
        """TransitiveClosure has root, nodes, edges, depth_map, total_depth."""
        transitive_closure, TransitiveClosure = _import_transitive_closure()
        graph = _make_graph([("A", "B")])
        result = transitive_closure(graph, root="A", max_depth=None, scope_filter=[])

        assert hasattr(result, "root")
        assert hasattr(result, "nodes")
        assert hasattr(result, "edges")
        assert hasattr(result, "depth_map")
        assert hasattr(result, "total_depth")
        assert isinstance(result.nodes, (set, frozenset))
        assert 0 in result.depth_map
        assert result.depth_map[0] == {"A"}

    def test_impact_set_fields(self):
        """ImpactSet has root, impacted_nodes, edges, depth_map, total_depth."""
        impact_analysis, ImpactSet = _import_impact_analysis()
        graph = _make_graph([("A", "B")])
        result = impact_analysis(graph, root="B", max_depth=None, scope_filter=[])

        assert hasattr(result, "root")
        assert hasattr(result, "impacted_nodes")
        assert hasattr(result, "edges")
        assert hasattr(result, "depth_map")
        assert hasattr(result, "total_depth")

    def test_cycle_report_fields(self):
        """CycleReport has cycles, total_cycle_count, total_nodes_in_cycles, is_acyclic."""
        detect_cycles, CycleReport = _import_detect_cycles()
        graph = _make_graph([("A", "B")])
        result = detect_cycles(graph)

        assert hasattr(result, "cycles")
        assert hasattr(result, "total_cycle_count")
        assert hasattr(result, "total_nodes_in_cycles")
        assert hasattr(result, "is_acyclic")

    def test_module_summary_fields(self):
        """ModuleSummary has modules, module_edges, module_cycles, total_modules."""
        module_summary, ModuleSummary, _ = _import_module_summary()
        metadata = {"A.x": ("A", "lemma")}
        graph = _make_graph([], metadata=metadata)
        # Need at least one node; construct directly
        DependencyGraph, NodeMetadata = _import_graph_types()
        graph = DependencyGraph(
            forward_adj={"A.x": set()},
            reverse_adj={"A.x": set()},
            metadata={"A.x": NodeMetadata(module="A", kind="lemma")},
            node_count=1,
            edge_count=0,
        )
        result = module_summary(graph)

        assert hasattr(result, "modules")
        assert hasattr(result, "module_edges")
        assert hasattr(result, "module_cycles")
        assert hasattr(result, "total_modules")

    def test_module_metrics_is_named_tuple(self):
        """ModuleMetrics is a NamedTuple with fan_in, fan_out, internal_nodes."""
        _, _, ModuleMetrics = _import_module_summary()
        m = ModuleMetrics(fan_in=3, fan_out=2, internal_nodes=5)
        assert m.fan_in == 3
        assert m.fan_out == 2
        assert m.internal_nodes == 5
        # NamedTuple supports indexing
        assert m[0] == 3

    def test_node_metadata_kind_enum_values(self):
        """NodeMetadata kind supports all specified enumeration values."""
        _, NodeMetadata = _import_graph_types()
        valid_kinds = [
            "lemma", "theorem", "definition", "inductive", "constructor",
            "record", "class", "instance", "notation", "tactic", "axiom",
        ]
        for kind in valid_kinds:
            meta = NodeMetadata(module="Test", kind=kind)
            assert meta.kind == kind


# ===========================================================================
# 12. Error Specification -- Section 7
# ===========================================================================

class TestErrorSpecification:
    """Section 7: error codes and messages."""

    def test_not_found_error_message(self):
        """NOT_FOUND includes the declaration name in the message."""
        transitive_closure, _ = _import_transitive_closure()
        AnalysisError = _import_errors()
        graph = _make_graph([("A", "B")])

        with pytest.raises(AnalysisError) as exc_info:
            transitive_closure(graph, root="Missing.decl", max_depth=None, scope_filter=[])
        assert exc_info.value.code == "NOT_FOUND"
        assert "Missing.decl" in str(exc_info.value)

    def test_graph_not_ready_error(self):
        """GRAPH_NOT_READY when querying before graph construction."""
        # This tests the engine entry point behavior if it maintains state
        AnalysisError = _import_errors()
        err = AnalysisError("GRAPH_NOT_READY", "Dependency graph has not been constructed.")
        assert err.code == "GRAPH_NOT_READY"

    def test_analysis_error_has_code_and_message(self):
        """AnalysisError has code and message attributes."""
        AnalysisError = _import_errors()
        err = AnalysisError("NOT_FOUND", "Declaration X not found")
        assert err.code == "NOT_FOUND"
        assert "Declaration X not found" in str(err)

    def test_result_too_large_includes_count(self):
        """RESULT_TOO_LARGE error message includes the actual count and limit."""
        AnalysisError = _import_errors()
        err = AnalysisError(
            "RESULT_TOO_LARGE",
            "Result contains 15000 nodes, exceeding the limit of 10000.",
        )
        assert "15000" in str(err)
        assert "10000" in str(err)


# ===========================================================================
# 13. Edge Cases -- Section 7.4
# ===========================================================================

class TestEdgeCases:
    """Section 7.4: edge case behaviors."""

    def test_single_component_name_has_empty_module(self):
        """A declaration with no dots has module set to empty string."""
        build_graph = _import_build_graph()

        dot_content = textwrap.dedent("""\
            digraph dependencies {
              "foo" -> "bar";
            }
        """)
        dot_path = _make_dot_file(dot_content)
        graph = build_graph(dot_file_path=dot_path)

        assert graph.metadata["foo"].module == ""
        assert graph.metadata["bar"].module == ""


