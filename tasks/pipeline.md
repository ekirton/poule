# Implementation Plan: Query Processing Pipeline

**Specification:** [specification/pipeline.md](../specification/pipeline.md)
**Architecture:** [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
**Feedback:** [specification/feedback/pipeline.md](../specification/feedback/pipeline.md)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) — ExprTree, NodeLabel, ScoredResult, WlHistogram, SymbolSet
- [storage.md](../specification/storage.md) — IndexReader, schema, read-path contracts
- [coq-normalization.md](../specification/coq-normalization.md) — `coq_normalize`, `recompute_depths`, `assign_node_ids`
- [cse-normalization.md](../specification/cse-normalization.md) — `cse_normalize`
- [channel-wl-kernel.md](../specification/channel-wl-kernel.md) — `wl_histogram`, `wl_screen`, `cosine_similarity`
- [channel-mepo.md](../specification/channel-mepo.md) — `mepo_select`
- [channel-fts.md](../specification/channel-fts.md) — `fts_search`, `preprocess_fts_query`
- [channel-ted.md](../specification/channel-ted.md) — `ted_similarity`, `ted_rerank`
- [channel-const-jaccard.md](../specification/channel-const-jaccard.md) — `const_jaccard`, `extract_consts`
- [fusion.md](../specification/fusion.md) — `rrf_fuse`, `collapse_match`, fine-ranking weighted sums

---

## Prerequisites

Before implementation of this component can begin:

1. **Data structures** (from data-structures.md tasks) must be implemented: `ExprTree`, `TreeNode`, `NodeLabel` hierarchy, `ScoredResult`, `WlHistogram`, `SymbolSet`, utility functions (`recompute_depths`, `assign_node_ids`, `node_count`, `same_category`), serialization/deserialization (`serialize_tree`, `deserialize_tree`).
2. **Storage layer** (from storage.md tasks) must be implemented: `IndexReader` with read-path methods — WL histogram loading, declaration lookup, FTS5 query execution, batch tree loading (`SELECT constr_tree FROM declarations WHERE id IN (...)`), symbol data loading.
3. **Coq normalization** (from coq-normalization.md tasks) must be implemented: `coq_normalize()` (which internally calls `constr_to_tree`, `recompute_depths`, `assign_node_ids`).
4. **CSE normalization** (from cse-normalization.md tasks) must be implemented: `cse_normalize()`.
5. **WL kernel channel** (from channel-wl-kernel.md tasks) must be implemented: `wl_histogram(tree, h)`, `wl_screen()`, `cosine_similarity()`.
6. **MePo channel** (from channel-mepo.md tasks) must be implemented: `mepo_select()`.
7. **FTS5 channel** (from channel-fts.md tasks) must be implemented: `fts_search()`, `preprocess_fts_query()`.
8. **TED channel** (from channel-ted.md tasks) must be implemented: `ted_similarity()`.
9. **Const Jaccard channel** (from channel-const-jaccard.md tasks) must be implemented: `const_jaccard()`, `extract_consts()`.
10. **Fusion module** (from fusion.md tasks) must be implemented: `rrf_fuse()`, `collapse_match()`, fine-ranking weighted sum functions.

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

1. **Single module vs. subpackage (T1):** The pipeline is implemented as a single `pipeline.py` module rather than a subpackage. The four pipeline functions, the dispatcher, the context factory, and helpers are cohesive enough to live in one file. If the module grows past ~500 lines, consider splitting into a `pipeline/` subpackage.

2. **PipelineContext as explicit dependency injection (T3):** The spec does not prescribe how shared state (WL histograms, inverted index, symbol frequencies, node counts) is passed to pipeline functions. Using a context dataclass passed as the first argument provides explicit dependency injection, making functions testable with mock data. An alternative would be a class-based `Pipeline` object, but the functional approach is simpler for a stateless orchestration layer.

3. **CoqParser as Protocol (T2):** The spec defines the parser contract (Section 3, step 1) but not a Python interface type. A `typing.Protocol` enables structural subtyping — any object with a `parse(str) -> ExprTree` method satisfies the contract without inheritance. The actual coq-lsp subprocess integration is out of scope for this task plan. See feedback Issue 4.

4. **`_structural_score` as shared subroutine with truncation flag (T8):** The architecture doc says `search_by_type` runs the "WL screening pipeline (above)" as one of its three channels. A `truncate` parameter on the shared structural scoring function avoids duplicating the structural scoring logic: `truncate=True` (default) for `search_by_structure`, `truncate=False` for `search_by_type` (which needs the full set for RRF).

