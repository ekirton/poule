"""Integration tests for the MCP server pipeline facade.

These tests exercise the _PipelineFacade through a real SQLite database
populated with spec-compliant data. They verify that the data returned
by each tool conforms to the specification contracts — in particular:

  - declaration names are fully qualified canonical form
  - module fields are logical Coq module paths (not file paths)
  - dependencies and symbols are populated when present in the DB
  - list_modules returns logical module names with declaration counts

These tests exist because the unit tests in test_mcp_server.py use
mocks for the pipeline, which cannot detect when the real storage
layer returns non-compliant data.

Spec: specification/mcp-server.md, specification/data-structures.md
Data model: doc/architecture/data-models/index-entities.md
"""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from Poule.storage import IndexWriter, IndexReader
from Poule.pipeline.context import PipelineContext, create_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Regex: a fully qualified Coq name has at least two dot-separated segments
_FQN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _is_fully_qualified(name: str) -> bool:
    """Return True if *name* looks like a fully qualified Coq identifier."""
    return bool(_FQN_RE.match(name))


def _is_logical_module_path(module: str) -> bool:
    """Return True if *module* is a logical Coq module path, not a file path.

    File paths contain '/' or end with '.vo'; logical paths are dot-separated
    identifiers like 'Coq.Init.Nat'.
    """
    if "/" in module or "\\" in module:
        return False
    if module.endswith(".vo"):
        return False
    return bool(_FQN_RE.match(module))


def _populate_integration_db(writer: IndexWriter) -> dict[str, int]:
    """Insert a realistic dataset with fully qualified names, dependencies,
    and symbols — suitable for integration testing of the pipeline facade."""
    decls = [
        {
            "name": "Coq.Arith.PeanoNat.Nat.add_comm",
            "module": "Coq.Arith.PeanoNat",
            "kind": "lemma",
            "statement": "forall n m : nat, n + m = m + n",
            "type_expr": "forall n m : nat, n + m = m + n",
            "constr_tree": None,
            "node_count": 7,
            "symbol_set": ["Coq.Init.Nat.add", "Coq.Init.Logic.eq"],
        },
        {
            "name": "Coq.Arith.PeanoNat.Nat.add_assoc",
            "module": "Coq.Arith.PeanoNat",
            "kind": "lemma",
            "statement": "forall n m p : nat, n + (m + p) = n + m + p",
            "type_expr": "forall n m p : nat, n + (m + p) = n + m + p",
            "constr_tree": None,
            "node_count": 11,
            "symbol_set": ["Coq.Init.Nat.add", "Coq.Init.Logic.eq"],
        },
        {
            "name": "Coq.Init.Nat.add",
            "module": "Coq.Init.Nat",
            "kind": "definition",
            "statement": "fix add (n m : nat) : nat := ...",
            "type_expr": "nat -> nat -> nat",
            "constr_tree": None,
            "node_count": 5,
            "symbol_set": ["Coq.Init.Datatypes.nat"],
        },
    ]
    ids = writer.insert_declarations(decls)

    id_comm = ids["Coq.Arith.PeanoNat.Nat.add_comm"]
    id_assoc = ids["Coq.Arith.PeanoNat.Nat.add_assoc"]
    id_add = ids["Coq.Init.Nat.add"]

    # add_comm uses add; add_assoc uses add
    writer.insert_dependencies([
        {"src": id_comm, "dst": id_add, "relation": "uses"},
        {"src": id_assoc, "dst": id_add, "relation": "uses"},
    ])

    # WL vectors (minimal, needed for create_context to succeed)
    writer.insert_wl_vectors([
        {"decl_id": id_comm, "h": 1, "histogram": {"LProd": 1}},
        {"decl_id": id_assoc, "h": 1, "histogram": {"LProd": 1}},
        {"decl_id": id_add, "h": 1, "histogram": {"LApp": 1}},
    ])

    writer.insert_symbol_freq({
        "Coq.Init.Nat.add": 3,
        "Coq.Init.Logic.eq": 2,
        "Coq.Init.Datatypes.nat": 1,
    })

    writer.write_meta("schema_version", "1")
    writer.write_meta("coq_version", "8.19")
    writer.write_meta("created_at", "2026-03-16T12:00:00Z")
    writer.finalize()
    return ids


def _build_facade(db_path):
    """Create a _PipelineFacade backed by a real database."""
    from Poule.server.__main__ import _PipelineFacade

    pipeline_ctx = create_context(str(db_path))
    return _PipelineFacade(pipeline_ctx)


