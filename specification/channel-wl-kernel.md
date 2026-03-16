# Channel 1: WL Kernel Screening

The primary structural retrieval channel. Precomputes feature vectors for all declarations offline; compares query vectors online via cosine similarity.

Parent architecture: [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
Prerequisites: [coq-normalization.md](coq-normalization.md), [cse-normalization.md](cse-normalization.md)
Data structures: [data-structures.md](data-structures.md)
Used by: [fusion.md](fusion.md), [channel-ted.md](channel-ted.md) (TED takes WL's top-N as input)

Based on the Weisfeiler-Lehman subtree kernel (see [doc/background/tree-based-retrieval.md](../doc/background/tree-based-retrieval.md)).

---

## 1. Purpose

Screen the full library down to a manageable candidate set (~500) using a fast, precomputed structural fingerprint. This is the first stage of the structural retrieval pipeline — downstream channels (TED, collapse-match, Jaccard) refine this candidate set.

---

## 2. Scope

Covers WL label computation, histogram construction, cosine similarity, size filtering, and the online screening query. Does not cover the normalization that precedes WL (see [coq-normalization.md](coq-normalization.md), [cse-normalization.md](cse-normalization.md)) or the fine-ranking that follows (see [channel-ted.md](channel-ted.md), [fusion.md](fusion.md)).

---

## 3. WL Label Computation

The Weisfeiler-Lehman subtree kernel iteratively refines node labels by incorporating neighborhood structure.

**Initial labeling** (iteration 0):

```
label_0(node) = simplified_label(node) + "_d" + str(node.depth)
```

Where `simplified_label` maps the `node_label` to a short string:
- `LRel _` -> `"Rel"`
- `LVar _` -> `"Var"`
- `LSort Prop` -> `"Prop"`, `LSort Set` -> `"Set"`, `LSort TypeUniv` -> `"Type"`
- `LProd` -> `"Prod"`
- `LLambda` -> `"Lam"`
- `LLetIn` -> `"Let"`
- `LApp` -> `"App"`
- `LConst name` -> `"C:" + name`  (preserves identity)
- `LInd name` -> `"I:" + name`
- `LConstruct(name, i)` -> `"K:" + name + "." + str(i)`
- `LCase` -> `"Case"`
- `LFix _` -> `"Fix"`
- `LCoFix _` -> `"CoFix"`
- `LProj name` -> `"Proj:" + name`
- `LCseVar _` -> `"CseVar"`

The depth suffix `_d3` makes the kernel position-sensitive: a `Nat` at depth 2 is a different feature than a `Nat` at depth 5.

**Iterative refinement** (iterations 1 through h):

```
function wl_iterate(tree, h):
    labels = {node.node_id: label_0(node) for node in tree}
    all_labels = copy(labels)  # accumulate labels from ALL iterations

    for i in 1..h:
        new_labels = {}
        for node in tree:
            child_labels = sorted([labels[c.node_id] for c in node.children])
            new_labels[node.node_id] = MD5(
                labels[node.node_id] + "(" + ",".join(child_labels) + ")"
            )
        labels = new_labels
        all_labels.update(labels)  # merge into the full set

    return all_labels
```

**Histogram construction**:

```
function wl_histogram(tree, h):
    all_labels = wl_iterate(tree, h)
    hist = {}
    for label in all_labels.values():
        hist[label] = hist.get(label, 0) + 1
    return hist
```

The histogram includes labels from iterations 0 through h. This means the histogram captures subtree structure at every granularity from individual nodes (h=0) up to depth-h neighborhoods (h=h).

---

## 4. Offline Indexing

For each declaration in the library:

1. Extract `Constr.t`, convert to `ExprTree`
2. Apply Coq adaptations (see [coq-normalization.md](coq-normalization.md)): currify App, strip Cast, erase universes
3. Apply CSE normalization (see [cse-normalization.md](cse-normalization.md))
4. Compute WL histogram at h=3
5. Store histogram in `wl_vectors` table: `(decl_id, h=3, histogram_json)`
6. Record `node_count` on the declaration

---

## 5. Online Query

```
function wl_screen(query_expr, library_vectors, N=500):
    query_tree = to_expr_tree(query_expr)
    query_tree = coq_normalize(query_tree)       # see coq-normalization.md
    query_tree = cse_normalize(query_tree)        # see cse-normalization.md
    query_hist = wl_histogram(query_tree, h=3)
    query_nc   = node_count(query_tree)

    candidates = []
    for (decl_id, hist, nc) in library_vectors:
        # Size filter: skip declarations outside size ratio
        ratio = max(query_nc, nc) / max(min(query_nc, nc), 1)
        if ratio > 1.2 and query_nc < 600:
            continue
        if ratio > 1.8:  # relaxed threshold for large expressions
            continue

        score = cosine_similarity(query_hist, hist)
        candidates.append((decl_id, score))

    candidates.sort(by=score, descending=True)
    return candidates[:N]
```

---

## 6. Cosine Similarity on Sparse Histograms

Both histograms are sparse maps. The dot product only iterates over shared keys.

```
function cosine_similarity(h1, h2):
    dot = 0
    for key in h1:
        if key in h2:
            dot += h1[key] * h2[key]
    norm1 = sqrt(sum(v*v for v in h1.values()))
    norm2 = sqrt(sum(v*v for v in h2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)
```

---

## 7. Deployment Notes

Precomputed histograms are loaded into memory at server startup.

---

## 8. Error Specification

| Error Condition | Classification | Outcome |
|-----------------|---------------|---------|
| Query tree has 0 nodes | Edge case | Return empty candidate list |
| Query histogram is empty (all labels hashed to nothing) | Edge case | Cosine similarity is 0.0 for all candidates; return empty list |
| Library has 0 declarations loaded | State error | Return empty candidate list |
| Size filter eliminates all candidates | Normal case | Return empty candidate list |
| Histogram JSON in database is malformed | Dependency error | Skip that declaration; log warning |
| Cosine similarity produces NaN (both norms zero) | Invariant violation | Return 0.0 (handled by the norm==0 check) |

---

## 9. Examples

### Example: WL label computation for `nat → nat`

**Given**: The tree for `nat → nat` (after normalization):
```
Prod(depth=0)
├── Ind("Coq.Init.Datatypes.nat")(depth=1)
└── Ind("Coq.Init.Datatypes.nat")(depth=1)
```

**When**: `wl_iterate(tree, h=1)` runs.

**Then**:
- Iteration 0 labels:
  - Node 0 (Prod): `"Prod_d0"`
  - Node 1 (Ind nat): `"I:Coq.Init.Datatypes.nat_d1"`
  - Node 2 (Ind nat): `"I:Coq.Init.Datatypes.nat_d1"`
- Iteration 1 labels:
  - Node 0: `MD5("Prod_d0(I:Coq.Init.Datatypes.nat_d1,I:Coq.Init.Datatypes.nat_d1)")`
  - Node 1: `MD5("I:Coq.Init.Datatypes.nat_d1()")` (leaf, no children)
  - Node 2: `MD5("I:Coq.Init.Datatypes.nat_d1()")` (same as Node 1)

Histogram has 3 distinct entries from iteration 0 (2 unique labels, one appearing twice) plus 2 distinct entries from iteration 1.

### Example: Size filtering

**Given**: Query tree has 10 nodes. Library contains declarations with node counts [5, 8, 12, 50, 200].

**When**: Size filter runs with thresholds 1.2 (small) and 1.8 (large). Query is < 600 nodes, so 1.2 threshold applies.

**Then**:
- nc=5: ratio = 10/5 = 2.0 > 1.2 → **filtered out**
- nc=8: ratio = 10/8 = 1.25 > 1.2 → **filtered out**
- nc=12: ratio = 12/10 = 1.2, not > 1.2 → **kept**
- nc=50: ratio = 50/10 = 5.0 > 1.8 → **filtered out**
- nc=200: ratio = 200/10 = 20.0 > 1.8 → **filtered out**

Only the declaration with 12 nodes passes the size filter.