5. **Reusing `extract_consts` for symbol extraction in `search_by_type` (T10):** The architecture doc says "extract_symbols at query time is equivalent to extract_consts (const-jaccard) operating on the ExprTree. Implementations should reuse extract_consts." The pipeline calls `extract_consts` from the const-jaccard module rather than implementing a separate symbol extraction function.

6. **Node counts stored in PipelineContext (T3):** The size filter in WL screening requires candidate node counts. These are stored in `declarations.node_count` per the storage spec. Loading them into a `dict[int, int]` on the context avoids per-query database lookups during screening. The spec does not prescribe this, but it is implied by the in-memory screening architecture.

7. **Dispatcher excludes non-pipeline tools (T11):** The dispatcher handles only the four search tools (`search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`). `get_lemma`, `find_related`, and `list_modules` are direct database lookups per mcp-server.md and do not flow through the retrieval pipeline.

8. **FTS input uses original user string (T10):** The architecture doc explicitly says FTS5 in `search_by_type` operates on "the original user-provided type_expr string", not the pretty-printed or normalized form. The spec is ambiguous here (see feedback Issue 2). This plan follows the architecture doc.

---

## Tasks

### Phase A: Module Scaffolding, Types, and Protocols

- [ ] **T1: Pipeline module with error types** — Create the pipeline module and define the error hierarchy for pipeline-level errors
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 7 (error specification); [mcp-server.md](../specification/mcp-server.md) Section 7 (error contract, PARSE_ERROR)
  - **Depends on:** Package skeleton (`src/coq_search/__init__.py`)
  - **Produces:** `src/coq_search/pipeline.py` with `PipelineError`, `ParseError`, `NormalizationError`, `DependencyError`
  - **Done when:** `PipelineError` (base) inherits from `Exception`; `ParseError` accepts `message: str` and wraps Coq parser failures; `NormalizationError` accepts `message: str` and wraps normalization failures; `DependencyError` accepts `message: str` and optional `cause: Exception` and wraps database/channel failures; all three are subclasses of `PipelineError`; all classes are importable from `coq_search.pipeline`

- [ ] **T2: CoqParser protocol** — Define a `typing.Protocol` class for the Coq parser subprocess interface used at query time
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 3 step 1 (parse contract); [pipeline.md](../specification/pipeline.md) Section 7 (parse error propagation)
  - **Depends on:** T1, data-structures tasks (ExprTree type)
  - **Produces:** `CoqParserProtocol` in `src/coq_search/pipeline.py`
  - **Done when:** Protocol class defines `parse(self, expression: str) -> ExprTree` method; docstring specifies that the method raises `ParseError` on failure; protocol uses structural subtyping (no `@runtime_checkable` required)

- [ ] **T3: PipelineContext dataclass** — Implement a context object holding all shared in-memory resources needed by pipeline functions
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 8.1 (startup loads in-memory structures); [storage.md](../specification/storage.md) Section 5.2 (read path); [channel-mepo.md](../specification/channel-mepo.md) Section 6 (inverted index at startup); [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) (WL histograms in memory)
  - **Depends on:** T1, T2
  - **Produces:** `PipelineContext` dataclass in `src/coq_search/pipeline.py`
  - **Done when:** Dataclass has typed fields: `wl_histograms: dict[int, WlHistogram]` (decl_id -> histogram, h=3 only), `inverted_index: dict[str, set[int]]` (symbol -> set of decl_ids), `symbol_freq: dict[str, int]` (symbol -> frequency), `decl_symbols: dict[int, set[str]]` (decl_id -> symbol set), `node_counts: dict[int, int]` (decl_id -> node count), `db_conn: sqlite3.Connection` (for FTS5 and batch tree loading), `coq_parser: CoqParserProtocol`; dataclass is importable and instantiable

---

### Phase B: Normalization Helper