@pytest.fixture
def facade(tmp_path):
    """Return a _PipelineFacade backed by a real SQLite database with
    spec-compliant test data."""
    db_path = tmp_path / "integration.db"
    writer = IndexWriter.create(db_path)
    _populate_integration_db(writer)
    return _build_facade(db_path)


# ===========================================================================
# 1. get_lemma: spec-compliant field values
# ===========================================================================


class TestGetLemmaIntegration:
    """_PipelineFacade.get_lemma returns spec-compliant LemmaDetail dicts."""

    def test_name_is_fully_qualified(self, facade):
        result = facade.get_lemma("Coq.Arith.PeanoNat.Nat.add_comm")
        assert result is not None
        assert _is_fully_qualified(result["name"]), (
            f"Expected fully qualified name, got: {result['name']}"
        )

    def test_module_is_logical_path(self, facade):
        result = facade.get_lemma("Coq.Arith.PeanoNat.Nat.add_comm")
        assert result is not None
        assert _is_logical_module_path(result["module"]), (
            f"Expected logical module path, got: {result['module']}"
        )

    def test_dependencies_populated(self, facade):
        """add_comm uses add — dependencies list must not be empty."""
        result = facade.get_lemma("Coq.Arith.PeanoNat.Nat.add_comm")
        assert result is not None
        assert len(result["dependencies"]) > 0, (
            "Expected non-empty dependencies for Nat.add_comm"
        )
        assert "Coq.Init.Nat.add" in result["dependencies"]

    def test_dependents_populated(self, facade):
        """add is used by add_comm and add_assoc — dependents must not be empty."""
        result = facade.get_lemma("Coq.Init.Nat.add")
        assert result is not None
        assert len(result["dependents"]) > 0, (
            "Expected non-empty dependents for Coq.Init.Nat.add"
        )

    def test_symbols_populated(self, facade):
        """add_comm has a non-empty symbol_set in the DB."""
        result = facade.get_lemma("Coq.Arith.PeanoNat.Nat.add_comm")
        assert result is not None
        assert len(result["symbols"]) > 0, (
            "Expected non-empty symbols for Nat.add_comm"
        )
        assert "Coq.Init.Nat.add" in result["symbols"]

    def test_node_count_positive(self, facade):
        result = facade.get_lemma("Coq.Arith.PeanoNat.Nat.add_comm")
        assert result is not None
        assert result["node_count"] > 0

    def test_score_is_1_point_0(self, facade):
        result = facade.get_lemma("Coq.Arith.PeanoNat.Nat.add_comm")
        assert result is not None
        assert result["score"] == 1.0

    def test_proof_sketch_empty_in_phase_1(self, facade):
        result = facade.get_lemma("Coq.Arith.PeanoNat.Nat.add_comm")
        assert result is not None
        assert result["proof_sketch"] == ""

    def test_all_required_fields_present(self, facade):
        result = facade.get_lemma("Coq.Arith.PeanoNat.Nat.add_comm")
        assert result is not None
        required = {
            "name", "statement", "type", "module", "kind", "score",
            "dependencies", "dependents", "proof_sketch", "symbols",
            "node_count",
        }
        assert required.issubset(set(result.keys())), (
            f"Missing fields: {required - set(result.keys())}"
        )

    def test_not_found_returns_none(self, facade):
        result = facade.get_lemma("Nonexistent.Declaration")
        assert result is None

    def test_dependency_names_are_fully_qualified(self, facade):
        result = facade.get_lemma("Coq.Arith.PeanoNat.Nat.add_comm")
        assert result is not None
        for dep_name in result["dependencies"]:
            assert _is_fully_qualified(dep_name), (
                f"Dependency name not fully qualified: {dep_name}"
            )

    def test_dependent_names_are_fully_qualified(self, facade):
        result = facade.get_lemma("Coq.Init.Nat.add")
        assert result is not None
        for dep_name in result["dependents"]:
            assert _is_fully_qualified(dep_name), (
                f"Dependent name not fully qualified: {dep_name}"
            )


# ===========================================================================
# 2. find_related: spec-compliant results
# ===========================================================================


