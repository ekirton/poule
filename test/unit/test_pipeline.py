"""TDD tests for the query processing pipeline -- written before implementation.

Tests target the public API defined in specification/pipeline.md:
  - PipelineContext and create_context(db_path)
  - CoqParser protocol with parse(expression) -> ConstrNode
  - search_by_structure(ctx, expression, limit) -> list[SearchResult]
  - search_by_type(ctx, type_expr, limit) -> list[SearchResult]
  - search_by_symbols(ctx, symbols, limit) -> list[SearchResult]
  - search_by_name(ctx, pattern, limit) -> list[SearchResult]
  - score_candidates(query_tree, candidates_with_wl, ctx)

Implementation will live in src/poule/pipeline/.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, Mock, patch

import pytest

from Poule.pipeline.context import PipelineContext, create_context
from Poule.pipeline.search import (
    _peel_n_prods,
    normalize_type_query,
    score_candidates,
    search_by_name,
    search_by_structure,
    search_by_symbols,
    search_by_type,
)
from Poule.pipeline.parser import CoqParser, ParseError


# ---------------------------------------------------------------------------
# Helpers: build minimal mock objects used across tests
# ---------------------------------------------------------------------------


def _mock_reader():
    """Return a mock IndexReader with default stubs for all loader methods."""
    reader = MagicMock()
    # Real IndexReader returns {decl_id: {h: histogram}} (storage.md §4.3).
    # create_context must select h=3 to produce flat {decl_id: histogram}.
    reader.load_wl_histograms.return_value = {
        1: {3: {"label_A": 3, "label_B": 1}},
        2: {3: {"label_A": 2, "label_C": 4}},
        3: {3: {"label_B": 5}},
    }
    reader.load_inverted_index.return_value = {
        "Coq.Init.Nat.add": {1, 2},
        "Coq.Init.Datatypes.nat": {1, 2, 3},
        "Coq.Init.Logic.eq": {1, 3},
    }
    reader.load_symbol_frequencies.return_value = {
        "Coq.Init.Nat.add": 2,
        "Coq.Init.Datatypes.nat": 3,
        "Coq.Init.Logic.eq": 2,
    }
    reader.load_declaration_node_counts.return_value = {1: 10, 2: 20, 3: 60}
    return reader


def _mock_search_result(decl_id, score):
    """Return a mock SearchResult with the given id and score."""
    result = MagicMock()
    result.name = f"Decl.{decl_id}"
    result.statement = f"statement_{decl_id}"
    result.type = f"type_{decl_id}"
    result.module = f"Module.{decl_id}"
    result.kind = "Lemma"
    result.score = score
    result.decl_id = decl_id
    return result


def _mock_parser():
    """Return a mock CoqParser whose parse() returns a mock ConstrNode."""
    parser = MagicMock(spec=CoqParser)
    constr_node = MagicMock()
    parser.parse.return_value = constr_node
    return parser


def _build_suffix_index(inverted_index):
    """Build a suffix index from inverted index keys (matches spec §4.1)."""
    suffix_index: dict[str, list[str]] = {}
    for fqn in inverted_index:
        parts = fqn.split(".")
        for k in range(1, len(parts)):
            suffix = ".".join(parts[k:])
            suffix_index.setdefault(suffix, []).append(fqn)
    return suffix_index


def _mock_context_corelib(parser=None):
    """Return a PipelineContext-like mock with Corelib.* FQNs (Rocq 9.x naming)."""
    ctx = MagicMock(spec=PipelineContext)
    ctx.reader = MagicMock()
    ctx.wl_histograms = {
        1: {"label_A": 3, "label_B": 1},
        2: {"label_A": 2, "label_C": 4},
        3: {"label_B": 5},
    }
    ctx.inverted_index = {
        "Corelib.Init.Nat.add": {1, 2},
        "Corelib.Init.Datatypes.nat": {1, 2, 3},
        "Corelib.Init.Logic.eq": {1, 3},
    }
    ctx.symbol_frequencies = {
        "Corelib.Init.Nat.add": 2,
        "Corelib.Init.Datatypes.nat": 3,
        "Corelib.Init.Logic.eq": 2,
    }
    ctx.declaration_node_counts = {1: 10, 2: 20, 3: 60}
    ctx.declaration_symbols = {
        1: {"Corelib.Init.Nat.add", "Corelib.Init.Datatypes.nat", "Corelib.Init.Logic.eq"},
        2: {"Corelib.Init.Nat.add", "Corelib.Init.Datatypes.nat"},
        3: {"Corelib.Init.Datatypes.nat", "Corelib.Init.Logic.eq"},
    }
    ctx.suffix_index = _build_suffix_index(ctx.inverted_index)
    ctx.parser = parser
    ctx.rrf_k = 60
    ctx.rrf_weights = None
    return ctx


def _mock_context_mixed_symbols(parser=None):
    """Return a PipelineContext-like mock reflecting production index where
    the same symbol appears under both short (Nat.add) and Corelib FQN
    (Corelib.Init.Nat.add) keys, pointing to different declaration sets.

    This mirrors the real index: most declarations use short names (Nat.add)
    while a few use Corelib-qualified names (Corelib.Init.Nat.add).
    """
    ctx = MagicMock(spec=PipelineContext)
    ctx.reader = MagicMock()
    ctx.wl_histograms = {i: {"label_A": 1} for i in range(1, 7)}
    ctx.inverted_index = {
        # Short names — most declarations use these
        "Nat.add": {1, 2, 3, 4},
        "Nat.mul": {2, 3, 4, 5},
        "=": {1, 2, 3, 4, 5, 6},
        "Corelib.Init.Datatypes.nat": {1, 2, 3, 4, 5, 6},
        # Corelib FQN — a few declarations use these
        "Corelib.Init.Nat.add": {6},
        "Corelib.Init.Nat.mul": {6},
    }
    ctx.symbol_frequencies = {
        "Nat.add": 4,
        "Nat.mul": 4,
        "=": 6,
        "Corelib.Init.Datatypes.nat": 6,
        "Corelib.Init.Nat.add": 1,
        "Corelib.Init.Nat.mul": 1,
    }
    ctx.declaration_node_counts = {i: 10 for i in range(1, 7)}
    ctx.declaration_symbols = {}
    for sym, ids in ctx.inverted_index.items():
        for did in ids:
            ctx.declaration_symbols.setdefault(did, set()).add(sym)
    ctx.suffix_index = _build_suffix_index(ctx.inverted_index)
    ctx.parser = parser
    ctx.rrf_k = 60
    ctx.rrf_weights = None
    return ctx


def _mock_context(parser=None):
    """Return a PipelineContext-like mock with all expected fields."""
    ctx = MagicMock(spec=PipelineContext)
    ctx.reader = _mock_reader()
    # Pipeline context holds flat {decl_id: histogram} after h-selection.
    raw_wl = ctx.reader.load_wl_histograms()
    ctx.wl_histograms = {did: hists[3] for did, hists in raw_wl.items() if 3 in hists}
    ctx.inverted_index = ctx.reader.load_inverted_index()
    ctx.symbol_frequencies = ctx.reader.load_symbol_frequencies()
    ctx.declaration_node_counts = ctx.reader.load_declaration_node_counts()
    # declaration_symbols derived from inverted index
    ctx.declaration_symbols = {
        1: {"Coq.Init.Nat.add", "Coq.Init.Datatypes.nat", "Coq.Init.Logic.eq"},
        2: {"Coq.Init.Nat.add", "Coq.Init.Datatypes.nat"},
        3: {"Coq.Init.Datatypes.nat", "Coq.Init.Logic.eq"},
    }
    ctx.suffix_index = _build_suffix_index(ctx.inverted_index)
    ctx.parser = parser
    ctx.rrf_k = 60
    ctx.rrf_weights = None
    return ctx


# ---------------------------------------------------------------------------
# 1. create_context loads all in-memory data from reader
# ---------------------------------------------------------------------------


class TestCreateContext:
    """create_context(db_path) opens the reader and loads all in-memory structures."""

    @patch("Poule.pipeline.context.IndexReader")
    def test_loads_all_data_from_reader(self, MockIndexReader):
        reader = _mock_reader()
        MockIndexReader.return_value = reader

        ctx = create_context("/tmp/test.db")

        reader.load_wl_histograms.assert_called_once()
        reader.load_inverted_index.assert_called_once()
        reader.load_symbol_frequencies.assert_called_once()
        assert ctx.reader is reader
        # create_context selects h=3 from the nested reader output (pipeline.md §4.1)
        raw_wl = reader.load_wl_histograms()
        expected_flat = {did: hists[3] for did, hists in raw_wl.items() if 3 in hists}
        assert ctx.wl_histograms == expected_flat
        assert ctx.inverted_index == reader.load_inverted_index()
        assert ctx.symbol_frequencies == reader.load_symbol_frequencies()

    @patch("Poule.pipeline.context.IndexReader")
    def test_declaration_symbols_derived_from_inverted_index(self, MockIndexReader):
        reader = _mock_reader()
        MockIndexReader.return_value = reader

        ctx = create_context("/tmp/test.db")

        # declaration_symbols should map decl_id -> set of symbols
        assert isinstance(ctx.declaration_symbols, dict)
        # decl 1 appears under Nat.add, nat, and eq
        assert "Coq.Init.Nat.add" in ctx.declaration_symbols[1]
        assert "Coq.Init.Datatypes.nat" in ctx.declaration_symbols[1]

    @patch("Poule.pipeline.context.IndexReader")
    def test_declaration_node_counts_loaded(self, MockIndexReader):
        reader = _mock_reader()
        MockIndexReader.return_value = reader

        ctx = create_context("/tmp/test.db")

        assert ctx.declaration_node_counts == {1: 10, 2: 20, 3: 60}

    @patch("Poule.pipeline.context.IndexReader")
    def test_suffix_index_built_from_inverted_index_keys(self, MockIndexReader):
        """create_context builds a suffix_index mapping suffixes to FQNs (spec §4.1)."""
        reader = _mock_reader()
        MockIndexReader.return_value = reader

        ctx = create_context("/tmp/test.db")

        assert hasattr(ctx, "suffix_index")
        assert isinstance(ctx.suffix_index, dict)
        # "Nat.add" is a suffix of "Coq.Init.Nat.add"
        assert "Nat.add" in ctx.suffix_index
        assert "Coq.Init.Nat.add" in ctx.suffix_index["Nat.add"]
        # "Init.Datatypes.nat" is a suffix of "Coq.Init.Datatypes.nat"
        assert "Init.Datatypes.nat" in ctx.suffix_index
        assert "Coq.Init.Datatypes.nat" in ctx.suffix_index["Init.Datatypes.nat"]

    @patch("Poule.pipeline.context.IndexReader")
    def test_suffix_index_contains_all_proper_suffixes(self, MockIndexReader):
        """Each FQN contributes all proper dot-separated suffixes (spec §4.1)."""
        reader = _mock_reader()
        MockIndexReader.return_value = reader

        ctx = create_context("/tmp/test.db")

        # "Coq.Init.Nat.add" should produce: "Init.Nat.add", "Nat.add", "add"
        for suffix in ["Init.Nat.add", "Nat.add", "add"]:
            assert suffix in ctx.suffix_index, f"Missing suffix: {suffix}"
            assert "Coq.Init.Nat.add" in ctx.suffix_index[suffix]

    @patch("Poule.pipeline.context.IndexReader")
    def test_suffix_index_ambiguous_suffixes_retain_all_fqns(self, MockIndexReader):
        """Ambiguous suffixes (matching multiple FQNs) retain all matches (spec §4.1)."""
        reader = _mock_reader()
        # Add a second FQN that shares the suffix "eq" with "Coq.Init.Logic.eq"
        inv_idx = reader.load_inverted_index.return_value
        inv_idx["Coq.Arith.PeanoNat.Nat.eq"] = {4}
        MockIndexReader.return_value = reader

        ctx = create_context("/tmp/test.db")

        # "eq" is a suffix of both FQNs
        assert "eq" in ctx.suffix_index
        fqns = ctx.suffix_index["eq"]
        assert "Coq.Init.Logic.eq" in fqns
        assert "Coq.Arith.PeanoNat.Nat.eq" in fqns

    @patch("Poule.pipeline.context.IndexReader")
    def test_suffix_index_enriched_with_re_export_aliases(self, MockIndexReader):
        """Re-export aliases contribute additional suffixes mapping to
        the canonical FQN (spec §4.1 suffix index construction).

        Alias: Coq.Lists.List.map → Coq.Lists.ListDef.map
        Produces suffixes: Lists.List.map, List.map, map → all pointing
        to Coq.Lists.ListDef.map."""
        reader = _mock_reader()
        # Add ListDef.map to the inverted index
        reader.load_inverted_index.return_value["Coq.Lists.ListDef.map"] = {4}
        # Add re-export alias
        reader.load_re_export_aliases = MagicMock(
            return_value={"Coq.Lists.List.map": "Coq.Lists.ListDef.map"}
        )
        MockIndexReader.return_value = reader

        ctx = create_context("/tmp/test.db")

        # "List.map" should be in the suffix index, mapping to the canonical FQN
        assert "List.map" in ctx.suffix_index
        assert "Coq.Lists.ListDef.map" in ctx.suffix_index["List.map"]
        # "Lists.List.map" should also be present
        assert "Lists.List.map" in ctx.suffix_index
        assert "Coq.Lists.ListDef.map" in ctx.suffix_index["Lists.List.map"]

    @patch("Poule.pipeline.context.IndexReader")
    def test_suffix_index_no_aliases_when_reader_has_none(self, MockIndexReader):
        """When the reader returns empty aliases, suffix index uses only
        inverted index keys (backward compatibility)."""
        reader = _mock_reader()
        reader.load_re_export_aliases = MagicMock(return_value={})
        MockIndexReader.return_value = reader

        ctx = create_context("/tmp/test.db")

        # Suffix index should still work from inverted index keys
        assert "Nat.add" in ctx.suffix_index


# ---------------------------------------------------------------------------
# 2. PipelineContext.parser is None initially (lazy)
# ---------------------------------------------------------------------------


class TestPipelineContextParserLazy:
    """The parser field is None until the first structural or type query."""

    @patch("Poule.pipeline.context.IndexReader")
    def test_parser_is_none_after_creation(self, MockIndexReader):
        MockIndexReader.return_value = _mock_reader()

        ctx = create_context("/tmp/test.db")

        assert ctx.parser is None


# ---------------------------------------------------------------------------
# 3. search_by_name: calls fts_query then fts_search
# ---------------------------------------------------------------------------


class TestSearchByName:
    """search_by_name delegates to fts_query and fts_search."""

    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    def test_calls_fts_query_then_fts_search(self, mock_fts_query, mock_fts_search):
        ctx = _mock_context()
        mock_fts_query.return_value = "Nat AND add AND comm"
        mock_fts_search.return_value = [
            _mock_search_result(1, 0.9),
            _mock_search_result(2, 0.7),
        ]

        results = search_by_name(ctx, "Nat.add_comm", limit=10)

        mock_fts_query.assert_called_once_with("Nat.add_comm")
        mock_fts_search.assert_called_once_with(
            "Nat AND add AND comm", limit=10, reader=ctx.reader
        )
        assert len(results) == 2

    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    def test_returns_search_result_list(self, mock_fts_query, mock_fts_search):
        ctx = _mock_context()
        mock_fts_query.return_value = "commutativity"
        expected = [_mock_search_result(1, 0.95)]
        mock_fts_search.return_value = expected

        results = search_by_name(ctx, "commutativity", limit=5)

        assert results == expected

    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    def test_empty_fts_query_returns_empty(self, mock_fts_query, mock_fts_search):
        ctx = _mock_context()
        mock_fts_query.return_value = ""

        results = search_by_name(ctx, "", limit=10)

        mock_fts_search.assert_not_called()
        assert results == []


# ---------------------------------------------------------------------------
# 4. search_by_symbols: resolves names, calls mepo_select, returns top-limit
# ---------------------------------------------------------------------------


class TestResolveQuerySymbols:
    """resolve_query_symbols resolves short/partial names to FQNs via suffix index (spec §4.5.1)."""

    def test_exact_fqn_used_directly(self):
        """A symbol that is an exact key in the inverted index passes through unchanged."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context()

        resolved = resolve_query_symbols(ctx, ["Coq.Init.Nat.add"])

        assert "Coq.Init.Nat.add" in resolved

    def test_short_name_resolved_via_suffix_index(self):
        """A short name like 'Nat.add' is resolved to its FQN via suffix match."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context()

        resolved = resolve_query_symbols(ctx, ["Nat.add"])

        assert "Coq.Init.Nat.add" in resolved

    def test_partial_qualification_resolved(self):
        """A partial qualification like 'Init.Nat.add' is resolved via suffix match."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context()

        resolved = resolve_query_symbols(ctx, ["Init.Nat.add"])

        assert "Coq.Init.Nat.add" in resolved

    def test_ambiguous_suffix_expands_to_all_fqns(self):
        """An ambiguous short name expands to all matching FQNs (spec §4.5.1)."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context()
        # "nat" is a suffix of "Coq.Init.Datatypes.nat"; add a second FQN
        ctx.suffix_index["nat"] = [
            "Coq.Init.Datatypes.nat",
            "Coq.ZArith.BinInt.Z.nat",
        ]

        resolved = resolve_query_symbols(ctx, ["nat"])

        assert "Coq.Init.Datatypes.nat" in resolved
        assert "Coq.ZArith.BinInt.Z.nat" in resolved

    def test_unknown_symbol_passed_through(self):
        """A symbol matching neither the inverted index nor suffix index is included as-is."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context()

        resolved = resolve_query_symbols(ctx, ["my_custom_def"])

        assert "my_custom_def" in resolved

    def test_mixed_symbols_resolved(self):
        """A mix of FQN, short, and unknown symbols are all resolved correctly."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context()

        resolved = resolve_query_symbols(
            ctx, ["Coq.Init.Nat.add", "Nat.add", "Logic.eq", "unknown"]
        )

        assert "Coq.Init.Nat.add" in resolved
        assert "Coq.Init.Logic.eq" in resolved
        assert "unknown" in resolved

    def test_coq_prefix_resolves_to_corelib_fqn(self):
        """Coq.* legacy prefix resolves to Corelib.* FQN when index uses Rocq 9.x naming."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context_corelib()

        resolved = resolve_query_symbols(ctx, ["Coq.Init.Nat.add"])

        # Must resolve to the Corelib FQN, not pass through as-is
        assert "Corelib.Init.Nat.add" in resolved
        assert "Coq.Init.Nat.add" not in resolved

    def test_coq_prefix_resolution_multiple_symbols(self):
        """Multiple Coq.* symbols all resolve to their Corelib.* counterparts."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context_corelib()

        resolved = resolve_query_symbols(
            ctx, ["Coq.Init.Nat.add", "Coq.Init.Datatypes.nat"]
        )

        assert "Corelib.Init.Nat.add" in resolved
        assert "Corelib.Init.Datatypes.nat" in resolved

    def test_coq_prefix_mixed_with_short_names(self):
        """Coq.* prefix resolution works alongside suffix resolution."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context_corelib()

        resolved = resolve_query_symbols(
            ctx, ["Coq.Init.Nat.add", "Nat.add", "unknown"]
        )

        assert "Corelib.Init.Nat.add" in resolved
        assert "unknown" in resolved

    def test_corelib_exact_match_still_works(self):
        """Direct Corelib.* FQN resolves via exact match as before."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context_corelib()

        resolved = resolve_query_symbols(ctx, ["Corelib.Init.Nat.add"])

        assert "Corelib.Init.Nat.add" in resolved

    def test_coq_prefix_not_applied_when_exact_match_exists(self):
        """If the index has a Coq.* key directly, exact match takes priority over alias."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context()  # uses Coq.* FQNs in the inverted index

        resolved = resolve_query_symbols(ctx, ["Coq.Init.Nat.add"])

        assert "Coq.Init.Nat.add" in resolved

    def test_fqn_also_resolves_short_form_via_suffix(self):
        """When the index stores both Corelib.Init.Nat.add (few decls) and
        Nat.add (many decls), querying with the FQN should resolve to both
        so MePo can find all relevant declarations."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context_mixed_symbols()

        resolved = resolve_query_symbols(ctx, ["Corelib.Init.Nat.add"])

        # Must include the exact match
        assert "Corelib.Init.Nat.add" in resolved
        # Must ALSO include the short form (Nat.add is a suffix of
        # Corelib.Init.Nat.add, and Nat.add is a key in the inverted index)
        assert "Nat.add" in resolved

    def test_fqn_suffix_expansion_finds_both_symbols(self):
        """Querying with two Corelib FQNs resolves both to their short forms,
        enabling MePo to find declarations containing both Nat.add and Nat.mul."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context_mixed_symbols()

        resolved = resolve_query_symbols(
            ctx, ["Corelib.Init.Nat.add", "Corelib.Init.Nat.mul"]
        )

        assert "Nat.add" in resolved
        assert "Nat.mul" in resolved

    def test_qualified_name_suffix_expansion_fallback(self):
        """When a qualified name like 'List.map' fails primary resolution
        (not in inverted_index, not in suffix_index), suffix expansion
        should find FQNs by trying shorter suffixes (spec §4.5.1 step 4).

        'List.map' -> try suffix 'map' -> finds 'Coq.Lists.ListDef.map'
        in suffix_index."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context()
        # Add a 'map'-related FQN that would be found via suffix expansion
        ctx.inverted_index["Coq.Lists.ListDef.map"] = {4}
        ctx.suffix_index = _build_suffix_index(ctx.inverted_index)
        # 'List.map' is NOT in the suffix index (no re-export alias)
        assert "List.map" not in ctx.suffix_index

        resolved = resolve_query_symbols(ctx, ["List.map"])

        # Must find 'Coq.Lists.ListDef.map' via suffix expansion of 'map'
        assert "Coq.Lists.ListDef.map" in resolved
        # Must NOT passthrough the unresolvable name
        assert "List.map" not in resolved

    def test_qualified_name_suffix_expansion_includes_all_matches(self):
        """Suffix expansion for an unresolvable qualified name includes all
        FQNs matching the suffix, not just the first."""
        from Poule.pipeline.search import resolve_query_symbols

        ctx = _mock_context()
        ctx.inverted_index["Coq.Lists.ListDef.map"] = {4}
        ctx.inverted_index["Coq.Init.Datatypes.map"] = {5}
        ctx.suffix_index = _build_suffix_index(ctx.inverted_index)

        resolved = resolve_query_symbols(ctx, ["List.map"])

        assert "Coq.Lists.ListDef.map" in resolved
        assert "Coq.Init.Datatypes.map" in resolved


class TestAliasPrefix:
    """alias_prefix: bidirectional Coq ↔ Corelib prefix aliasing (§4.1.1)."""

    def test_corelib_to_coq(self):
        """Corelib.Arith → Coq.Arith."""
        from Poule.pipeline.search import alias_prefix

        assert alias_prefix("Corelib.Arith") == "Coq.Arith"

    def test_coq_to_corelib(self):
        """Coq.Init → Corelib.Init."""
        from Poule.pipeline.search import alias_prefix

        assert alias_prefix("Coq.Init") == "Corelib.Init"

    def test_no_alias_for_other_prefix(self):
        """mathcomp.algebra → None (no alias applies)."""
        from Poule.pipeline.search import alias_prefix

        assert alias_prefix("mathcomp.algebra") is None

    def test_no_alias_for_empty_string(self):
        """Empty string → None."""
        from Poule.pipeline.search import alias_prefix

        assert alias_prefix("") is None

    def test_corelib_exact_prefix(self):
        """'Corelib.' alone → 'Coq.'."""
        from Poule.pipeline.search import alias_prefix

        assert alias_prefix("Corelib.") == "Coq."

    def test_coq_exact_prefix(self):
        """'Coq.' alone → 'Corelib.'."""
        from Poule.pipeline.search import alias_prefix

        assert alias_prefix("Coq.") == "Corelib."


class TestSearchBySymbols:
    """search_by_symbols resolves names then delegates to mepo_select."""

    @patch("Poule.pipeline.search.mepo_select")
    def test_calls_mepo_select_with_correct_args(self, mock_mepo):
        ctx = _mock_context()
        mock_mepo.return_value = [(1, 0.8), (2, 0.6)]
        ctx.reader.get_declarations_by_ids.return_value = [
            {"id": 1, "name": "D.1", "module": "M", "kind": "lemma", "statement": "", "type_expr": ""},
            {"id": 2, "name": "D.2", "module": "M", "kind": "lemma", "statement": "", "type_expr": ""},
        ]
        symbols = ["Coq.Init.Nat.add", "Coq.Init.Datatypes.nat"]

        results = search_by_symbols(ctx, symbols, limit=10)

        mock_mepo.assert_called_once()
        call_args = mock_mepo.call_args
        # First positional arg should be the symbol set
        assert set(call_args[0][0]) == set(symbols) or set(
            call_args[1].get("symbols", call_args[0][0])
        ) == set(symbols)
        assert len(results) == 2

    @patch("Poule.pipeline.search.mepo_select")
    def test_short_names_resolved_before_mepo(self, mock_mepo):
        """Short names like 'Nat.add' are resolved to FQNs before passing to mepo_select (spec §4.5)."""
        ctx = _mock_context()
        mock_mepo.return_value = [(1, 0.8)]
        ctx.reader.get_declarations_by_ids.return_value = [
            {"id": 1, "name": "D.1", "module": "M", "kind": "lemma", "statement": "", "type_expr": ""},
        ]

        results = search_by_symbols(ctx, ["Nat.add", "Nat.mul"], limit=10)

        mock_mepo.assert_called_once()
        call_args = mock_mepo.call_args
        resolved_set = call_args[0][0]
        # "Nat.add" should have been resolved to "Coq.Init.Nat.add"
        assert "Coq.Init.Nat.add" in resolved_set

    @patch("Poule.pipeline.search.mepo_select")
    def test_limits_results(self, mock_mepo):
        ctx = _mock_context()
        mock_mepo.return_value = [(i, 1.0 - i * 0.1) for i in range(20)]
        ctx.reader.get_declarations_by_ids.return_value = [
            {"id": i, "name": f"D.{i}", "module": "M", "kind": "lemma", "statement": "", "type_expr": ""}
            for i in range(20)
        ]

        results = search_by_symbols(ctx, ["Coq.Init.Nat.add"], limit=5)

        assert len(results) <= 5


# ---------------------------------------------------------------------------
# 5. search_by_structure: full flow with mocked dependencies
# ---------------------------------------------------------------------------


class TestSearchByStructure:
    """search_by_structure orchestrates parse -> normalize -> CSE -> WL -> scoring."""

    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_full_flow(
        self,
        mock_coq_norm,
        mock_cse_norm,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
    ):
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        raw_tree = MagicMock()
        normalized_tree = MagicMock()
        cse_tree = MagicMock()
        cse_tree.node_count = 15
        query_histogram = {"label_A": 3, "label_B": 1}

        parser.parse.return_value = raw_tree
        mock_coq_norm.return_value = normalized_tree
        mock_cse_norm.return_value = cse_tree
        mock_wl_hist.return_value = query_histogram
        mock_wl_screen.return_value = [(1, 0.95), (2, 0.80)]
        mock_score.return_value = [(1, 0.92), (2, 0.78)]

        results = search_by_structure(ctx, "forall n : nat, n + 0 = n", limit=10)

        parser.parse.assert_called_once_with("forall n : nat, n + 0 = n")
        mock_coq_norm.assert_called_once_with(raw_tree)
        mock_cse_norm.assert_called_once_with(normalized_tree)
        mock_wl_hist.assert_called_once_with(cse_tree, h=3)
        mock_wl_screen.assert_called_once()
        mock_score.assert_called_once()
        assert len(results) <= 10


# ---------------------------------------------------------------------------
# 6. search_by_structure: ParseError propagated
# ---------------------------------------------------------------------------


class TestSearchByStructureParseError:
    """ParseError from the parser is propagated, not swallowed."""

    def test_parse_error_propagated(self):
        parser = _mock_parser()
        parser.parse.side_effect = ParseError("invalid expression")
        ctx = _mock_context(parser=parser)

        with pytest.raises(ParseError, match="invalid expression"):
            search_by_structure(ctx, "bad expression", limit=10)


# ---------------------------------------------------------------------------
# 7. search_by_structure: NormalizationError -> empty results
# ---------------------------------------------------------------------------


class TestSearchByStructureNormalizationError:
    """NormalizationError is caught and produces empty results with a warning."""

    @patch("Poule.pipeline.search.coq_normalize")
    def test_normalization_error_returns_empty(self, mock_coq_norm, caplog):
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        # Import the error that normalization would raise
        from Poule.pipeline.search import NormalizationError

        mock_coq_norm.side_effect = NormalizationError("normalization failed")

        with caplog.at_level(logging.WARNING):
            results = search_by_structure(ctx, "some expression", limit=10)

        assert results == []

    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_cse_normalization_error_returns_empty(
        self, mock_coq_norm, mock_cse_norm, caplog
    ):
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        from Poule.pipeline.search import NormalizationError

        mock_coq_norm.return_value = MagicMock()
        mock_cse_norm.side_effect = NormalizationError("CSE failed")

        with caplog.at_level(logging.WARNING):
            results = search_by_structure(ctx, "some expression", limit=10)

        assert results == []


# ---------------------------------------------------------------------------
# 8. search_by_type: runs 3 channels + RRF fusion
# ---------------------------------------------------------------------------


class TestSearchByType:
    """search_by_type runs structural + MePo + FTS channels and fuses via RRF."""

    @patch("Poule.pipeline.search.rrf_fuse")
    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_three_channels_fused(
        self,
        mock_coq_norm,
        mock_cse_norm,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
        mock_rrf,
    ):
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq_norm.return_value = MagicMock()
        mock_cse_norm.return_value = cse_tree
        mock_wl_hist.return_value = {"label_A": 2}
        mock_wl_screen.return_value = [(1, 0.9)]
        mock_score.return_value = [(1, 0.85)]

        structural_results = [_mock_search_result(1, 0.85)]
        mepo_results = [_mock_search_result(2, 0.7)]
        fts_results = [_mock_search_result(3, 0.6)]

        mock_extract.return_value = {"Coq.Init.Nat.add"}
        mock_mepo.return_value = mepo_results
        mock_fts_query.return_value = "nat AND nat AND nat"
        mock_fts_search.return_value = fts_results

        fused = [
            _mock_search_result(1, 0.9),
            _mock_search_result(2, 0.5),
            _mock_search_result(3, 0.4),
        ]
        mock_rrf.return_value = fused

        results = search_by_type(ctx, "nat -> nat -> nat", limit=20)

        # RRF should receive lists from all three channels
        mock_rrf.assert_called_once()
        rrf_args = mock_rrf.call_args
        ranked_lists = rrf_args[0][0] if rrf_args[0] else rrf_args[1]["ranked_lists"]
        assert len(ranked_lists) == 3
        assert len(results) <= 20


# ---------------------------------------------------------------------------
# 8b. search_by_type: real rrf_fuse with actual channel output types
# ---------------------------------------------------------------------------


class TestSearchByTypeRealFusion:
    """Exercise search_by_type WITHOUT mocking rrf_fuse, so the real fusion
    function receives the actual output types from each channel.

    This is the contract test for the interaction between search_by_type
    and rrf_fuse.  Existing test_three_channels_fused mocks rrf_fuse
    entirely, hiding the type mismatch between channel outputs and
    rrf_fuse's expected input format.

    Per spec (fusion.md §4.5): rrf_fuse expects lists of (decl_id, score)
    pairs.  score_candidates returns list[tuple[int, float]], mepo_select
    returns list[tuple[int, float]], fts_search returns list[SearchResult].
    All three must be converted to a compatible format before passing to
    rrf_fuse."""

    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_real_rrf_fuse_with_channel_outputs(
        self,
        mock_coq_norm,
        mock_cse_norm,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
    ):
        """search_by_type must pass the real rrf_fuse without TypeError.

        Channels return:
        - score_candidates: [(1, 0.85), (2, 0.70)]  (int, float) tuples
        - mepo_select:      [(2, 0.90), (3, 0.60)]  (int, float) tuples
        - fts_search:       [SearchResult(...)]       SearchResult objects

        rrf_fuse must handle all three without raising TypeError."""
        from Poule.models.responses import SearchResult

        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq_norm.return_value = MagicMock()
        mock_cse_norm.return_value = cse_tree
        mock_wl_hist.return_value = {"label_A": 2}
        mock_wl_screen.return_value = [(1, 0.9), (2, 0.8)]

        # score_candidates returns list[tuple[int, float]]
        mock_score.return_value = [(1, 0.85), (2, 0.70)]

        # mepo_select returns list[tuple[int, float]]
        mock_extract.return_value = {"Coq.Init.Nat.add"}
        mock_mepo.return_value = [(2, 0.90), (3, 0.60)]

        # fts_search returns list[SearchResult]
        mock_fts_query.return_value = "nat AND nat AND nat"
        mock_fts_search.return_value = [
            SearchResult(
                name="Coq.Init.Nat.add",
                statement="forall n m : nat, ...",
                type="nat -> nat -> nat",
                module="Coq.Init.Nat",
                kind="Lemma",
                score=0.95,
            ),
            SearchResult(
                name="Coq.Init.Nat.mul",
                statement="forall n m : nat, ...",
                type="nat -> nat -> nat",
                module="Coq.Init.Nat",
                kind="Lemma",
                score=0.80,
            ),
        ]

        # This must not raise TypeError
        results = search_by_type(ctx, "nat -> nat -> nat", limit=20)

        # Results must be a non-empty list (channels returned data)
        assert isinstance(results, list)
        assert len(results) > 0

    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_real_rrf_fuse_result_ids_are_declaration_identifiers(
        self,
        mock_coq_norm,
        mock_cse_norm,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
    ):
        """After RRF fusion, result decl_ids must be the original identifiers
        from the channels — not tuples, not SearchResult objects."""
        from Poule.models.responses import SearchResult

        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq_norm.return_value = MagicMock()
        mock_cse_norm.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = [(1, 0.9)]
        mock_score.return_value = [(1, 0.85)]
        mock_extract.return_value = {"Coq.Init.Nat.add"}
        mock_mepo.return_value = [(1, 0.70)]
        mock_fts_query.return_value = "nat"
        mock_fts_search.return_value = [
            SearchResult(
                name="Coq.Init.Nat.add",
                statement="",
                type="nat -> nat -> nat",
                module="Coq.Init.Nat",
                kind="Lemma",
                score=0.95,
            ),
        ]

        results = search_by_type(ctx, "nat -> nat -> nat", limit=20)

        # Each fused result should have a decl_id that is either an int
        # or a string — never a tuple or a SearchResult object.
        for r in results:
            decl_id = r[0] if isinstance(r, tuple) else r
            assert isinstance(decl_id, (int, str)), (
                f"Expected decl_id to be int or str, got {type(decl_id).__name__}: {decl_id!r}"
            )


# ---------------------------------------------------------------------------
# 8c. search_by_type: MePo resolves extracted symbols (spec §4.4 step 7)
# ---------------------------------------------------------------------------


class TestSearchByTypeMePoResolution:
    """search_by_type must resolve extracted symbols via resolve_query_symbols
    before passing to mepo_select (spec §4.4 step 7)."""

    @patch("Poule.pipeline.search.rrf_fuse")
    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.resolve_query_symbols")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_mepo_receives_resolved_symbols(
        self,
        mock_coq_norm,
        mock_cse_norm,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_resolve,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
        mock_rrf,
    ):
        """extract_consts output is passed through resolve_query_symbols
        before mepo_select, so qualified names like 'List.map' get resolved."""
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq_norm.return_value = MagicMock()
        mock_cse_norm.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = []
        mock_score.return_value = []

        # extract_consts returns unresolved qualified names
        mock_extract.return_value = {"List.map", "eq"}
        # resolve_query_symbols resolves them to FQNs
        mock_resolve.return_value = {"Coq.Lists.ListDef.map", "Coq.Init.Logic.eq"}
        mock_mepo.return_value = []
        mock_fts_query.return_value = "List OR map"
        mock_fts_search.return_value = []
        mock_rrf.return_value = []

        search_by_type(ctx, "List.map f l = l", limit=20)

        # resolve_query_symbols must be called with the raw extracted symbols
        mock_resolve.assert_called_once()
        raw_syms = mock_resolve.call_args[0][1]
        assert set(raw_syms) == {"List.map", "eq"}

        # mepo_select must receive the RESOLVED symbols, not the raw ones
        mock_mepo.assert_called_once()
        mepo_syms = mock_mepo.call_args[0][0]
        assert "Coq.Lists.ListDef.map" in mepo_syms
        assert "List.map" not in mepo_syms


# ---------------------------------------------------------------------------
# 8d. search_by_type: FTS query uses cleaned tokens (spec §4.4 step 8)
# ---------------------------------------------------------------------------


class TestSearchByTypeFtsTokenization:
    """search_by_type must extract identifier tokens from the type expression
    and flatten dots before passing to fts_query, so Rule 3 (OR) applies
    instead of Rule 1 (dot-split AND)."""

    @patch("Poule.pipeline.search.rrf_fuse")
    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_fts_query_receives_cleaned_tokens_not_raw_expr(
        self,
        mock_coq_norm,
        mock_cse_norm,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
        mock_rrf,
    ):
        """For type expressions containing dots (e.g., 'List.map f l'),
        fts_query must receive cleaned tokens (no dots), not the raw string."""
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq_norm.return_value = MagicMock()
        mock_cse_norm.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = []
        mock_score.return_value = []
        mock_extract.return_value = set()
        mock_mepo.return_value = []
        mock_fts_query.return_value = "List OR map"
        mock_fts_search.return_value = []
        mock_rrf.return_value = []

        type_expr = "List.map f (List.map g l) = List.map (fun x => f (g x)) l"
        search_by_type(ctx, type_expr, limit=20)

        # fts_query must NOT receive the raw type_expr (which contains dots)
        fts_input = mock_fts_query.call_args[0][0]
        assert "." not in fts_input, (
            f"fts_query received dotted input: {fts_input!r}; "
            f"expected cleaned tokens without dots"
        )
        # Must contain the significant identifier 'map'
        assert "map" in fts_input.lower()


# ---------------------------------------------------------------------------
# 9. search_by_type: ParseError propagated
# ---------------------------------------------------------------------------


class TestSearchByTypeParseError:
    """ParseError from the parser propagates through search_by_type."""

    def test_parse_error_propagated(self):
        parser = _mock_parser()
        parser.parse.side_effect = ParseError("bad type expression")
        ctx = _mock_context(parser=parser)

        with pytest.raises(ParseError, match="bad type expression"):
            search_by_type(ctx, "bad type", limit=20)


# ---------------------------------------------------------------------------
# 10. score_candidates: computes jaccard, collapse_match, conditional TED
# ---------------------------------------------------------------------------


class TestScoreCandidates:
    """score_candidates computes per-candidate metrics and weighted sums."""

    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_computes_all_metrics(
        self, mock_extract, mock_jaccard, mock_collapse, mock_ted
    ):
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 15

        # Mock candidate tree retrieval
        candidate_tree = MagicMock()
        candidate_tree.node_count = 12
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        mock_extract.return_value = {"Coq.Init.Nat.add"}
        mock_jaccard.return_value = 0.6
        mock_collapse.return_value = 0.8
        mock_ted.return_value = 0.7

        candidates_with_wl = [(1, 0.9)]

        scored = score_candidates(query_tree, candidates_with_wl, ctx)

        assert len(scored) == 1
        mock_extract.assert_called_once_with(query_tree)
        mock_jaccard.assert_called_once()
        mock_collapse.assert_called_once()
        mock_ted.assert_called_once()

    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_returns_decl_id_score_pairs(
        self, mock_extract, mock_jaccard, mock_collapse, mock_ted
    ):
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 10

        candidate_tree = MagicMock()
        candidate_tree.node_count = 8
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree, 2: candidate_tree}

        mock_extract.return_value = {"Coq.Init.Nat.add"}
        mock_jaccard.return_value = 0.5
        mock_collapse.return_value = 0.7
        mock_ted.return_value = 0.6

        candidates_with_wl = [(1, 0.9), (2, 0.85)]

        scored = score_candidates(query_tree, candidates_with_wl, ctx)

        assert len(scored) == 2
        for decl_id, structural_score in scored:
            assert isinstance(decl_id, int)
            assert isinstance(structural_score, float)


# ---------------------------------------------------------------------------
# 11. score_candidates: large trees skip TED (has_ted=False weight formula)
# ---------------------------------------------------------------------------


class TestScoreCandidatesLargeTreesNoTED:
    """When query or candidate has >50 nodes, TED is skipped.
    Uses weights: 0.25 * wl + 0.50 * collapse + 0.25 * jaccard."""

    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_large_query_skips_ted(
        self, mock_extract, mock_jaccard, mock_collapse, mock_ted
    ):
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 60  # > 50

        candidate_tree = MagicMock()
        candidate_tree.node_count = 20
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        mock_extract.return_value = set()
        mock_jaccard.return_value = 0.4
        mock_collapse.return_value = 0.8
        mock_ted.return_value = 0.99  # Should not be used

        candidates_with_wl = [(1, 0.6)]

        scored = score_candidates(query_tree, candidates_with_wl, ctx)

        mock_ted.assert_not_called()
        decl_id, structural_score = scored[0]
        # Expected: 0.25 * 0.6 + 0.50 * 0.8 + 0.25 * 0.4 = 0.15 + 0.40 + 0.10 = 0.65
        assert structural_score == pytest.approx(0.65, abs=1e-6)

    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_large_candidate_skips_ted(
        self, mock_extract, mock_jaccard, mock_collapse, mock_ted
    ):
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 20

        candidate_tree = MagicMock()
        candidate_tree.node_count = 55  # > 50
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        mock_extract.return_value = set()
        mock_jaccard.return_value = 1.0
        mock_collapse.return_value = 1.0
        mock_ted.return_value = 0.99  # Should not be used

        candidates_with_wl = [(1, 1.0)]

        scored = score_candidates(query_tree, candidates_with_wl, ctx)

        mock_ted.assert_not_called()
        decl_id, structural_score = scored[0]
        # Expected: 0.25 * 1.0 + 0.50 * 1.0 + 0.25 * 1.0 = 1.0
        assert structural_score == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# 12. score_candidates: small trees include TED (has_ted=True weight formula)
# ---------------------------------------------------------------------------


class TestScoreCandidatesSmallTreesWithTED:
    """When both query and candidate have <=50 nodes, TED is included.
    Uses weights: 0.15 * wl + 0.40 * ted + 0.30 * collapse + 0.15 * jaccard."""

    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_small_trees_include_ted(
        self, mock_extract, mock_jaccard, mock_collapse, mock_ted
    ):
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 15  # <= 50

        candidate_tree = MagicMock()
        candidate_tree.node_count = 12  # <= 50
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        mock_extract.return_value = set()
        mock_jaccard.return_value = 0.6
        mock_collapse.return_value = 0.8
        mock_ted.return_value = 0.7

        wl_cosine = 0.9
        candidates_with_wl = [(1, wl_cosine)]

        scored = score_candidates(query_tree, candidates_with_wl, ctx)

        mock_ted.assert_called_once()
        decl_id, structural_score = scored[0]
        # Expected: 0.15 * 0.9 + 0.40 * 0.7 + 0.30 * 0.8 + 0.15 * 0.6
        #         = 0.135 + 0.28 + 0.24 + 0.09 = 0.745
        assert structural_score == pytest.approx(0.745, abs=1e-6)

    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_boundary_50_nodes_includes_ted(
        self, mock_extract, mock_jaccard, mock_collapse, mock_ted
    ):
        """Exactly 50 nodes on both sides should still include TED."""
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 50

        candidate_tree = MagicMock()
        candidate_tree.node_count = 50
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        mock_extract.return_value = set()
        mock_jaccard.return_value = 0.5
        mock_collapse.return_value = 0.5
        mock_ted.return_value = 0.5

        candidates_with_wl = [(1, 0.5)]

        scored = score_candidates(query_tree, candidates_with_wl, ctx)

        mock_ted.assert_called_once()
        decl_id, structural_score = scored[0]
        # Expected: 0.15 * 0.5 + 0.40 * 0.5 + 0.30 * 0.5 + 0.15 * 0.5 = 0.5
        assert structural_score == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# 13. Results are limited to `limit` parameter
# ---------------------------------------------------------------------------


class TestResultsLimited:
    """All search functions respect the limit parameter."""

    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    def test_search_by_name_respects_limit(self, mock_fts_query, mock_fts_search):
        ctx = _mock_context()
        mock_fts_query.return_value = "test"
        mock_fts_search.return_value = [
            _mock_search_result(i, 1.0 - i * 0.05) for i in range(20)
        ]

        results = search_by_name(ctx, "test", limit=5)

        assert len(results) <= 5

    @patch("Poule.pipeline.search.mepo_select")
    def test_search_by_symbols_respects_limit(self, mock_mepo):
        ctx = _mock_context()
        mock_mepo.return_value = [(i, 1.0 - i * 0.05) for i in range(20)]
        ctx.reader.get_declarations_by_ids.return_value = [
            {"id": i, "name": f"D.{i}", "module": "M", "kind": "lemma", "statement": "", "type_expr": ""}
            for i in range(20)
        ]

        results = search_by_symbols(ctx, ["Coq.Init.Nat.add"], limit=3)

        assert len(results) <= 3

    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_search_by_structure_respects_limit(
        self, mock_coq, mock_cse, mock_wl_hist, mock_wl_screen, mock_score
    ):
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq.return_value = MagicMock()
        mock_cse.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = [(i, 1.0 - i * 0.01) for i in range(100)]
        mock_score.return_value = [(i, 1.0 - i * 0.01) for i in range(100)]

        results = search_by_structure(ctx, "forall n, n = n", limit=7)

        assert len(results) <= 7


# ---------------------------------------------------------------------------
# 14. Results are sorted by score descending
# ---------------------------------------------------------------------------


class TestResultsSortedDescending:
    """All search functions return results sorted by score, highest first."""

    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_structure_results_sorted_descending(
        self, mock_coq, mock_cse, mock_wl_hist, mock_wl_screen, mock_score
    ):
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq.return_value = MagicMock()
        mock_cse.return_value = cse_tree
        mock_wl_hist.return_value = {}
        # Return candidates in non-sorted order
        mock_wl_screen.return_value = [(1, 0.5), (2, 0.9), (3, 0.7)]
        mock_score.return_value = [(1, 0.5), (2, 0.9), (3, 0.7)]

        results = search_by_structure(ctx, "some expr", limit=10)

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    @patch("Poule.pipeline.search.mepo_select")
    def test_symbols_results_sorted_descending(self, mock_mepo):
        ctx = _mock_context()
        # Return in non-sorted order
        mock_mepo.return_value = [(1, 0.3), (2, 0.9), (3, 0.6)]
        ctx.reader.get_declarations_by_ids.return_value = [
            {"id": 1, "name": "D.1", "module": "M", "kind": "lemma", "statement": "", "type_expr": ""},
            {"id": 2, "name": "D.2", "module": "M", "kind": "lemma", "statement": "", "type_expr": ""},
            {"id": 3, "name": "D.3", "module": "M", "kind": "lemma", "statement": "", "type_expr": ""},
        ]

        results = search_by_symbols(ctx, ["Coq.Init.Nat.add"], limit=10)

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    @patch("Poule.pipeline.search.rrf_fuse")
    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_type_results_sorted_descending(
        self,
        mock_coq,
        mock_cse,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
        mock_rrf,
    ):
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq.return_value = MagicMock()
        mock_cse.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = []
        mock_score.return_value = []
        mock_extract.return_value = set()
        mock_mepo.return_value = []
        mock_fts_query.return_value = "test"
        mock_fts_search.return_value = []
        # RRF returns in non-sorted order
        mock_rrf.return_value = [
            _mock_search_result(1, 0.3),
            _mock_search_result(2, 0.9),
            _mock_search_result(3, 0.6),
        ]

        results = search_by_type(ctx, "nat -> nat", limit=10)

        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# 15. _ensure_parser lazy initialization
# ---------------------------------------------------------------------------

import io
import json
import subprocess

from Poule.parsing.type_expr_parser import TypeExprParser
from Poule.pipeline.search import _ensure_parser


def _make_lsp_message(msg_dict):
    """Encode a JSON-RPC message with Content-Length framing."""
    body = json.dumps(msg_dict).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


class TestEnsureParser:
    """Tests for the _ensure_parser() lazy initialization."""

    def test_initializes_parser_when_none(self):
        """Given ctx.parser is None, after calling _ensure_parser, ctx.parser
        is a TypeExprParser."""
        ctx = _mock_context(parser=None)
        # Allow attribute assignment on the mock
        ctx.parser = None

        _ensure_parser(ctx)

        assert isinstance(ctx.parser, TypeExprParser)

    def test_does_not_replace_existing_parser(self):
        """Given ctx.parser is already set, _ensure_parser does not replace it."""
        existing_parser = _mock_parser()
        ctx = _mock_context(parser=existing_parser)

        _ensure_parser(ctx)

        assert ctx.parser is existing_parser

    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_search_by_structure_calls_ensure_parser(
        self, mock_coq, mock_cse, mock_wl_hist, mock_wl_screen, mock_score
    ):
        """search_by_structure with ctx.parser=None should still work
        (parser gets created via _ensure_parser)."""
        ctx = _mock_context(parser=None)
        ctx.parser = None

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq.return_value = MagicMock()
        mock_cse.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = []
        mock_score.return_value = []

        # Patch TypeExprParser so we control its output
        with patch(
            "Poule.parsing.type_expr_parser.TypeExprParser",
            return_value=_mock_parser(),
        ):
            results = search_by_structure(ctx, "nat", limit=5)

        assert isinstance(results, list)

    @patch("Poule.pipeline.search.rrf_fuse")
    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_search_by_type_calls_ensure_parser(
        self,
        mock_coq,
        mock_cse,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
        mock_rrf,
    ):
        """search_by_type with ctx.parser=None should still work."""
        ctx = _mock_context(parser=None)
        ctx.parser = None

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq.return_value = MagicMock()
        mock_cse.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = []
        mock_score.return_value = []
        mock_extract.return_value = set()
        mock_mepo.return_value = []
        mock_fts_query.return_value = "nat"
        mock_fts_search.return_value = []
        mock_rrf.return_value = []

        with patch(
            "Poule.parsing.type_expr_parser.TypeExprParser",
            return_value=_mock_parser(),
        ):
            results = search_by_type(ctx, "nat", limit=5)

        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# 16. CoqLspParser unit tests (mocked subprocess)
# ---------------------------------------------------------------------------

from Poule.pipeline.coqlsp_parser import CoqLspParser


def _mock_popen(stdout_bytes):
    """Create a mock Popen whose stdout is a BytesIO with the given bytes."""
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = io.BytesIO(stdout_bytes)
    proc.stderr = MagicMock()
    proc.poll.return_value = None  # process is alive
    proc.wait.return_value = 0
    return proc


def _build_lsp_responses_for_parse(
    *,
    diagnostics=None,
    goals_messages=None,
    initialize_result=None,
):
    """Build concatenated LSP response bytes for a full parse() call.

    The sequence is:
    1. initialize response (id=1)
    2. publishDiagnostics notification
    3. proof/goals response (id=2)
    4. shutdown response (id depends on flow, but not needed for parse)
    """
    if initialize_result is None:
        initialize_result = {"capabilities": {}}
    if diagnostics is None:
        diagnostics = []
    if goals_messages is None:
        goals_messages = []

    responses = b""

    # 1. Initialize response (request id=1)
    responses += _make_lsp_message(
        {"jsonrpc": "2.0", "id": 1, "result": initialize_result}
    )

    # 2. publishDiagnostics notification
    responses += _make_lsp_message(
        {
            "jsonrpc": "2.0",
            "method": "textDocument/publishDiagnostics",
            "params": {
                "uri": "file:///tmp/poule_parser_0.v",
                "diagnostics": diagnostics,
            },
        }
    )

    # 3. proof/goals response (request id=2)
    responses += _make_lsp_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"messages": goals_messages},
        }
    )

    return responses


class TestCoqLspParserUnit:
    """Unit tests for CoqLspParser with mocked subprocess."""

    @patch("Poule.pipeline.coqlsp_parser.parse_constr_json")
    @patch("Poule.pipeline.coqlsp_parser.subprocess.Popen")
    def test_parse_returns_constr_node(self, mock_popen_cls, mock_parse_constr):
        """Mock coq-lsp responses; verify parse() returns the result of
        parse_constr_json."""
        raw_constr = {"v": ["Ind", {"name": "nat"}]}
        constr_node = MagicMock()
        mock_parse_constr.return_value = constr_node

        responses = _build_lsp_responses_for_parse(
            diagnostics=[],
            goals_messages=[{"level": 0, "raw": raw_constr}],
        )
        proc = _mock_popen(responses)
        mock_popen_cls.return_value = proc

        parser = CoqLspParser()
        result = parser.parse("nat")

        mock_parse_constr.assert_called_once_with(raw_constr)
        assert result is constr_node

    @patch("Poule.pipeline.coqlsp_parser.subprocess.Popen")
    def test_parse_raises_parse_error_on_diagnostic_error(self, mock_popen_cls):
        """Mock error diagnostics; verify ParseError is raised."""
        error_diag = {
            "severity": 1,
            "message": "The reference foobar was not found",
        }
        responses = _build_lsp_responses_for_parse(
            diagnostics=[error_diag],
        )
        proc = _mock_popen(responses)
        mock_popen_cls.return_value = proc

        parser = CoqLspParser()

        with pytest.raises(ParseError, match="Coq rejected expression"):
            parser.parse("foobar")

    @patch("Poule.pipeline.coqlsp_parser.subprocess.Popen")
    def test_parse_raises_parse_error_when_coq_lsp_not_found(
        self, mock_popen_cls
    ):
        """Patch subprocess.Popen to raise FileNotFoundError; verify
        ParseError."""
        mock_popen_cls.side_effect = FileNotFoundError("coq-lsp not found")

        parser = CoqLspParser()

        with pytest.raises(ParseError, match="coq-lsp not found on PATH"):
            parser.parse("nat")

    @patch("Poule.pipeline.coqlsp_parser.subprocess.Popen")
    def test_parse_raises_parse_error_on_text_only_messages(
        self, mock_popen_cls
    ):
        """When coq-lsp returns text messages without structured ``raw``
        data, parse() raises ParseError (spec §4.2: on failure raises
        ParseError)."""
        responses = _build_lsp_responses_for_parse(
            diagnostics=[],
            goals_messages=[{"level": 0, "text": "nat : Set"}],
        )
        proc = _mock_popen(responses)
        mock_popen_cls.return_value = proc

        parser = CoqLspParser()

        with pytest.raises(ParseError, match="returned text but no structured"):
            parser.parse("nat")

    @patch("Poule.pipeline.coqlsp_parser.subprocess.Popen")
    def test_parse_raises_parse_error_on_empty_messages(self, mock_popen_cls):
        """When coq-lsp returns no messages for a valid expression,
        parse() raises ParseError (spec §4.2: on failure raises ParseError)."""
        responses = _build_lsp_responses_for_parse(
            diagnostics=[],
            goals_messages=[],
        )
        proc = _mock_popen(responses)
        mock_popen_cls.return_value = proc

        parser = CoqLspParser()

        with pytest.raises(ParseError, match="No output from coq-lsp"):
            parser.parse("nat")

    def test_ensure_started_is_lazy(self):
        """Verify coq-lsp isn't spawned until parse() is called."""
        parser = CoqLspParser()

        # The process should be None before any parse call
        assert parser._proc is None

    @patch("Poule.pipeline.coqlsp_parser.subprocess.Popen")
    def test_close_sends_shutdown(self, mock_popen_cls):
        """Verify close() sends shutdown request."""
        # Build responses for: initialize + parse sequence + shutdown
        init_response = _make_lsp_message(
            {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}
        )
        diag_notification = _make_lsp_message(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/publishDiagnostics",
                "params": {
                    "uri": "file:///tmp/poule_parser_0.v",
                    "diagnostics": [],
                },
            }
        )
        goals_response = _make_lsp_message(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "messages": [{"level": 0, "raw": {"v": ["Sort", "Set"]}}]
                },
            }
        )
        shutdown_response = _make_lsp_message(
            {"jsonrpc": "2.0", "id": 3, "result": None}
        )

        all_responses = (
            init_response + diag_notification + goals_response + shutdown_response
        )
        proc = _mock_popen(all_responses)
        mock_popen_cls.return_value = proc

        with patch("Poule.pipeline.coqlsp_parser.parse_constr_json"):
            parser = CoqLspParser()
            parser.parse("nat")
            parser.close()

        # Verify shutdown was sent by checking that write was called
        # with a message containing "shutdown"
        write_calls = proc.stdin.write.call_args_list
        shutdown_sent = any(
            b'"shutdown"' in call[0][0] for call in write_calls
        )
        assert shutdown_sent, "shutdown request was not sent during close()"

        # Verify exit notification was sent
        exit_sent = any(b'"exit"' in call[0][0] for call in write_calls)
        assert exit_sent, "exit notification was not sent during close()"

        proc.wait.assert_called()


