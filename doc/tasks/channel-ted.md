# Task: TED Fine Ranking Channel

## 1. Overview

Implement the Tree Edit Distance (TED) fine ranking channel as specified in [specification/channel-ted.md](../../specification/channel-ted.md). This channel uses the Zhang-Shasha algorithm to compute precise structural edit distances between small expression trees (at most 50 nodes each). It operates as a refinement stage: the WL kernel screening channel produces a candidate set, and TED re-scores the eligible subset of those candidates.

The TED channel fills a gap that WL cosine similarity cannot: two trees with similar histogram distributions but different topology (e.g., swapped subtrees, differently nested applications) will receive different TED scores.

---

## 2. Dependencies

The following must be implemented or available before TED work begins:

| Dependency | Spec | Reason |
|------------|------|--------|
| `ExprTree` and `NodeLabel` types | `specification/data-structures.md` | TED operates on `ExprTree` nodes and dispatches on `NodeLabel` variants for the cost model |
| `node_count` utility | `specification/data-structures.md` | Required for the 50-node size constraint and the similarity denominator |
| WL kernel screening | `specification/channel-wl-kernel.md` | TED's input is the candidate list from WL screening |
| `ScoredResult` type | `specification/data-structures.md` | TED produces `ScoredResult` entries with `channel="ted"` |

No database or storage dependency is required for TED itself — it operates entirely in memory on deserialized `ExprTree` objects provided by the caller.

---

## 3. Implementation Steps

### Step 1: Cost Model

Create functions that encode the cost model from spec Section 4.

#### 1a. Category Classification

Define a function `label_category(label: NodeLabel) -> int` that maps each `NodeLabel` variant to one of 7 category groups:

| Category ID | Members |
|-------------|---------|
| 0 | `LConst`, `LInd`, `LConstruct` (leaf constants) |
| 1 | `LRel`, `LVar`, `LCseVar` (leaf variables) |
| 2 | `LSort` (sorts) |
| 3 | `LProd`, `LLambda`, `LLetIn` (binders) |
| 4 | `LApp` (application) |
| 5 | `LCase`, `LProj` (elimination) |
| 6 | `LFix`, `LCoFix` (recursion) |

`LInt` is not listed in the spec's category groups. Assign it to a distinct category (e.g., category 7) so that renaming `LInt` to any other label always incurs the cross-category cost. See feedback file for details.

Implementation: use `isinstance` checks or a dict mapping `type(label)` to category ID. A dict is cleaner and O(1).

#### 1b. Insert/Delete Cost

Define `insert_delete_cost(label: NodeLabel) -> float`:

- If label is `LRel`, `LVar`, `LCseVar`, or `LSort`: return 0.2 (lightweight leaf variables).
- If label is `LConst`, `LInd`, `LConstruct`: return 1.0 (semantic-identity leaf constants).
- All other labels (interior nodes: `LApp`, `LProd`, `LLambda`, `LLetIn`, `LCase`, `LFix`, `LCoFix`, `LProj`, and `LInt`): return 1.0.

#### 1c. Rename Cost

Define `rename_cost(label_a: NodeLabel, label_b: NodeLabel) -> float`:

- If `label_category(label_a) == label_category(label_b)`: return 0.0.
- Otherwise: return 0.4.

### Step 2: Tree Linearization (Postorder Traversal)

Zhang-Shasha operates on a postorder-numbered tree. Convert an `ExprTree` into the arrays the algorithm needs:

1. **Postorder traversal**: Walk the tree recursively (left-to-right children, then node) to assign postorder indices 1..n.
2. **Labels array** `labels[1..n]`: the `NodeLabel` at each postorder index.
3. **Leftmost leaf descendants** `l(i)`: for each node i (in postorder), the postorder index of its leftmost leaf descendant. For a leaf, `l(i) = i`. For an interior node, `l(i) = l(first_child)`.
4. **Parents array** (optional, for reconstruction): `parent[i]` is the postorder index of i's parent.

Encapsulate this in a helper class or dataclass:

