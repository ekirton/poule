# Implementation Plan: Channel MePo (Symbol-Relevance Retrieval)

**Specification:** [specification/channel-mepo.md](../specification/channel-mepo.md)
**Architecture:** [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) (MePo Symbol Overlap section)
**Feedback:** [specification/feedback/channel-mepo.md](../specification/feedback/channel-mepo.md)

**Spec dependencies:**
- [data-structures.md](../specification/data-structures.md) — ExprTree, NodeLabel, SymbolSet, ScoredResult types
- [storage.md](../specification/storage.md) — Schema DDL, `symbol_freq` and `declarations.symbol_set` tables
- [pipeline.md](../specification/pipeline.md) — `search_by_type` (Section 4) and `search_by_symbols` (Section 5) invoke MePo
- [fusion.md](../specification/fusion.md) — RRF fusion consumes MePo's ranked list

---

## Prerequisites

Before implementation of this component can begin:

1. **Package scaffold** — `src/coq_search/` package with `__init__.py` (tasks/data-structures.md).
2. **Core data structures** — `ScoredResult`, `ExprTree`, `TreeNode`, `NodeLabel` hierarchy (tasks/data-structures.md).
3. **SQLite schema** — `declarations` table with `symbol_set` JSON column and `symbol_freq` table (tasks/storage.md).
4. **`extract_symbols` function** — From the extraction module; extracts `LConst`, `LInd`, `LConstruct` names from an `ExprTree` (tasks/extraction.md). MePo uses this at query time in the `search_by_type` pipeline. For `search_by_symbols`, the caller provides symbols directly.

---

## Tasks

### Phase A: Module Setup

- [ ] **T1: Create the MePo channel module** — Create `channel_mepo.py` inside the `coq_search` package with module docstring and initial imports.
  - **Traces to:** channel-mepo.md (entire spec); pipeline.md Section 5 (`search_by_symbols` invokes MePo)
  - **Depends on:** tasks/data-structures.md (package scaffold)
  - **Produces:** `src/coq_search/channel_mepo.py`
  - **Done when:** `from coq_search.channel_mepo import mepo_select` is importable (even if the function body is a stub)

### Phase B: Core Algorithm Functions

- [ ] **T2: Symbol weight function** — Implement `symbol_weight()`: the inverse-frequency weighting formula `1.0 + 2.0 / log2(f + 1)` where `f` is the symbol's frequency. Guard against `f == 0` by returning 3.0 (spec Section 8, row 5). For symbols not found in the freq table, treat frequency as 1 per spec Section 8 row 2 and architecture doc (missing symbol handling); log a warning.
  - **Traces to:** channel-mepo.md Section 3 (formula); Section 8 (error spec: `log2(f+1)` guard, missing symbol)
  - **Depends on:** T1
  - **Produces:** `symbol_weight(symbol: str, freq_table: dict[str, int]) -> float` in `src/coq_search/channel_mepo.py`
  - **Done when:** `symbol_weight("x", {"x": 1})` returns 3.0; `symbol_weight("x", {"x": 100})` returns approximately 1.30; `symbol_weight("x", {"x": 10000})` returns approximately 1.15; `symbol_weight("missing", {})` returns 3.0 and logs a warning; `symbol_weight("x", {"x": 0})` returns 3.0 (guard for f=0)

- [ ] **T3: Denominator precomputation** — Precompute the total weighted symbol mass for every declaration: `sum(symbol_weight(s, freq_table) for s in symbols(d))`. This is constant per declaration across all rounds. Cache individual symbol weights to avoid redundant `log2` calls.
  - **Traces to:** channel-mepo.md Section 4 (relevance formula — denominator is fixed per declaration)
  - **Depends on:** T2
  - **Produces:** `precompute_denominators(decl_symbols: dict[int, list[str]], freq_table: dict[str, int]) -> dict[int, float]` in `src/coq_search/channel_mepo.py`
  - **Done when:** For a declaration with symbols `["A", "B"]` at freq=100 each, the returned denominator equals `2 * symbol_weight("A", {"A": 100})`; declarations with empty symbol sets map to 0.0

