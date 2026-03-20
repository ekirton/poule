# MePo Symbol-Relevance Channel

Iterative symbol-overlap retrieval inspired by Sledgehammer's MePo (Meng-Paulson) relevance filter.

**Architecture**: [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) § MePo Symbol Overlap

---

## 1. Purpose

Define the MePo channel that selects declarations based on weighted symbol overlap with a query's symbol set, using iterative breadth-first expansion to discover transitively relevant declarations.

## 2. Scope

**In scope**: Symbol weight function, relevance scoring, iterative selection with decaying threshold, inverted index construction, symbol extraction from expression trees.

**Out of scope**: Storage of inverted indices (owned by storage), fusion with other channels (owned by fusion/pipeline), tree normalization.

## 3. Definitions

| Term | Definition |
|------|-----------|
| Symbol set | The set of fully qualified kernel names (constants, inductives, constructors) appearing in a declaration's expression tree. Stored as FQNs after resolution (see [extraction.md](extraction.md) §4.4.1). |
| Working set | The set of symbols used to score candidates; starts as the query's symbol set (pre-resolved to FQNs by the pipeline) and expands each round |
| Inverted index | A map from FQN symbol → set of declaration IDs containing that symbol |

## 4. Behavioral Requirements

### 4.1 Symbol Weight Function

#### symbol_weight(freq)

- REQUIRES: `freq` is a positive integer (the number of declarations containing the symbol).
- ENSURES: Returns `1.0 + 2.0 / log2(freq + 1)`. Rare symbols receive higher weight.

**Missing symbol handling**: When a query-time symbol is not found in `symbol_freq` (not present in any indexed declaration), treat its frequency as 1. Declaration symbols are guaranteed to be in `symbol_freq` by the indexing invariant.

### 4.2 Relevance Scoring

#### mepo_relevance(candidate_symbols, working_set, symbol_frequencies)

- REQUIRES: `candidate_symbols` is the candidate declaration's symbol set. `working_set` is the current working symbol set. `symbol_frequencies` is the global frequency map.
- ENSURES: Returns the weighted overlap normalized by the candidate's total weight:

```
overlap = sum(symbol_weight(freq[s]) for s in candidate_symbols ∩ working_set)
total   = sum(symbol_weight(freq[s]) for s in candidate_symbols)
relevance = overlap / total  (0.0 if total == 0)
```

### 4.3 Iterative Selection

#### mepo_select(query_symbols, inverted_index, symbol_frequencies, declaration_symbols, p, c, max_rounds)

- REQUIRES: `query_symbols` is a non-empty set of FQN symbol names (pre-resolved by the calling pipeline function; see [pipeline.md](pipeline.md) §4.5.1). `inverted_index` maps FQN symbol → set of decl_ids. `symbol_frequencies` maps FQN symbol → freq. `declaration_symbols` maps decl_id → FQN symbol set. Parameters: `p=0.6`, `c=2.4`, `max_rounds=5`.
- ENSURES: Returns a list of `(decl_id, relevance_score)` pairs, ordered by relevance descending.

Algorithm:
1. Initialize working set `S` = `query_symbols`
2. Initialize threshold `t` = `p`
3. For each round (up to `max_rounds`):
   a. Find all candidates reachable from `S` via the inverted index (declarations sharing at least one symbol with `S`)
   b. Score each unseen candidate with `mepo_relevance`
   c. Select candidates with `relevance >= t`
   d. **Batch expansion**: After all candidates in the round are evaluated, add selected candidates' symbols to `S`
   e. Decay threshold: `t = t * (1/c)`
   f. If no new candidates were selected, stop early
4. Return all selected candidates with their scores

MAINTAINS: The working set `S` is updated only between rounds, not during iteration within a round.

### 4.4 Extract Symbols

#### extract_consts(tree)

- REQUIRES: `tree` is a valid `ExprTree`.
- ENSURES: Returns the set of fully qualified names from all `LConst`, `LInd`, and `LConstruct` nodes in the tree. For `LConstruct`, the contributed name is the parent inductive FQN (already stored in the label). No additional mapping is needed — the constructor-to-inductive mapping happens at tree construction time.

This function is shared with the Const Jaccard channel.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| Empty query symbol set | — | Return empty result list |
| Symbol not in frequency map (query-time) | — | Use frequency = 1 |

No errors are raised by MePo functions. Edge cases produce empty or degraded results.

## 6. Non-Functional Requirements

- Typical runtime: < 200ms for 100K declarations with inverted index.
- Inverted index loaded into memory at server startup.

## 7. Examples

### Symbol weighting

Given: `freq = 1`

When: `symbol_weight(1)` is called

Then: `1.0 + 2.0 / log2(2) = 1.0 + 2.0 = 3.0`

Given: `freq = 1000`

When: `symbol_weight(1000)` is called

Then: `1.0 + 2.0 / log2(1001) ≈ 1.0 + 0.2 = 1.2`

### Iterative expansion

Given: Query symbols = `{Coq.Init.Nat.add, Coq.Init.Nat.mul}` (pre-resolved from user input `["Nat.add", "Nat.mul"]` by the pipeline), threshold `p=0.6`

Round 1 (t=0.6): Finds declarations containing `Coq.Init.Nat.add` or `Coq.Init.Nat.mul`, selects those with relevance ≥ 0.6. Adds their symbols to S.

Round 2 (t=0.25): Broader working set finds more candidates at the lower threshold.

Continues until `max_rounds` or no new candidates.

## 8. Language-Specific Notes (Python)

- Use `math.log2` for the weight function.
- Inverted index as `dict[str, set[int]]`.
- Declaration symbols as `dict[int, set[str]]`.
- Package location: `src/poule/channels/`.
