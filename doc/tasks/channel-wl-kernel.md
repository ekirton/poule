# Task: WL Kernel Screening Channel

## Overview

Implement the Weisfeiler-Lehman subtree kernel screening channel as specified in [specification/channel-wl-kernel.md](../../specification/channel-wl-kernel.md). This channel is the first stage of the structural retrieval pipeline: it screens the full library (~50K declarations) down to ~500 candidates using precomputed histogram fingerprints and cosine similarity. Downstream channels (TED, collapse-match, Jaccard) refine this candidate set.

The implementation covers two distinct execution paths:
1. **Offline indexing**: compute and store WL histograms for every declaration in the library
2. **Online query**: compute the query histogram and rank library declarations by cosine similarity with size filtering

---

## Dependencies

These components must be implemented before the WL kernel channel can function end-to-end:

| Dependency | Specification | Reason |
|-----------|--------------|--------|
| Data structures (`ExprTree`, `NodeLabel`, `WlHistogram`, `ScoredResult`) | [specification/data-structures.md](../../specification/data-structures.md) | WL operates on `ExprTree` and produces `WlHistogram` |
| Coq normalization | [specification/coq-normalization.md](../../specification/coq-normalization.md) | Trees must be normalized before WL labeling |
| CSE normalization | [specification/cse-normalization.md](../../specification/cse-normalization.md) | CSE must run after Coq normalization and before WL |
| Storage schema (`wl_vectors`, `declarations` tables) | [specification/storage.md](../../specification/storage.md) | Histograms are stored in and loaded from `wl_vectors` |

**Can be developed in parallel with** (no dependency): MePo channel, FTS channel, fusion logic, MCP server.

**Note**: For unit testing of WL itself, only the data structures module is required. Normalization and storage can be mocked.

---

## Implementation Steps

### Step 1: Simplified Label Mapping

Implement `simplified_label(node: ExprTree) -> str` that maps each `NodeLabel` variant to a short string.

**All 16 mappings** (from data-structures.md `NodeLabel` variants):

| NodeLabel variant | simplified_label output |
|-------------------|------------------------|
| `LRel(index)` | `"Rel"` |
| `LVar(name)` | `"Var"` |
| `LSort(SortKind.PROP)` | `"Prop"` |
| `LSort(SortKind.SET)` | `"Set"` |
| `LSort(SortKind.TYPE_UNIV)` | `"Type"` |
| `LProd()` | `"Prod"` |
| `LLambda()` | `"Lam"` |
| `LLetIn()` | `"Let"` |
| `LApp()` | `"App"` |
| `LConst(name)` | `"C:" + name` |
| `LInd(name)` | `"I:" + name` |
| `LConstruct(name, i)` | `"K:" + name + "." + str(i)` |
| `LCase()` | `"Case"` |
| `LFix(mutual_index)` | `"Fix"` |
| `LCoFix(mutual_index)` | `"CoFix"` |
| `LProj(name)` | `"Proj:" + name` |
| `LCseVar(var_id)` | `"CseVar"` |
| `LInt(value)` | `"Int"` |

**Note on `LInt`**: The spec lists 15 mappings but `data-structures.md` defines 16 `NodeLabel` variants including `LInt`. This mapping must handle `LInt` -- use `"Int"` (discarding the value, consistent with how `LRel`, `LFix`, `LCoFix`, and `LCseVar` discard their payloads). See feedback file for details.

**Implementation notes**:
- Use `match` statement (Python 3.10+) or `isinstance` chain on the `NodeLabel` subclasses.
- `LConst`, `LInd`, `LConstruct`, and `LProj` preserve their name in the label. All other variants discard payloads.
- This function is pure and trivially testable.

### Step 2: Initial Labeling (Iteration 0)

Implement `initial_label(node: ExprTree) -> str`:

```
label_0(node) = simplified_label(node) + "_d" + str(node.depth)
```

The depth suffix makes the kernel position-sensitive. A `Nat` at depth 2 produces a different WL feature than a `Nat` at depth 5.