# ---------------------------------------------------------------------------
# 17. TED tree-size boundary (spec §4.7, condition: both ≤ 50)
# ---------------------------------------------------------------------------


class TestTEDBoundaryExact:
    """TED is included when both query and candidate have ≤50 nodes (boundary ≤50).
    Exactly 50 nodes on both sides → TED used.
    Exactly 51 nodes on either side → TED skipped."""

    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_exactly_50_nodes_uses_ted(
        self, mock_extract, mock_jaccard, mock_collapse, mock_ted
    ):
        """Both query=50 and candidate=50: boundary is ≤50, so TED is computed.
        Score = 0.15*wl + 0.40*ted + 0.30*collapse + 0.15*jaccard."""
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 50  # exactly at boundary

        candidate_tree = MagicMock()
        candidate_tree.node_count = 50  # exactly at boundary
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        mock_extract.return_value = set()
        mock_jaccard.return_value = 1.0
        mock_collapse.return_value = 1.0
        mock_ted.return_value = 1.0

        candidates_with_wl = [(1, 1.0)]

        scored = score_candidates(query_tree, candidates_with_wl, ctx)

        # TED must be called — both sides at boundary (≤50)
        mock_ted.assert_called_once()
        assert len(scored) == 1
        decl_id, structural_score = scored[0]
        # Score = 0.15*1.0 + 0.40*1.0 + 0.30*1.0 + 0.15*1.0 = 1.0
        assert structural_score == pytest.approx(1.0, abs=1e-6)

    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_exactly_51_nodes_skips_ted(
        self, mock_extract, mock_jaccard, mock_collapse, mock_ted
    ):
        """Query=51 (> 50): TED is skipped.
        Score = 0.25*wl + 0.50*collapse + 0.25*jaccard."""
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 51  # one over boundary

        candidate_tree = MagicMock()
        candidate_tree.node_count = 30
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        mock_extract.return_value = set()
        mock_jaccard.return_value = 0.4
        mock_collapse.return_value = 0.8
        mock_ted.return_value = 0.99  # should not be used

        candidates_with_wl = [(1, 0.6)]

        scored = score_candidates(query_tree, candidates_with_wl, ctx)

        # TED must NOT be called — query side exceeds boundary
        mock_ted.assert_not_called()
        decl_id, structural_score = scored[0]
        # Score = 0.25*0.6 + 0.50*0.8 + 0.25*0.4 = 0.15 + 0.40 + 0.10 = 0.65
        assert structural_score == pytest.approx(0.65, abs=1e-6)

    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_asymmetric_query_49_candidate_51_skips_ted(
        self, mock_extract, mock_jaccard, mock_collapse, mock_ted
    ):
        """Asymmetric case: query=49 (≤50) but candidate=51 (>50) → TED skipped.
        Condition requires BOTH to be ≤50; one side over the limit is enough to skip."""
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 49  # within boundary

        candidate_tree = MagicMock()
        candidate_tree.node_count = 51  # exceeds boundary
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        mock_extract.return_value = set()
        mock_jaccard.return_value = 0.5
        mock_collapse.return_value = 0.6
        mock_ted.return_value = 0.99  # should not be used

        candidates_with_wl = [(1, 0.8)]

        scored = score_candidates(query_tree, candidates_with_wl, ctx)

        # TED must NOT be called — candidate side exceeds boundary
        mock_ted.assert_not_called()
        decl_id, structural_score = scored[0]
        # Score = 0.25*0.8 + 0.50*0.6 + 0.25*0.5 = 0.20 + 0.30 + 0.125 = 0.625
        assert structural_score == pytest.approx(0.625, abs=1e-6)


