# Channel 2: MePo Symbol Overlap

An iterative, breadth-first symbol-relevance filter. Selects declarations whose symbol sets overlap with the query, with inverse-frequency weighting so rare symbols count more.

Parent architecture: [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
Data structures: [data-structures.md](data-structures.md)
Used by: [fusion.md](fusion.md)

Based on the MePo algorithm (see [doc/background/tree-based-retrieval.md](../doc/background/tree-based-retrieval.md)).

---

## 1. Purpose

Retrieve declarations that share mathematical symbols with the query, using inverse-frequency weighting to prioritize declarations sharing rare (more informative) symbols. The iterative expansion discovers transitive relevance — declarations that share symbols with already-selected declarations.

---

## 2. Scope

Covers the symbol weight function, relevance scoring, iterative selection algorithm, and offline precomputation. Does not cover symbol extraction from expression trees (see [extraction.md](extraction.md)) or how MePo results are fused with other channels (see [fusion.md](fusion.md)).

---

## 3. Symbol Weight Function

```
function symbol_weight(symbol, freq_table):
    f = freq_table[symbol]  # number of declarations containing this symbol
    return 1.0 + 2.0 / log2(f + 1)
```

Rare symbols (low frequency) get high weight. A symbol appearing in 1 declaration has weight ~3.0; a symbol appearing in 10,000 declarations has weight ~1.15.

---

## 4. Relevance Score

For a candidate declaration `d` with symbol set `symbols(d)`, and the current working symbol set `S`:

```
function relevance(d, S, freq_table):
    numerator   = sum(symbol_weight(s, freq_table) for s in symbols(d) ∩ S)
    denominator = sum(symbol_weight(s, freq_table) for s in symbols(d))
    if denominator == 0:
        return 0.0
    return numerator / denominator
```

---

## 5. Iterative Selection

MePo selects declarations in rounds. Each round adds new symbols from selected declarations, allowing transitive relevance discovery.

```
function mepo_select(query_symbols, library, freq_table, p=0.6, c=2.4, max_rounds=5):
    S = set(query_symbols)          # working symbol set
    selected = []                    # (decl_id, relevance_score) pairs
    remaining = set(all declaration IDs)

    for round_i in 0..max_rounds:
        threshold = p * (1/c) ^ round_i
        newly_selected = []

        for decl_id in remaining:
            r = relevance(decl_id, S, freq_table)
            if r >= threshold:
                newly_selected.append((decl_id, r))

        if len(newly_selected) == 0:
            break

        for (decl_id, r) in newly_selected:
            remaining.remove(decl_id)
            selected.append((decl_id, r))
            S = S ∪ symbols(decl_id)   # expand working symbol set

    selected.sort(by=score, descending=True)
    return selected
```

**Parameters**:
- `p = 0.6`: Base threshold. Declarations must have at least 60% of their weighted symbol mass overlapping with the working set to be selected in round 0.
- `c = 2.4`: Decay factor. Each subsequent round reduces the threshold by a factor of 1/2.4, admitting weaker matches.
- `max_rounds = 5`: Cap on iteration depth. In practice, most useful results appear in rounds 0-2.

---

## 6. Offline Precomputation

1. For each declaration, extract its symbol set (all `LConst`, `LInd`, `LConstruct` names from the expression tree). Store in `declarations.symbol_set` as a JSON array.
2. Build the global `symbol_freq` table by counting how many declarations each symbol appears in.
3. For fast lookup, build an inverted index in memory: `symbol -> set of decl_ids`. This enables efficient intersection of `symbols(d) ∩ S`.

---

## 7. Online Query

1. Extract symbols from the query expression.
2. Run iterative selection.
3. Return results with scores.

---

## 8. Error Specification

| Error Condition | Classification | Outcome |
|-----------------|---------------|---------|
| Query has no extractable symbols | Edge case | Return empty result list |
| Symbol not found in `freq_table` | Dependency error | Treat as frequency 1 (maximally rare); log warning |
| Declaration has empty symbol set | Edge case | Relevance is 0.0 (denominator is 0); never selected |
| All declarations filtered below threshold in every round | Normal case | Return empty result list |
| `log2(f + 1)` produces 0 (f=0) | Edge case | `log2(1)` = 0; formula yields division by zero. Guard: if `f == 0`, return weight 3.0 (same as `f = 1`) |

---

## 9. Examples

### Example: Single-round selection

**Given**: Query symbols: `{Nat.add, Nat.S}`. Library has 3 declarations:
- D1: symbols `{Nat.add, Nat.S, Nat.O}`, all with freq=100
- D2: symbols `{Nat.mul, Nat.S}`, all with freq=100
- D3: symbols `{List.map, List.cons}`, all with freq=50

Weights at freq=100: `1.0 + 2.0/log2(101)` ≈ 1.30. All symbols have similar weight.

**When**: `mepo_select({Nat.add, Nat.S}, library, freq_table, p=0.6)` runs round 0 (threshold=0.6).

**Then**:
- D1: overlap = `{Nat.add, Nat.S}`, 2 of 3 symbols. Relevance ≈ 2/3 = 0.67 ≥ 0.6 → **selected**
- D2: overlap = `{Nat.S}`, 1 of 2 symbols. Relevance = 0.50 < 0.6 → **not selected in round 0**
- D3: overlap = `{}`, 0 of 2 symbols. Relevance = 0.0 → **not selected**

After round 0: S expands to `{Nat.add, Nat.S, Nat.O}`.

Round 1 (threshold ≈ 0.25): D2 relevance with expanded S = `{Nat.S}` / `{Nat.mul, Nat.S}` = 0.50 ≥ 0.25 → **selected**.

### Example: Rare symbol boost

**Given**: Query symbols: `{MyProject.custom_lemma}` (appears in only 2 declarations). Library declaration D1 has symbols `{MyProject.custom_lemma, Nat.add}` where `Nat.add` has freq=5000.

**When**: Relevance of D1 is computed.

**Then**:
- Weight of `MyProject.custom_lemma`: `1.0 + 2.0/log2(3)` ≈ 2.26
- Weight of `Nat.add`: `1.0 + 2.0/log2(5001)` ≈ 1.16
- Relevance = 2.26 / (2.26 + 1.16) ≈ 0.66

The rare symbol contributes disproportionately to relevance, making D1 likely to pass the 0.6 threshold despite only 1 of 2 symbols matching.