- [ ] **T4: Relevance score function** — Compute weighted overlap relevance. Numerator = sum of weights for symbols in `symbols(d) ∩ S`. Denominator = precomputed total weight. Return 0.0 if denominator is 0.0 (spec Section 4).
  - **Traces to:** channel-mepo.md Section 4 (formula, zero-denominator guard)
  - **Depends on:** T2, T3
  - **Produces:** `relevance(decl_symbol_set: list[str], working_symbols: set[str], freq_table: dict[str, int], denominator: float) -> float` in `src/coq_search/channel_mepo.py`
  - **Done when:** Spec Example 1 D1 (symbols `{Nat.add, Nat.S, Nat.O}`, S=`{Nat.add, Nat.S}`, all freq=100) returns approximately 0.67; D2 (symbols `{Nat.mul, Nat.S}`, S=`{Nat.add, Nat.S}`) returns 0.50; D3 (symbols `{List.map, List.cons}`, S=`{Nat.add, Nat.S}`) returns 0.0; empty symbol set returns 0.0; return value always in [0.0, 1.0]

- [ ] **T5: Inverted index builder** — Build an in-memory inverted index mapping each symbol to the set of declaration IDs whose symbol set contains it. Used for efficient candidate filtering per spec Section 6 item 3.
  - **Traces to:** channel-mepo.md Section 6 (offline precomputation, inverted index)
  - **Depends on:** T1
  - **Produces:** `build_inverted_index(decl_symbols: dict[int, list[str]]) -> dict[str, set[int]]` in `src/coq_search/channel_mepo.py`
  - **Done when:** For input `{1: ["A", "B"], 2: ["B", "C"]}`, output is `{"A": {1}, "B": {1, 2}, "C": {2}}`; empty input returns empty dict; declarations with empty symbol sets produce no index entries

- [ ] **T6: Iterative selection algorithm** — Implement the core `mepo_select()` loop per spec Section 5. Critical behavioral requirements:
  1. Initialize working set `S` from `query_symbols`. If `query_symbols` is empty, return empty list immediately (spec Section 8 row 1).
  2. Loop for up to `max_rounds` rounds. Terminate early if `newly_selected` is empty in a round (spec Section 5 pseudocode: `if len(newly_selected) == 0: break`).
  3. Each round: compute `threshold = p * (1/c) ^ round_i`.
  4. Use inverted index to find candidates overlapping with `S`, intersected with `remaining`.
  5. Score each candidate. Select those with `relevance >= threshold`.
  6. Batch expansion: update `S` only after all candidates in the round are evaluated and selected (spec Section 5 pseudocode structure; architecture doc batch expansion note).
  7. After all rounds, sort by score descending.
  8. Return `list[ScoredResult]` with `channel="mepo"`, 1-based ranks.
  - **Traces to:** channel-mepo.md Section 5 (algorithm, parameters, pseudocode); Section 8 (empty query symbols); retrieval-pipeline.md (batch expansion note)
  - **Depends on:** T2, T3, T4, T5; tasks/data-structures.md (ScoredResult)
  - **Produces:** `mepo_select(query_symbols: list[str], decl_symbols: dict[int, list[str]], freq_table: dict[str, int], inverted_index: dict[str, set[int]], denominators: dict[int, float], p: float = 0.6, c: float = 2.4, max_rounds: int = 5) -> list[ScoredResult]` in `src/coq_search/channel_mepo.py`
  - **Done when:** Spec Example 1 reproduced: D1 selected round 0, D2 selected round 1 after S expands, D3 never selected; Spec Example 2 (rare symbol boost) reproduced: D1 with `{MyProject.custom_lemma, Nat.add}` at freqs 2 and 5000 has relevance ~0.66 and passes threshold; empty query returns empty list; deterministic output given identical inputs

### Phase C: Data Loading and Public API