# ---------------------------------------------------------------------------
# 19. RRF fusion with missing neural channel (spec §4.4 step 5-6)
# ---------------------------------------------------------------------------


class TestRRFFusionMissingNeuralChannel:
    """When the neural channel is unavailable, search_by_type fuses only 3
    channels (structural, symbol, lexical).  The neural channel is omitted when
    ctx.neural_encoder is None OR ctx.embedding_index is None (spec §4.4)."""

    @patch("Poule.pipeline.search.rrf_fuse")
    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_neural_encoder_none_fuses_only_3_channels(
        self,
        mock_coq_norm,
        mock_cse_norm,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
        mock_rrf,
    ):
        """When ctx.neural_encoder is None, RRF is called with exactly 3 ranked
        lists (structural, symbol, lexical) — not 4."""
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)
        ctx.neural_encoder = None
        ctx.embedding_index = None

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq_norm.return_value = MagicMock()
        mock_cse_norm.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = [(1, 0.9)]
        mock_score.return_value = [(1, 0.85)]
        mock_extract.return_value = set()
        mock_mepo.return_value = [_mock_search_result(2, 0.7)]
        mock_fts_query.return_value = "nat"
        mock_fts_search.return_value = [_mock_search_result(3, 0.6)]
        mock_rrf.return_value = [_mock_search_result(1, 0.9)]

        search_by_type(ctx, "nat -> nat", limit=10)

        mock_rrf.assert_called_once()
        rrf_args = mock_rrf.call_args
        ranked_lists = rrf_args[0][0] if rrf_args[0] else rrf_args[1]["ranked_lists"]
        # Must be exactly 3 channels — neural was not appended
        assert len(ranked_lists) == 3

    @patch("Poule.pipeline.search.rrf_fuse")
    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_encoder_present_but_embedding_index_none_fuses_only_3_channels(
        self,
        mock_coq_norm,
        mock_cse_norm,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
        mock_rrf,
    ):
        """When ctx.neural_encoder is present but ctx.embedding_index is None,
        the neural channel is excluded from RRF fusion (spec §4.4 step 5)."""
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)
        ctx.neural_encoder = MagicMock()  # encoder exists
        ctx.embedding_index = None         # but index does not

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq_norm.return_value = MagicMock()
        mock_cse_norm.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = []
        mock_score.return_value = []
        mock_extract.return_value = set()
        mock_mepo.return_value = [_mock_search_result(1, 0.7)]
        mock_fts_query.return_value = "nat"
        mock_fts_search.return_value = [_mock_search_result(2, 0.6)]
        mock_rrf.return_value = [_mock_search_result(1, 0.8)]

        search_by_type(ctx, "nat -> nat", limit=10)

        rrf_args = mock_rrf.call_args
        ranked_lists = rrf_args[0][0] if rrf_args[0] else rrf_args[1]["ranked_lists"]
        # Neural excluded because embedding_index is None
        assert len(ranked_lists) == 3

    @patch("Poule.pipeline.search.rrf_fuse")
    @patch("Poule.pipeline.search.fts_search")
    @patch("Poule.pipeline.search.fts_query")
    @patch("Poule.pipeline.search.mepo_select")
    @patch("Poule.pipeline.search.extract_consts")
    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_results_valid_when_neural_channel_absent(
        self,
        mock_coq_norm,
        mock_cse_norm,
        mock_wl_hist,
        mock_wl_screen,
        mock_score,
        mock_extract,
        mock_mepo,
        mock_fts_query,
        mock_fts_search,
        mock_rrf,
    ):
        """Results are still valid (non-empty if data exists) when the neural
        channel is absent.  The 3-channel fusion still produces results."""
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)
        ctx.neural_encoder = None
        ctx.embedding_index = None

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq_norm.return_value = MagicMock()
        mock_cse_norm.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = []
        mock_score.return_value = []
        mock_extract.return_value = set()
        mock_mepo.return_value = []
        mock_fts_query.return_value = "nat"
        mock_fts_search.return_value = []
        fused = [_mock_search_result(1, 0.85), _mock_search_result(2, 0.7)]
        mock_rrf.return_value = fused

        results = search_by_type(ctx, "nat -> nat", limit=10)

        # Results come from the fused output even without neural channel
        assert isinstance(results, list)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# 20. coq_normalize failure degradation (spec §4.8)
