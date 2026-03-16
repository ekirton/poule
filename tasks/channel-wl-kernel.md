# Implementation Plan: WL Kernel Screening Channel

**Specification:** [specification/channel-wl-kernel.md](../specification/channel-wl-kernel.md)
**Architecture:** [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
**Feedback:** [specification/feedback/channel-wl-kernel.md](../specification/feedback/channel-wl-kernel.md)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) — ExprTree, NodeLabel, WlHistogram types
- [coq-normalization.md](../specification/coq-normalization.md) — `coq_normalize`, `constr_to_tree`
- [cse-normalization.md](../specification/cse-normalization.md) — `cse_normalize`
- [storage.md](../specification/storage.md) — `wl_vectors` table schema, `declarations.node_count`
- [pipeline.md](../specification/pipeline.md) — Orchestration: WL screening is step 5 of `search_by_structure`
- [fusion.md](../specification/fusion.md) — `wl_cosine` score consumed by fine-ranking weighted sum

---

## Prerequisites

Before implementation of this component can begin:

1. **Data structures** (from data-structures.md tasks) must be implemented: `ExprTree`, `TreeNode`, `NodeLabel` hierarchy (all concrete subtypes including `LConst`, `LInd`, `LConstruct`, `LCseVar`, `LRel`, `LSort`, `LProd`, `LLambda`, `LLetIn`, `LApp`, `LCase`, `LFix`, `LCoFix`, `LProj`, `LInt`), `WlHistogram` type alias, utility functions (`recompute_depths`, `assign_node_ids`, `node_count`).
2. **Storage schema** (from storage.md tasks) must be stable: `wl_vectors` table with columns `(decl_id, h, histogram)` and `declarations` table with `node_count` column.
3. **Coq normalization** (from coq-normalization.md tasks) must be implemented for online query path: `coq_normalize()`.
4. **CSE normalization** (from cse-normalization.md tasks) must be implemented for online query path: `cse_normalize()`.

---

## Decomposition Notes

The following decisions go beyond what the specification prescribes and are surfaced here for architect review:

- **Simplified label mapping is a separate function (T1)** rather than inlined in the WL iterate logic. The spec presents `simplified_label` as a conceptual mapping; this plan extracts it as a standalone, independently testable function. The depth suffix `"_d" + str(depth)` is appended to form the complete iteration-0 label.
- **WL iterate and histogram construction are separate functions (T2, T3)** matching the spec's pseudocode structure (`wl_iterate` and `wl_histogram`). They could be merged for performance, but separating them aids testability and matches the spec's presentation.
- **Label accumulation uses a list, not a dict** (see feedback Issue 4). The spec's pseudocode uses `all_labels.update(labels)` keyed by `node_id`, which overwrites earlier iterations' labels. The prose states labels from all iterations are included. This plan accumulates labels as a flat list of values to preserve all iterations, pending spec resolution.
- **Cosine similarity (T4) is a standalone function** because it is reused: the `wl_cosine` score feeds into fine-ranking fusion (fusion.md) and must be accessible independently from the screening loop.
- **Size filter (T5) is extracted as a standalone predicate** rather than inlined in the screening loop. This aids testability and makes the dual-threshold logic independently verifiable.
- **The in-memory index loader (T7) is separated from the screening function (T6)** because loading happens once at server startup while screening happens per query. This follows the architecture doc's "loaded into memory at server startup" directive.
- **The offline indexing helper (T8) is a thin wrapper** that fixes h=3, ensuring the offline h value always matches the online h value per the architecture doc's critical constraint. The extraction pipeline (extraction.md) calls this function per declaration.
- **Normalization is out of scope.** The spec's Section 2 explicitly excludes normalization. The `wl_screen` function accepts a pre-normalized ExprTree. The pipeline orchestrator (pipeline.md) is responsible for calling normalization before passing trees to WL.

---

## Tasks

### Phase A: Core Algorithms