- [ ] **T7: MepoIndex class** — Encapsulates all MePo-related precomputed data loaded from SQLite at startup. The class:
  1. Reads `declarations` table to build `decl_symbols: dict[int, list[str]]` by parsing each row's `symbol_set` JSON column.
  2. Reads `symbol_freq` table to build `freq_table: dict[str, int]`.
  3. Calls `build_inverted_index()` to construct the inverted index.
  4. Calls `precompute_denominators()` to cache denominators.
  5. Exposes `query(query_symbols: list[str], p=0.6, c=2.4, max_rounds=5) -> list[ScoredResult]` that delegates to `mepo_select()`.
  6. Does not hold the database connection open after loading.
  - **Traces to:** channel-mepo.md Section 6 (offline precomputation — inverted index, symbol_freq); Section 7 (online query entry point); storage.md Section 5.2 (read path — build in-memory inverted index and symbol_freq from SQLite)
  - **Depends on:** T3, T5, T6; tasks/storage.md (schema)
  - **Produces:** `MepoIndex` class in `src/coq_search/channel_mepo.py`
  - **Done when:** `MepoIndex(db_path)` loads data from a valid SQLite database; `index.query(["Nat.add"])` returns `list[ScoredResult]`; works with zero declarations (returns empty results); database connection released after construction

- [ ] **T8: Module exports** — Add `__all__` to `channel_mepo.py` listing public API: `MepoIndex`, `mepo_select`, `symbol_weight`, `relevance`, `build_inverted_index`, `precompute_denominators`. Add `MepoIndex` to `coq_search/__init__.py` re-exports.
  - **Traces to:** pipeline.md Sections 4, 5 (pipeline invokes MePo); fusion.md (channel contributions)
  - **Depends on:** T1-T7
  - **Produces:** `__all__` in `src/coq_search/channel_mepo.py`; re-export in `src/coq_search/__init__.py`
  - **Done when:** `from coq_search.channel_mepo import MepoIndex, mepo_select` works; `from coq_search import MepoIndex` works

### Phase D: Unit Tests

- [ ] **T9: Unit tests -- symbol weight function** — Verify the weight formula against spec values and edge cases:
  1. freq=1 → weight 3.0 (spec: "A symbol appearing in 1 declaration has weight ~3.0").
  2. freq=100 → weight approximately 1.30.
  3. freq=10000 → weight approximately 1.15 (spec: "a symbol appearing in 10,000 declarations has weight ~1.15").
  4. freq=0 → weight 3.0 (spec Section 8 row 5: guard against `log2(1)=0`).
  5. Missing symbol (not in freq_table) → weight 3.0, warning logged (spec Section 8 row 2).
  6. Return value always > 1.0 for any valid frequency.
  - **Traces to:** channel-mepo.md Section 3 (formula, reference values); Section 8 (error spec rows 2, 5)
  - **Depends on:** T2
  - **Produces:** `test/test_channel_mepo.py` (symbol_weight tests)
  - **Done when:** All 6 cases pass with tolerance +/-0.01

- [ ] **T10: Unit tests -- relevance scoring** — Verify against spec examples:
  1. Spec Example 1 D1: symbols `{Nat.add, Nat.S, Nat.O}`, S=`{Nat.add, Nat.S}`, all freq=100. Relevance approximately 2/3 = 0.67.
  2. Spec Example 1 D2: symbols `{Nat.mul, Nat.S}`, S=`{Nat.add, Nat.S}`. Relevance = 0.50.
  3. Spec Example 1 D3: symbols `{List.map, List.cons}`, S=`{Nat.add, Nat.S}`. Relevance = 0.0.
  4. Spec Example 2 (rare symbol boost): symbols `{MyProject.custom_lemma, Nat.add}`, freq 2 and 5000. S=`{MyProject.custom_lemma}`. Relevance approximately 0.66.
  5. Empty symbol set → 0.0 (spec Section 4: denominator is 0).
  6. Full overlap (all symbols in S) → 1.0.
  7. Empty working set S → 0.0.
  - **Traces to:** channel-mepo.md Section 4 (formula); Section 9 Examples 1, 2
  - **Depends on:** T4
  - **Produces:** Tests in `test/test_channel_mepo.py`
  - **Done when:** All 7 cases pass within +/-0.01 tolerance