**Precondition**: `node.depth` must be correctly set by `recompute_depths()` from the normalization pipeline before WL runs.

### Step 3: WL Iterative Refinement

Implement `wl_iterate(tree: ExprTree, h: int) -> dict[int, str]`:

1. Traverse the tree to collect all nodes (any traversal order works; a pre-order DFS into a list is simplest).
2. Build the initial label map: `labels = {node.node_id: initial_label(node) for node in all_nodes}`.
3. Copy to `all_labels = dict(labels)` -- this accumulates labels from ALL iterations.
4. For each iteration `i` in `1..h`:
   a. For each node, gather its children's current labels, **sort them lexicographically**.
   b. Concatenate: `current_label + "(" + ",".join(sorted_child_labels) + ")"`.
   c. Hash the concatenation with MD5 (hex digest).
   d. Store in `new_labels[node.node_id]`.
5. After each iteration, merge `new_labels` into `all_labels` (overwriting node_id keys with new iteration labels).
6. Set `labels = new_labels` for the next iteration.
7. Return `all_labels`.

**Critical detail on `all_labels.update(labels)`**: The spec uses `dict.update()` which overwrites keys. Since every node gets a new label each iteration, the final `all_labels` contains exactly one label per node per iteration -- but only the LAST iteration's label survives per `node_id`. This means `all_labels` has exactly `N` entries (one per node), not `N * (h+1)`.

**Wait -- re-reading the spec more carefully**: The pseudocode initializes `all_labels = copy(labels)` (iteration 0 labels), then in each iteration does `all_labels.update(labels)`. Since the keys are `node_id` (integers), and each iteration overwrites the same node_id keys, only the latest iteration's labels survive per node. The histogram therefore counts labels from only the LAST iteration (iteration h), not all iterations.

**However**, the spec's prose says: "The histogram includes labels from iterations 0 through h. This means the histogram captures subtree structure at every granularity." This contradicts the pseudocode. See the feedback file for this issue.

**Recommended implementation (matching the prose intent)**: Accumulate labels across iterations without overwriting. Use a list of `(node_id, label)` pairs, or use `(node_id, iteration)` as the key:

```python
all_labels: list[str] = []

# Iteration 0
labels = {node.node_id: initial_label(node) for node in all_nodes}
all_labels.extend(labels.values())

for i in range(1, h + 1):
    new_labels = {}
    for node in all_nodes:
        child_labels = sorted(labels[c.node_id] for c in node.children)
        concat = labels[node.node_id] + "(" + ",".join(child_labels) + ")"
        new_labels[node.node_id] = md5_hex(concat)
    labels = new_labels
    all_labels.extend(labels.values())

# all_labels now has N * (h+1) entries
```

This way the histogram counts labels from all iterations (0 through h), matching the prose and the standard WL kernel definition.

### Step 4: MD5 Hashing

Use Python's `hashlib.md5` to produce hex digests:

```python
import hashlib

def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()
```

The hash compresses arbitrarily long label+children strings into 32-character hex strings. Collision probability is negligible for the tree sizes involved (<10K nodes).

### Step 5: Histogram Construction

Implement `wl_histogram(tree: ExprTree, h: int) -> WlHistogram`:

1. Call `wl_iterate(tree, h)` to get all labels (a list of strings if following the recommended approach, or dict values if following the spec pseudocode).
2. Count occurrences of each label string:

```python
hist: dict[str, int] = {}
for label in all_labels:
    hist[label] = hist.get(label, 0) + 1
return hist
```

**Important**: Iteration 0 labels are NOT MD5-hashed (they are raw strings like `"Prod_d0"`). Iteration 1+ labels ARE MD5 hex strings. Both types appear as histogram keys. This is correct per the spec -- the histogram has mixed key formats.

**Consideration**: For the initial labels (iteration 0), the keys are human-readable strings. For iteration 1+, they are MD5 hex strings. Both coexist in the same histogram. This is fine for cosine similarity since keys only need equality comparison.

