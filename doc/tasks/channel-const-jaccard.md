# Task: Implement Const Name Jaccard Channel

Specification: [specification/channel-const-jaccard.md](../../specification/channel-const-jaccard.md)

---

## 1. Overview

Implement Channel 5 (Const Name Jaccard), a lightweight retrieval signal that measures overlap between the sets of fully qualified constant names in two expression trees using Jaccard similarity. This channel complements WL (shape-based) and TED (edit-distance-based) channels by capturing whether two expressions reference the same mathematical objects, regardless of structural arrangement.

The channel provides two entry points: pairwise `const_jaccard(tree1, tree2)` and batch `const_jaccard_rank(query_tree, candidates)`. It is used in the fine-ranking weighted sum during `search_by_structure` (weight 0.15 with TED, 0.25 without TED) and optionally in `search_by_symbols`.

---

## 2. Dependencies

### Must be implemented first

| Dependency | Spec | Reason |
|-----------|------|--------|
| `ExprTree`, `NodeLabel` types | `specification/data-structures.md` | `extract_consts` traverses `ExprTree` nodes and pattern-matches on `LConst`, `LInd`, `LConstruct` labels |

### Must exist but need not be complete

| Dependency | Spec | Reason |
|-----------|------|--------|
| Coq normalization pipeline | `specification/coq-normalization.md` | Produces the `ExprTree` instances this channel consumes; needed for integration tests but not unit tests |

### Downstream consumers (not blocking)

| Consumer | Spec | Reason |
|----------|------|--------|
| Fusion | `specification/fusion.md` | Reads `const_jaccard` scores in the fine-ranking weighted sum |
| Pipeline | `specification/pipeline.md` | Orchestrates channel invocation |

---

## 3. Implementation Steps

### Step 1: Create module file

Create `src/channels/const_jaccard.py`.

### Step 2: Implement `extract_consts`

A function that recursively walks an `ExprTree` and collects the names from constant-bearing node labels into a Python `set[str]`.

Matching logic:
- `LConst(name)` -- add `name`
- `LInd(name)` -- add `name`
- `LConstruct(name, _index)` -- add `name` (the inductive type name, not the constructor index)
- All other labels -- skip, but continue recursing into children

Use a simple iterative stack-based traversal (avoids Python recursion limit on deep trees). Alternatively, a recursive traversal is acceptable given the recursion depth cap of 1,000 from coq-normalization.

Return type: `set[str]`.

### Step 3: Implement `const_jaccard`

Pairwise similarity between two trees:

1. Call `extract_consts` on each tree.
2. Compute `union = c1 | c2` and `intersection = c1 & c2`.
3. If `len(union) == 0`, return `0.0`.
4. Return `len(intersection) / len(union)`.

Return type: `float` in range `[0.0, 1.0]`.

### Step 4: Implement `const_jaccard_rank`

Batch scoring of candidates against a single query:

1. Extract query consts once: `q_consts = extract_consts(query_tree)`.
2. For each `(decl_id, candidate_tree)` in candidates:
   - Extract `c_consts = extract_consts(candidate_tree)`.
   - Compute Jaccard between `q_consts` and `c_consts` (inline the set math rather than re-extracting query consts).
   - Produce a `ScoredResult(decl_id=decl_id, channel="const_jaccard", rank=0, raw_score=score)`.
3. Sort results by `raw_score` descending, assign 1-based ranks.
4. Return the list of `ScoredResult`.

Handle candidate deserialization failures: if a candidate tree cannot be deserialized, log a warning and skip that candidate (per the error specification).

### Step 5: Add logging

Use Python's `logging` module. Log at WARNING level when:
- A candidate tree fails deserialization (skip it).
- A score falls outside `[0.0, 1.0]` (should not happen with correct Jaccard, but clamp and log per fusion spec).

---

## 4. Module Structure

```
src/
  channels/
    __init__.py
    const_jaccard.py      # extract_consts, const_jaccard, const_jaccard_rank
  data_structures.py      # ExprTree, NodeLabel variants, ScoredResult (from data-structures spec)

test/
  channels/
    __init__.py
    test_const_jaccard.py
```