- [ ] **T11: Unit tests -- inverted index** — Verify:
  1. Basic: `{1: ["A", "B"], 2: ["B", "C"]}` produces `{"A": {1}, "B": {1, 2}, "C": {2}}`.
  2. Empty input produces empty dict.
  3. Declaration with empty symbol set produces no entries.
  4. Single declaration with N symbols: all N symbols map to that decl_id.
  5. Many declarations sharing one symbol: that symbol's set contains all of them.
  - **Traces to:** channel-mepo.md Section 6 (inverted index)
  - **Depends on:** T5
  - **Produces:** Tests in `test/test_channel_mepo.py`
  - **Done when:** All 5 cases pass

- [ ] **T12: Unit tests -- iterative selection (spec examples)** — Reproduce both spec Section 9 examples:
  1. **Example 1 (single-round + expansion):** Query `{Nat.add, Nat.S}`, D1 with `{Nat.add, Nat.S, Nat.O}` (all freq=100), D2 with `{Nat.mul, Nat.S}` (all freq=100), D3 with `{List.map, List.cons}` (all freq=50). Round 0 (threshold=0.6): D1 selected (relevance ~0.67), D2 not selected (0.50 < 0.6), D3 not selected (0.0). S expands to `{Nat.add, Nat.S, Nat.O}`. Round 1 (threshold ~0.25): D2 selected (0.50 >= 0.25). D3 never selected.
  2. **Example 2 (rare symbol boost):** Query `{MyProject.custom_lemma}` (freq=2). D1 has `{MyProject.custom_lemma, Nat.add}` (Nat.add freq=5000). Relevance of D1 = 2.26 / (2.26 + 1.16) ~= 0.66 >= 0.6, so D1 selected round 0.
  3. **Empty query symbols:** Returns empty list without entering selection loop (spec Section 8 row 1).
  4. **All declarations below threshold every round:** Returns empty list (spec Section 8 row 4).
  - **Traces to:** channel-mepo.md Section 5 (algorithm); Section 8 (error spec); Section 9 (examples 1, 2)
  - **Depends on:** T6
  - **Produces:** Tests in `test/test_channel_mepo.py`
  - **Done when:** All 4 test cases pass; ScoredResult channel is "mepo"; ranks are 1-based in descending score order

- [ ] **T13: Unit tests -- threshold decay and round behavior** — Verify:
  1. Default parameters: round 0 = 0.6000, round 1 = 0.2500, round 2 = 0.1042, round 3 = 0.0434, round 4 = 0.0181.
  2. Custom parameters `p=0.8, c=2.0`: round 0 = 0.8, round 1 = 0.4, round 2 = 0.2.
  3. Early termination when `newly_selected` is empty: loop breaks per spec pseudocode.
  4. Early termination when `remaining` is empty: all declarations selected mid-loop, remaining rounds skipped.
  5. `max_rounds` respected: with `max_rounds=2`, only rounds 0 and 1 run.
  6. Transitive discovery: declaration unreachable from query symbols but reachable through a round-0 selection's symbols gets selected in a later round (demonstrated by spec Example 1 D2).
  - **Traces to:** channel-mepo.md Section 5 (parameters, threshold formula, early termination)
  - **Depends on:** T6
  - **Produces:** Tests in `test/test_channel_mepo.py`
  - **Done when:** All 6 cases pass; threshold values verified to +/-0.0001