### Step 6: Cosine Similarity on Sparse Histograms

Implement `cosine_similarity(h1: WlHistogram, h2: WlHistogram) -> float`:

```python
import math

def cosine_similarity(h1: dict[str, int], h2: dict[str, int]) -> float:
    # Iterate over the smaller histogram for efficiency
    if len(h1) > len(h2):
        h1, h2 = h2, h1

    dot = 0
    for key, v1 in h1.items():
        v2 = h2.get(key)
        if v2 is not None:
            dot += v1 * v2

    norm1 = math.sqrt(sum(v * v for v in h1.values()))
    norm2 = math.sqrt(sum(v * v for v in h2.values()))

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0

    return dot / (norm1 * norm2)
```

**Performance notes**:
- Always iterate the smaller histogram to minimize dictionary lookups.
- Pre-compute and cache `norm` values for library histograms at load time. Each library histogram's norm is constant -- computing it once at startup saves ~50K sqrt computations per query.
- The dot product is the only per-query computation that scales with histogram size.

### Step 7: Size Filtering

Implement the dual-threshold size filter applied before cosine similarity:

```python
def passes_size_filter(query_nc: int, candidate_nc: int) -> bool:
    ratio = max(query_nc, candidate_nc) / max(min(query_nc, candidate_nc), 1)
    if query_nc < 600 and ratio > 1.2:
        return False
    if ratio > 1.8:
        return False
    return True
```

**Logic**:
- For small queries (node_count < 600): strict threshold of 1.2x size ratio
- For large queries (node_count >= 600): relaxed threshold of 1.8x size ratio
- The `max(..., 1)` in the denominator prevents division by zero when either count is 0

**Edge case**: If `query_nc == 0`, ratio = `max(0, candidate_nc) / max(0, 1) = candidate_nc`. Any non-zero candidate will likely be filtered out. The error spec says to return an empty candidate list for 0-node queries.

### Step 8: Online Query (wl_screen)

Implement `wl_screen(query_tree: ExprTree, library_vectors: dict, N: int = 500) -> list[ScoredResult]`:

1. Compute `query_hist = wl_histogram(query_tree, h=3)`
2. Compute `query_nc = node_count(query_tree)` (total nodes in the tree)
3. If `query_nc == 0`, return empty list
4. Pre-compute `query_norm = sqrt(sum(v*v for v in query_hist.values()))`
5. For each `(decl_id, hist, nc, cached_norm)` in library_vectors:
   a. Apply size filter: skip if `passes_size_filter(query_nc, nc)` is False
   b. Compute cosine similarity (using cached library norm)
   c. Append `(decl_id, score)` to candidates
6. Sort candidates by score descending
7. Return top N as `ScoredResult` objects with `channel="wl_kernel"`

### Step 9: Offline Indexing

Implement `index_wl_histograms(declarations, db_connection)`:

For each declaration:
1. Deserialize the `ExprTree` from `declarations.constr_tree` (tree is already Coq-normalized and CSE-normalized)
2. Compute `wl_histogram(tree, h=3)`
3. Serialize histogram as JSON: `json.dumps(histogram)`
4. Insert into `wl_vectors` table: `(decl_id, h=3, histogram_json)`
5. Compute and store `node_count` on the declaration record

**Batch processing**: Commit every 1,000 declarations for throughput (per storage spec).

### Step 10: In-Memory Loading at Startup

Implement `load_wl_vectors(db_path: str) -> dict[int, tuple[WlHistogram, int, float]]`:

1. Open database read-only
2. Query: `SELECT wv.decl_id, wv.histogram, d.node_count FROM wl_vectors wv JOIN declarations d ON wv.decl_id = d.id WHERE wv.h = 3`
3. For each row:
   a. Parse histogram JSON: `json.loads(histogram_text)`
   b. Pre-compute norm: `sqrt(sum(v*v for v in hist.values()))`
   c. Store as `{decl_id: (hist, node_count, norm)}`
4. Return the dictionary