- [ ] **T1: Simplified label mapping** — Map each NodeLabel variant to its canonical WL tag string for iteration-0 labeling
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 3 (Initial Labeling); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** data-structures tasks (NodeLabel hierarchy)
  - **Produces:** `src/coq_search/retrieval/wl_kernel.py` (initial file with `simplified_label` function)
  - **Done when:** A function `simplified_label(label: NodeLabel) -> str` returns the correct string for all node label variants per the spec Section 3 table: `LRel` -> `"Rel"`, `LVar` -> `"Var"`, `LSort(Prop)` -> `"Prop"`, `LSort(Set)` -> `"Set"`, `LSort(TypeUniv)` -> `"Type"`, `LProd` -> `"Prod"`, `LLambda` -> `"Lam"`, `LLetIn` -> `"Let"`, `LApp` -> `"App"`, `LConst(name)` -> `"C:" + name`, `LInd(name)` -> `"I:" + name`, `LConstruct(name, i)` -> `"K:" + name + "." + str(i)`, `LCase` -> `"Case"`, `LFix(_)` -> `"Fix"`, `LCoFix(_)` -> `"CoFix"`, `LProj(name)` -> `"Proj:" + name`, `LCseVar(_)` -> `"CseVar"`; a separate function `label_0(node: TreeNode) -> str` produces the full iteration-0 label by computing `simplified_label(node.label) + "_d" + str(node.depth)`; unit tests cover every variant with representative payloads and depths (0, 3, 10)