```
@dataclass
class OrderedTree:
    size: int                    # number of nodes
    labels: list[NodeLabel]      # 1-indexed: labels[1..n]
    leftmost_leaf: list[int]     # 1-indexed: l[1..n]
    children: list[list[int]]    # 1-indexed: children postorder indices per node
```

Build this from `ExprTree` via a single postorder DFS.

### Step 3: Keyroots Computation

Compute the set of keyroots for a tree. A keyroot is the root or any node that has a left sibling (equivalently, any node whose leftmost leaf descendant differs from its parent's leftmost leaf descendant, plus the root).

Efficient method: collect all unique values of `l(i)` for i in 1..n. For each unique leftmost-leaf value, the keyroot is the node with the largest postorder index having that leftmost-leaf value. Alternatively:

```python
def keyroots(tree: OrderedTree) -> list[int]:
    # For each leftmost-leaf value, find the rightmost (highest postorder) node
    lr_map: dict[int, int] = {}
    for i in range(1, tree.size + 1):
        ll = tree.leftmost_leaf[i]
        if ll not in lr_map or i > lr_map[ll]:
            lr_map[ll] = i
    return sorted(lr_map.values())
```

### Step 4: Zhang-Shasha Algorithm

Implement the core algorithm. The algorithm fills a tree distance matrix `TD[i][j]` using forest distance sub-computations.

```
function zhang_shasha(tree_a: OrderedTree, tree_b: OrderedTree) -> float:
    n = tree_a.size
    m = tree_b.size
    TD = 2D array (n+1) x (m+1), initialized to 0.0

    kr_a = keyroots(tree_a)
    kr_b = keyroots(tree_b)

    for i in kr_a:
        for j in kr_b:
            compute_forest_distance(tree_a, tree_b, i, j, TD)

    return TD[n][m]
```

The `compute_forest_distance` subroutine:

```
function compute_forest_distance(A, B, i, j, TD):
    la_i = A.leftmost_leaf[i]
    lb_j = B.leftmost_leaf[j]

    # FD is a local 2D array indexed [la_i..i+1][lb_j..j+1]
    # Using offset indexing: FD[s - la_i + 1][t - lb_j + 1]
    rows = i - la_i + 2
    cols = j - lb_j + 2
    FD = 2D array rows x cols, initialized to 0.0

    # Base cases
    FD[0][0] = 0.0
    for s in range(la_i, i + 1):
        FD[s - la_i + 1][0] = FD[s - la_i][0] + insert_delete_cost(A.labels[s])
    for t in range(lb_j, j + 1):
        FD[0][t - lb_j + 1] = FD[0][t - lb_j] + insert_delete_cost(B.labels[t])

    # Fill
    for s in range(la_i, i + 1):
        for t in range(lb_j, j + 1):
            si = s - la_i + 1
            ti = t - lb_j + 1

            cost_delete = FD[si - 1][ti] + insert_delete_cost(A.labels[s])
            cost_insert = FD[si][ti - 1] + insert_delete_cost(B.labels[t])

            if A.leftmost_leaf[s] == la_i and B.leftmost_leaf[t] == lb_j:
                # Both s and t are rooted at the same leftmost leaf boundary
                cost_rename = FD[si - 1][ti - 1] + rename_cost(A.labels[s], B.labels[t])
                FD[si][ti] = min(cost_delete, cost_insert, cost_rename)
                TD[s][t] = FD[si][ti]
            else:
                # Use previously computed tree distance
                ls = A.leftmost_leaf[s]
                lt = B.leftmost_leaf[t]
                cost_subtree = FD[ls - la_i][lt - lb_j] + TD[s][t]
                FD[si][ti] = min(cost_delete, cost_insert, cost_subtree)
```

Key implementation notes:
- `TD` is shared across all keyroot pairs and accumulates results.
- `FD` is local to each `(i, j)` keyroot pair.
- Index arithmetic must be exact. Off-by-one errors are the primary implementation risk. Use 1-based indexing internally to match the algorithm's published formulation.
- Allocate `FD` as a list-of-lists or a flat array with manual indexing. For trees up to 50 nodes, a 51x51 allocation is fine.

### Step 5: Similarity Score

```python
def ted_similarity(tree_a: ExprTree, tree_b: ExprTree) -> float:
    n_a = node_count(tree_a)
    n_b = node_count(tree_b)

    if n_a == 0 and n_b == 0:
        return 1.0  # both empty, identical

    ot_a = to_ordered_tree(tree_a)
    ot_b = to_ordered_tree(tree_b)

    dist = zhang_shasha(ot_a, ot_b)
    max_nodes = max(n_a, n_b)
    similarity = 1.0 - dist / max_nodes

    if similarity < 0.0:
        # Invariant violation: edit distance exceeds max node count
        # Log warning: indicates cost model issue
        logger.warning(
            "TED similarity clamped to 0.0: dist=%.4f, max_nodes=%d",
            dist, max_nodes,
        )
        similarity = 0.0
    elif similarity > 1.0:
        similarity = 1.0

    return similarity
```

### Step 6: Integration — `ted_rerank`

```python
def ted_rerank(
    query_tree: ExprTree,
    wl_candidates: list[tuple[int, ExprTree]],
    max_nodes: int = 50,
) -> list[ScoredResult]:
    if node_count(query_tree) > max_nodes:
        return []

    results = []
    for decl_id, candidate_tree in wl_candidates:
        if node_count(candidate_tree) > max_nodes:
            continue
        try:
            sim = ted_similarity(query_tree, candidate_tree)
        except Exception:
            # Deserialization or computation error for this candidate
            logger.warning("TED computation failed for decl_id=%d, skipping", decl_id)
            continue
        results.append(ScoredResult(
            decl_id=decl_id,
            channel="ted",
            rank=0,  # assigned after sorting
            raw_score=sim,
        ))

    results.sort(key=lambda r: r.raw_score, reverse=True)
    for i, r in enumerate(results, start=1):
        r.rank = i

    return results
```

### Step 7: Library Evaluation — Implement from Scratch vs. Use Existing Library

**Recommendation: Implement from scratch.** Rationale:

1. The custom cost model (category-aware rename, variable-weight insert/delete) cannot be trivially plugged into most existing Python TED libraries. Libraries like `zss` (Zhang-Shasha for Python) support custom cost functions, but their APIs assume a specific tree format requiring adapter code.
2. The trees are small (at most 50 nodes), so performance is not a concern. A pure-Python implementation is sufficient.
3. The algorithm is well-defined (approximately 60 lines of core logic) and having a self-contained implementation avoids a dependency and makes debugging cost model issues straightforward.
4. If the `zss` library is used, it would still need: (a) an adapter to convert `ExprTree` to `zss.Node`, (b) custom cost functions passed as callbacks, (c) trust that the library's Zhang-Shasha implementation is correct. The adapter overhead approaches the cost of a direct implementation.

If future profiling reveals that TED is a bottleneck, consider: (a) a Cython or C extension for the inner loops, or (b) the APTED algorithm (O(n^2) worst case) as a drop-in replacement.

---

## 4. Module Structure

```
src/
  wily_rooster/
    channels/
      __init__.py
      ted.py              # Main module: ted_rerank, ted_similarity
    algorithms/
      __init__.py
      zhang_shasha.py     # OrderedTree, keyroots, zhang_shasha, compute_forest_distance
    models/
      __init__.py
      expr_tree.py        # ExprTree, NodeLabel variants, node_count (from data-structures spec)
      scored_result.py    # ScoredResult (from data-structures spec)
    cost_model/
      __init__.py
      ted_costs.py        # label_category, insert_delete_cost, rename_cost
```

Alternatively, if the project prefers a flatter layout, `zhang_shasha.py` and `ted_costs.py` can live directly in `channels/` alongside `ted.py`. The key constraint is that the Zhang-Shasha algorithm and cost model are independently testable units, separate from the integration logic in `ted_rerank`.

---

## 5. Testing Plan

### Unit Tests: Cost Model

| Test | Input | Expected |
|------|-------|----------|
| Same-category rename (leaf constants) | `LConst("a")`, `LConst("b")` | 0.0 |
| Same-category rename (binders) | `LProd()`, `LLambda()` | 0.0 |
| Cross-category rename (binder to app) | `LProd()`, `LApp()` | 0.4 |
| Cross-category rename (leaf var to leaf const) | `LRel(0)`, `LConst("x")` | 0.4 |
| Insert/delete lightweight leaf | `LRel(0)` | 0.2 |
| Insert/delete lightweight leaf | `LSort(SortKind.PROP)` | 0.2 |
| Insert/delete constant leaf | `LConst("x")` | 1.0 |
| Insert/delete interior node | `LApp()` | 1.0 |
| All 7 categories are distinct | Pairwise check across representatives | All cross-category pairs return 0.4 |

### Unit Tests: Tree Linearization

| Test | Input | Verified Properties |
|------|-------|---------------------|
| Single leaf node | `ExprTree(label=LRel(0))` | size=1, labels=[LRel(0)], leftmost_leaf=[1], keyroots=[1] |
| Three-node tree (Prod with two Ind children) | Spec example: `Prod(Ind("nat"), Ind("nat"))` | size=3, postorder=[Ind, Ind, Prod], leftmost_leaf correct, keyroots correct |
| Five-node nested tree | `App(Construct(nat,1), App(Construct(nat,1), Construct(nat,0)))` | Verify postorder, leftmost_leaf, keyroots match hand-computed values |

### Unit Tests: Zhang-Shasha Core

| Test | Trees | Expected Distance |
|------|-------|-------------------|
| Identical single node | `LRel(0)` vs `LRel(0)` | 0.0 |
| Single node, same category | `LRel(0)` vs `LVar("x")` | 0.0 |
| Single node, cross category | `LRel(0)` vs `LConst("x")` | 0.4 |
| Insert one node | `LRel(0)` vs `Prod(LRel(0), LRel(1))` | 1.0 (insert Prod) + 0.2 (insert LRel) = 1.2, but the algorithm may find a cheaper alignment. Verify by hand. |
| Empty vs single node | empty tree vs `LRel(0)` | 0.2 (insert one lightweight leaf) |
| Identical three-node tree | `Prod(Ind(nat), Ind(nat))` vs same | 0.0 |

### Integration Tests: Spec Examples (Section 9)

These are the mandatory acceptance tests taken directly from the specification:

| Test | Query | Candidate | Expected Similarity |
|------|-------|-----------|---------------------|
| Identical trees | `Prod(Ind("nat"), Ind("nat"))` | identical | 1.0 |
| Single rename within category | `Prod(Ind("nat"), Ind("nat"))` | `Prod(Ind("bool"), Ind("nat"))` | 1.0 (distance=0.0) |
| Structural difference | `Prod(Ind("nat"), Ind("nat"))` | `App(Ind("nat"), Ind("nat"))` | 0.867 (distance=0.4) |
| Size constraint skip | Query with 60 nodes | any | `ted_rerank` returns `[]` |

### Edge Case Tests

| Test | Condition | Expected |
|------|-----------|----------|
| Both trees empty | 0 nodes each | similarity = 1.0 |
| Query exceeds 50 nodes | 51-node query | `ted_rerank` returns `[]` |
| Candidate exceeds 50 nodes | 51-node candidate | Candidate skipped |
| Distance exceeds max(n, m) | Construct pathological cost model scenario | Similarity clamped to 0.0, warning logged |
| Deserialization failure | Candidate tree raises exception | Candidate skipped, warning logged |

### Property-Based Tests (optional, recommended)

- For any tree T, `ted_similarity(T, T) == 1.0`.
- For any trees A and B, `ted_similarity(A, B) == ted_similarity(B, A)` (symmetry — holds because insert cost equals delete cost for every label).
- Similarity is always in [0.0, 1.0].

---

## 6. Acceptance Criteria

1. All four spec examples (Section 9 of channel-ted.md) pass as automated tests with exact expected values (within floating-point tolerance of 1e-6).
2. `ted_rerank` returns an empty list when the query tree exceeds `max_nodes`.
3. `ted_rerank` skips candidates exceeding `max_nodes`.
4. The cost model correctly classifies all 16 `NodeLabel` variants into the 7 category groups (plus `LInt` — see feedback).
5. Insert/delete costs match spec: 0.2 for `LRel`, `LVar`, `LCseVar`, `LSort`; 1.0 for all others.
6. Rename costs match spec: 0.0 within category, 0.4 across categories.
7. Similarity is clamped to [0.0, 1.0] with a logged warning when clamped to 0.0.
8. Both-empty-trees edge case returns 1.0.
9. The Zhang-Shasha implementation produces correct results for trees up to 50 nodes (verified via the spec examples and at least one hand-computed 5+ node example).
10. `ted_rerank` produces `ScoredResult` entries with `channel="ted"`, correct ranks (1-based, descending by score), and scores in [0.0, 1.0].
11. Failed candidate computations are logged and skipped, not propagated as exceptions.

---

## 7. Risks and Mitigations

### Risk 1: Zhang-Shasha Index Arithmetic Errors

**Severity**: High. Off-by-one errors in the postorder indexing, leftmost-leaf computation, or forest distance array indexing will produce silently wrong results.

**Mitigation**:
- Use 1-based indexing internally to match the original paper's notation.
- Write exhaustive unit tests for `to_ordered_tree` output on 1-, 2-, 3-, and 5-node trees with hand-verified expected values.
- Add an assertion that `zhang_shasha(T, T) == 0.0` for every test tree.
- Compare results against the `zss` Python library on a set of random trees as a cross-validation step during development (even though we do not depend on `zss` at runtime).

### Risk 2: Performance of O(n^2 m^2) for Larger Candidate Sets

**Severity**: Low (mitigated by design). The 50-node constraint bounds worst-case per-pair cost to 50^2 * 50^2 = 6.25M operations. With a typical candidate set of 200 trees, that is 200 * 6.25M = 1.25B operations total.

**Mitigation**:
- The 50-node cap is an architectural constraint that should not be relaxed without re-evaluating performance.
- Pure Python may be slow for the full 200-candidate case. Profile during integration. If needed: (a) use NumPy for the 2D arrays, (b) port the inner loop to Cython, or (c) reduce the candidate set size for TED (e.g., top-100 instead of top-200).
- Consider early termination: if the edit distance already exceeds `max(n, m)` during computation, the similarity will be 0.0 and further computation is wasted. This optimization is non-trivial to add to Zhang-Shasha but possible.

### Risk 3: Cost Model Ambiguities

**Severity**: Medium. The spec's cost table uses the terms "leaf node" and "interior node" but some labels (`LConst`, `LInd`, `LConstruct`) are leaves by the tree invariant yet cost 1.0 for insert/delete. The spec's clarifying paragraph resolves this, but implementers could misread the table.

**Mitigation**:
- The implementation should dispatch on label type, not on leaf/interior status. The `insert_delete_cost` function checks the label variant directly, not whether the node has children.
- Test that `LConst` insert/delete costs 1.0 (not 0.2) explicitly.

### Risk 4: Spec Does Not Classify `LInt` in Any Category Group

**Severity**: Low. `LInt` (primitive integer literal) is not mentioned in the 7 category groups or in the insert/delete cost rules.

**Mitigation**: Assign `LInt` to its own category (category 7) and give it insert/delete cost 1.0. Document this decision. See feedback file.

### Risk 5: Symmetry Assumption

**Severity**: Low. The spec does not explicitly state that `ted_similarity(A, B) == ted_similarity(B, A)`, but this holds because insert cost equals delete cost for every label in the cost model. If the cost model is later changed to have asymmetric insert/delete costs, symmetry would break.

**Mitigation**: Add a property-based test asserting symmetry. If the cost model changes, this test will catch the regression.

### Risk 6: Floating-Point Precision in Similarity Comparison

**Severity**: Low. The similarity formula involves division and subtraction, which can produce floating-point rounding artifacts (e.g., 0.8666666... instead of 0.867).

**Mitigation**: Use tolerance-based comparison (1e-6) in all tests. The spec example says 0.867 for the structural difference case — verify this is 1.0 - 0.4/3 = 0.8666... repeating, and test with `abs(result - expected) < 1e-3`.