**Memory estimate**: 50K declarations x ~200 histogram entries x ~40 bytes per entry = ~400MB. Actual usage depends on histogram sparsity. The storage spec targets <2s load time.

---

## Module Structure

```
src/
  wily_rooster/
    __init__.py
    models/
      __init__.py
      expr_tree.py          # ExprTree, NodeLabel variants, SortKind (from data-structures spec)
      scored_result.py       # ScoredResult dataclass
      types.py               # WlHistogram, Symbol, SymbolSet type aliases
    normalization/
      __init__.py
      coq_normalize.py       # Coq-specific tree normalization
      cse_normalize.py       # CSE normalization
    channels/
      __init__.py
      wl_kernel.py           # THIS TASK: WL label, histogram, cosine, screening
    storage/
      __init__.py
      database.py            # SQLite read/write operations
      loader.py              # In-memory loading of WL vectors, symbol indices
    indexing/
      __init__.py
      wl_indexer.py          # Offline WL histogram computation and storage
```

**Primary file for this task**: `src/wily_rooster/channels/wl_kernel.py`

This file contains:
- `simplified_label(label: NodeLabel) -> str`
- `initial_label(node: ExprTree) -> str`
- `wl_iterate(tree: ExprTree, h: int) -> list[str]`
- `wl_histogram(tree: ExprTree, h: int) -> WlHistogram`
- `cosine_similarity(h1: WlHistogram, h2: WlHistogram) -> float`
- `passes_size_filter(query_nc: int, candidate_nc: int) -> bool`
- `wl_screen(query_hist: WlHistogram, query_nc: int, library_vectors: dict, n: int) -> list[ScoredResult]`

**Secondary file**: `src/wily_rooster/indexing/wl_indexer.py`
- `index_declaration_wl(tree: ExprTree) -> tuple[WlHistogram, int]`
- `batch_index_wl(declarations, db) -> None`

**Secondary file**: `src/wily_rooster/storage/loader.py`
- `load_wl_vectors(db_path: str) -> dict[int, tuple[WlHistogram, int, float]]`

---

## Testing Plan

All tests go in `test/channels/test_wl_kernel.py` (and `test/indexing/test_wl_indexer.py` for indexing).

### Test 1: simplified_label covers all 16 NodeLabel variants

For each of the 16 `NodeLabel` subclasses, assert the correct simplified string:
- `LRel(5)` -> `"Rel"`
- `LVar("x")` -> `"Var"`
- `LSort(SortKind.PROP)` -> `"Prop"`
- `LSort(SortKind.SET)` -> `"Set"`
- `LSort(SortKind.TYPE_UNIV)` -> `"Type"`
- `LProd()` -> `"Prod"`
- `LLambda()` -> `"Lam"`
- `LLetIn()` -> `"Let"`
- `LApp()` -> `"App"`
- `LConst("Coq.Init.Nat.add")` -> `"C:Coq.Init.Nat.add"`
- `LInd("Coq.Init.Datatypes.nat")` -> `"I:Coq.Init.Datatypes.nat"`
- `LConstruct("Coq.Init.Datatypes.nat", 0)` -> `"K:Coq.Init.Datatypes.nat.0"`
- `LCase()` -> `"Case"`
- `LFix(0)` -> `"Fix"`
- `LCoFix(0)` -> `"CoFix"`
- `LProj("Coq.Init.Specif.proj1_sig")` -> `"Proj:Coq.Init.Specif.proj1_sig"`
- `LCseVar(3)` -> `"CseVar"`
- `LInt(42)` -> `"Int"`

### Test 2: WL labels for `nat -> nat` (spec example)

Build the tree:
```
Prod(depth=0, node_id=0)
  Ind("Coq.Init.Datatypes.nat")(depth=1, node_id=1)
  Ind("Coq.Init.Datatypes.nat")(depth=1, node_id=2)
```

Run `wl_iterate(tree, h=1)`.