- [ ] **T2: WL iterate** — Implement the iterative WL label refinement algorithm
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 3 (Iterative Refinement); [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** T1; data-structures tasks (ExprTree, node traversal)
  - **Produces:** `wl_iterate(tree, h)` function in `src/coq_search/retrieval/wl_kernel.py`
  - **Done when:** A function `wl_iterate(tree: ExprTree, h: int) -> list[str]` performs h iterations of WL label refinement per spec Section 3 pseudocode; iteration 0 computes `label_0(node)` for every node; iterations 1..h refine labels by computing `MD5(current_label + "(" + ",".join(sorted_child_labels) + ")")` per node; MD5 produces lowercase 32-character hex strings from UTF-8-encoded input; leaf nodes with no children produce `MD5(current_label + "()")` during refinement; returns a flat list of all label values from all iterations (iteration 0 through h), one entry per node per iteration, to ensure labels from every iteration are included in the histogram; label count equals `node_count * (h + 1)`; h=0 returns only iteration-0 labels; function is deterministic and stateless; unit tests verify: single-node tree at h=0 produces 1 label; single-node tree at h=1 produces 2 labels; spec example `nat -> nat` at h=1 produces correct label values; child labels are sorted lexicographically before concatenation

- [ ] **T3: WL histogram construction** — Build sparse histogram from WL labels
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 3 (Histogram Construction); [data-structures.md](../specification/data-structures.md) Section 4
  - **Depends on:** T2
  - **Produces:** `wl_histogram(tree, h)` function in `src/coq_search/retrieval/wl_kernel.py`
  - **Done when:** A function `wl_histogram(tree: ExprTree, h: int) -> WlHistogram` calls `wl_iterate(tree, h)`, counts occurrences of each label string, and returns a `dict[str, int]` where every value >= 1; empty tree (0 nodes) returns empty dict `{}`; a tree with n nodes produces at most `n * (h + 1)` label occurrences spread across the histogram values; histogram for spec example `nat -> nat` at h=1 has correct entry count; the function is deterministic; h >= 0 is required

- [ ] **T4: Cosine similarity on sparse histograms** — Compute cosine similarity for two sparse histogram dicts
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 6; [fusion.md](../specification/fusion.md) Section 4 (`wl_cosine` score)
  - **Depends on:** None (pure function on dicts)
  - **Produces:** `cosine_similarity(h1, h2)` function in `src/coq_search/retrieval/wl_kernel.py`
  - **Done when:** A function `cosine_similarity(h1: WlHistogram, h2: WlHistogram) -> float` computes the dot product over shared keys, divides by the product of L2 norms per spec Section 6 pseudocode; returns 0.0 if either norm is zero (handles empty histograms, no NaN); identical histograms return 1.0; disjoint histograms (no shared keys) return 0.0; result is always in [0.0, 1.0] for non-negative histograms; unit tests cover: identical dicts -> 1.0, disjoint dicts -> 0.0, empty dict vs non-empty -> 0.0, both empty -> 0.0, partially overlapping dicts -> correct float value verified by hand calculation, proportionally identical histograms (e.g., `{"a": 2, "b": 4}` vs `{"a": 1, "b": 2}`) -> 1.0

- [ ] **T5: Size filter predicate** — Implement the dual-threshold size filter
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 5 (Online Query); [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) "Size filter thresholds"
  - **Depends on:** None (pure function on integers)
  - **Produces:** `passes_size_filter(query_nc, candidate_nc)` function in `src/coq_search/retrieval/wl_kernel.py`
  - **Done when:** A function `passes_size_filter(query_nc: int, candidate_nc: int) -> bool` returns `True` when the candidate passes (should be scored) and `False` when it should be rejected; computes `ratio = max(query_nc, candidate_nc) / max(min(query_nc, candidate_nc), 1)`; for `query_nc < 600`: rejects if `ratio > 1.2`; for `query_nc >= 600`: rejects if `ratio > 1.8`; ratio exactly equal to threshold passes (strictly greater is the reject condition); `max(..., 1)` denominator prevents division by zero; unit tests verify all 5 cases from spec Section 9 size filter example (query_nc=10 against nc=5,8,12,50,200 -> only nc=12 passes); boundary tests: query_nc=599 uses 1.2 threshold, query_nc=600 uses 1.8 threshold, query_nc=0 does not raise, equal sizes always pass

### Phase B: Online Screening

- [ ] **T6: WL screening function** — Screen the library against a query, applying size filter and cosine similarity ranking
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 5 (Online Query); [pipeline.md](../specification/pipeline.md) Section 3 step 5; [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** T3, T4, T5
  - **Produces:** `wl_screen(query_tree, library_vectors, n)` function in `src/coq_search/retrieval/wl_kernel.py`
  - **Done when:** A function `wl_screen(query_tree: ExprTree, library_vectors: dict[int, tuple[WlHistogram, int]], n: int = 500) -> list[tuple[int, float]]` performs: (1) compute `wl_histogram(query_tree, h=3)`, (2) compute `node_count(query_tree)`, (3) for each `(decl_id, (hist, nc))` in library_vectors: apply `passes_size_filter(query_nc, nc)`, compute `cosine_similarity(query_hist, hist)` for passing candidates, (4) sort by score descending, (5) return top-n as `(decl_id, score)` tuples; the h=3 value is hardcoded to match the indexed h value per architecture doc critical constraint; returns empty list when: query tree has 0 nodes, library_vectors is empty, or all candidates filtered by size; scores are floats in [0.0, 1.0]; unit tests use small synthetic libraries (5-10 entries) with known histograms

- [ ] **T7: In-memory index loader** — Load precomputed WL vectors from SQLite into memory at server startup
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 7 (Deployment Notes); [storage.md](../specification/storage.md) Section 5.2 (Read Path); [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target)
  - **Depends on:** storage tasks (wl_vectors table, declarations table)
  - **Produces:** `load_wl_index(conn)` function in `src/coq_search/retrieval/wl_kernel.py`
  - **Done when:** A function `load_wl_index(conn: sqlite3.Connection) -> dict[int, tuple[WlHistogram, int]]` queries `SELECT wv.decl_id, wv.histogram, d.node_count FROM wl_vectors wv JOIN declarations d ON wv.decl_id = d.id WHERE wv.h = 3`; parses each `histogram` JSON string into `dict[str, int]`; returns `{decl_id: (histogram_dict, node_count)}`; skips rows with malformed histogram JSON and logs a warning per spec Section 8 error table; returns empty dict if no rows found; unit tests use in-memory SQLite with test data inserted; verify correct parsing, malformed JSON skipping, and empty table handling

### Phase C: Offline Indexing Support

- [ ] **T8: Per-declaration WL histogram computation for indexing** — Provide the function called by the extraction pipeline to compute a declaration's WL histogram
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 4 (Offline Indexing); [extraction.md](../specification/extraction.md) Section 5.2 step 7
  - **Depends on:** T3
  - **Produces:** `compute_wl_for_indexing(tree)` function in `src/coq_search/retrieval/wl_kernel.py`
  - **Done when:** A function `compute_wl_for_indexing(tree: ExprTree) -> WlHistogram` calls `wl_histogram(tree, h=3)` and returns the result; this is a thin wrapper that fixes h=3 as the indexing parameter, ensuring the offline h value always matches the online h value per the architecture doc critical constraint; unit tests verify it produces the same output as `wl_histogram(tree, h=3)` directly

### Phase D: Unit Tests

- [ ] **T9: Unit tests — simplified label mapping** — Test all NodeLabel variants through the simplified_label and label_0 functions
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 3 (Initial Labeling)
  - **Depends on:** T1
  - **Produces:** `tests/retrieval/test_wl_kernel.py` (initial test file)
  - **Done when:** Tests cover every row in the spec's simplified_label mapping table: `LRel(5)` -> `"Rel"`, `LVar("x")` -> `"Var"`, all three `LSort` variants (`"Prop"`, `"Set"`, `"Type"`), `LProd` -> `"Prod"`, `LLambda` -> `"Lam"`, `LLetIn` -> `"Let"`, `LApp` -> `"App"`, `LConst("Coq.Init.Nat.add")` -> `"C:Coq.Init.Nat.add"`, `LInd("Coq.Init.Datatypes.nat")` -> `"I:Coq.Init.Datatypes.nat"`, `LConstruct("Coq.Init.Datatypes.nat", 1)` -> `"K:Coq.Init.Datatypes.nat.1"`, `LCase` -> `"Case"`, `LFix(0)` -> `"Fix"`, `LCoFix(0)` -> `"CoFix"`, `LProj("proj_name")` -> `"Proj:proj_name"`, `LCseVar(0)` -> `"CseVar"`; `label_0` tests verify depth suffix: node at depth 0 produces `"<tag>_d0"`, depth 3 produces `"<tag>_d3"`, depth 10 produces `"<tag>_d10"`

- [ ] **T10: Unit tests — WL iterate and histogram** — Test WL label computation and histogram construction
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 3, Section 9 (Examples)
  - **Depends on:** T2, T3
  - **Produces:** Additional tests in `tests/retrieval/test_wl_kernel.py`
  - **Done when:** Tests cover: (1) spec example `nat -> nat` tree at h=1: verify iteration-0 labels are `"Prod_d0"`, `"I:Coq.Init.Datatypes.nat_d1"`, `"I:Coq.Init.Datatypes.nat_d1"`; verify iteration-1 labels are correct MD5 values; verify total label count is `3 * (1+1) = 6`; (2) single leaf node at h=0 produces 1 label; at h=1 produces 2 labels; (3) h=0 produces only plain-string labels with depth suffix (no MD5); (4) h=3 produces labels from 4 iterations; (5) child labels sorted lexicographically before concatenation (test with asymmetric children); (6) leaf nodes with no children produce `MD5(label + "()")` during refinement; (7) empty tree returns empty histogram; (8) determinism: same tree and h always produce the same histogram

- [ ] **T11: Unit tests — cosine similarity** — Test sparse histogram cosine similarity
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 6
  - **Depends on:** T4
  - **Produces:** Additional tests in `tests/retrieval/test_wl_kernel.py`
  - **Done when:** Tests cover: identical histograms -> 1.0; completely disjoint histograms -> 0.0; empty vs non-empty -> 0.0; both empty -> 0.0; single shared key with different counts -> correct value by hand calculation; proportionally identical histograms -> 1.0; result is always in [0.0, 1.0] range; no NaN produced for any input combination

- [ ] **T12: Unit tests — size filter** — Test dual-threshold size filter predicate
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 5, Section 9 (Size Filtering Example)
  - **Depends on:** T5
  - **Produces:** Additional tests in `tests/retrieval/test_wl_kernel.py`
  - **Done when:** Tests reproduce all 5 cases from spec Section 9 size filtering example (query_nc=10 against nc=5,8,12,50,200 -> only nc=12 passes); boundary tests: query_nc=599 uses 1.2 threshold, query_nc=600 uses 1.8 threshold; edge cases: query_nc=0 does not raise (division guarded by `max(..., 1)`), equal sizes always pass, query_nc=1 candidate_nc=1 passes; ratio exactly at threshold passes (not strictly greater)

- [ ] **T13: Unit tests — WL screening** — Test the full online screening loop
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 5; [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target)
  - **Depends on:** T6
  - **Produces:** Additional tests in `tests/retrieval/test_wl_kernel.py`
  - **Done when:** Tests cover: screening against empty library returns empty list; query with 0 nodes returns empty list; N=3 returns at most 3 results; results are sorted by score descending; size filter eliminates candidates correctly; identical tree in library scores 1.0 (or near 1.0); results contain `(decl_id, score)` tuples; all scores are in [0.0, 1.0]

- [ ] **T14: Unit tests — index loader** — Test loading WL vectors from SQLite into memory
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 7; [storage.md](../specification/storage.md) Section 5.2
  - **Depends on:** T7
  - **Produces:** Additional tests in `tests/retrieval/test_wl_kernel.py`
  - **Done when:** Tests use in-memory SQLite with schema from storage.md; inserting 3 valid rows and loading produces dict with 3 entries; histogram JSON is correctly parsed to `dict[str, int]`; node_count is correctly joined from declarations table; row with malformed JSON is skipped with warning logged; row with h != 3 is excluded; empty table returns empty dict

### Phase E: Integration Tests

- [ ] **T15: Integration test — end-to-end WL screening** — Test the complete flow from ExprTree to ranked candidate list
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Sections 3-6; [pipeline.md](../specification/pipeline.md) Section 3 steps 4-5; [Story 2.4](../doc/requirements/stories/tree-search-mcp.md#24-search-by-structure)
  - **Depends on:** T6, T7, T8, data-structures tasks, storage tasks
  - **Produces:** `tests/retrieval/test_wl_kernel_integration.py`
  - **Done when:** Test constructs 5-10 ExprTree instances of varying structure and size; computes WL histograms for each via `compute_wl_for_indexing`; inserts into in-memory SQLite `wl_vectors` and `declarations` tables; loads via `load_wl_index`; screens with a query tree; verifies: (1) most structurally similar tree ranks highest, (2) identical tree to query gets score near 1.0, (3) completely different tree gets low score, (4) size-filtered trees are absent from results, (5) result count respects N parameter; spec example `nat -> nat` tree included as one test case

- [ ] **T16: Integration test — error scenarios** — Test all error conditions from spec Section 8
  - **Traces to:** [channel-wl-kernel.md](../specification/channel-wl-kernel.md) Section 8 (Error Specification)
  - **Depends on:** T6, T7
  - **Produces:** Additional tests in `tests/retrieval/test_wl_kernel_integration.py`
  - **Done when:** Tests verify all 6 error conditions from spec Section 8: (1) query tree with 0 nodes returns empty candidate list, (2) query histogram empty (all labels hashed to nothing) returns empty list with cosine 0.0 for all, (3) library with 0 declarations returns empty candidate list, (4) size filter eliminates all candidates returns empty candidate list, (5) malformed histogram JSON in database is skipped with warning logged, (6) cosine similarity when both norms are zero returns 0.0 (handled by norm==0 check, no NaN)

### Phase F: Performance Tests

- [ ] **T17: Performance test — screening throughput** — Validate sub-second screening on realistic library sizes
  - **Traces to:** [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) "Sub-second on 100K items"; [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target)
  - **Depends on:** T6
  - **Produces:** `tests/retrieval/test_wl_kernel_performance.py`
  - **Done when:** Test (marked `@pytest.mark.performance`, skipped in CI by default) generates 10K-50K synthetic histograms of realistic size (50-500 entries each); measures wall-clock time for a single `wl_screen` call; screening completes in < 1 second for 50K histograms; memory usage for loaded histograms stays within expected bounds (~100MB for 100K per architecture doc)

### Phase G: Package Structure

- [ ] **T18: Retrieval package scaffolding** — Create the retrieval subpackage if it does not already exist
  - **Traces to:** Project setup
  - **Depends on:** None (implement first, before all other tasks)
  - **Produces:** `src/coq_search/retrieval/__init__.py`, `tests/retrieval/__init__.py`
  - **Done when:** `from coq_search.retrieval.wl_kernel import wl_histogram, wl_screen, cosine_similarity` works; `pytest` discovers tests under `tests/retrieval/`; the `__init__.py` exports the public API: `wl_histogram`, `wl_screen`, `cosine_similarity`, `load_wl_index`, `compute_wl_for_indexing`

---

## Dependency Graph

```
data-structures tasks (prerequisites: ExprTree, NodeLabel, WlHistogram, node_count)
│
├── T18 (package scaffold) — first, before all others
│
├── T1 (simplified_label, label_0)
│   └── T2 (wl_iterate)
│       └── T3 (wl_histogram)
│           ├── T6 (wl_screen) ← also depends on T4, T5
│           └── T8 (compute_wl_for_indexing)
│
├── T4 (cosine_similarity) — no internal deps
│   └── T6 (wl_screen)
│
├── T5 (passes_size_filter) — no internal deps
│   └── T6 (wl_screen)
│
├── T7 (load_wl_index) ← depends on storage tasks
│
├── T9-T14 (unit tests) — each depends on the task it tests
│
├── T15-T16 (integration tests) ← depend on T6, T7, T8
│
└── T17 (performance test) ← depends on T6
```
