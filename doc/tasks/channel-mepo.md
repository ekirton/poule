# Task: Implement MePo Symbol Overlap Channel

---

## 1. Overview

Implement the MePo (Meng-Paulson) symbol overlap retrieval channel as specified in `specification/channel-mepo.md`. This channel ranks library declarations by how much their symbol sets overlap with the query's symbols, using inverse-frequency weighting so that rare symbols contribute more to relevance. The algorithm works iteratively: each round selects declarations above a decaying threshold, then expands the working symbol set with symbols from newly selected declarations, enabling transitive relevance discovery.

MePo is one of the primary retrieval channels used by `search_by_type` and `search_by_symbols` (see `specification/pipeline.md`). It operates on precomputed symbol sets and frequency data stored in SQLite, loaded into memory at startup.

---

## 2. Dependencies

### Must Be Implemented First

| Dependency | Spec | Reason |
|-----------|------|--------|
| Core data structures | `specification/data-structures.md` | `ScoredResult`, `SymbolSet`, `Symbol` type aliases |
| Storage schema | `specification/storage.md` | `declarations.symbol_set`, `symbol_freq` table |
| Symbol extraction | `specification/extraction.md` (Section 4.3) | Populates `declarations.symbol_set` and `symbol_freq` during indexing |

### Must Be Implemented Before Integration (but not before this channel)

| Dependency | Spec | Reason |
|-----------|------|--------|
| Fusion | `specification/fusion.md` | Consumes MePo's `ScoredResult` list |
| Pipeline orchestration | `specification/pipeline.md` | Invokes MePo as part of `search_by_type` and `search_by_symbols` |

### Assumed Available

- Python 3.11+ with standard library (`math.log2`, `json`, `sqlite3`)
- A populated SQLite database with `declarations` and `symbol_freq` tables

---

## 3. Implementation Steps

### Step 1: Define the MePo In-Memory Index

Create a class that loads data from SQLite at startup and provides fast lookup during queries.

**Data to load at startup:**

1. **Symbol frequency table**: `dict[str, int]` mapping each symbol to the number of declarations containing it. Source: `symbol_freq` table.
2. **Inverted index**: `dict[str, set[int]]` mapping each symbol to the set of `decl_id` values whose `symbol_set` contains that symbol. Source: iterate all rows from `declarations` table, parse `symbol_set` JSON.
3. **Per-declaration symbol sets**: `dict[int, list[str]]` mapping each `decl_id` to its list of symbols. Source: same iteration as the inverted index.
4. **Per-declaration denominator cache**: `dict[int, float]` mapping each `decl_id` to the precomputed sum of `symbol_weight(s)` for all `s` in `symbols(d)`. This denominator is constant for a given declaration and freq_table. Compute during startup to avoid redundant work per query.

**Loading procedure:**

```
1. SELECT symbol, freq FROM symbol_freq
   -> populate freq_table dict

2. SELECT id, symbol_set FROM declarations WHERE symbol_set IS NOT NULL
   For each row:
     a. Parse symbol_set JSON -> list of symbol strings
     b. Store in decl_symbols[id] = symbol_list
     c. For each symbol in symbol_list:
        inverted_index[symbol].add(id)
     d. Compute and cache denominator:
        denom = sum(symbol_weight(s, freq_table) for s in symbol_list)
        decl_denom[id] = denom
```

**Memory estimate**: For 50K declarations with an average of 5 symbols each, the inverted index holds ~250K (symbol, decl_id) pairs. With Python set overhead, expect 50-100 MB total for all in-memory structures.

### Step 2: Implement `symbol_weight`

```python
def symbol_weight(symbol: str, freq_table: dict[str, int]) -> float:
    f = freq_table.get(symbol, 0)
    if f == 0:
        return 3.0  # Guard: treat as maximally rare (same as f=1)
    return 1.0 + 2.0 / math.log2(f + 1)
```

Key behaviors:
- `f=0` (symbol not in freq_table): return 3.0 and log a warning. This matches the error spec: "Treat as frequency 1 (maximally rare); log warning."
- `f=1`: `1.0 + 2.0/log2(2) = 1.0 + 2.0 = 3.0`
- `f=100`: `1.0 + 2.0/log2(101) ≈ 1.30`
- `f=5000`: `1.0 + 2.0/log2(5001) ≈ 1.16`