# ---------------------------------------------------------------------------


class TestCoqNormalizeFailureDegradation:
    """§4.8: When coq_normalize raises NormalizationError, the pipeline returns
    empty results and logs a warning (not propagated as a user error)."""

    @patch("Poule.pipeline.search.coq_normalize")
    def test_coq_normalize_failure_returns_empty_for_structure(
        self, mock_coq_norm, caplog
    ):
        """search_by_structure: NormalizationError from coq_normalize → empty
        result list (spec §4.8)."""
        from Poule.pipeline.search import NormalizationError
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        mock_coq_norm.side_effect = NormalizationError("coq_normalize failed: unsupported term")

        with caplog.at_level(logging.WARNING):
            results = search_by_structure(ctx, "some expression", limit=10)

        assert results == []

    @patch("Poule.pipeline.search.coq_normalize")
    def test_coq_normalize_failure_logs_warning_for_structure(
        self, mock_coq_norm, caplog
    ):
        """search_by_structure: NormalizationError from coq_normalize is logged
        at WARNING level (spec §4.8)."""
        from Poule.pipeline.search import NormalizationError
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        mock_coq_norm.side_effect = NormalizationError("coq_normalize failed")

        with caplog.at_level(logging.WARNING):
            search_by_structure(ctx, "some expression", limit=10)

        # A WARNING-level log entry must be emitted
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1

    @patch("Poule.pipeline.search.coq_normalize")
    def test_coq_normalize_failure_returns_empty_for_type(
        self, mock_coq_norm, caplog
    ):
        """search_by_type: NormalizationError from coq_normalize → empty
        result list (spec §4.8)."""
        from Poule.pipeline.search import NormalizationError
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        mock_coq_norm.side_effect = NormalizationError("coq_normalize failed: universe inconsistency")

        with caplog.at_level(logging.WARNING):
            results = search_by_type(ctx, "nat -> nat", limit=10)

        assert results == []

    @patch("Poule.pipeline.search.coq_normalize")
    def test_coq_normalize_failure_logs_warning_for_type(
        self, mock_coq_norm, caplog
    ):
        """search_by_type: NormalizationError from coq_normalize is logged
        at WARNING level (spec §4.8)."""
        from Poule.pipeline.search import NormalizationError
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)

        mock_coq_norm.side_effect = NormalizationError("coq_normalize failed")

        with caplog.at_level(logging.WARNING):
            search_by_type(ctx, "nat -> nat", limit=10)

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) >= 1


