# Implementation Plan: TED Fine Ranking

**Specification:** [specification/channel-ted.md](../specification/channel-ted.md)
**Architecture:** [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
**Feedback:** [specification/feedback/channel-ted.md](../specification/feedback/channel-ted.md)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) — ExprTree, NodeLabel, ScoredResult types
- [channel-wl-kernel.md](../specification/channel-wl-kernel.md) — WL screening produces the input candidate set
- [fusion.md](../specification/fusion.md) — Fine-ranking weighted sum consumes TED similarity scores; collapse-match reuses `same_category`
- [pipeline.md](../specification/pipeline.md) — Pipeline orchestration invokes `ted_rerank`

---

## Prerequisites

Before implementation of this component can begin:

1. **Data structures** (from data-structures.md tasks) must be implemented: `ExprTree`, `TreeNode`, `NodeLabel` hierarchy (all concrete subtypes), utility function `node_count`.
2. **Storage** (from storage.md tasks) must be implemented: `declarations` table with `constr_tree` BLOB column for candidate tree deserialization.
3. **WL kernel screening** (from channel-wl-kernel.md tasks) must be implemented: `wl_screen` produces the candidate set that TED refines.
4. **Tree serialization/deserialization** must be implemented: the pipeline orchestrator deserializes candidate trees from `declarations.constr_tree` BLOBs before passing them to `ted_rerank` (per retrieval-pipeline.md).

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **The cost model is implemented as a standalone module (T2)** separate from the Zhang-Shasha algorithm (T4). This allows the cost model to be unit-tested independently and the `same_category` function to be reused by collapse-match (fusion.md Section 4).
- **Category membership is encoded as a lookup table (T1)** rather than an inheritance hierarchy. The spec defines 7 categories with enumerated members; a dict-based lookup is simpler and more directly traceable to the spec table.
- **Zhang-Shasha preprocessing is separated from the DP core (T3 vs T4).** The spec says "Zhang-Shasha algorithm" without detailing the preprocessing data structures. The standard algorithm requires postorder enumeration, leftmost-leaf arrays, and keyroot lists. These are packaged into a `ZsTree` helper for clean separation.
- **No third-party Zhang-Shasha library.** A from-scratch implementation is chosen over the `zss` PyPI package to: (a) integrate the custom cost model directly, (b) avoid an external dependency for a bounded algorithm (50-node cap), (c) maintain full testability.
- **`LInt` handling**: The spec does not assign a cost model category for `LInt` nodes (see feedback Issue 3). This plan provisionally assigns `LInt` to its own "Primitives" category with insert/delete cost 0.2 (analogous to `LSort` as a lightweight leaf). This decision is flagged in feedback for architect resolution.
- **Return type of `ted_rerank`**: The spec defines the return as `list[tuple[int, float]]` — `(declaration_id, ted_similarity_score)` tuples. The pipeline orchestrator wraps these into `ScoredResult` if needed for fusion.

---

## Tasks

### Phase A: Cost Model

- [ ] **T1: Node label category mapping** — Define the category groupings for TED rename cost computation
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 4 (Category definition); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** data-structures tasks (NodeLabel types)
  - **Produces:** `src/coq_search/retrieval/ted/categories.py`
  - **Done when:** A `node_category(label: NodeLabel) -> str` function maps each NodeLabel variant to its category name per the spec's 7 categories: `LConst`, `LInd`, `LConstruct` -> `"leaf_constant"`; `LRel`, `LVar`, `LCseVar` -> `"leaf_variable"`; `LSort` -> `"sort"`; `LProd`, `LLambda`, `LLetIn` -> `"binder"`; `LApp` -> `"application"`; `LCase`, `LProj` -> `"elimination"`; `LFix`, `LCoFix` -> `"recursion"`; `LInt` -> `"primitive"` (provisional — see feedback Issue 3); a `same_category(label1: NodeLabel, label2: NodeLabel) -> bool` function returns `True` when both labels map to the same category; unit tests verify every NodeLabel variant is assigned a category; unit tests verify same-category and cross-category pairs from the spec examples

- [ ] **T2: TED cost model** — Implement the edit operation cost functions per the spec's cost table
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 4 (Cost Model table); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** T1
  - **Produces:** `src/coq_search/retrieval/ted/cost_model.py`
  - **Done when:** Three cost functions are implemented: `insert_cost(label: NodeLabel) -> float` returns 0.2 for leaf variable nodes (`LRel`, `LVar`, `LCseVar`, `LSort`) and `LInt` (provisional), returns 1.0 for leaf constant nodes (`LConst`, `LInd`, `LConstruct`), returns 1.0 for all interior nodes (`LApp`, `LProd`, `LLambda`, `LLetIn`, `LCase`, `LFix`, `LCoFix`, `LProj`); `delete_cost(label: NodeLabel) -> float` returns the same values as `insert_cost` (symmetric per spec); `rename_cost(label1: NodeLabel, label2: NodeLabel) -> float` returns 0.0 when `same_category(label1, label2)` is `True`, returns 0.4 when `False`; unit tests verify all spec table rows