- [ ] **T4: Query normalization helper** — Implement a private function encapsulating the parse-then-normalize sequence that is shared across all expression-based pipelines
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 3 steps 1-3 (parse, normalize, CSE); [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) (normalization happens once, shared across all channels); [pipeline.md](../specification/pipeline.md) Section 7 (normalization produces empty tree -> empty result, not an error)
  - **Depends on:** T1, T2, coq-normalization tasks (`coq_normalize`), cse-normalization tasks (`cse_normalize`)
  - **Produces:** `_normalize(parser: CoqParserProtocol, expression: str) -> ExprTree | None` in `src/coq_search/pipeline.py`
  - **Done when:** Function calls `parser.parse(expression)` to get a raw ExprTree; then calls `coq_normalize(tree)` (which internally runs `constr_to_tree`, `recompute_depths`, `assign_node_ids`); then calls `cse_normalize(tree)` (which internally recomputes depths and node_ids); parse failure raises `ParseError` with the parser's message; normalization failure (any step after parse) returns `None` and logs a warning; this function is the single normalization entry point enforcing the once-per-query invariant

---

### Phase C: Individual Pipeline Functions

- [ ] **T5: Implement `search_by_name`** — Implement the FTS5-only search pipeline
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 6 (search_by_name flow); [channel-fts.md](../specification/channel-fts.md) Section 5 (query preprocessing); [Story 2.2](../doc/requirements/stories/tree-search-mcp.md#22-search-by-name)
  - **Depends on:** T3, fts-channel tasks (`fts_search`, `preprocess_fts_query`)
  - **Produces:** `search_by_name(ctx: PipelineContext, pattern: str, limit: int = 50) -> list[ScoredResult]` in `src/coq_search/pipeline.py`
  - **Done when:** Function preprocesses the pattern via `preprocess_fts_query(pattern)` (qualified name splitting on `.` and `_`, FTS5 escaping, 20-token limit); executes `fts_search(ctx.db_conn, fts_query, limit)` with BM25 weights (name=10.0, statement=1.0, module=5.0); returns `ScoredResult` list ordered by BM25 score descending; returns empty list for empty pattern (not an error per Section 7 design rule); propagates database read failures as `DependencyError`

- [ ] **T6: Implement `search_by_symbols`** — Implement the MePo-only search pipeline
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 5 (search_by_symbols flow); [channel-mepo.md](../specification/channel-mepo.md) Section 5 (iterative selection); [Story 2.5](../doc/requirements/stories/tree-search-mcp.md#25-search-by-symbols)
  - **Depends on:** T3, mepo-channel tasks (`mepo_select`)
  - **Produces:** `search_by_symbols(ctx: PipelineContext, symbols: list[str], limit: int = 50) -> list[ScoredResult]` in `src/coq_search/pipeline.py`
  - **Done when:** Function calls `mepo_select(symbols, ctx.inverted_index, ctx.decl_symbols, ctx.symbol_freq, p=0.6, c=2.4, max_rounds=5)`; truncates result list to `limit`; returns `ScoredResult` list ordered by MePo relevance score descending; returns empty list when `symbols` is empty (not an error); Const Jaccard refinement is NOT included (deferred to Phase 2 per architecture doc)

- [ ] **T7: Implement size filter** — Implement the size ratio filter applied during WL screening
  - **Traces to:** [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) (size filter thresholds); [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 5 (size filter in online query)
  - **Depends on:** T1
  - **Produces:** `passes_size_filter(query_nc: int, candidate_nc: int) -> bool` in `src/coq_search/pipeline.py`
  - **Done when:** Function computes `ratio = max(query_nc, candidate_nc) / max(min(query_nc, candidate_nc), 1)`; for `query_nc < 600`: returns `True` if `ratio <= 1.2`; for `query_nc >= 600`: returns `True` if `ratio <= 1.8`; handles `candidate_nc=0` without division error; both node counts are measured on post-CSE-normalized trees

- [ ] **T8: Implement structural scoring subroutine** — Implement the shared structural scoring logic used by `search_by_structure` directly and as a sub-channel within `search_by_type`
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 3 steps 4-9 (WL screening through ranking); [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) (fine-ranking metric fusion formulas, batch tree retrieval); [fusion.md](../specification/fusion.md) Section 4 (weighted sum formulas); [channel-ted.md](../specification/channel-ted.md) Section 7 (TED reranking integration)
  - **Depends on:** T3, T7, wl-kernel tasks (`wl_histogram`, `wl_screen`, `cosine_similarity`), ted-channel tasks (`ted_similarity`), const-jaccard tasks (`const_jaccard`, `extract_consts`), fusion tasks (`collapse_match`)
  - **Produces:** `_structural_score(ctx: PipelineContext, query_tree: ExprTree, truncate: bool = True, limit: int = 50) -> list[ScoredResult]` in `src/coq_search/pipeline.py`
  - **Done when:** Function performs in order:
    1. Compute `wl_histogram(query_tree, h=3)` for query histogram
    2. Run `wl_screen(query_histogram, ctx.wl_histograms, N=500)` with `passes_size_filter` applied during screening using stored node counts from `ctx.node_counts`
    3. Batch-load candidate trees from database: `SELECT id, constr_tree FROM declarations WHERE id IN (...)` — deserialization failures logged and skipped
    4. For each candidate, determine TED eligibility: both query `node_count <= 50` AND candidate `node_count <= 50`
    5. TED-eligible candidates: `structural_score = 0.15 * wl_cosine + 0.40 * ted_similarity + 0.30 * collapse_match + 0.15 * const_jaccard`
    6. TED-ineligible candidates: `structural_score = 0.25 * wl_cosine + 0.50 * collapse_match + 0.25 * const_jaccard`
    7. `wl_cosine` is the cosine similarity from WL screening for the same query-candidate pair (not recomputed)
    8. If TED computation fails for a TED-eligible pair, fall back to TED-ineligible formula and log warning
    9. All metric values clamped to [0, 1] before combination (fusion.md Section 5)
    10. Sort by `structural_score` descending; ties broken by `decl_id` ascending
    11. When `truncate=True`: return top `limit`; when `truncate=False`: return full scored set
    Returns empty list if WL screening returns 0 candidates

- [ ] **T9: Implement `search_by_structure`** — Implement the full structural similarity search pipeline
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 3 (complete flow); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure); [pipeline.md](../specification/pipeline.md) Section 8 example 1
  - **Depends on:** T4, T8
  - **Produces:** `search_by_structure(ctx: PipelineContext, expression: str, limit: int = 50) -> list[ScoredResult]` in `src/coq_search/pipeline.py`
  - **Done when:** Function calls `_normalize(ctx.coq_parser, expression)` to get the normalized tree; returns empty list if normalization returns `None` (not an error per Section 7); calls `_structural_score(ctx, normalized_tree, truncate=True, limit=limit)` and returns the result; `ParseError` from `_normalize` propagates to the caller unchanged

- [ ] **T10: Implement `search_by_type`** — Implement the multi-channel search pipeline combining structural, symbol, and lexical channels via RRF fusion
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 4 (complete flow); [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) Section `search_by_type`; [fusion.md](../specification/fusion.md) Section 3 (RRF, k=60); [Story 2.3](../doc/requirements/stories/tree-search-mcp.md#23-search-by-type); [pipeline.md](../specification/pipeline.md) Section 7 (channel failure isolation); [pipeline.md](../specification/pipeline.md) Section 8 example 3 (channel failure)
  - **Depends on:** T4, T8, fusion tasks (`rrf_fuse`)
  - **Produces:** `search_by_type(ctx: PipelineContext, type_expr: str, limit: int = 50) -> list[ScoredResult]` in `src/coq_search/pipeline.py`
  - **Done when:** Function performs:
    1. `_normalize(ctx.coq_parser, type_expr)` — `ParseError` propagates; `None` returns empty list
    2. Structural channel: `_structural_score(ctx, normalized_tree, truncate=False)` — returns full candidate set (no truncation before RRF)
    3. Symbol channel: `extract_consts(normalized_tree)` to get query symbol set, then `mepo_select(list(symbols), ctx.inverted_index, ctx.decl_symbols, ctx.symbol_freq, p=0.6, c=2.4, max_rounds=5)` — reuses `extract_consts` from const-jaccard module per architecture doc
    4. Lexical channel: `fts_search(ctx.db_conn, preprocess_fts_query(type_expr))` — uses the ORIGINAL user-provided `type_expr` string per architecture doc, not the normalized form
    5. Each channel wrapped in try/except: on exception, log warning with channel name and error, exclude that channel's results from fusion
    6. `rrf_fuse(surviving_ranked_lists, k=60)` — works with 1, 2, or 3 surviving channel lists
    7. Truncate fused results to `limit`; return as `ScoredResult` list
    Returns empty list if all channels fail or return 0 results

---

### Phase D: Pipeline Dispatch and Context Factory

- [ ] **T11: Pipeline dispatcher** — Implement a top-level dispatch function that routes MCP tool names to the appropriate pipeline function
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 4 (tool definitions); [pipeline.md](../specification/pipeline.md) Section 7 (error propagation to MCP server)
  - **Depends on:** T5, T6, T9, T10
  - **Produces:** `dispatch(ctx: PipelineContext, tool_name: str, params: dict) -> list[ScoredResult]` in `src/coq_search/pipeline.py`
  - **Done when:** Routes `"search_by_name"` to `search_by_name(ctx, params["pattern"], params.get("limit", 50))`; `"search_by_type"` to `search_by_type(ctx, params["type_expr"], params.get("limit", 50))`; `"search_by_structure"` to `search_by_structure(ctx, params["expression"], params.get("limit", 50))`; `"search_by_symbols"` to `search_by_symbols(ctx, params["symbols"], params.get("limit", 50))`; raises `PipelineError` for unknown tool names; does NOT handle `get_lemma`, `find_related`, `list_modules` (these are direct database lookups, not pipeline queries)

- [ ] **T12: PipelineContext factory** — Implement a factory function that constructs a `PipelineContext` from a database path and parser, loading all in-memory data structures at startup
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 8.1 (startup sequence steps 5-7); [storage.md](../specification/storage.md) Section 5.2 (read path in-memory loading)
  - **Depends on:** T3, storage tasks (IndexReader)
  - **Produces:** `create_pipeline_context(db_path: str, coq_parser: CoqParserProtocol) -> PipelineContext` in `src/coq_search/pipeline.py`
  - **Done when:** Function opens database in read-only mode; loads all WL histograms (h=3) into `dict[int, WlHistogram]`; builds inverted symbol index `dict[str, set[int]]` by parsing each declaration's `symbol_set` JSON; loads `symbol_freq` table into `dict[str, int]`; loads declaration symbol sets into `dict[int, set[str]]`; loads node counts into `dict[int, int]`; stores open connection and parser reference on the context; raises `DependencyError` if database cannot be opened or any data loading step fails

- [ ] **T13: Module exports** — Set up `__all__` in `pipeline.py` with all public names
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) (MCP server imports pipeline functions)
  - **Depends on:** T1-T12
  - **Produces:** `__all__` list in `src/coq_search/pipeline.py`
  - **Done when:** Exports include: `PipelineContext`, `PipelineError`, `ParseError`, `NormalizationError`, `DependencyError`, `CoqParserProtocol`, `create_pipeline_context`, `dispatch`, `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `passes_size_filter`

---

### Phase E: Unit Tests

- [ ] **T14: Unit tests — error types and size filter** — Test error hierarchy and size filter boundary behavior
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 7 (error specification); [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) (size filter thresholds)
  - **Depends on:** T1, T7
  - **Produces:** `test/test_pipeline_core.py`
  - **Done when:** Tests cover:
    1. `PipelineError`, `ParseError`, `NormalizationError`, `DependencyError` inheritance chain
    2. `ParseError` carries message string; `DependencyError` carries message and optional cause
    3. `passes_size_filter(10, 11)` -> True (ratio 1.1, query < 600)
    4. `passes_size_filter(10, 13)` -> False (ratio 1.3, exceeds 1.2 threshold)
    5. `passes_size_filter(600, 1000)` -> True (ratio 1.67, query >= 600, within 1.8)
    6. `passes_size_filter(600, 1200)` -> False (ratio 2.0, exceeds 1.8 threshold)
    7. `passes_size_filter(10, 0)` -> does not raise (division-by-zero guard)
    8. Boundary: `passes_size_filter(599, ...)` uses tight 1.2 threshold; `passes_size_filter(600, ...)` uses relaxed 1.8 threshold
    9. Symmetric check: `passes_size_filter(13, 10)` equals `passes_size_filter(10, 13)` (ratio uses max/min)

- [ ] **T15: Unit tests — `_normalize` helper** — Test parse-then-normalize sequence with mock parser
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 3 steps 1-3; Section 7 (normalization failure handling)
  - **Depends on:** T4
  - **Produces:** `test/test_pipeline_normalize.py`
  - **Done when:** Tests cover:
    1. Happy path: mock parser returns ExprTree, normalization steps produce final CSE-reduced tree
    2. Parse failure: mock parser raises exception -> `ParseError` propagated with message
    3. `coq_normalize` failure -> returns `None`, warning logged (not an error)
    4. `cse_normalize` failure -> returns `None`, warning logged
    5. Normalization steps called in correct order: `coq_normalize` then `cse_normalize`

- [ ] **T16: Unit tests — `search_by_name`** — Test FTS5 pipeline with mock database
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 6; Section 8 example 2 ("Nat.add_comm")
  - **Depends on:** T5
  - **Produces:** `test/test_pipeline_search_by_name.py`
  - **Done when:** Tests cover:
    1. Happy path: query returns BM25-ranked results
    2. Empty pattern returns empty list (not an error)
    3. No FTS matches returns empty list
    4. `limit` parameter respected (results truncated)
    5. Qualified name preprocessing: "Nat.add_comm" -> `"Nat" AND "add" AND "comm"` (dots and underscores split into AND terms)
    6. Database error wrapped as `DependencyError`

- [ ] **T17: Unit tests — `search_by_symbols`** — Test MePo pipeline with mock in-memory data
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 5; [channel-mepo.md](../specification/channel-mepo.md) Section 9 (examples)
  - **Depends on:** T6
  - **Produces:** `test/test_pipeline_search_by_symbols.py`
  - **Done when:** Tests cover:
    1. Happy path: symbols produce MePo-ranked results sorted by relevance descending
    2. Empty symbol list returns empty list
    3. Symbols not found in any declaration return empty list
    4. `limit` parameter respected
    5. Const Jaccard refinement is NOT applied (Phase 2 deferral)

- [ ] **T18: Unit tests — `_structural_score`** — Test structural scoring with synthetic trees and mock WL data
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 3 steps 4-9; [fusion.md](../specification/fusion.md) Section 4 (weighted sums); [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) (fine-ranking formulas)
  - **Depends on:** T8
  - **Produces:** `test/test_pipeline_structural.py`
  - **Done when:** Tests cover:
    1. TED-eligible path (both trees <= 50 nodes): formula `0.15*wl + 0.40*ted + 0.30*collapse + 0.15*jaccard` verified numerically
    2. TED-ineligible path (query > 50 nodes): formula `0.25*wl + 0.50*collapse + 0.25*jaccard` verified numerically
    3. Mixed candidates: some TED-eligible, some TED-ineligible — correct formula applied per candidate
    4. WL screening returns 0 candidates -> empty result list
    5. Candidate deserialization failure -> skipped with warning, remaining candidates processed
    6. TED computation failure -> falls back to TED-ineligible formula, warning logged
    7. Results sorted by `structural_score` descending, ties broken by `decl_id` ascending
    8. `truncate=False` returns full scored set; `truncate=True` returns top `limit`
    9. Size filter integrated: candidates failing size filter excluded during WL screening
    10. Metric values outside [0, 1] clamped before combination

- [ ] **T19: Unit tests — `search_by_structure`** — Test full structural search with mock parser and channels
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 3; Section 8 example 1 (`forall n : nat, n + 0 = n`)
  - **Depends on:** T9
  - **Produces:** `test/test_pipeline_search_by_structure.py`
  - **Done when:** Tests cover:
    1. Happy path: expression -> parse -> normalize -> structural score -> ranked results
    2. Parse failure -> `ParseError` propagated to caller
    3. Normalization failure -> empty result list (not an error)
    4. `limit` parameter respected
    5. Expression string passed unchanged to parser

- [ ] **T20: Unit tests — `search_by_type`** — Test multi-channel fusion with mocks for all channels
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 4; Section 7 (channel failure isolation); Section 8 example 3 (channel failure); [fusion.md](../specification/fusion.md) Section 6 example 1 (RRF with 3 channels)
  - **Depends on:** T10
  - **Produces:** `test/test_pipeline_search_by_type.py`
  - **Done when:** Tests cover:
    1. Happy path: all 3 channels return results -> RRF fused -> ranked by RRF score
    2. Items appearing in multiple channels rank higher than items from a single channel (verifies RRF behavior)
    3. One channel fails (exception) -> remaining 2 fused, warning logged, results returned normally
    4. Two channels fail -> single surviving channel's results returned with RRF scoring
    5. All channels return empty -> empty result list
    6. Parse failure -> `ParseError` propagated
    7. Normalization failure -> empty result list
    8. `limit` parameter respected on fused results
    9. Structural sub-channel called with `truncate=False` (full candidate set before RRF)
    10. Symbol extraction uses `extract_consts` from const-jaccard module
    11. FTS channel receives ORIGINAL `type_expr` string, not normalized/re-rendered form

- [ ] **T21: Unit tests — dispatcher and context factory** — Test routing and startup loading
  - **Traces to:** [mcp-server.md](../specification/mcp-server.md) Section 8.1 (startup); T11, T12
  - **Depends on:** T11, T12
  - **Produces:** `test/test_pipeline_context.py`
  - **Done when:** Tests cover:
    1. `dispatch` routes `"search_by_name"` to `search_by_name`
    2. `dispatch` routes `"search_by_type"` to `search_by_type`
    3. `dispatch` routes `"search_by_structure"` to `search_by_structure`
    4. `dispatch` routes `"search_by_symbols"` to `search_by_symbols`
    5. `dispatch` raises `PipelineError` for unknown tool name
    6. `create_pipeline_context` loads WL histograms (h=3) into memory dict with correct decl_id keys
    7. `create_pipeline_context` builds inverted symbol index from declaration symbol sets
    8. `create_pipeline_context` loads symbol_freq table
    9. `create_pipeline_context` loads node counts
    10. `create_pipeline_context` raises `DependencyError` on database open failure
    11. Tests use in-memory SQLite with test fixtures

---

### Phase F: Integration and Performance Tests

- [ ] **T22: Integration test with in-memory SQLite** — End-to-end test with a real SQLite database, synthetic declarations, and a mock Coq parser returning pre-built ExprTrees
  - **Traces to:** [pipeline.md](../specification/pipeline.md) Section 8 (all examples); [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target)
  - **Depends on:** T11, T12, T14-T21
  - **Produces:** `test/test_pipeline_integration.py`
  - **Done when:** Tests cover:
    1. Database has at least 10 synthetic declarations with WL histograms, symbol sets, FTS content, and constr_tree BLOBs
    2. `search_by_name` returns correct FTS5 results from real SQLite
    3. `search_by_symbols` returns correct MePo results from in-memory data
    4. `search_by_structure` returns structurally scored results (WL + fine-ranking)
    5. `search_by_type` returns RRF-fused results from all 3 channels
    6. At least one declaration pair shares symbols (verifies MePo overlap works end-to-end)
    7. At least one declaration pair has similar WL histograms (verifies WL screening works end-to-end)
    8. Empty result scenarios tested (query with no matches)
    9. Channel failure scenario tested (mock one channel to fail mid-query)
    10. All assertions verify result types, field presence, score ordering, and rank correctness

- [ ] **T23: Performance benchmarks** — Verify pipeline meets latency targets using synthetic data at relevant scale
  - **Traces to:** [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target) (< 1 second end-to-end for 50K declarations); [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) (sub-second WL, <200ms MePo, <10ms FTS5)
  - **Depends on:** T22
  - **Produces:** `test/test_pipeline_performance.py`
  - **Done when:** Benchmarks cover (all marked `@pytest.mark.performance`, skipped in CI by default):
    1. `search_by_name` < 50ms on FTS5 with 100K-row synthetic FTS table
    2. `search_by_symbols` < 500ms with 100K-declaration in-memory inverted index
    3. Batch tree loading (`SELECT ... WHERE id IN (...)`) < 100ms for 500 trees
    4. `rrf_fuse` < 10ms for three lists of 500 entries each
    5. Full `search_by_type` pipeline < 1s with 50K synthetic declarations
    6. `PipelineContext` creation (startup loading) < 2s for 50K declarations

---

## Dependency Graph

```
T1 (module + errors)
├── T2 (CoqParser protocol)
│   └── T4 (_normalize helper)
│       ├── T9 (search_by_structure) ──depends──> T8
│       └── T10 (search_by_type) ──depends──> T8
├── T3 (PipelineContext) ──depends──> T2
│   ├── T5 (search_by_name)
│   ├── T6 (search_by_symbols)
│   ├── T8 (_structural_score) ──depends──> T7
│   └── T12 (context factory)
├── T7 (size filter)
└── T11 (dispatcher) ──depends──> T5, T6, T9, T10

T13 (exports) ──depends──> T1-T12

Tests:
T14 ──depends──> T1, T7
T15 ──depends──> T4
T16 ──depends──> T5
T17 ──depends──> T6
T18 ──depends──> T8
T19 ──depends──> T9
T20 ──depends──> T10
T21 ──depends──> T11, T12
T22 ──depends──> T11, T12, T14-T21
T23 ──depends──> T22
```
