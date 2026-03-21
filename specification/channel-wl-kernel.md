# WL Kernel Screening Channel

Weisfeiler-Lehman graph kernel for fast structural screening of expression trees.

**Architecture**: [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) § WL Kernel Screening, [expression-tree.md](../doc/architecture/data-models/expression-tree.md)

---

## 1. Purpose

Define the WL kernel screening channel that computes structural similarity between expression trees using Weisfeiler-Lehman histogram vectors. This channel serves as a fast first-pass filter, reducing the candidate set from 100K+ declarations to a manageable number (200–500) for expensive fine-ranking.

## 2. Scope

**In scope**: WL label initialization, iterative label refinement, histogram construction, cosine similarity, size filter, online screening function, offline histogram computation for indexing.

**Out of scope**: Tree normalization (owned by coq-normalization/cse-normalization), storage of histograms (owned by storage), fusion with other channels (owned by fusion/pipeline).

## 3. Definitions

| Term | Definition |
|------|-----------|
| WL iteration | One round of label refinement where each node's label incorporates its children's labels |
| Simplified label | The initial label derived from a node's type, payload, and structural properties (depth, child count) |
| WL histogram | A sparse map from refined label hashes to occurrence counts |
| h value | The number of WL refinement iterations; h=3 is the only value computed in Phase 1 |

## 4. Behavioral Requirements

### 4.1 Label Initialization (Iteration 0)

For each node in the tree, compute a simplified label string incorporating:
- The node's label type name
- The node's depth (from `TreeNode.depth`)
- The node's child count

The simplified label string (e.g., `"Prod_d0"` or `"LProd_3_2"`) shall be MD5-hashed to produce a 32-character lowercase hex string. This hex string is the iteration-0 label.

MAINTAINS: All histogram keys are uniformly formatted as 32-character lowercase hex MD5 digests, including iteration 0.

### 4.2 Iterative Refinement (Iterations 1..h)

For each iteration `i` from 1 to `h`:
1. For each node, concatenate its current label with the sorted labels of its children
2. MD5-hash the concatenated string to produce the new label

- REQUIRES: All nodes have labels from iteration `i-1`.
- ENSURES: Each node's label reflects its local neighborhood structure up to depth `i`.

**MD5 encoding**: All MD5 calls produce lowercase 32-character hex strings from UTF-8-encoded input.

### 4.3 Histogram Construction

After `h` iterations, build a sparse histogram counting the frequency of each final label across all nodes.

#### wl_histogram(tree, h)

- REQUIRES: `tree` is a valid `ExprTree` with `depth` fields set. `h` is a positive integer.
- ENSURES: Returns a `dict[str, int]` mapping label hashes to counts. Only labels with count > 0 are included (sparse representation).

### 4.4 Cosine Similarity

#### wl_cosine(hist_a, hist_b)

- REQUIRES: Both histograms are sparse `dict[str, int]`.
- ENSURES: Returns the cosine similarity as a float in [0.0, 1.0]. If either histogram is empty (zero vector), returns 0.0.

Cosine similarity formula: `dot(A, B) / (norm(A) * norm(B))` using sparse dot product over shared keys.

### 4.5 Size Filter

Before computing cosine similarity, candidates shall be filtered by relative size.

#### size_filter(query_node_count, candidate_node_count, size_ratio)

- REQUIRES: Both counts are positive integers. Both are post-CSE-normalized node counts. `size_ratio` is a positive float (default: use built-in thresholds).
- ENSURES: Returns `True` if the candidate passes the filter, `False` otherwise.

When `size_ratio` is provided, reject if `max(query, candidate) / min(query, candidate) > size_ratio`.

When `size_ratio` is not provided (default), apply built-in thresholds:
- When `query_node_count < 600`: reject if `max(query, candidate) / min(query, candidate) > 1.2`
- When `query_node_count >= 600`: reject if `max(query, candidate) / min(query, candidate) > 1.8`

### 4.6 Online Screening

#### wl_screen(query_histogram, query_node_count, library_histograms, library_node_counts, n, size_ratio)

- REQUIRES: `query_histogram` is a WL histogram for the query. `library_histograms` is a map of `decl_id → histogram`. `library_node_counts` is a map of `decl_id → node_count`. `n` is the number of candidates to return (default 500). `size_ratio` is an optional positive float forwarded to `size_filter` (default: not provided, use built-in thresholds).
- ENSURES: Returns up to `n` `(decl_id, wl_cosine_score)` pairs, ranked by cosine similarity descending. Only candidates passing the size filter are considered.

### 4.7 Offline Indexing

#### compute_wl_vector(tree, h)

Alias for `wl_histogram(tree, h)`. Used during extraction to precompute vectors for storage.

In Phase 1, only h=3 is computed. The schema supports h∈{1, 3, 5} for future experimentation.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| Query normalization failure (depths not set, etc.) | Caller handles | Return empty candidate list, log warning |
| Empty query histogram | — | `wl_screen` returns empty list |

## 6. Non-Functional Requirements

- Sub-second screening on 100K declarations.
- Histograms loaded into memory at server startup (~100MB for 100K declarations).
- Critical constraint: query h value must match indexed h value. Comparing histograms at different h values produces meaningless results.

## 7. Examples

### Simple histogram

Given a tree with 3 nodes: `LProd(LSort(PROP), LRel(0))`:

When: `wl_histogram(tree, h=3)` is called

Then: Returns a sparse dict with entries for the refined labels of all 3 nodes after 3 iterations of WL refinement. The exact hash values depend on the simplified label format and MD5 computation.

### Size filter

Given: `query_node_count = 30`, `candidate_node_count = 40`

When: `size_filter(30, 40)` is called

Then: `40 / 30 = 1.33 > 1.2` → returns `False` (candidate rejected).

Given: `query_node_count = 700`, `candidate_node_count = 900`

When: `size_filter(700, 900)` is called

Then: `900 / 700 = 1.29 < 1.8` → returns `True` (candidate passes).

## 8. Language-Specific Notes (Python)

- Use `hashlib.md5` for all hashing.
- Histograms as `dict[str, int]` — Python dicts are efficient for sparse representations.
- Cosine similarity via manual sparse dot product (no NumPy dependency needed for this).
- Package location: `src/poule/channels/`.