class TestFindRelatedIntegration:
    """_PipelineFacade.find_related returns spec-compliant SearchResult dicts."""

    def test_uses_returns_dependencies(self, facade):
        results = facade.find_related(
            "Coq.Arith.PeanoNat.Nat.add_comm", "uses"
        )
        assert results is not None
        assert len(results) > 0
        names = [r["name"] for r in results]
        assert "Coq.Init.Nat.add" in names

    def test_used_by_returns_dependents(self, facade):
        results = facade.find_related("Coq.Init.Nat.add", "used_by")
        assert results is not None
        assert len(results) > 0
        names = [r["name"] for r in results]
        assert "Coq.Arith.PeanoNat.Nat.add_comm" in names

    def test_same_module_returns_siblings(self, facade):
        results = facade.find_related(
            "Coq.Arith.PeanoNat.Nat.add_comm", "same_module"
        )
        assert results is not None
        assert len(results) > 0
        names = [r["name"] for r in results]
        assert "Coq.Arith.PeanoNat.Nat.add_assoc" in names

    def test_result_names_are_fully_qualified(self, facade):
        results = facade.find_related(
            "Coq.Arith.PeanoNat.Nat.add_comm", "uses"
        )
        assert results is not None
        for r in results:
            assert _is_fully_qualified(r["name"]), (
                f"Related name not fully qualified: {r['name']}"
            )

    def test_result_modules_are_logical_paths(self, facade):
        results = facade.find_related(
            "Coq.Arith.PeanoNat.Nat.add_comm", "same_module"
        )
        assert results is not None
        for r in results:
            assert _is_logical_module_path(r["module"]), (
                f"Module not a logical path: {r['module']}"
            )

    def test_all_scores_are_1_point_0(self, facade):
        results = facade.find_related(
            "Coq.Arith.PeanoNat.Nat.add_comm", "uses"
        )
        assert results is not None
        for r in results:
            assert r["score"] == 1.0

    def test_not_found_returns_none(self, facade):
        result = facade.find_related("Nonexistent.Decl", "uses")
        assert result is None

    def test_result_has_all_search_result_fields(self, facade):
        results = facade.find_related(
            "Coq.Arith.PeanoNat.Nat.add_comm", "uses"
        )
        assert results is not None and len(results) > 0
        required = {"name", "statement", "type", "module", "kind", "score"}
        for r in results:
            assert required.issubset(set(r.keys())), (
                f"Missing fields: {required - set(r.keys())}"
            )


# ===========================================================================
# 3. list_modules: logical module names
# ===========================================================================


class TestListModulesIntegration:
    """_PipelineFacade.list_modules returns logical module paths."""

    def test_returns_logical_module_names(self, facade):
        modules = facade.list_modules("")
        assert len(modules) > 0
        for m in modules:
            assert _is_logical_module_path(m["name"]), (
                f"Module name is not a logical path: {m['name']}"
            )

    def test_prefix_filtering(self, facade):
        modules = facade.list_modules("Coq.Arith")
        assert len(modules) > 0
        for m in modules:
            assert m["name"].startswith("Coq.Arith"), (
                f"Module {m['name']} doesn't match prefix 'Coq.Arith'"
            )

    def test_empty_prefix_returns_all_modules(self, facade):
        modules = facade.list_modules("")
        names = {m["name"] for m in modules}
        assert "Coq.Arith.PeanoNat" in names
        assert "Coq.Init.Nat" in names

    def test_each_module_has_decl_count(self, facade):
        modules = facade.list_modules("")
        for m in modules:
            assert "decl_count" in m
            assert m["decl_count"] > 0

    def test_decl_counts_are_accurate(self, facade):
        modules = facade.list_modules("")
        by_name = {m["name"]: m["decl_count"] for m in modules}
        # Coq.Arith.PeanoNat has add_comm and add_assoc
        assert by_name.get("Coq.Arith.PeanoNat") == 2
        # Coq.Init.Nat has add
        assert by_name.get("Coq.Init.Nat") == 1

    def test_corelib_prefix_returns_same_as_coq(self, facade):
        """Corelib.Arith prefix returns the same modules as Coq.Arith."""
        coq_modules = facade.list_modules("Coq.Arith")
        corelib_modules = facade.list_modules("Corelib.Arith")
        assert len(corelib_modules) > 0
        assert len(corelib_modules) == len(coq_modules)
        coq_names = {m["name"] for m in coq_modules}
        corelib_names = {m["name"] for m in corelib_modules}
        assert coq_names == corelib_names

    def test_corelib_prefix_init(self, facade):
        """Corelib.Init prefix returns modules."""
        modules = facade.list_modules("Corelib.Init")
        assert len(modules) > 0
        for m in modules:
            assert m["name"].startswith("Coq.Init"), (
                f"Module {m['name']} doesn't start with 'Coq.Init'"
            )

    def test_no_match_returns_empty_list(self, facade):
        modules = facade.list_modules("Nonexistent.Prefix")
        assert modules == []

    def test_module_names_not_file_paths(self, facade):
        """Regression: module names must never be file system paths."""
        modules = facade.list_modules("")
        for m in modules:
            assert "/" not in m["name"], (
                f"Module name looks like a file path: {m['name']}"
            )
            assert not m["name"].endswith(".vo"), (
                f"Module name looks like a .vo file: {m['name']}"
            )


