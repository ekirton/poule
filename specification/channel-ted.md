# Channel 4: TED Fine Ranking

Tree Edit Distance provides precise structural comparison for small expressions. Applied only to the top candidates from WL screening, not to the full library.

Parent architecture: [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
Prerequisites: [channel-wl-kernel.md](channel-wl-kernel.md) (WL screening must run first)
Data structures: [data-structures.md](data-structures.md)
Used by: [fusion.md](fusion.md)

---

## 1. Purpose

Provide fine-grained structural comparison for small expression trees (≤ 50 nodes). TED captures edit-level differences that WL cosine similarity misses — for example, two trees with similar histogram distributions but different topology will have different edit distances.

---

## 2. Scope

Covers the Zhang-Shasha algorithm selection, cost model, similarity score, size constraints, and integration with WL screening. Does not cover the WL screening that provides input candidates (see [channel-wl-kernel.md](channel-wl-kernel.md)) or the fusion that combines TED with other metrics (see [fusion.md](fusion.md)).

---

## 3. Algorithm: Zhang-Shasha

The Zhang-Shasha algorithm computes the minimum-cost edit distance between two ordered labeled trees in O(n1 * n2 * min(d1, l1) * min(d2, l2)) time, where n = node count, d = depth, l = leaf count. For balanced trees this is approximately O(n^2 * m^2).

The algorithm uses dynamic programming over "keyroots" (rightmost nodes in left subtrees) and the leftmost-leaf decomposition.

The implementation must produce a minimum-cost edit distance consistent with the Zhang-Shasha algorithm's semantics.

---

## 4. Cost Model

Edit operation costs reflect structural importance:

| Operation | Condition | Cost |
|-----------|-----------|------|
| Insert leaf node | `LRel`, `LVar`, `LCseVar`, `LSort` | 0.2 |
| Delete leaf node | `LRel`, `LVar`, `LCseVar`, `LSort` | 0.2 |
| Insert interior node | `LApp`, `LProd`, `LLambda`, `LCase`, ... | 1.0 |
| Delete interior node | `LApp`, `LProd`, `LLambda`, `LCase`, ... | 1.0 |
| Rename same category | e.g., `LConst "a"` -> `LConst "b"` | 0.0 |
| Rename cross category | e.g., `LConst _` -> `LProd` | 0.4 |

**Category definition** for same-vs-cross rename:
- Leaf constants: `LConst`, `LInd`, `LConstruct` (all in one category)
- Leaf variables: `LRel`, `LVar`, `LCseVar` (one category)
- Sorts: `LSort _` (one category)
- Binders: `LProd`, `LLambda`, `LLetIn` (one category)
- Application: `LApp` (its own category)
- Elimination: `LCase`, `LProj` (one category)
- Recursion: `LFix`, `LCoFix` (one category)

Renaming within the same category costs 0 (e.g., swapping one constant for another doesn't change the structural shape). Renaming across categories costs 0.4 (the structural role changed).

**Insert/delete cost rule**: Leaf variable nodes (`LRel`, `LVar`, `LCseVar`, `LSort`) cost 0.2 because they are structurally lightweight. Constant leaf nodes (`LConst`, `LInd`, `LConstruct`) cost 1.0 because they carry semantic identity. All interior nodes cost 1.0.

---

## 5. Similarity Score

```
ted_similarity(T1, T2) = 1.0 - edit_distance(T1, T2) / max(node_count(T1), node_count(T2))
```

Clamped to [0, 1].

---

## 6. Application Constraints

- Only compute TED for expression pairs where **both** trees have node_count <= 50 (after CSE normalization).
- For larger expressions, omit TED from the fusion. The WL kernel and other channels provide sufficient discrimination.

---

## 7. Integration with WL Screening

TED is a **refinement** channel. It takes the top candidates from WL screening (typically top-200 that pass the size constraint) and re-scores them:

```
function ted_rerank(query_tree, wl_candidates, max_nodes=50):
    if node_count(query_tree) > max_nodes:
        return []  # skip TED entirely for large queries
    eligible = [(id, tree) for (id, tree) in wl_candidates
                if node_count(tree) <= max_nodes]
    results = []
    for (id, tree) in eligible:
        sim = ted_similarity(query_tree, tree)
        results.append((id, sim))
    return results
```

---

## 8. Error Specification

| Error Condition | Classification | Outcome |
|-----------------|---------------|---------|
| Either tree exceeds 50 nodes | Constraint violation | Skip TED for this pair; return no score |
| Both trees are empty (0 nodes) | Edge case | `ted_similarity` = 1.0 (identical empty trees; edit distance = 0, max node count = 0 — guard against division by zero) |
| Edit distance exceeds `max(node_count(T1), node_count(T2))` | Invariant violation | Clamp similarity to 0.0; log warning (indicates cost model issue) |
| Deserialization of candidate tree from BLOB fails | Dependency error | Skip this candidate; log warning |

---

## 9. Examples

### Example: Identical trees

**Given**: Query tree `Prod(Ind("nat"), Ind("nat"))` (3 nodes). Candidate tree is identical.

**When**: `ted_similarity` is computed.

**Then**: Edit distance = 0. Similarity = 1.0 - 0/3 = **1.0**.

### Example: Single rename within category

**Given**: Query: `Prod(Ind("nat"), Ind("nat"))`. Candidate: `Prod(Ind("bool"), Ind("nat"))`.

**When**: `ted_similarity` is computed.

**Then**: Minimum edit: rename `Ind("nat")` → `Ind("bool")` at cost 0.0 (same category: leaf constants). Edit distance = 0.0. Similarity = 1.0 - 0.0/3 = **1.0**.

### Example: Structural difference

**Given**: Query: `Prod(Ind("nat"), Ind("nat"))` (3 nodes). Candidate: `App(Ind("nat"), Ind("nat"))` (3 nodes).

**When**: `ted_similarity` is computed.

**Then**: Minimum edit: rename `Prod` → `App` at cost 0.4 (cross-category: binder → application). Edit distance = 0.4. Similarity = 1.0 - 0.4/3 = **0.867**.

### Example: Size constraint skip

**Given**: Query tree has 60 nodes.

**When**: `ted_rerank` is called.

**Then**: Query exceeds `max_nodes=50`. Function returns empty list. TED is excluded from fusion for this query.
