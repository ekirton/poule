# TED Fine Ranking Channel

Tree Edit Distance via the Zhang-Shasha algorithm for fine structural comparison of small expression trees.

**Architecture**: [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) § TED Fine Ranking, [expression-tree.md](../doc/architecture/data-models/expression-tree.md)

---

## 1. Purpose

Define the TED channel that computes pairwise tree edit distance between a query expression tree and candidate declaration trees, converting distances to similarity scores for fine-grained structural ranking.

## 2. Scope

**In scope**: Cost model, Zhang-Shasha algorithm, similarity score computation, size constraint (node_count ≤ 50 threshold), reranking orchestration.

**Out of scope**: Tree normalization (owned by coq-normalization/cse-normalization), tree deserialization (owned by storage), fusion weights (owned by fusion).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Tree edit distance | The minimum cost of transforming one tree into another using insert, delete, and rename operations |
| Zhang-Shasha | An O(n²) algorithm for computing tree edit distance on ordered, labeled trees |
| Node category | A classification of node labels used to determine rename costs |

## 4. Behavioral Requirements

### 4.1 Cost Model

Operations and their costs:

| Operation | Cost |
|-----------|------|
| Insert leaf node | 1.0 |
| Delete leaf node | 1.0 |
| Insert interior node | 1.0 |
| Delete interior node | 1.0 |
| Rename: same label | 0.0 |
| Rename: different label, same category | 0.5 |
| Rename: different label, cross-category | 1.0 |

#### Node Categories

| Category | Node types |
|----------|-----------|
| Binder | `LAbs`, `LProd`, `LLet` |
| Application | `LApp` |
| Constant reference | `LConst`, `LInd`, `LConstruct` |
| Variable | `LRel`, `LCseVar` |
| Sort | `LSort` |
| Control | `LCase`, `LFix`, `LCoFix` |
| Projection | `LProj` |
| Primitive | `LPrimitive` |

#### rename_cost(label_a, label_b)

- REQUIRES: Both labels are `NodeLabel` instances.
- ENSURES: Returns 0.0 if labels are equal, 0.5 if same category but different labels, 1.0 if different categories.

### 4.2 Zhang-Shasha Algorithm

#### ted(tree_a, tree_b)

- REQUIRES: Both trees are valid `ExprTree` instances with `node_id` fields set via `assign_node_ids`.
- ENSURES: Returns the tree edit distance as a non-negative float.

The implementation shall follow the standard Zhang-Shasha algorithm:
1. Compute leftmost leaf descendants for all nodes (preprocessing)
2. Identify keyroots (nodes whose leftmost leaf descendant differs from their parent's)
3. For each pair of keyroots, compute the forest distance matrix using dynamic programming
4. The final cell of the top-level forest distance computation is the tree edit distance

### 4.3 Similarity Score

#### ted_similarity(tree_a, tree_b)

- REQUIRES: Both trees are valid `ExprTree` instances.
- ENSURES: Returns `max(0.0, 1.0 - ted(tree_a, tree_b) / max(node_count(tree_a), node_count(tree_b)))`.

The formula can produce negative values for very dissimilar trees. The result is clamped to 0.0 — no warning is needed, as negative pre-clamp values are expected for structurally dissimilar trees.

### 4.4 Size Constraint

TED is applied only when **both** the query tree and the candidate tree have `node_count ≤ 50`.

When either tree exceeds 50 nodes, TED is skipped for that pair. The fusion layer uses the no-TED weight formula instead (see [fusion.md](fusion.md)).

### 4.5 Reranking

#### ted_rerank(query_tree, candidates, reader)

- REQUIRES: `query_tree` is a valid `ExprTree` with `node_count ≤ 50`. `candidates` is a list of `(decl_id, wl_score)` pairs from WL screening. `reader` is an open `IndexReader`.
- ENSURES: Returns `(decl_id, ted_similarity_score)` pairs for all candidates with `node_count ≤ 50`. Candidate trees are fetched via batched `reader.get_constr_trees(ids)`.

Candidates with `node_count > 50` are not scored by TED — they are passed through with `ted_similarity = None` so the fusion layer knows to use the no-TED formula.

## 5. Error Specification

| Condition | Error type | Outcome |
|-----------|-----------|---------|
| Candidate tree deserialization fails | Logged warning | Candidate excluded from TED scoring |
| Empty candidate list | — | Return empty list |

## 6. Non-Functional Requirements

- Zhang-Shasha is O(n² × m²) where n, m are node counts. With the 50-node threshold, worst case is 50² × 50² = 6.25M operations per pair — acceptable for up to 500 candidates.
- Phase 2 may raise the threshold to 200–500 nodes with an OCaml/Rust APTED implementation.

## 7. Examples

### Identical trees

Given: Two identical trees with 10 nodes each.

When: `ted_similarity(tree_a, tree_b)` is called

Then: `ted = 0`, similarity = `1.0 - 0/10 = 1.0`

### Completely different trees

Given: `tree_a` has 5 nodes, `tree_b` has 5 nodes, all labels differ across categories.

When: `ted_similarity(tree_a, tree_b)` is called

Then: `ted = 5.0` (delete all of A, insert all of B), similarity = `max(0.0, 1.0 - 5.0/5) = 0.0`

### Same-category rename

Given: `tree_a` has root `LAbs`, `tree_b` has root `LProd` (both in Binder category), each with 1 identical child.

When: `ted(tree_a, tree_b)` is called

Then: `ted = 0.5` (one same-category rename).

## 8. Language-Specific Notes (Python)

- Implement Zhang-Shasha with explicit stack/DP tables (avoid deep recursion).
- Use `@functools.lru_cache` or similar for leftmost leaf computation if beneficial.
- Package location: `src/wily_rooster/channels/`.