# ---------------------------------------------------------------------------
# _peel_n_prods: strips leading LProd layers from an ExprTree
# ---------------------------------------------------------------------------


class TestPeelNProds:
    """_peel_n_prods strips up to n leading LProd layers, returning the body
    as a new ExprTree with recomputed depths, IDs, and node count.

    Spec: pipeline.md §4.7 step 2."""

    def test_peel_zero_returns_same_tree(self):
        """Peeling 0 binders returns an equivalent tree (identity)."""
        from Poule.models.labels import LProd, LSort, LRel
        from Poule.models.enums import SortKind
        from Poule.models.tree import TreeNode, ExprTree

        root = TreeNode(
            label=LProd(),
            children=[
                TreeNode(label=LSort(SortKind.TYPE_UNIV), children=[]),
                TreeNode(label=LRel(1), children=[]),
            ],
        )
        original = ExprTree(root=root, node_count=3)
        result = _peel_n_prods(original, 0)
        # Same root node when n=0
        assert result.root is root
        assert result.node_count == 3

    def test_peel_one_returns_body(self):
        """Peeling 1 binder from Prod(Sort, body) returns body subtree."""
        from Poule.models.labels import LProd, LSort, LConst
        from Poule.models.enums import SortKind
        from Poule.models.tree import TreeNode, ExprTree

        body = TreeNode(
            label=LConst("Coq.Init.Nat.add"),
            children=[],
        )
        root = TreeNode(
            label=LProd(),
            children=[
                TreeNode(label=LSort(SortKind.TYPE_UNIV), children=[]),
                body,
            ],
        )
        original = ExprTree(root=root, node_count=3)
        result = _peel_n_prods(original, 1)
        assert result.root is body
        assert result.node_count == 1

    def test_peel_three_strips_three_prod_layers(self):
        """Peeling 3 from a chain of 3 Prods reaches the innermost body."""
        from Poule.models.labels import LProd, LSort, LRel
        from Poule.models.enums import SortKind
        from Poule.models.tree import TreeNode, ExprTree

        innermost = TreeNode(label=LRel(1), children=[])
        layer2 = TreeNode(
            label=LProd(),
            children=[
                TreeNode(label=LSort(SortKind.TYPE_UNIV), children=[]),
                innermost,
            ],
        )
        layer1 = TreeNode(
            label=LProd(),
            children=[
                TreeNode(label=LSort(SortKind.TYPE_UNIV), children=[]),
                layer2,
            ],
        )
        root = TreeNode(
            label=LProd(),
            children=[
                TreeNode(label=LSort(SortKind.TYPE_UNIV), children=[]),
                layer1,
            ],
        )
        # 3 Prod + 3 Sort + 1 Rel = 7 nodes
        original = ExprTree(root=root, node_count=7)
        result = _peel_n_prods(original, 3)
        assert result.root is innermost
        assert result.node_count == 1

    def test_peel_more_than_available_stops_early(self):
        """Peeling more binders than exist stops at the first non-Prod node."""
        from Poule.models.labels import LProd, LSort, LConst
        from Poule.models.enums import SortKind
        from Poule.models.tree import TreeNode, ExprTree

        body = TreeNode(label=LConst("Coq.Init.Nat.add"), children=[])
        root = TreeNode(
            label=LProd(),
            children=[
                TreeNode(label=LSort(SortKind.TYPE_UNIV), children=[]),
                body,
            ],
        )
        original = ExprTree(root=root, node_count=3)
        # Ask to peel 5, but only 1 Prod exists
        result = _peel_n_prods(original, 5)
        assert result.root is body
        assert result.node_count == 1

    def test_peel_non_prod_root_returns_unchanged(self):
        """Peeling from a non-Prod root returns the tree unchanged."""
        from Poule.models.labels import LConst
        from Poule.models.tree import TreeNode, ExprTree

        root = TreeNode(label=LConst("Coq.Init.Nat.add"), children=[])
        original = ExprTree(root=root, node_count=1)
        result = _peel_n_prods(original, 3)
        assert result.root is root
        assert result.node_count == 1