- [ ] **T14: Unit tests -- MepoIndex loading** — Create in-memory SQLite databases with the schema from storage.md and verify:
  1. Correct loading: `MepoIndex` loads `decl_symbols`, `freq_table`, builds inverted index and denominators.
  2. Query produces correct results matching standalone `mepo_select` output.
  3. Empty declarations table (zero declarations): construction succeeds, `query()` returns empty list.
  4. Declaration with `symbol_set = "[]"` (empty JSON array): handled correctly (never selected, no crash).
  5. Database connection released after construction.
  - **Traces to:** channel-mepo.md Section 6 (offline precomputation); Section 7 (online query)
  - **Depends on:** T7; tasks/storage.md (schema)
  - **Produces:** Tests in `test/test_channel_mepo.py`
  - **Done when:** All 5 cases pass

### Phase E: Performance Test

- [ ] **T15: Performance test -- 100K declarations** — Generate a synthetic library with 100K declarations, average 15 symbols each, realistic frequency distribution (Zipf-like). Verify:
  1. `MepoIndex` construction (including inverted index build and denominator precomputation) completes in reasonable time.
  2. `query()` latency < 200 ms end-to-end (architecture doc: "Typical runtime: <200ms for 100K declarations with inverted index").
  3. Determinism: same query on same data produces identical results across 10 runs.
  - **Traces to:** retrieval-pipeline.md (MePo runtime < 200ms); [Story 3.3](../doc/requirements/stories/tree-search-mcp.md#33-latency-target) (< 1s end-to-end)
  - **Depends on:** T7
  - **Produces:** `test/test_channel_mepo_perf.py` (marked `@pytest.mark.performance`, skipped in CI by default)
  - **Done when:** All 3 benchmarks meet targets on a modern laptop

---

## Dependency Graph

```
tasks/data-structures.md (ScoredResult, ExprTree, NodeLabel)
tasks/storage.md (schema)
│
└── T1 (module creation)
    ├── T2 (symbol_weight)
    │   ├── T3 (precompute_denominators)
    │   │   └── T4 (relevance)
    │   │       └── T6 (mepo_select)
    │   │           ├── T7 (MepoIndex)
    │   │           │   ├── T14 (test: MepoIndex)
    │   │           │   └── T15 (perf: 100K benchmark)
    │   │           ├── T12 (test: iterative selection)
    │   │           └── T13 (test: threshold/rounds)
    │   └── T9 (test: symbol_weight)
    ├── T5 (inverted index)
    │   └── T11 (test: inverted index)
    └── T10 (test: relevance) [depends on T4]

T1-T7 → T8 (module exports)
```

---

## Decomposition Decisions

The following decisions go beyond what the spec explicitly prescribes and should be reviewed by the architect:

1. **Separate denominator precomputation (T3):** The spec defines the denominator as `sum(symbol_weight(s, freq_table) for s in symbols(d))` inside the relevance function. Since this value is constant per declaration, precomputing it avoids redundant computation across rounds and candidates. This is a performance optimization with no behavioral change.

2. **Relevance function signature (T4):** The spec shows `relevance(d, S, freq_table)` with implicit access to `symbols(d)`. The implementation passes `decl_symbol_set` and `denominator` explicitly, keeping the function pure and testable in isolation.

3. **`mepo_select` parameter design (T6):** The spec's pseudocode uses `library` as an opaque reference. The implementation expands this into explicit `decl_symbols`, `inverted_index`, and `denominators` parameters. This makes data dependencies explicit and avoids coupling to a storage representation. The `MepoIndex` class (T7) provides the convenience wrapper that assembles these from the database.

4. **MepoIndex as a class (T7):** The spec describes offline precomputation and online query as separate phases. A class encapsulates the loaded state, supports multiple instances (e.g., for testing), and provides a clean lifecycle (construct once, query many times). The architect should confirm this is the preferred pattern.

5. **No separate `extract_symbols` task:** The retrieval-pipeline.md notes that `extract_symbols` at query time is equivalent to `extract_consts`. This function belongs to the extraction module (tasks/extraction.md) and is not reimplemented here. The MePo channel imports it. For `search_by_symbols`, the caller provides symbols directly.

6. **Internal weight caching (T3):** During batch denominator precomputation, individual `symbol_weight(s)` results are cached since the same symbol appears in many declarations. This avoids redundant `log2` calls with no behavioral change.
