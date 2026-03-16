# Implementation Plan: RRF and Fine-Ranking Metric Fusion

**Specification:** [specification/fusion.md](../specification/fusion.md)
**Architecture:** [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
**Feedback:** [specification/feedback/fusion.md](../specification/feedback/fusion.md)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) — ExprTree, TreeNode, NodeLabel, ScoredResult types
- [channel-ted.md](../specification/channel-ted.md) — `ted_similarity`, category definitions for `same_category`
- [channel-wl-kernel.md](../specification/channel-wl-kernel.md) — `wl_cosine` scores passed through from WL screening
- [channel-const-jaccard.md](../specification/channel-const-jaccard.md) — `const_jaccard` scores
- [pipeline.md](../specification/pipeline.md) — Orchestration that invokes fusion

---

## Prerequisites

Before implementation of this component can begin:

1. **Data structures** (from data-structures.md tasks) must be implemented: `ExprTree`, `TreeNode`, `NodeLabel` hierarchy (all 16 concrete subtypes), `ScoredResult`.
2. **TED channel** (from channel-ted.md tasks) must be implemented: `ted_similarity()` and the category definitions used by `same_category`.
3. **Const Jaccard channel** (from channel-const-jaccard.md tasks) must be implemented: `const_jaccard()` and `extract_consts()`.
4. **WL kernel channel** (from channel-wl-kernel.md tasks) must be implemented: WL screening that produces cosine similarity scores for each candidate.

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **`same_category` is implemented as a shared utility (T2)** rather than being duplicated from the TED channel. The TED spec defines the category groupings, and the fusion spec references them for `collapse_match`. This plan creates a single shared function importable by both TED and fusion. If the TED task file already provides this as a shared module, T2 reduces to verifying the existing implementation covers all 16 NodeLabel variants.
- **`collapse_match` is implemented as its own module (T3)** because it is a self-contained recursive algorithm with its own recursion depth cap and distinct test surface. The spec embeds it in the fusion section, but it is algorithmically independent of both RRF and the weighted sum.
- **Fine-ranking metric fusion and RRF are separate functions in separate modules (T4, T5)** since they serve different MCP tools: fine-ranking combines structural sub-metrics for `search_by_structure`, while RRF combines cross-channel ranked lists for `search_by_type`. They share no state or logic.
- **`search_by_structure` does not use RRF.** The spec's Section 3 table says `search_by_structure` uses "RRF" but the architecture doc explicitly says "no RRF — uses only the fine-ranking weighted sum." The pipeline spec (Section 3) also shows a single ranked list output from the weighted sum. This plan follows the architecture doc. See feedback Issue 1.
- **Input clamping (T1) is applied defensively** inside the fine-ranking function to all metric scores before the weighted sum, per the error spec (Section 5, row 4). This prevents invalid upstream scores from producing out-of-range structural scores.
- **No `top_n` parameter on `rrf_fuse` or `fine_rank`.** The specs define these as returning all results. Truncation to top-N is the pipeline orchestrator's responsibility (per pipeline.md), so fusion returns the full sorted list.
- **`LInt` category assignment.** The TED spec's category list omits `LInt` (primitive integer literal). This plan assigns `LInt` to its own singleton category, consistent with how `LApp` and `LSort` each have their own. See feedback — this needs architect confirmation.

---

## Tasks

### Phase A: Package Structure

- [ ] **T1: Fusion package scaffolding** — Create the fusion subpackage and shared retrieval utilities directory
  - **Traces to:** Project setup
  - **Depends on:** None (implement first, before all other tasks)
  - **Produces:** `src/coq_search/retrieval/__init__.py`, `src/coq_search/retrieval/fusion/__init__.py`, `src/coq_search/retrieval/shared/__init__.py`, `tests/retrieval/__init__.py`, `tests/retrieval/fusion/__init__.py`, `tests/retrieval/shared/__init__.py`
  - **Done when:** `import coq_search.retrieval.fusion` works; `import coq_search.retrieval.shared` works; `pytest` discovers tests under `tests/retrieval/fusion/` and `tests/retrieval/shared/`