# ---------------------------------------------------------------------------
# normalize_type_query: returns (ConstrNode, auto_binder_count)
# ---------------------------------------------------------------------------


class TestNormalizeTypeQueryReturnsTuple:
    """normalize_type_query returns (ConstrNode, int) where the int is the
    count of auto-generated forall binders.

    Spec: pipeline.md §4.4.1."""

    def test_no_free_vars_returns_zero_count(self):
        """When no free variables are detected, count is 0."""
        from Poule.normalization.constr_node import Const

        ctx = MagicMock()
        ctx.inverted_index = {"Coq.Init.Nat.add": {1}}
        ctx.suffix_index = {}
        # A single resolved const — no free vars
        constr = Const("Coq.Init.Nat.add")
        result, count = normalize_type_query(ctx, constr)
        assert count == 0

    def test_explicit_forall_returns_zero_count(self):
        """When outermost node is already Prod, count is 0 (user wrote forall)."""
        from Poule.normalization.constr_node import Prod, Sort, Rel

        ctx = MagicMock()
        ctx.inverted_index = {}
        ctx.suffix_index = {}
        # User wrote forall n : Type, ...
        constr = Prod("n", Sort("Type"), Rel(1))
        result, count = normalize_type_query(ctx, constr)
        assert count == 0

    def test_one_free_var_returns_count_one(self):
        """One detected free variable → count is 1."""
        from Poule.normalization.constr_node import Const, Prod

        ctx = MagicMock()
        ctx.inverted_index = {}
        ctx.suffix_index = {}
        # "a" is a free variable (lowercase, no dots, not a keyword)
        constr = Const("a")
        result, count = normalize_type_query(ctx, constr)
        assert count == 1
        assert isinstance(result, Prod)

    def test_three_free_vars_returns_count_three(self):
        """Three detected free variables → count is 3."""
        from Poule.normalization.constr_node import App, Const, Prod

        ctx = MagicMock()
        ctx.inverted_index = {"Coq.Init.Logic.eq": {1}}
        ctx.suffix_index = {}
        # "f a b" has three free variables
        constr = App(Const("Coq.Init.Logic.eq"), [Const("f"), Const("a"), Const("b")])
        result, count = normalize_type_query(ctx, constr)
        assert count == 3
        # Should be wrapped in 3 Prod layers
        assert isinstance(result, Prod)
        assert isinstance(result.body, Prod)
        assert isinstance(result.body.body, Prod)