### Step 3: Implement `relevance`

```python
def relevance(
    decl_id: int,
    working_symbols: set[str],
    freq_table: dict[str, int],
    decl_symbols: dict[int, list[str]],
    decl_denom: dict[int, float],
) -> float:
    denom = decl_denom[decl_id]
    if denom == 0.0:
        return 0.0
    symbols_d = decl_symbols[decl_id]
    overlap = [s for s in symbols_d if s in working_symbols]
    numerator = sum(symbol_weight(s, freq_table) for s in overlap)
    return numerator / denom
```

**Optimization note**: The `working_symbols` parameter is a `set` for O(1) membership testing. The overlap computation is O(|symbols(d)|), not O(|S|), since we iterate over the (smaller) declaration symbol set and check membership in S.

### Step 4: Implement `mepo_select` (Iterative Selection)

This is the core algorithm. The key optimization is using the inverted index to avoid scanning all remaining declarations.

```python
def mepo_select(
    query_symbols: list[str],
    index: MePoIndex,  # holds freq_table, inverted_index, decl_symbols, decl_denom
    p: float = 0.6,
    c: float = 2.4,
    max_rounds: int = 5,
) -> list[ScoredResult]:
    S = set(query_symbols)          # working symbol set
    selected = []                   # (decl_id, score) pairs
    already_selected = set()        # for O(1) membership check

    for round_i in range(max_rounds):
        threshold = p * (1.0 / c) ** round_i

        # Use inverted index: find all decl_ids sharing >= 1 symbol with S
        candidate_ids = set()
        for sym in S:
            candidate_ids |= index.inverted_index.get(sym, set())
        candidate_ids -= already_selected  # exclude already-selected

        newly_selected = []
        for decl_id in candidate_ids:
            r = relevance(decl_id, S, index.freq_table,
                          index.decl_symbols, index.decl_denom)
            if r >= threshold:
                newly_selected.append((decl_id, r))

        if not newly_selected:
            break

        for decl_id, r in newly_selected:
            already_selected.add(decl_id)
            selected.append((decl_id, r))
            # Expand working symbol set
            for sym in index.decl_symbols[decl_id]:
                S.add(sym)

    # Sort by score descending
    selected.sort(key=lambda x: x[1], reverse=True)

    # Convert to ScoredResult
    return [
        ScoredResult(
            decl_id=decl_id,
            channel="mepo",
            rank=rank + 1,  # 1-based
            raw_score=score,
        )
        for rank, (decl_id, score) in enumerate(selected)
    ]
```

**Important implementation detail**: The inverted index lookup (`candidate_ids`) replaces the naive "iterate over all remaining" loop from the spec pseudocode. This is the essential optimization for interactive query latency with 50K declarations. Each round only examines declarations that share at least one symbol with the current working set.

### Step 5: Wire Into the Query Path

The MePo channel is invoked by the pipeline orchestration layer:

1. For `search_by_symbols`: Extract symbols from the query expression (or accept a symbol list), call `mepo_select`, return results.
2. For `search_by_type`: Extract symbols from the query type expression, call `mepo_select`, pass results to RRF fusion alongside other channels.

The MePo index must be initialized once at server startup (when the storage read path loads data into memory per `specification/storage.md` Section 5.2) and reused across queries.

---

## 4. Module Structure

```
src/
  wily_rooster/
    __init__.py
    data_structures.py          # ExprTree, NodeLabel, ScoredResult, type aliases
    storage/
      __init__.py
      schema.py                 # SQLite table definitions, read/write helpers
      loader.py                 # Startup loading: WL histograms, MePo index, etc.
    channels/
      __init__.py
      mepo.py                   # MePoIndex class, symbol_weight, relevance, mepo_select
    pipeline.py                 # Query orchestration (calls channels)
    fusion.py                   # RRF and metric fusion
```

### `src/wily_rooster/channels/mepo.py` Contents