Assert iteration 0 labels:
- Node 0: `"Prod_d0"`
- Node 1: `"I:Coq.Init.Datatypes.nat_d1"`
- Node 2: `"I:Coq.Init.Datatypes.nat_d1"`

Assert iteration 1 labels (MD5 hashes):
- Node 0: `md5("Prod_d0(I:Coq.Init.Datatypes.nat_d1,I:Coq.Init.Datatypes.nat_d1)")`
- Node 1: `md5("I:Coq.Init.Datatypes.nat_d1()")`
- Node 2: `md5("I:Coq.Init.Datatypes.nat_d1()")` (same as Node 1)

Assert histogram from `wl_histogram(tree, h=1)`:
- 2 distinct keys from iteration 0: `"Prod_d0"` (count 1), `"I:Coq.Init.Datatypes.nat_d1"` (count 2)
- 2 distinct keys from iteration 1: hash of Prod-with-children (count 1), hash of leaf-Ind (count 2)
- Total: 4 distinct keys, 6 total label instances

### Test 3: Size filtering (spec example)

Query tree has 10 nodes. Test against library node counts:
- nc=5: ratio 2.0 > 1.2, query < 600 -> filtered out
- nc=8: ratio 1.25 > 1.2, query < 600 -> filtered out
- nc=12: ratio 1.2, not > 1.2 -> kept
- nc=50: ratio 5.0 > 1.8 -> filtered out
- nc=200: ratio 20.0 > 1.8 -> filtered out

### Test 4: Size filtering for large query

Query tree has 700 nodes (>= 600). Test:
- nc=500: ratio 1.4, 1.4 > 1.2 but query >= 600 so skip strict check; 1.4 <= 1.8 -> kept
- nc=350: ratio 2.0 > 1.8 -> filtered out

### Test 5: Cosine similarity

- Identical histograms: `cosine_similarity({"a": 3, "b": 4}, {"a": 3, "b": 4})` = 1.0
- Orthogonal histograms: `cosine_similarity({"a": 1}, {"b": 1})` = 0.0
- Partial overlap: `cosine_similarity({"a": 1, "b": 2}, {"a": 1, "c": 3})` = known value (1 / (sqrt(5) * sqrt(10)) = 1/sqrt(50))
- Empty histogram: `cosine_similarity({}, {"a": 1})` = 0.0
- Both empty: `cosine_similarity({}, {})` = 0.0

### Test 6: Edge case -- 0-node query tree

Given a degenerate tree with 0 nodes (or None), `wl_screen` returns an empty list.

### Test 7: Edge case -- empty library

Given a query histogram and an empty library_vectors dict, `wl_screen` returns an empty list.

### Test 8: Histogram JSON round-trip

Serialize a `WlHistogram` to JSON and deserialize. Assert the result is identical to the original (keys are strings, values are ints).

### Test 9: WL iteration with h=0

Only iteration 0 labels are produced. Histogram keys are human-readable strings (no MD5). Verify for a simple tree.

### Test 10: WL iteration with h=3 (standard depth)

Build a moderately complex tree (~10 nodes). Verify that:
- `wl_iterate` produces `N * 4` labels (iterations 0, 1, 2, 3)
- Histogram has the correct number of distinct keys
- Leaf nodes at the same depth with the same label produce identical iteration-1 hashes

### Test 11: wl_screen returns top-N sorted by score

Build 10 mock library entries with known histograms. Run `wl_screen` with N=3. Verify:
- Only 3 results returned
- Results are sorted by cosine similarity descending
- Each result has `channel="wl_kernel"`

### Test 12: Child label sorting is lexicographic

Build a node with children labeled `"B_d1"` and `"A_d1"`. Verify the concatenation for iteration 1 is `"...(A_d1,B_d1)"` (sorted), not `"...(B_d1,A_d1)"`.

---

## Acceptance Criteria

