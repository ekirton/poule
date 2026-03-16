# Implementation Plan: Const Name Jaccard Channel

**Specification:** [specification/channel-const-jaccard.md](../specification/channel-const-jaccard.md)
**Architecture:** [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
**Feedback:** [specification/feedback/channel-const-jaccard.md](../specification/feedback/channel-const-jaccard.md)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) -- ExprTree, TreeNode, NodeLabel subtypes (LConst, LInd, LConstruct), ScoredResult
- [pipeline.md](../specification/pipeline.md) -- orchestration context: where const_jaccard is invoked
- [fusion.md](../specification/fusion.md) -- how const_jaccard scores feed into fine-ranking weighted sums

---

## Prerequisites

Before implementation of this component can begin:

1. **Data structures** (from data-structures.md tasks) must be implemented: `ExprTree`, `TreeNode`, `NodeLabel` hierarchy (specifically `LConst`, `LInd`, `LConstruct`), `ScoredResult`.
2. **Tree serialization** (from data-structures.md tasks) must be implemented: `deserialize_tree()` for loading candidate trees from storage at query time.

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

1. **`extract_consts` vs `extract_symbols`.** The extraction module's `extract_symbols()` (from extraction.md Section 5.5) collects the same node types (`LConst`, `LInd`, `LConstruct`) and returns a sorted, deduplicated list. `extract_consts` returns a set. The architecture doc says "implementations should reuse `extract_consts`" for symbol extraction at query time (retrieval-pipeline.md line 42). This plan implements `extract_consts` as the canonical set-returning function; `extract_symbols` in the extraction module should delegate to it and convert to a sorted list. The architect should confirm this direction.

2. **Module placement.** The spec does not prescribe where this code lives. The existing task file placed it under `coq_search.channels`. This plan follows that convention, placing it in `src/coq_search/channels/const_jaccard.py`, grouping all channel implementations together.

3. **Separate `jaccard_similarity` function.** The spec defines `const_jaccard(tree1, tree2)` as a pairwise function (Section 4) and `const_jaccard_rank` as a batch function (Section 5). This plan factors out the pure set math into `jaccard_similarity(set_a, set_b)` for reusability and testability, then composes both `const_jaccard` and `const_jaccard_rank` from it.

4. **Pre-extraction optimization.** The spec's `const_jaccard_rank` pseudocode (Section 5) extracts query constants once and reuses them across candidates. The implementation follows this optimization directly.

5. **Output type.** The spec returns `list[(id, score)]` tuples. The data-structures spec defines `ScoredResult` as the standard channel output type. This plan uses tuples as the spec prescribes; conversion to `ScoredResult` is the pipeline orchestrator's responsibility. The architect should confirm this boundary.

6. **Pre-computed symbol set optimization.** At query time, candidate constant sets could be loaded from `declarations.symbol_set` (a JSON column) instead of deserializing full trees and traversing them. This is a significant performance optimization for large candidate sets. This plan includes it as a separate task (T5) that can be deferred if initial performance is acceptable.

---

## Tasks

### Phase A: Package Structure

- [ ] **T1: Channel package scaffolding** -- Create the channels subpackage if it does not already exist
  - **Traces to:** Project setup
  - **Depends on:** None (implement first, before all other tasks)
  - **Produces:** `src/coq_search/channels/__init__.py`, `tests/channels/__init__.py`
  - **Done when:** `from coq_search.channels import const_jaccard` will work once the module is created; `pytest` discovers tests under `tests/channels/`

### Phase B: Core Functions