| Component | Type | Description |
|-----------|------|-------------|
| `symbol_weight()` | Function | Computes inverse-frequency weight for a single symbol |
| `MePoIndex` | Class | Holds in-memory freq_table, inverted_index, decl_symbols, decl_denom |
| `MePoIndex.from_db(conn)` | Class method | Loads all MePo data from SQLite connection |
| `MePoIndex.relevance()` | Method | Computes weighted overlap ratio for one declaration |
| `MePoIndex.select()` | Method | Runs iterative selection, returns `list[ScoredResult]` |

---

## 5. Testing Plan

### Unit Tests: `symbol_weight`

| Test Case | Input | Expected Output | Rationale |
|-----------|-------|-----------------|-----------|
| Rare symbol (f=1) | freq=1 | 3.0 | `1.0 + 2.0/log2(2) = 3.0` |
| Common symbol (f=100) | freq=100 | ~1.30 | `1.0 + 2.0/log2(101)` |
| Very common (f=5000) | freq=5000 | ~1.16 | `1.0 + 2.0/log2(5001)` |
| f=0 guard | freq=0 | 3.0 | Division-by-zero guard, same as f=1 |
| Missing symbol | symbol not in freq_table | 3.0 + warning logged | Error spec: treat as frequency 1 |

### Unit Tests: `relevance`

| Test Case | Setup | Expected |
|-----------|-------|----------|
| Full overlap | `symbols(d) = {A, B}`, `S = {A, B}` | 1.0 |
| No overlap | `symbols(d) = {A, B}`, `S = {C}` | 0.0 |
| Partial overlap, equal weights | `symbols(d) = {A, B, C}`, `S = {A, B}`, all freq=100 | ~0.667 |
| Empty symbol set | `symbols(d) = {}` | 0.0 (denominator guard) |
| Rare symbol boost | `symbols(d) = {rare, common}`, `S = {rare}`, rare freq=2, common freq=5000 | ~0.66 (matches spec Example 2) |

### Integration Tests: Iterative Selection (Spec Examples)

**Test 1: Single-round selection (Spec Section 9, Example 1)**

Setup:
- Query symbols: `{Nat.add, Nat.S}`
- D1: symbols `{Nat.add, Nat.S, Nat.O}`, all freq=100
- D2: symbols `{Nat.mul, Nat.S}`, all freq=100
- D3: symbols `{List.map, List.cons}`, all freq=50

Assertions:
- Round 0 (threshold=0.6): D1 selected (relevance ~0.667), D2 not selected (relevance=0.5), D3 not selected (relevance=0.0)
- After round 0: S = `{Nat.add, Nat.S, Nat.O}`
- Round 1 (threshold ~0.25): D2 selected (relevance=0.5 >= 0.25)
- D3 never selected (no overlap with expanded S)
- Final result: D1 and D2, sorted by score descending (D1 first)

**Test 2: Rare symbol boost (Spec Section 9, Example 2)**

Setup:
- Query symbols: `{MyProject.custom_lemma}`
- D1: symbols `{MyProject.custom_lemma, Nat.add}`, custom_lemma freq=2, Nat.add freq=5000

Assertions:
- Weight of custom_lemma: `1.0 + 2.0/log2(3) ≈ 2.26`
- Weight of Nat.add: `1.0 + 2.0/log2(5001) ≈ 1.16`
- Relevance of D1: `2.26 / (2.26 + 1.16) ≈ 0.66`
- D1 passes threshold of 0.6

### Edge Case Tests

| Test Case | Setup | Expected |
|-----------|-------|----------|
| Empty query symbols | query_symbols=[] | Return empty list |
| No declarations match | All declarations disjoint from query | Return empty list |
| Single declaration, single symbol | 1 decl with 1 symbol matching query | Selected in round 0 with relevance 1.0 |
| Max rounds reached | Symbols keep expanding but max_rounds=5 | Stop after 5 rounds |
| Large library simulation | 10K declarations, varied overlap | Completes within 1 second |

### Performance Tests

| Scenario | Target |
|----------|--------|
| Startup load (50K declarations, avg 5 symbols each) | < 3 seconds |
| Single query (50K declarations, 5 query symbols) | < 200 ms |
| Single query with heavy expansion (10 query symbols, 3 rounds of expansion) | < 500 ms |