### Phase B: Shared Utilities

- [ ] **T2: Score clamping utility** — Define clamping and validation logic for fusion metric inputs
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 5 (Error Specification, row 4: scores outside [0, 1] clamped with warning); [Story 3.1](../doc/requirements/stories/tree-search-mcp.md#31-multi-channel-fusion)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/retrieval/fusion/utils.py`
  - **Done when:** `clamp_score(value: float, metric_name: str) -> float` clamps any float to [0.0, 1.0] and logs a warning via the `logging` module when the original value was outside [0, 1]; in-range values pass through unchanged with no logging; boundary values 0.0 and 1.0 pass through without warning

- [ ] **T3: Node category classification** — Implement `same_category()` for collapse-match using TED's category groupings
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 4 ("The `same_category` grouping uses the same node categories as the TED cost model"); [channel-ted.md](../specification/channel-ted.md) Section 4 (Category definition)
  - **Depends on:** T1, data-structures tasks (NodeLabel types)
  - **Produces:** `src/coq_search/retrieval/shared/node_categories.py`
  - **Done when:** `node_category(label: NodeLabel) -> str` returns the category name for any of the 16 NodeLabel variants; `same_category(label_a: NodeLabel, label_b: NodeLabel) -> bool` returns True iff both labels belong to the same category; categories match TED spec Section 4 exactly: leaf constants (`LConst`, `LInd`, `LConstruct`), leaf variables (`LRel`, `LVar`, `LCseVar`), sorts (`LSort`), binders (`LProd`, `LLambda`, `LLetIn`), application (`LApp`), elimination (`LCase`, `LProj`), recursion (`LFix`, `LCoFix`); `LInt` assigned its own category; function is importable from `coq_search.retrieval.shared.node_categories`

### Phase C: Collapse-Match Similarity

- [ ] **T4: Collapse-match implementation** — Implement the recursive collapse-match similarity metric
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 4 (Collapse-Match Similarity algorithm); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure); [Story 3.1](../doc/requirements/stories/tree-search-mcp.md#31-multi-channel-fusion)
  - **Depends on:** T3, data-structures tasks (ExprTree, TreeNode)
  - **Produces:** `src/coq_search/retrieval/fusion/collapse_match.py`
  - **Done when:** `collapse_match(query: ExprTree, candidate: ExprTree, _depth: int = 0, max_depth: int = 200) -> float` implements the recursive algorithm from fusion.md Section 4 exactly: (1) both leaves with same category -> 1.0, different category -> 0.0; (2) query is leaf, candidate is not -> recurse into candidate children, take max; (3) candidate is leaf, query is not -> 0.0; (4) both interior, different category -> 0.0; (5) both interior, same category -> greedy left-to-right child matching, each query child matched against all candidate children taking the max, sum divided by `max(len(candidate.children), matched)`; (6) recursion depth capped at `max_depth` (default 200), returns 0.0 when exceeded per error spec Section 5; (7) result is always in [0.0, 1.0]; function is importable from `coq_search.retrieval.fusion.collapse_match`

### Phase D: Fine-Ranking Metric Fusion

- [ ] **T5: Weight constants** — Define all fusion weight constants and thresholds as named module-level constants
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 4 (Score Computation formulas); Section 3 (Parameter k)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/retrieval/fusion/constants.py`
  - **Done when:** Module exports: `TED_ELIGIBLE_WL_WEIGHT = 0.15`, `TED_ELIGIBLE_TED_WEIGHT = 0.40`, `TED_ELIGIBLE_CM_WEIGHT = 0.30`, `TED_ELIGIBLE_CJ_WEIGHT = 0.15`, `TED_INELIGIBLE_WL_WEIGHT = 0.25`, `TED_INELIGIBLE_CM_WEIGHT = 0.50`, `TED_INELIGIBLE_CJ_WEIGHT = 0.25`, `DEFAULT_RRF_K = 60`, `TED_NODE_COUNT_THRESHOLD = 50`; no magic numbers appear in any fusion formula implementation

- [ ] **T6: Fine-ranking weighted sum** — Implement structural score computation with and without TED
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 4 (Score Computation); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure); [Story 3.1](../doc/requirements/stories/tree-search-mcp.md#31-multi-channel-fusion)
  - **Depends on:** T2, T4, T5
  - **Produces:** `src/coq_search/retrieval/fusion/fine_ranking.py`
  - **Done when:** `compute_structural_score(wl_cosine: float, ted_similarity: float | None, collapse_match_score: float, const_jaccard: float, node_count: int) -> float` applies the correct weighted sum formula based on whether TED is available; when `node_count <= 50` and `ted_similarity is not None`: uses TED-eligible weights (0.15/0.40/0.30/0.15); when `node_count > 50` or `ted_similarity is None`: uses TED-ineligible weights (0.25/0.50/0.25); all input scores are clamped via `clamp_score` before weighting; result is a float in [0, 1]; `fine_rank(candidates: list[CandidateMetrics], query_tree: ExprTree) -> list[FusedResult]` takes a list of candidates with their precomputed per-channel scores (`decl_id`, `wl_cosine`, `candidate_tree`, `const_set`, `node_count`), computes `collapse_match` and `const_jaccard` for each, calls `compute_structural_score`, returns candidates sorted descending by `structural_score` with ties broken by `decl_id` ascending, 1-based ranks assigned; returns `list[FusedResult]` with `structural_score` set and `rrf_score` as `None`; empty candidates returns empty list

### Phase E: Reciprocal Rank Fusion

- [ ] **T7: RRF implementation** — Implement Reciprocal Rank Fusion across channel ranked lists
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 3 (Reciprocal Rank Fusion); [Story 2.3](../doc/requirements/stories/tree-search-mcp.md#23-search-by-type); [Story 3.1](../doc/requirements/stories/tree-search-mcp.md#31-multi-channel-fusion)
  - **Depends on:** T5
  - **Produces:** `src/coq_search/retrieval/fusion/rrf.py`
  - **Done when:** `rrf_fuse(ranked_lists: list[list[str]], k: int = 60) -> list[tuple[str, float]]` accumulates RRF scores per `decl_id` using formula `1.0 / (k + rank)` where rank is 1-based; returns list of `(decl_id, score)` tuples sorted descending by score; all input ranked lists empty -> returns empty output (per error spec: "fusion never fails"); single list returns that list re-scored with RRF formula (rank order preserved); k uses `DEFAULT_RRF_K` from constants; a declaration absent from a channel contributes zero to its score (not a default rank)

### Phase F: Public API and Integration

- [ ] **T8: Fusion module public API** — Define the public interface that the pipeline orchestrator calls
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 3 (Channel Contributions by MCP Tool); [pipeline.md](../specification/pipeline.md) Sections 3-6
  - **Depends on:** T6, T7
  - **Produces:** `src/coq_search/retrieval/fusion/__init__.py` (updated with exports)
  - **Done when:** Module exports: `rrf_fuse`, `compute_structural_score`, `fine_rank`, `collapse_match`; `fuse_search_by_structure(candidates_with_metrics: list, query_tree: ExprTree) -> list[ScoredResult]` is a convenience function that runs `fine_rank` and converts `FusedResult` to `ScoredResult` format; `fuse_search_by_type(structural_list: list[str], symbol_list: list[str], lexical_list: list[str], k: int = 60) -> list[ScoredResult]` is a convenience function that runs `rrf_fuse` on the provided lists and converts to `ScoredResult` format; both convenience functions handle empty/missing channel lists gracefully (per error spec: "fusion never fails", degenerate inputs produce degenerate outputs); `from coq_search.retrieval.fusion import rrf_fuse, collapse_match, fine_rank` works

### Phase G: Unit Tests

- [ ] **T9: Unit tests — score clamping** — Test the clamping utility
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 5 (Error Specification)
  - **Depends on:** T2
  - **Produces:** `tests/retrieval/fusion/test_utils.py`
  - **Done when:** Tests cover: in-range value (0.5) passes through unchanged; negative value (-0.3) clamps to 0.0; value > 1.0 (1.5) clamps to 1.0; boundary values 0.0 and 1.0 pass through without warning; warning is logged for out-of-range values (verified via `caplog` or mock)

- [ ] **T10: Unit tests — node categories** — Test category classification for all NodeLabel variants
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 4 (Category definition)
  - **Depends on:** T3
  - **Produces:** `tests/retrieval/shared/test_node_categories.py`
  - **Done when:** Tests cover: every one of the 16 NodeLabel variants is assigned a category; `same_category` returns True for all within-category pairs (`LConst`/`LInd`, `LConst`/`LConstruct`, `LRel`/`LVar`/`LCseVar`, `LProd`/`LLambda`/`LLetIn`, `LCase`/`LProj`, `LFix`/`LCoFix`); `same_category` returns False for representative cross-category pairs (`LConst`/`LApp`, `LRel`/`LProd`, `LSort`/`LLambda`); `LApp` is in its own category (not same as any other); `LSort` variants (`Prop`, `Set`, `TypeUniv`) are all in one category; `LInt` is in its own category

- [ ] **T11: Unit tests — collapse-match** — Test the collapse-match recursive algorithm
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 4 (Collapse-Match Similarity)
  - **Depends on:** T4
  - **Produces:** `tests/retrieval/fusion/test_collapse_match.py`
  - **Done when:** Tests cover: (1) two identical leaf nodes with same category return 1.0; (2) two leaf nodes with different categories return 0.0; (3) query leaf vs candidate interior node with matching subtree returns > 0.0; (4) candidate leaf vs non-leaf query returns 0.0; (5) interior nodes with same category and identical children structure; (6) interior nodes with different categories return 0.0; (7) greedy matching with partial child overlap produces proportional score; (8) normalization divides by `max(len(candidate.children), matched)` verified explicitly; (9) recursion depth cap at 200 returns 0.0; (10) asymmetry verified: `collapse_match(small, large)` differs from `collapse_match(large, small)`; (11) interior node with no children and same category returns 1.0 (the `matched == 0` branch)

- [ ] **T12: Unit tests — fine-ranking weighted sum** — Test structural score computation
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 4 (Score Computation), Section 6 (Examples)
  - **Depends on:** T6
  - **Produces:** `tests/retrieval/fusion/test_fine_ranking.py`
  - **Done when:** Tests cover: (1) spec example with TED available: node_count=30, wl=0.82, ted=0.65, cm=0.71, cj=0.50, expected structural_score=0.671 (within 1e-3); (2) spec example without TED: node_count=80, wl=0.82, cm=0.71, cj=0.50, expected structural_score=0.685 (within 1e-3); (3) boundary node_count=50 uses TED formula; (4) node_count=51 uses non-TED formula; (5) all-zero inputs produce 0.0; (6) all-one inputs produce 1.0; (7) out-of-range input (e.g., wl_cosine=1.5) is clamped with warning logged; (8) `ted_similarity=None` with node_count <= 50 uses non-TED formula (graceful fallback); (9) `fine_rank` returns candidates sorted descending by score; (10) `fine_rank` with empty input returns empty list; (11) `fine_rank` tie-breaking: equal scores ordered by `decl_id` ascending

- [ ] **T13: Unit tests — RRF** — Test Reciprocal Rank Fusion
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 3 (Reciprocal Rank Fusion), Section 6 (Examples)
  - **Depends on:** T7
  - **Produces:** `tests/retrieval/fusion/test_rrf.py`
  - **Done when:** Tests cover: (1) spec example with 3 channels: D1 in all 3 lists at ranks 1/3/2 -> score 0.04839 (within 1e-4), D2 at ranks 2/1 -> 0.03252, D3 at ranks 3/1 -> 0.03226, D4 at rank 2 -> 0.01613, D5 at rank 3 -> 0.01587; final ranking D1, D2, D3, D4, D5; (2) empty input returns empty list; (3) single list preserves rank order with RRF scores 1/(k+rank); (4) two lists with overlapping items — overlapping items score higher than non-overlapping; (5) k parameter affects scores (test with k=1 vs k=60); (6) item appearing in all N lists scores higher than item in N-1 lists; (7) large lists (500+ items) complete without error

- [ ] **T14: Unit tests — fusion public API** — Test the convenience functions and module exports
  - **Traces to:** [fusion.md](../specification/fusion.md) Sections 3-4; [pipeline.md](../specification/pipeline.md) Sections 3-4
  - **Depends on:** T8
  - **Produces:** `tests/retrieval/fusion/test_fusion_api.py`
  - **Done when:** Tests cover: (1) `fuse_search_by_structure` with mixed TED/non-TED candidates returns sorted ScoredResult list; (2) `fuse_search_by_type` with 3 channel lists returns fused ScoredResult list; (3) `fuse_search_by_type` with one empty channel list still returns results from remaining channels; (4) `fuse_search_by_structure` with empty candidates returns empty list; (5) `fuse_search_by_type` with all empty lists returns empty list; (6) all expected symbols are importable from the package

### Phase H: Integration Tests

- [ ] **T15: Integration test — fine-ranking end-to-end** — Test fine-ranking with realistic tree inputs
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 6 (Examples); [Story 3.1](../doc/requirements/stories/tree-search-mcp.md#31-multi-channel-fusion)
  - **Depends on:** T6, T4, data-structures tasks
  - **Produces:** `tests/retrieval/fusion/test_fine_ranking_integration.py`
  - **Done when:** Test constructs realistic ExprTree instances (e.g., a `forall n : nat, n + 0 = n` tree with ~12 nodes); `collapse_match` is computed on these trees and produces a float in [0, 1]; `compute_structural_score` is called with the collapse_match result plus mock wl_cosine, ted_similarity, and const_jaccard values; the structural_score is a plausible value in [0, 1]; test includes both TED-eligible (node_count <= 50) and TED-ineligible (node_count > 50) candidates in the same `fine_rank` call

- [ ] **T16: Integration test — RRF with heterogeneous channels** — Test RRF fusion simulating a `search_by_type` pipeline
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 3; [pipeline.md](../specification/pipeline.md) Section 4; [Story 2.3](../doc/requirements/stories/tree-search-mcp.md#23-search-by-type)
  - **Depends on:** T7, T8
  - **Produces:** `tests/retrieval/fusion/test_rrf_integration.py`
  - **Done when:** Test simulates `search_by_type` with 3 channel lists (structural, symbol, lexical) of 50+ items each; items appearing in multiple channels rank higher in fused output; fused list is ordered by RRF score descending; `fuse_search_by_type` convenience function produces correct ScoredResult output; test with one channel returning empty list still produces valid results from remaining channels

### Phase I: Performance Tests

- [ ] **T17: Performance test — fusion latency** — Validate fusion meets latency contribution target
  - **Traces to:** [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target) (retrieval < 1 second end-to-end, so fusion must be a small fraction)
  - **Depends on:** T4, T6, T7
  - **Produces:** `tests/retrieval/fusion/test_performance.py`
  - **Done when:** Test (marked `@pytest.mark.performance`, skipped in CI by default) measures wall-clock time for: (1) `collapse_match` on two trees with 50 nodes each completes in < 100ms; (2) `fine_rank` on 500 candidates completes in < 500ms; (3) `rrf_fuse` on 3 lists of 500 items each completes in < 10ms; (4) total fusion overhead for a realistic `search_by_structure` scenario (500 candidates with collapse_match + fine_rank) completes in < 500ms; memory usage stays bounded (no unbounded accumulation)
