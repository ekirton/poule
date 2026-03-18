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
    reader.load_wl_histograms.return_value = {
        1: {"label_A": 3, "label_B": 1},
        2: {"label_A": 2, "label_C": 4},
        3: {"label_B": 5},
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


def _mock_context(parser=None):
    """Return a PipelineContext-like mock with all expected fields."""
    ctx = MagicMock(spec=PipelineContext)
    ctx.reader = _mock_reader()
    ctx.wl_histograms = ctx.reader.load_wl_histograms()
    ctx.inverted_index = ctx.reader.load_inverted_index()
    ctx.symbol_frequencies = ctx.reader.load_symbol_frequencies()
    ctx.declaration_node_counts = ctx.reader.load_declaration_node_counts()
    # declaration_symbols derived from inverted index
    ctx.declaration_symbols = {
        1: {"Coq.Init.Nat.add", "Coq.Init.Datatypes.nat", "Coq.Init.Logic.eq"},
        2: {"Coq.Init.Nat.add", "Coq.Init.Datatypes.nat"},
        3: {"Coq.Init.Datatypes.nat", "Coq.Init.Logic.eq"},
    }
    ctx.parser = parser
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
        assert ctx.wl_histograms == reader.load_wl_histograms()
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
# 4. search_by_symbols: calls mepo_select, returns top-limit results
# ---------------------------------------------------------------------------


class TestSearchBySymbols:
    """search_by_symbols delegates to mepo_select and respects limit."""

    @patch("Poule.pipeline.search.mepo_select")
    def test_calls_mepo_select_with_correct_args(self, mock_mepo):
        ctx = _mock_context()
        mock_mepo.return_value = [
            _mock_search_result(1, 0.8),
            _mock_search_result(2, 0.6),
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
    def test_limits_results(self, mock_mepo):
        ctx = _mock_context()
        mock_mepo.return_value = [
            _mock_search_result(i, 1.0 - i * 0.1) for i in range(20)
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
        mock_mepo.return_value = [
            _mock_search_result(i, 1.0 - i * 0.05) for i in range(20)
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
        mock_mepo.return_value = [
            _mock_search_result(1, 0.3),
            _mock_search_result(2, 0.9),
            _mock_search_result(3, 0.6),
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
# 17. CoqLspParser contract tests (real coq-lsp)
# ---------------------------------------------------------------------------


@pytest.mark.requires_coq
class TestCoqLspParserContract:
    """Contract tests exercising real coq-lsp.

    These tests require coq-lsp to be installed and on PATH.
    Run with: pytest -m requires_coq

    Note: coq-lsp currently returns text output (not structured Constr.t
    JSON) for ``Check`` commands via ``proof/goals``.  Positive parse tests
    are marked ``xfail`` until coq-lsp supports structured constr output
    or the parser is extended with a text-to-ConstrNode fallback.
    """

    @pytest.mark.xfail(
        reason="coq-lsp returns text, not structured Constr.t JSON",
        raises=ParseError,
    )
    def test_parse_simple_nat_expression(self):
        """Parse "nat" — currently xfail because coq-lsp lacks structured output."""
        parser = CoqLspParser()
        try:
            result = parser.parse("nat")
            import Poule.normalization.constr_node as cn

            valid_types = (
                cn.Rel, cn.Var, cn.Sort, cn.Cast, cn.Prod, cn.Lambda,
                cn.LetIn, cn.App, cn.Const, cn.Ind, cn.Construct,
                cn.Case, cn.Fix, cn.CoFix, cn.Proj, cn.Int, cn.Float,
            )
            assert isinstance(result, valid_types), (
                f"Expected a ConstrNode variant, got {type(result)}"
            )
        finally:
            parser.close()

    @pytest.mark.xfail(
        reason="coq-lsp returns text, not structured Constr.t JSON",
        raises=ParseError,
    )
    def test_parse_forall_expression(self):
        """Parse 'forall n : nat, n = n' — currently xfail."""
        parser = CoqLspParser()
        try:
            result = parser.parse("forall n : nat, n = n")
            import Poule.normalization.constr_node as cn

            valid_types = (
                cn.Rel, cn.Var, cn.Sort, cn.Cast, cn.Prod, cn.Lambda,
                cn.LetIn, cn.App, cn.Const, cn.Ind, cn.Construct,
                cn.Case, cn.Fix, cn.CoFix, cn.Proj, cn.Int, cn.Float,
            )
            assert isinstance(result, valid_types), (
                f"Expected a ConstrNode variant, got {type(result)}"
            )
        finally:
            parser.close()

    def test_parse_invalid_expression_raises(self):
        """Parse 'not_a_valid_coq_thing!!!' and verify ParseError."""
        parser = CoqLspParser()
        try:
            with pytest.raises(ParseError):
                parser.parse("not_a_valid_coq_thing!!!")
        finally:
            parser.close()

    def test_close_terminates_process(self):
        """Verify close() terminates the coq-lsp subprocess."""
        parser = CoqLspParser()
        # Trigger _ensure_started by attempting a parse (will raise ParseError
        # because coq-lsp returns text, not structured JSON — catch it)
        try:
            parser.parse("nat")
        except ParseError:
            pass

        # Process should be running
        assert parser._proc is not None
        proc = parser._proc

        parser.close()

        # After close, internal ref should be None
        assert parser._proc is None
        # The real process should have terminated
        assert proc.poll() is not None