- [ ] **T2: `extract_consts` function** -- Extract the set of constant names from an ExprTree by traversing all nodes
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Section 3; [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure) (structural similarity); [Story 3.1](../doc/requirements/stories/tree-search-mcp.md#31-multi-channel-fusion) (multi-channel retrieval)
  - **Depends on:** data-structures tasks (ExprTree, TreeNode, LConst, LInd, LConstruct)
  - **Produces:** `extract_consts(tree: ExprTree) -> set[str]` in `src/coq_search/channels/const_jaccard.py`
  - **Done when:** Traversal visits every node in the tree; collects `.name` from `LConst`, `LInd`, and `LConstruct` nodes into a `set[str]`; `LConstruct` contributes its `.name` field (the parent inductive FQN, per expression-tree.md invariant "Canonical names only"); all other node types are skipped but their children are still traversed; tree with no constant/inductive/constructor nodes returns empty set; duplicate references collapse naturally via set semantics; handles trees up to 1000 levels deep without stack overflow (iterative traversal, consistent with data-structures NFR); time complexity is O(n) where n is node count

- [ ] **T3: `jaccard_similarity` function** -- Compute Jaccard similarity coefficient between two string sets
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Section 4
  - **Depends on:** None (pure set math)
  - **Produces:** `jaccard_similarity(set_a: set[str], set_b: set[str]) -> float` in `src/coq_search/channels/const_jaccard.py`
  - **Done when:** Returns `len(set_a & set_b) / len(set_a | set_b)`; returns 0.0 when both sets are empty (guarded by `len(union) == 0` check); returns 0.0 when one set is empty and the other is not; returns 1.0 when both sets are identical and nonempty; return value is always a float in [0.0, 1.0]; is symmetric: `jaccard_similarity(A, B) == jaccard_similarity(B, A)`

- [ ] **T4: `const_jaccard` pairwise function** -- Compute Jaccard similarity between two expression trees' constant sets
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Section 4; [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** T2, T3
  - **Produces:** `const_jaccard(tree1: ExprTree, tree2: ExprTree) -> float` in `src/coq_search/channels/const_jaccard.py`
  - **Done when:** Calls `extract_consts` on both trees then `jaccard_similarity` on the resulting sets; spec examples verified: identical constant sets `{Nat.add, Nat.S, Nat.O}` returns 1.0; partial overlap `{Nat.add, Nat.S}` vs `{Nat.add, Nat.mul, Nat.S, Nat.O}` returns 0.5; no overlap `{List.map, List.cons}` vs `{Nat.add, Nat.S}` returns 0.0; both trees with no constants returns 0.0

- [ ] **T5: `const_jaccard_rank` batch function** -- Score and rank a list of candidates by Jaccard similarity to a query tree
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Section 5; [pipeline.md](../specification/pipeline.md) Section 3 steps 6-7; [fusion.md](../specification/fusion.md) Section 4; [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** T2, T3
  - **Produces:** `const_jaccard_rank(query_tree: ExprTree, candidates: list[tuple[int, ExprTree]]) -> list[tuple[int, float]]` in `src/coq_search/channels/const_jaccard.py`
  - **Done when:** Extracts query constants once (not per candidate); iterates candidates computing `jaccard_similarity(q_consts, extract_consts(candidate_tree))`; returns list of `(decl_id, score)` tuples; handles empty candidate list (returns empty list); if processing a candidate raises an exception during constant extraction, that candidate is skipped, a warning is logged identifying the skipped `decl_id`, and remaining candidates are still processed (per spec Section 6 "Tree deserialization fails for a candidate"); all scores in [0.0, 1.0]

- [ ] **T6: Pre-computed symbol set optimization path** -- Support using pre-computed symbol sets from storage instead of re-extracting from trees
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Section 5; [data-structures.md](../specification/data-structures.md) Section 5 (SymbolSet)
  - **Depends on:** T2, T3, T5; storage tasks (IndexReader for `declarations.symbol_set` access)
  - **Produces:** `const_jaccard_rank_from_symbols(query_consts: set[str], candidates: list[tuple[int, list[str]]]) -> list[tuple[int, float]]` in `src/coq_search/channels/const_jaccard.py`
  - **Done when:** Accepts query constant set and candidates as `(decl_id, symbol_set_list)` tuples where `symbol_set_list` is the pre-computed `SymbolSet` from storage; converts each candidate's symbol list to a set and computes Jaccard against query set; result is identical to tree-based extraction (equivalence guaranteed by the extraction pipeline invariant that `declarations.symbol_set` equals the output of `extract_consts`); avoids tree deserialization and traversal overhead

### Phase C: Module Exports

- [ ] **T7: Module exports and docstrings** -- Set up `__all__` and public API documentation
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) (all sections)
  - **Depends on:** T2, T3, T4, T5, T6
  - **Produces:** `__all__` in `src/coq_search/channels/const_jaccard.py`
  - **Done when:** `from coq_search.channels.const_jaccard import extract_consts, const_jaccard, const_jaccard_rank` works; all public functions have type annotations on parameters and return types; all public functions have docstrings referencing the spec section they implement

### Phase D: Unit Tests

- [ ] **T8: Unit tests -- `extract_consts`** -- Test constant extraction from expression trees
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Section 3
  - **Depends on:** T2
  - **Produces:** `tests/channels/test_const_jaccard.py`
  - **Done when:** Tests cover: (1) tree with `LConst("Nat.add")` node returns `{"Nat.add"}`; (2) tree with `LInd("Nat")` node returns `{"Nat"}`; (3) tree with `LConstruct("Nat", 1)` node returns `{"Nat"}` (parent inductive FQN); (4) tree with mix of LConst, LInd, LConstruct returns union of all names; (5) tree with only structural nodes (LApp, LProd, etc.) returns empty set; (6) tree with duplicate constant references returns single entry per unique name; (7) single-node tree with `LConst` label returns singleton set; (8) single-node tree with non-constant label returns empty set; (9) deeply nested tree collects constants at all depths

- [ ] **T9: Unit tests -- `jaccard_similarity`** -- Test pure set Jaccard computation
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Section 4
  - **Depends on:** T3
  - **Produces:** Tests in `tests/channels/test_const_jaccard.py`
  - **Done when:** Tests cover: (1) identical nonempty sets return 1.0; (2) both empty sets return 0.0; (3) one empty, one nonempty returns 0.0; (4) partial overlap returns correct fraction; (5) no overlap returns 0.0; (6) subset relationship returns correct fraction; (7) symmetry: `jaccard(A, B) == jaccard(B, A)` for multiple pairs; (8) return value is always float in [0.0, 1.0]

- [ ] **T10: Unit tests -- `const_jaccard` pairwise** -- Test Jaccard similarity between two trees
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Sections 4, 6, 7
  - **Depends on:** T4
  - **Produces:** Tests in `tests/channels/test_const_jaccard.py`
  - **Done when:** Tests cover all three spec Section 7 examples: (1) identical constant sets `{Nat.add, Nat.S, Nat.O}` returns 1.0; (2) partial overlap query `{Nat.add, Nat.S}` vs candidate `{Nat.add, Nat.mul, Nat.S, Nat.O}` returns 0.5; (3) no overlap `{List.map, List.cons}` vs `{Nat.add, Nat.S}` returns 0.0; plus all spec Section 6 edge cases: (4) query tree with no constants returns 0.0; (5) candidate tree with no constants returns 0.0; (6) both trees with no constants returns 0.0

- [ ] **T11: Unit tests -- `const_jaccard_rank` batch** -- Test batch ranking function
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Sections 5, 6
  - **Depends on:** T5
  - **Produces:** Tests in `tests/channels/test_const_jaccard.py`
  - **Done when:** Tests cover: (1) three candidates ranked correctly by score; (2) empty candidate list returns empty list; (3) single candidate returns single result; (4) query tree with no constants gives all candidates score 0.0; (5) candidate with no constants receives 0.0; (6) both query and candidate with no constants gives 0.0; (7) scores match pairwise `const_jaccard` results (consistency check); (8) deserialization failure: candidate that raises during extraction is skipped, warning is logged (use `caplog` pytest fixture), remaining candidates still ranked; (9) output length equals input length in normal case (no failures)

- [ ] **T12: Unit tests -- pre-computed symbol set path** -- Test the optimization using stored symbol sets
  - **Traces to:** [channel-const-jaccard.md](../specification/channel-const-jaccard.md) Section 5
  - **Depends on:** T6
  - **Produces:** Tests in `tests/channels/test_const_jaccard.py`
  - **Done when:** Tests cover: (1) results from `const_jaccard_rank_from_symbols` match tree-based `const_jaccard_rank` for the same data; (2) empty symbol list treated as empty constant set; (3) scores computed correctly from pre-computed symbol lists

### Phase E: Integration Tests

- [ ] **T13: Integration test -- const_jaccard in fine-ranking context** -- Verify const_jaccard integrates with the fine-ranking weighted sum
  - **Traces to:** [fusion.md](../specification/fusion.md) Section 4; [pipeline.md](../specification/pipeline.md) Section 3 steps 6-7; [Story 3.1](../doc/requirements/stories/tree-search-mcp.md#31-multi-channel-fusion)
  - **Depends on:** T5; fusion module tasks
  - **Produces:** `tests/channels/test_const_jaccard_integration.py`
  - **Done when:** Test constructs synthetic ExprTrees with known constant sets; computes `const_jaccard` scores; verifies scores are in [0.0, 1.0] and can be plugged into the TED-available weighted sum formula: `structural_score = 0.15 * wl_cosine + 0.40 * ted_similarity + 0.30 * collapse_match + 0.15 * const_jaccard`; verifies the no-TED formula also accepts const_jaccard scores: `structural_score = 0.25 * wl_cosine + 0.50 * collapse_match + 0.25 * const_jaccard`

### Phase F: Performance Tests

- [ ] **T14: Performance test -- extraction and ranking throughput** -- Validate non-functional requirements
  - **Traces to:** [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target) (retrieval < 1 second)
  - **Depends on:** T5
  - **Produces:** `tests/channels/test_const_jaccard_perf.py` (marked `@pytest.mark.performance`)
  - **Done when:** `extract_consts` on a tree with 500 nodes completes in under 5ms; `const_jaccard_rank` with 500 candidates (typical post-WL-screening count) completes in under 100ms; memory usage is bounded (constant sets are transient, no persistent allocations beyond the call)

---

## Dependency Graph

```
T1 (package scaffold)
├── T2 (extract_consts)
│   ├── T4 (const_jaccard pairwise) ← also T3
│   ├── T5 (const_jaccard_rank batch) ← also T3
│   │   └── T6 (pre-computed symbol set optimization)
│   └── T8 (test extract_consts)
├── T3 (jaccard_similarity)
│   ├── T4 (const_jaccard pairwise)
│   ├── T5 (const_jaccard_rank batch)
│   └── T9 (test jaccard_similarity)
├── T7 (module exports) ← T2-T6
│
Tests:
T8  (test extract_consts)       ← T2
T9  (test jaccard_similarity)   ← T3
T10 (test const_jaccard)        ← T4
T11 (test const_jaccard_rank)   ← T5
T12 (test pre-computed path)    ← T6
T13 (integration test)          ← T5, fusion module
T14 (performance test)          ← T5
```