### Phase B: Zhang-Shasha Algorithm

- [ ] **T3: Zhang-Shasha tree preprocessing** — Implement the preprocessing step that produces postorder enumeration, leftmost-leaf indices, and keyroot lists
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 3 (keyroots, leftmost-leaf decomposition); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** data-structures tasks (ExprTree, TreeNode)
  - **Produces:** `src/coq_search/retrieval/ted/zhang_shasha.py` (preprocessing portion)
  - **Done when:** A `ZsTree` dataclass (or named tuple) is defined with fields: `labels: list[NodeLabel]` (indexed by postorder position, 0-based), `children_indices: list[list[int]]` (children in postorder indices), `leftmost_leaf: list[int]` (`leftmost_leaf[i]` is the postorder index of the leftmost leaf descendant of node `i`), `keyroots: list[int]` (sorted list of keyroot postorder indices — a node is a keyroot if its leftmost-leaf index differs from its parent's, or if it is the root), `size: int` (total node count); a `prepare_tree(tree: ExprTree) -> ZsTree` factory function performs the preprocessing; unit tests verify: single leaf node produces `size=1`, `leftmost_leaf=[0]`, `keyroots=[0]`; 3-node tree `Prod(Ind, Ind)` produces correct postorder, leftmost-leaf, and keyroot arrays

- [ ] **T4: Zhang-Shasha edit distance core** — Implement the dynamic programming algorithm for minimum-cost tree edit distance
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 3 (Algorithm: Zhang-Shasha); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** T2, T3
  - **Produces:** `src/coq_search/retrieval/ted/zhang_shasha.py` (DP core)
  - **Done when:** `tree_edit_distance(tree1: ExprTree, tree2: ExprTree, cost_model) -> float` computes the minimum-cost edit distance between two ordered labeled trees using the Zhang-Shasha algorithm; the implementation iterates over keyroot pairs, computing forest distances using the standard three-way min recurrence (delete from tree1 + `delete_cost`, insert from tree2 + `insert_cost`, match nodes + `rename_cost`); handles edge cases: empty trees (distance = sum of insert costs for all nodes of the nonempty tree), single-node trees, trees of different sizes and topologies; unit tests verify: identical trees -> distance 0; spec example `Prod(Ind("nat"), Ind("nat"))` vs `Prod(Ind("bool"), Ind("nat"))` -> distance 0.0 (same-category rename); spec example `Prod(Ind, Ind)` vs `App(Ind, Ind)` -> distance 0.4 (cross-category rename); symmetry: `distance(A, B) == distance(B, A)`

### Phase C: Similarity Score

- [ ] **T5: TED similarity score** — Implement the normalized similarity score with clamping and edge case handling
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 5 (Similarity Score), Section 8 (Error Specification); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** T4, data-structures tasks (`node_count`)
  - **Produces:** `src/coq_search/retrieval/ted/similarity.py`
  - **Done when:** `ted_similarity(tree1: ExprTree, tree2: ExprTree) -> float` computes `1.0 - edit_distance(tree1, tree2) / max(node_count(tree1), node_count(tree2))`, clamped to [0, 1]; division-by-zero guard: when both trees have 0 nodes, returns 1.0 (pre-check before formula per spec Section 8); when edit distance exceeds `max(node_count)`, clamps to 0.0 and logs warning per spec Section 8; negative pre-clamp values from high edit distances are clamped to 0.0 without warning per retrieval-pipeline.md; unit tests verify all four spec Section 9 examples: identical trees -> 1.0, same-category rename -> 1.0 (distance 0.0), cross-category rename `Prod` vs `App` -> approx 0.867, both empty -> 1.0

### Phase D: Reranking Orchestrator

- [ ] **T6: TED reranking function** — Implement the `ted_rerank` orchestrator that applies size constraints and scores eligible candidates
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 6 (Application Constraints), Section 7 (Integration with WL Screening); [pipeline.md](../specification/pipeline.md) Section 3; [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure), [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target)
  - **Depends on:** T5
  - **Produces:** `src/coq_search/retrieval/ted/rerank.py`
  - **Done when:** `ted_rerank(query_tree: ExprTree, wl_candidates: list[tuple[int, ExprTree]], max_nodes: int = 50) -> list[tuple[int, float]]` implements the spec's pseudocode from Section 7: (1) if `node_count(query_tree) > max_nodes`, return empty list; (2) filter candidates to those with `node_count(tree) <= max_nodes`; (3) for each eligible candidate, compute `ted_similarity(query_tree, candidate_tree)`; (4) return list of `(decl_id, similarity_score)` pairs; candidates whose tree deserialization failed are skipped with logged warning per spec Section 8; unit tests verify: query with 60 nodes returns `[]` (spec Section 9 size constraint skip example); candidates exceeding max_nodes filtered out; eligible candidates receive correct similarity scores; empty candidate list returns `[]`

### Phase E: Package Structure

- [ ] **T7: TED package scaffolding** — Create the TED subpackage and wire up public exports
  - **Traces to:** Project structure
  - **Depends on:** None (implement first, before all other tasks)
  - **Produces:** `src/coq_search/retrieval/ted/__init__.py`, `tests/retrieval/ted/__init__.py`
  - **Done when:** `from coq_search.retrieval.ted import ted_rerank, ted_similarity` works; `from coq_search.retrieval.ted.categories import same_category` works (needed by collapse-match in fusion.md); `pytest` discovers tests under `tests/retrieval/ted/`

### Phase F: Unit Tests

- [ ] **T8: Unit tests — category mapping** — Test all NodeLabel variants map to correct categories
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 4 (Category definition)
  - **Depends on:** T1
  - **Produces:** `tests/retrieval/ted/test_categories.py`
  - **Done when:** Tests cover every NodeLabel variant mapping to its expected category; tests verify `same_category` returns `True` for all within-category pairs from the spec: (`LConst`, `LInd`), (`LConst`, `LConstruct`), (`LInd`, `LConstruct`), (`LRel`, `LCseVar`), (`LRel`, `LVar`), (`LProd`, `LLambda`), (`LProd`, `LLetIn`), (`LLambda`, `LLetIn`), (`LCase`, `LProj`), (`LFix`, `LCoFix`); tests verify `same_category` returns `False` for cross-category pairs: (`LConst`, `LRel`), (`LApp`, `LProd`), (`LSort`, `LConst`), (`LCase`, `LFix`), (`LApp`, `LCase`); tests verify `LApp` is its own category (not same as any other non-`LApp` label); tests verify `LSort` is its own category

- [ ] **T9: Unit tests — cost model** — Test all cost function values against spec cost table
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 4 (Cost Model table)
  - **Depends on:** T2
  - **Produces:** `tests/retrieval/ted/test_cost_model.py`
  - **Done when:** Tests verify insert/delete costs: `LRel` -> 0.2, `LVar` -> 0.2, `LCseVar` -> 0.2, `LSort` -> 0.2, `LConst` -> 1.0, `LInd` -> 1.0, `LConstruct` -> 1.0, `LApp` -> 1.0, `LProd` -> 1.0, `LLambda` -> 1.0, `LLetIn` -> 1.0, `LCase` -> 1.0, `LFix` -> 1.0, `LCoFix` -> 1.0, `LProj` -> 1.0; tests verify rename costs: `LConst("a")` vs `LConst("b")` -> 0.0, `LConst("a")` vs `LInd("b")` -> 0.0, `LConst("a")` vs `LProd` -> 0.4, `LProd` vs `LLambda` -> 0.0, `LApp` vs `LProd` -> 0.4, `LCase` vs `LProj` -> 0.0, `LFix` vs `LCoFix` -> 0.0, `LCase` vs `LFix` -> 0.4; tests verify symmetry: `insert_cost(l) == delete_cost(l)` for all variants; `rename_cost(a, b) == rename_cost(b, a)` for multiple pairs

- [ ] **T10: Unit tests — Zhang-Shasha algorithm** — Test edit distance computation on varied tree structures
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 3, Section 9 (Examples)
  - **Depends on:** T4
  - **Produces:** `tests/retrieval/ted/test_zhang_shasha.py`
  - **Done when:** Tests cover: (1) identical trees -> distance 0; (2) single-node trees with same-category labels -> 0.0, cross-category labels -> 0.4; (3) empty tree vs nonempty tree -> sum of insert costs for all nodes of the nonempty tree; (4) spec example: `Prod(Ind("nat"), Ind("nat"))` vs `Prod(Ind("bool"), Ind("nat"))` -> 0.0 (same-category rename of `Ind("nat")` to `Ind("bool")`); (5) spec example: `Prod(Ind("nat"), Ind("nat"))` vs `App(Ind("nat"), Ind("nat"))` -> 0.4 (cross-category rename `Prod` -> `App`); (6) tree with one added leaf node -> distance equals insert cost of that leaf (0.2 for variable-type leaf, 1.0 for constant-type leaf); (7) asymmetric trees (different depths and branching factors); (8) symmetry: `distance(A, B) == distance(B, A)` for all test pairs

- [ ] **T11: Unit tests — similarity score** — Test normalized similarity with clamping and edge cases
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 5, Section 8, Section 9
  - **Depends on:** T5
  - **Produces:** `tests/retrieval/ted/test_similarity.py`
  - **Done when:** Tests verify: (1) identical 3-node trees -> 1.0; (2) both empty trees -> 1.0; (3) spec example: identical `Prod(Ind("nat"), Ind("nat"))` -> 1.0; (4) spec example: same-category rename `Ind("nat")` -> `Ind("bool")` -> 1.0 (distance 0.0 / 3 nodes); (5) spec example: cross-category rename `Prod` vs `App` on 3-node trees -> approx 0.867 (1.0 - 0.4/3); (6) very different trees -> value clamped to >= 0.0; (7) result always in [0, 1] range; (8) edit distance exceeding max node count produces 0.0 with logged warning (verify via caplog or mock); (9) self-similarity: `ted_similarity(T, T) == 1.0` for multiple tree shapes

- [ ] **T12: Unit tests — ted_rerank** — Test the reranking orchestrator with size constraints
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 6, Section 7, Section 9 (size constraint skip example)
  - **Depends on:** T6
  - **Produces:** `tests/retrieval/ted/test_rerank.py`
  - **Done when:** Tests verify: (1) query with 60 nodes (> max_nodes=50) returns empty list (spec Section 9 example); (2) query with 30 nodes, candidates with node counts [20, 40, 60, 80] -> only candidates with 20 and 40 nodes scored; (3) all candidates exceed max_nodes -> empty list; (4) empty candidate list -> empty list; (5) query with 1 node, single eligible candidate -> returns `[(decl_id, similarity)]`; (6) custom max_nodes parameter respected (e.g., max_nodes=30 excludes 31+ node candidates); (7) result list contains correct `(decl_id, similarity_score)` tuples for eligible candidates; (8) input candidates list is not mutated

### Phase G: Integration Tests

- [ ] **T13: Integration test — end-to-end TED scoring** — Test the full TED pipeline from ExprTree inputs through similarity scoring
  - **Traces to:** [channel-ted.md](../specification/channel-ted.md) Section 9 (all four examples); [pipeline.md](../specification/pipeline.md) Section 3
  - **Depends on:** T6
  - **Produces:** `tests/retrieval/ted/test_ted_integration.py`
  - **Done when:** Integration test constructs ExprTree instances matching all four spec Section 9 examples and verifies exact outcomes: (1) identical `Prod(Ind("nat"), Ind("nat"))` trees -> similarity 1.0; (2) same-category rename `Ind("nat")` to `Ind("bool")` -> similarity 1.0; (3) structural difference `Prod` vs `App` -> similarity approx 0.867; (4) query with 60 nodes -> `ted_rerank` returns empty list; test verifies `ted_rerank` correctly orchestrates the full flow: size check -> filter -> similarity computation -> result list; test verifies output format is compatible with fine-ranking weighted sum in fusion.md (returns `(decl_id, float)` tuples where float is in [0, 1])

### Phase H: Performance Validation

- [ ] **T14: Performance test — TED computation latency** — Validate that TED stays within latency budget for the expected candidate set size
  - **Traces to:** [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target) (< 1 second end-to-end); [channel-ted.md](../specification/channel-ted.md) Section 6 (node_count <= 50 constraint)
  - **Depends on:** T6
  - **Produces:** `tests/retrieval/ted/test_performance.py`
  - **Done when:** Test (marked `@pytest.mark.performance`, skipped in CI by default) measures wall-clock time for computing TED similarity on 200 candidate pairs (worst case from retrieval-pipeline.md — top-200 WL candidates passing the size filter) with trees of up to 50 nodes each; total TED computation completes within 500ms (half the 1-second end-to-end budget, leaving room for other channels); test generates random trees of varying sizes (10-50 nodes) to simulate realistic candidate distributions; memory usage stays bounded (no accumulation across iterations)

---

## Dependency Graph

```
data-structures tasks (NodeLabel, ExprTree, node_count) [prerequisites]
│
├── T7 (package scaffolding) — implement first
│
├── T1 (category mapping)
│   └── T2 (cost model)
│       └── T3 (ZS preprocessing)
│           └── T4 (ZS edit distance)
│               └── T5 (similarity score)
│                   └── T6 (ted_rerank)
│
└── Tests (proceed as soon as their implementation task is done)
    ├── T8  (test categories)          depends on T1
    ├── T9  (test cost model)          depends on T2
    ├── T10 (test Zhang-Shasha)        depends on T4
    ├── T11 (test similarity)          depends on T5
    ├── T12 (test ted_rerank)          depends on T6
    ├── T13 (integration test)         depends on T6
    └── T14 (performance test)         depends on T6
```
