"""Search functions for the query processing pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from wily_rooster.channels.const_jaccard import jaccard_similarity
from wily_rooster.channels.fts import fts_query, fts_search
from wily_rooster.channels.mepo import extract_consts, mepo_select
from wily_rooster.channels.ted import ted_similarity
from wily_rooster.channels.wl_kernel import wl_histogram, wl_screen
from wily_rooster.fusion.fusion import collapse_match, rrf_fuse
from wily_rooster.normalization.cse import cse_normalize
from wily_rooster.normalization.errors import NormalizationError as _InternalNormalizationError
from wily_rooster.normalization.normalize import coq_normalize
from wily_rooster.pipeline.parser import ParseError


class NormalizationError(Exception):
    """Error during query normalization."""
    pass

logger = logging.getLogger(__name__)


@dataclass
class _ScoredResult:
    """Lightweight result object with decl_id and score."""
    decl_id: int
    score: float


def search_by_name(ctx: Any, pattern: str, limit: int) -> list[Any]:
    """Search declarations by name pattern using FTS5.

    Returns up to *limit* SearchResult items ranked by BM25.
    """
    query = fts_query(pattern)
    if not query:
        return []
    results = fts_search(query, limit=limit, reader=ctx.reader)
    return results[:limit]


def search_by_symbols(ctx: Any, symbols: list[str], limit: int) -> list[Any]:
    """Search declarations by symbol names using MePo relevance.

    Returns up to *limit* SearchResult items ranked by MePo relevance.
    """
    results = mepo_select(
        set(symbols),
        ctx.inverted_index,
        ctx.symbol_frequencies,
        ctx.declaration_symbols,
        p=0.6,
        c=2.4,
        max_rounds=5,
    )
    results = sorted(results, key=lambda r: r.score if hasattr(r, 'score') else r[1], reverse=True)
    return results[:limit]


def search_by_structure(ctx: Any, expression: str, limit: int) -> list[Any]:
    """Search declarations by structural similarity.

    Returns up to *limit* result items ranked by structural score.
    """
    # Step 1: Parse expression (ParseError propagates)
    constr_node = ctx.parser.parse(expression)

    # Steps 2-3: Normalize (NormalizationError -> empty results)
    try:
        normalized_tree = coq_normalize(constr_node)
        cse_tree = cse_normalize(normalized_tree)
    except (NormalizationError, _InternalNormalizationError) as exc:
        logger.warning(
            "Normalization failed for expression %r: %s", expression, exc
        )
        return []

    # If cse_normalize returns None (in-place mutation), use normalized_tree
    if cse_tree is None:
        cse_tree = normalized_tree

    # Step 4: WL histogram
    query_histogram = wl_histogram(cse_tree, h=3)

    # Step 5: WL screening
    candidates_with_wl = wl_screen(
        query_histogram,
        cse_tree.node_count,
        ctx.wl_histograms,
        ctx.declaration_node_counts,
        n=500,
    )

    # Step 6: Structural scoring
    scored = score_candidates(cse_tree, candidates_with_wl, ctx)

    # Step 7: Sort by score descending, take top limit
    scored.sort(key=lambda x: x[1], reverse=True)
    scored = scored[:limit]

    # Step 8: Construct result objects
    results = [_ScoredResult(decl_id=decl_id, score=score) for decl_id, score in scored]
    return results


def search_by_type(ctx: Any, type_expr: str, limit: int) -> list[Any]:
    """Search declarations by type expression using multi-channel fusion.

    Returns up to *limit* result items ranked by RRF-fused score.
    """
    # Step 1: Parse expression (ParseError propagates)
    constr_node = ctx.parser.parse(type_expr)

    # Steps 2: Normalize (NormalizationError -> empty results)
    try:
        normalized_tree = coq_normalize(constr_node)
        cse_tree = cse_normalize(normalized_tree)
    except (NormalizationError, _InternalNormalizationError) as exc:
        logger.warning(
            "Normalization failed for type expression %r: %s", type_expr, exc
        )
        return []

    # If cse_normalize returns None (in-place mutation), use normalized_tree
    if cse_tree is None:
        cse_tree = normalized_tree

    # WL histogram + screening + scoring -> structural ranked list
    query_histogram = wl_histogram(cse_tree, h=3)
    candidates_with_wl = wl_screen(
        query_histogram,
        cse_tree.node_count,
        ctx.wl_histograms,
        ctx.declaration_node_counts,
        n=500,
    )
    structural_scored = score_candidates(cse_tree, candidates_with_wl, ctx)

    # Step 3: Symbol channel via MePo
    query_symbols = extract_consts(cse_tree)
    mepo_results = mepo_select(
        query_symbols,
        ctx.inverted_index,
        ctx.symbol_frequencies,
        ctx.declaration_symbols,
        p=0.6,
        c=2.4,
        max_rounds=5,
    )

    # Step 4: Lexical channel via FTS
    query = fts_query(type_expr)
    fts_results = fts_search(query, limit=limit, reader=ctx.reader)

    # Step 5: RRF fusion
    fused = rrf_fuse([structural_scored, mepo_results, fts_results], k=60)

    # Step 6: Sort by score descending, take top limit
    fused = sorted(fused, key=lambda r: r.score if hasattr(r, 'score') else r[1], reverse=True)
    return fused[:limit]


def score_candidates(
    query_tree: Any,
    candidates_with_wl: list[tuple[int, float]],
    ctx: Any,
) -> list[tuple[int, float]]:
    """Compute structural scores for candidates.

    Returns (decl_id, structural_score) pairs.
    """
    if not candidates_with_wl:
        return []

    # Extract query constants
    query_consts = extract_consts(query_tree)

    # Fetch candidate trees in batch
    candidate_ids = [decl_id for decl_id, _ in candidates_with_wl]
    candidate_trees = ctx.reader.get_constr_trees(candidate_ids)

    results: list[tuple[int, float]] = []
    for decl_id, wl_cosine in candidates_with_wl:
        candidate_tree = candidate_trees.get(decl_id)
        if candidate_tree is None:
            continue

        # Compute const jaccard using pre-computed declaration symbols
        candidate_consts = ctx.declaration_symbols.get(decl_id, set())
        cj = jaccard_similarity(query_consts, candidate_consts)

        # Compute collapse match
        cm = collapse_match(query_tree, candidate_tree)

        # Determine if TED should be computed
        use_ted = (query_tree.node_count <= 50 and candidate_tree.node_count <= 50)

        if use_ted:
            ted_sim = ted_similarity(query_tree, candidate_tree)
            # Weights: 0.15 * wl + 0.40 * ted + 0.30 * collapse + 0.15 * jaccard
            structural = 0.15 * wl_cosine + 0.40 * ted_sim + 0.30 * cm + 0.15 * cj
        else:
            # Weights: 0.25 * wl + 0.50 * collapse + 0.25 * jaccard
            structural = 0.25 * wl_cosine + 0.50 * cm + 0.25 * cj

        results.append((decl_id, float(structural)))

    return results