1. `simplified_label` handles all 16 `NodeLabel` variants without raising exceptions.
2. `wl_histogram` produces correct histograms for the spec's `nat -> nat` example.
3. Size filter matches the spec's example exactly (only nc=12 passes for query_nc=10).
4. `cosine_similarity` returns 1.0 for identical histograms, 0.0 for orthogonal histograms, and 0.0 when either histogram is empty.
5. `wl_screen` returns results sorted by score descending, capped at N.
6. All error conditions from spec section 8 are handled:
   - 0-node query -> empty list
   - Empty histogram -> cosine 0.0 for all candidates
   - 0 library declarations -> empty list
   - Size filter eliminates all -> empty list
   - Malformed histogram JSON -> skip with logged warning
   - NaN from both-zero norms -> returns 0.0
7. Offline indexing writes valid JSON histograms to `wl_vectors` at h=3.
8. In-memory loading correctly parses all stored histograms and pre-computes norms.
9. All tests pass.

---

## Risks and Mitigations

### Risk 1: Scanning 50K histograms per query is too slow

**Impact**: Each query must compute cosine similarity against all non-filtered library entries. At 50K entries, this is 50K sparse dot products.

**Mitigation**:
- Size filtering eliminates a significant fraction before cosine computation. With threshold 1.2, typically 60-80% of candidates are filtered.
- Pre-compute and cache library histogram norms at load time, saving 50K sqrt calls per query.
- Iterate the smaller histogram in dot product (query histograms are typically smaller).
- Python dict lookup is O(1); a 200-entry histogram produces ~200 lookups.
- Estimated: ~10-50ms per query for 50K entries after size filtering. If insufficient, consider NumPy vectorization or Cython for the inner loop.
- Fallback: batch queries with `numpy` sparse vectors if pure Python is too slow.

### Risk 2: Memory usage for 50K in-memory histograms

**Impact**: Each histogram is a `dict[str, int]`. 50K histograms with ~200 entries each = ~10M dict entries.

**Mitigation**:
- Python dict overhead is ~50-100 bytes per entry. 10M entries = ~500MB-1GB. This is significant.
- Optimization 1: Store histograms as two parallel arrays (keys list, values numpy array) instead of dicts. Reduces per-entry overhead.
- Optimization 2: Intern common MD5 strings (many library entries share subtree labels). Use `sys.intern()`.
- Optimization 3: Store histograms as sorted `(key_array, value_array)` tuples and use binary search for dot product. Trades CPU for memory.
- The storage spec targets <2s load time and implies ~100MB for 100K declarations. Monitor actual memory and optimize if needed.

### Risk 3: Spec ambiguity in histogram accumulation (pseudocode vs. prose)

**Impact**: The pseudocode uses `dict.update()` which overwrites per-node labels, meaning only the last iteration's labels survive. The prose says "iterations 0 through h" are all included.

**Mitigation**: Implement the prose intent (accumulate all iterations). This matches the standard WL kernel definition in the literature. File feedback on the spec. See feedback file for details.

### Risk 4: Missing `LInt` in simplified_label spec

**Impact**: If a tree contains `LInt` nodes and `simplified_label` doesn't handle them, the function will raise an error.

**Mitigation**: Add `LInt -> "Int"` mapping. File feedback on the spec. This is a minor gap -- `LInt` (primitive integer literals) are rare in Coq stdlib types but can appear in compiled code.

### Risk 5: MD5 hash collisions

**Impact**: Two structurally different subtrees could produce the same MD5 hash, causing them to be counted as the same feature.

**Mitigation**: Negligible risk. MD5 collision probability is ~2^-64 for birthday attacks on the number of distinct subtree patterns in a typical library (<100K). The CSE normalization spec explicitly accepts this risk.

### Risk 6: Histogram sparsity varies widely

**Impact**: Very small declarations (2-3 nodes) produce tiny histograms where cosine similarity is unstable. Very large declarations (500+ nodes) produce dense histograms that dominate the dot product cost.

**Mitigation**: Size filtering handles the small-vs-large mismatch. For computational cost, the "iterate smaller histogram" strategy ensures the query histogram size (not the library histogram size) drives the dot product cost.