The `channels/` package groups all channel implementations. Each channel is a separate module.

---

## 5. Testing Plan

### Unit tests for `extract_consts`

| Test case | Input tree | Expected output |
|-----------|-----------|-----------------|
| Single `LConst` leaf | `ExprTree(LConst("Nat.add"))` | `{"Nat.add"}` |
| Single `LInd` leaf | `ExprTree(LInd("Coq.Init.Datatypes.nat"))` | `{"Coq.Init.Datatypes.nat"}` |
| Single `LConstruct` leaf | `ExprTree(LConstruct("Coq.Init.Datatypes.nat", 1))` | `{"Coq.Init.Datatypes.nat"}` |
| Mixed tree | Tree with `LConst("Nat.add")`, `LInd("nat")`, `LConstruct("nat", 0)`, `LApp`, `LProd` | `{"Nat.add", "nat"}` |
| No constants | Tree of only `LProd`, `LRel`, `LSort` nodes | `set()` |
| Duplicate constants | Tree with `LInd("nat")` appearing 3 times | `{"nat"}` (set deduplicates) |
| Deep tree | Linear chain of 100 `LApp` nodes with `LConst("f")` at leaf | `{"f"}` |

### Unit tests for `const_jaccard`

These map directly from the specification examples:

| Test case | Query consts | Candidate consts | Expected |
|-----------|-------------|-----------------|----------|
| Identical sets | `{Nat.add, Nat.S, Nat.O}` | `{Nat.add, Nat.S, Nat.O}` | `1.0` |
| Partial overlap | `{Nat.add, Nat.S}` | `{Nat.add, Nat.mul, Nat.S, Nat.O}` | `0.5` |
| No overlap | `{List.map, List.cons}` | `{Nat.add, Nat.S}` | `0.0` |
| Both empty | `{}` | `{}` | `0.0` |
| Query empty, candidate non-empty | `{}` | `{Nat.add}` | `0.0` |
| Candidate empty, query non-empty | `{Nat.add}` | `{}` | `0.0` |

### Unit tests for `const_jaccard_rank`

| Test case | Description |
|-----------|-------------|
| Multiple candidates | 3 candidates with varying overlap; verify scores and ranks are correct |
| Empty candidate list | Returns empty list |
| All candidates score 0 | Query shares no constants with any candidate; all scores 0.0 |
| Query consts extracted once | Verify query const extraction is not repeated per candidate (performance check via mock or timing) |

### Integration test (when normalization is available)

Build an `ExprTree` for `S (S O)` (from the data-structures spec example) and verify `extract_consts` returns `{"Coq.Init.Datatypes.nat"}`.

---

## 6. Acceptance Criteria

1. `extract_consts` correctly collects names from `LConst`, `LInd`, and `LConstruct` nodes and returns a `set[str]`.
2. `const_jaccard` returns `0.0` when the union of const sets is empty (both trees have no constants).
3. `const_jaccard` returns a float in `[0.0, 1.0]` for all inputs.
4. `const_jaccard_rank` extracts query constants exactly once and reuses them across all candidates.
5. `const_jaccard_rank` returns `ScoredResult` instances with `channel="const_jaccard"`, correct scores, and 1-based ranks sorted descending by score.
6. Candidate deserialization failures are logged and skipped, not propagated as exceptions.
7. All spec examples (Section 7) pass as unit tests with exact expected values.
8. All unit tests pass.

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Python recursion limit on deep trees during `extract_consts` | Low (coq-normalization caps at 1,000 depth) | Stack overflow | Use iterative traversal with an explicit stack instead of recursion |
| `LConstruct` name semantics confusion -- the `name` field is the inductive type name, not the constructor name | Medium | Incorrect constant extraction | The spec and data-structures spec are clear: `LConstruct(name, index)` where `name` is the inductive name. Add a code comment and a test that verifies `LConstruct("nat", 0)` yields `"nat"` not `"O"` |
| Performance on large candidate lists | Low | Slow ranking | `extract_consts` is O(n) per tree; Jaccard set operations are O(min(|c1|, |c2|)). For 500 candidates of typical size, this is negligible compared to TED |