# ---------------------------------------------------------------------------
# score_candidates: peeling with auto_binder_count
# ---------------------------------------------------------------------------


class TestScoreCandidatesWithAutoBinders:
    """When auto_binder_count > 0, score_candidates peels that many leading
    Prod layers from both query and candidate before computing collapse_match
    and ted_similarity. WL cosine and const_jaccard use full trees.

    Spec: pipeline.md §4.7 steps 2, 4b-4d."""

    @patch("Poule.pipeline.search._peel_n_prods")
    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_peels_when_auto_binder_count_positive(
        self,
        mock_extract,
        mock_jaccard,
        mock_collapse,
        mock_ted,
        mock_peel,
    ):
        """With auto_binder_count=2, _peel_n_prods is called for query and
        each candidate, and the peeled trees are passed to collapse_match
        and ted_similarity."""
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 15

        candidate_tree = MagicMock()
        candidate_tree.node_count = 12
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        # Peeled trees are smaller
        peeled_query = MagicMock()
        peeled_query.node_count = 8
        peeled_candidate = MagicMock()
        peeled_candidate.node_count = 6

        # _peel_n_prods returns peeled_query for query, peeled_candidate for cand
        mock_peel.side_effect = [peeled_query, peeled_candidate]

        mock_extract.return_value = {"Coq.Init.Nat.add"}
        mock_jaccard.return_value = 0.6
        mock_collapse.return_value = 0.8
        mock_ted.return_value = 0.7

        candidates_with_wl = [(1, 0.9)]
        scored = score_candidates(
            query_tree, candidates_with_wl, ctx, auto_binder_count=2,
        )

        # _peel_n_prods called twice: once for query, once for candidate
        assert mock_peel.call_count == 2
        mock_peel.assert_any_call(query_tree, 2)
        mock_peel.assert_any_call(candidate_tree, 2)

        # collapse_match and ted_similarity use peeled trees
        mock_collapse.assert_called_once_with(peeled_query, peeled_candidate)
        mock_ted.assert_called_once_with(peeled_query, peeled_candidate)

        # extract_consts uses the original query tree (not peeled)
        mock_extract.assert_called_once_with(query_tree)

        assert len(scored) == 1

    @patch("Poule.pipeline.search._peel_n_prods")
    @patch("Poule.pipeline.search.ted_similarity")
    @patch("Poule.pipeline.search.collapse_match")
    @patch("Poule.pipeline.search.jaccard_similarity")
    @patch("Poule.pipeline.search.extract_consts")
    def test_no_peeling_when_auto_binder_count_zero(
        self,
        mock_extract,
        mock_jaccard,
        mock_collapse,
        mock_ted,
        mock_peel,
    ):
        """With auto_binder_count=0 (default), _peel_n_prods is not called."""
        ctx = _mock_context()
        query_tree = MagicMock()
        query_tree.node_count = 15

        candidate_tree = MagicMock()
        candidate_tree.node_count = 12
        ctx.reader.get_constr_trees.return_value = {1: candidate_tree}

        mock_extract.return_value = set()
        mock_jaccard.return_value = 0.5
        mock_collapse.return_value = 0.7
        mock_ted.return_value = 0.6

        candidates_with_wl = [(1, 0.9)]
        scored = score_candidates(
            query_tree, candidates_with_wl, ctx, auto_binder_count=0,
        )

        mock_peel.assert_not_called()
        # collapse_match and ted use original trees
        mock_collapse.assert_called_once_with(query_tree, candidate_tree)
        mock_ted.assert_called_once_with(query_tree, candidate_tree)