---

## 6. Acceptance Criteria

1. `symbol_weight` produces correct values for f=0, f=1, f=100, f=5000, and missing symbols.
2. `relevance` returns 0.0 for empty symbol sets, 1.0 for full overlap, and correct fractional values for partial overlap with frequency-weighted symbols.
3. `mepo_select` reproduces both spec examples (Section 9) with matching selection decisions and approximate scores.
4. The inverted index is used to restrict candidate scanning per round (no full table scan of remaining declarations).
5. Results are returned as `ScoredResult` instances with `channel="mepo"`, 1-based ranks, and `raw_score` set to the relevance score.
6. Edge cases are handled: empty query returns empty list, empty symbol set declarations are never selected, unknown symbols are treated as maximally rare with a logged warning.
7. The `MePoIndex.from_db()` class method successfully loads from a populated SQLite database matching the storage schema.
8. A query against 50K declarations completes in under 500 ms.

---

## 7. Risks and Mitigations

### Risk 1: Per-Round Candidate Set Size

**Risk**: If the working symbol set S grows large (containing very common symbols), the inverted index lookup may return nearly all 50K declarations as candidates each round, negating the optimization.

**Mitigation**: In practice, the threshold decay limits this. Early rounds have a high threshold (0.6) that filters aggressively. By the time S is large (later rounds), the threshold is low (~0.1) but most high-overlap declarations have already been selected and removed from candidates. Monitor candidate set sizes in logging. If performance is still an issue, consider skipping inverted-index lookup for symbols with freq > 10K (they contribute minimal weight anyway).

### Risk 2: Memory Footprint of In-Memory Structures

**Risk**: Loading all 50K declarations' symbol sets plus the inverted index into memory may consume significant RAM.

**Mitigation**: Estimated at 50-100 MB for 50K declarations (5 symbols average, ~50 chars each). This is acceptable for a server process. If memory becomes a constraint, the denominator cache (`decl_denom`) can be computed lazily instead of at startup, trading CPU for memory.

### Risk 3: Working Set Explosion in Later Rounds

**Risk**: Each round adds all symbols from newly selected declarations to S. If round 0 selects many declarations, S may grow to contain thousands of symbols, making round 1 select nearly everything above the (now low) threshold.

**Mitigation**: The threshold decay (0.6 -> 0.25 -> 0.10 -> ...) already controls this. Additionally, `max_rounds=5` hard-caps the iteration. In practice, MePo on mathematical libraries stabilizes within 2-3 rounds. If the result set grows too large for downstream processing, the pipeline can truncate to a top-N (e.g., top 500) after MePo returns.

### Risk 4: Floating Point Comparison at Threshold Boundary

**Risk**: Relevance scores very close to the threshold (e.g., 0.5999999 vs 0.6) may produce non-deterministic selection due to floating-point arithmetic.

**Mitigation**: This is inherent to the algorithm and acceptable -- borderline declarations have minimal impact on retrieval quality. Do not add epsilon-based comparison; the spec uses `>=` and standard floating-point behavior is sufficient.

### Risk 5: Spec Pseudocode vs. Inverted Index Optimization Mismatch

**Risk**: The spec pseudocode iterates over all `remaining` declarations per round. The optimized implementation uses the inverted index to find only candidates sharing a symbol with S. These produce different iteration orders, which could theoretically yield different results if `newly_selected` processing order matters.

**Mitigation**: The algorithm's correctness does not depend on iteration order within a round. All declarations above the threshold are selected regardless of order. The symbol set expansion happens after all selections in a round (the spec appends to `newly_selected` first, then processes all of them). The implementation must preserve this two-phase structure: score all candidates first, then expand S with all newly selected declarations.

**Note on implementation**: Re-reading the spec pseudocode carefully, it scores candidates and appends to `newly_selected`, then iterates `newly_selected` to expand S. This means S expansion is interleaved with the newly_selected list (S grows as each newly-selected declaration is processed). However, this does not affect which declarations are selected in the current round because scoring was already completed. It only affects S for the *next* round. The implementation should match this behavior: compute all scores for the current round against the current S, then expand S with all newly selected declarations' symbols.