# ===========================================================================
# 4. search_by_name: spec-compliant results via FTS
# ===========================================================================


class TestSearchByNameIntegration:
    """_PipelineFacade.search_by_name returns spec-compliant SearchResults."""

    def test_finds_declaration_by_substring(self, facade):
        results = facade.search_by_name("add_comm", 10)
        assert len(results) > 0

    def test_result_names_are_fully_qualified(self, facade):
        results = facade.search_by_name("add", 10)
        for r in results:
            name = r["name"] if isinstance(r, dict) else r.name
            assert _is_fully_qualified(name), (
                f"Search result name not fully qualified: {name}"
            )

    def test_result_modules_are_logical_paths(self, facade):
        results = facade.search_by_name("add", 10)
        for r in results:
            module = r["module"] if isinstance(r, dict) else r.module
            assert _is_logical_module_path(module), (
                f"Search result module not a logical path: {module}"
            )


# ===========================================================================
# 5. Full-stack handler integration: _dispatch_tool → facade → real DB
# ===========================================================================


class TestDispatchToolIntegration:
    """End-to-end: _dispatch_tool through _PipelineFacade to real SQLite."""

    @pytest.fixture
    def server_ctx(self, tmp_path):
        """Create a _ServerContext with a real _PipelineFacade."""
        from Poule.server.__main__ import _ServerContext, _PipelineFacade

        db_path = tmp_path / "integration.db"
        writer = IndexWriter.create(db_path)
        _populate_integration_db(writer)

        pipeline_ctx = create_context(str(db_path))

        ctx = _ServerContext()
        ctx.index_ready = True
        ctx.index_version_mismatch = False
        ctx.pipeline = _PipelineFacade(pipeline_ctx)
        return ctx

    def test_get_lemma_returns_fully_qualified_name(self, server_ctx):
        from Poule.server.__main__ import _dispatch_tool

        result = _dispatch_tool(
            server_ctx, "get_lemma",
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm"},
        )
        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert _is_fully_qualified(parsed["name"])

    def test_get_lemma_module_is_logical_path(self, server_ctx):
        from Poule.server.__main__ import _dispatch_tool

        result = _dispatch_tool(
            server_ctx, "get_lemma",
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm"},
        )
        parsed = json.loads(result["content"][0]["text"])
        assert _is_logical_module_path(parsed["module"])

    def test_get_lemma_has_populated_dependencies(self, server_ctx):
        from Poule.server.__main__ import _dispatch_tool

        result = _dispatch_tool(
            server_ctx, "get_lemma",
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm"},
        )
        parsed = json.loads(result["content"][0]["text"])
        assert len(parsed["dependencies"]) > 0
        assert "Coq.Init.Nat.add" in parsed["dependencies"]

    def test_get_lemma_has_populated_symbols(self, server_ctx):
        from Poule.server.__main__ import _dispatch_tool

        result = _dispatch_tool(
            server_ctx, "get_lemma",
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm"},
        )
        parsed = json.loads(result["content"][0]["text"])
        assert len(parsed["symbols"]) > 0

    def test_list_modules_returns_logical_paths(self, server_ctx):
        from Poule.server.__main__ import _dispatch_tool

        result = _dispatch_tool(
            server_ctx, "list_modules", {"prefix": "Coq.Arith"},
        )
        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert len(parsed) > 0
        for m in parsed:
            assert _is_logical_module_path(m["name"]), (
                f"Module name is not a logical path: {m['name']}"
            )

    def test_find_related_uses_returns_results(self, server_ctx):
        from Poule.server.__main__ import _dispatch_tool

        result = _dispatch_tool(
            server_ctx, "find_related",
            {"name": "Coq.Arith.PeanoNat.Nat.add_comm", "relation": "uses"},
        )
        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert len(parsed) > 0
        for r in parsed:
            assert _is_fully_qualified(r["name"])

    def test_search_by_name_results_are_spec_compliant(self, server_ctx):
        from Poule.server.__main__ import _dispatch_tool

        result = _dispatch_tool(
            server_ctx, "search_by_name",
            {"pattern": "add_comm", "limit": 10},
        )
        assert result.get("isError") is not True
        parsed = json.loads(result["content"][0]["text"])
        assert len(parsed) > 0
        for r in parsed:
            assert _is_fully_qualified(r["name"]), (
                f"Name not fully qualified: {r['name']}"
            )
            assert _is_logical_module_path(r["module"]), (
                f"Module not logical path: {r['module']}"
            )