# ---------------------------------------------------------------------------
# 23. search_by_structure and search_by_symbols return SearchResult objects
# ---------------------------------------------------------------------------

from Poule.models.responses import SearchResult


def _decl_row(decl_id, name, module="Test.Module", kind="lemma"):
    """Return a declaration dict as produced by IndexReader.get_declarations_by_ids."""
    return {
        "id": decl_id,
        "name": name,
        "module": module,
        "kind": kind,
        "statement": f"{name} : nat -> nat",
        "type_expr": "nat -> nat",
    }


class TestSearchReturnsSearchResult:
    """All search functions must return SearchResult objects (spec §4.3 step 8,
    §4.5 step 3, §4.4 step 11), not raw tuples or _ScoredResult."""

    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_search_by_structure_returns_search_result(
        self, mock_coq, mock_cse, mock_wl_hist, mock_wl_screen, mock_score
    ):
        """search_by_structure must return SearchResult, not _ScoredResult."""
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)
        # Mock reader to return declaration data
        ctx.reader.get_declarations_by_ids.return_value = [
            _decl_row(1, "Coq.Init.Nat.add_0_r"),
            _decl_row(2, "Coq.Init.Nat.add_comm"),
        ]

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq.return_value = MagicMock()
        mock_cse.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = [(1, 0.9), (2, 0.7)]
        # score_candidates returns (decl_id, score) tuples — not SearchResult
        mock_score.return_value = [(1, 0.85), (2, 0.65)]

        results = search_by_structure(ctx, "forall n, n = n", limit=10)

        assert len(results) == 2
        for r in results:
            assert isinstance(r, SearchResult), (
                f"Expected SearchResult, got {type(r).__name__}"
            )
            assert r.name  # non-empty
            assert r.module  # non-empty
            assert isinstance(r.score, float)

    @patch("Poule.pipeline.search.mepo_select")
    def test_search_by_symbols_returns_search_result(self, mock_mepo):
        """search_by_symbols must return SearchResult, not raw tuples."""
        ctx = _mock_context()
        # mepo_select returns (decl_id, score) tuples — the real return type
        mock_mepo.return_value = [(1, 0.95), (2, 0.80)]
        ctx.reader.get_declarations_by_ids.return_value = [
            _decl_row(1, "Coq.Init.Nat.add_0_r"),
            _decl_row(2, "Coq.Init.Nat.add_comm"),
        ]

        results = search_by_symbols(ctx, ["Coq.Init.Nat.add"], limit=10)

        assert len(results) == 2
        for r in results:
            assert isinstance(r, SearchResult), (
                f"Expected SearchResult, got {type(r).__name__}"
            )
            assert r.name
            assert r.module

    @patch("Poule.pipeline.search.mepo_select")
    def test_search_by_symbols_result_fields_populated(self, mock_mepo):
        """SearchResult fields come from the declaration row, score from MePo."""
        ctx = _mock_context()
        mock_mepo.return_value = [(1, 0.95)]
        ctx.reader.get_declarations_by_ids.return_value = [
            _decl_row(1, "Coq.Init.Nat.add_0_r", module="Coq.Init.Nat", kind="lemma"),
        ]

        results = search_by_symbols(ctx, ["Coq.Init.Nat.add"], limit=10)

        assert len(results) == 1
        r = results[0]
        assert r.name == "Coq.Init.Nat.add_0_r"
        assert r.module == "Coq.Init.Nat"
        assert r.kind == "lemma"
        assert r.score == 0.95

    @patch("Poule.pipeline.search.score_candidates")
    @patch("Poule.pipeline.search.wl_screen")
    @patch("Poule.pipeline.search.wl_histogram")
    @patch("Poule.pipeline.search.cse_normalize")
    @patch("Poule.pipeline.search.coq_normalize")
    def test_search_by_structure_result_fields_populated(
        self, mock_coq, mock_cse, mock_wl_hist, mock_wl_screen, mock_score
    ):
        """SearchResult fields come from the declaration row, score from scoring."""
        parser = _mock_parser()
        ctx = _mock_context(parser=parser)
        ctx.reader.get_declarations_by_ids.return_value = [
            _decl_row(1, "Coq.Arith.PeanoNat.Nat.add_comm",
                       module="Coq.Arith.PeanoNat", kind="theorem"),
        ]

        cse_tree = MagicMock()
        cse_tree.node_count = 10
        mock_coq.return_value = MagicMock()
        mock_cse.return_value = cse_tree
        mock_wl_hist.return_value = {}
        mock_wl_screen.return_value = [(1, 0.9)]
        mock_score.return_value = [(1, 0.85)]

        results = search_by_structure(ctx, "_ * _ = _ * _", limit=10)

        assert len(results) == 1
        r = results[0]
        assert r.name == "Coq.Arith.PeanoNat.Nat.add_comm"
        assert r.module == "Coq.Arith.PeanoNat"
        assert r.kind == "theorem"
        assert r.score == 0.85
