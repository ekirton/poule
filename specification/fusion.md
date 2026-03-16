# Metric Fusion

Reciprocal Rank Fusion and fine-ranking weighted sum for combining retrieval channel scores.

**Architecture**: [retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md) § Fine-Ranking Metric Fusion, § Reciprocal Rank Fusion

---

## 1. Purpose

Define the fusion strategies that combine scores from multiple retrieval channels into final rankings: (1) a weighted sum for structural fine-ranking, and (2) Reciprocal Rank Fusion (RRF) for multi-channel search.

## 2. Scope

**In scope**: Structural score weighted sum (with/without TED), RRF, collapse-match similarity, score clamping.

**Out of scope**: Individual channel implementations (owned by channel specs), pipeline orchestration (owned by pipeline).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Structural score | The combined fine-ranking score from WL cosine, TED, collapse match, and const Jaccard |
| RRF | Reciprocal Rank Fusion — a rank-based combination method that does not require score calibration |
| Collapse match | A recursive structural similarity metric that compares tree shapes by collapsing matching subtrees |

## 4. Behavioral Requirements

### 4.1 Score Clamping

All individual channel scores shall be clamped to [0.0, 1.0] before entering any fusion formula.

#### clamp_score(score)

- ENSURES: Returns `max(0.0, min(1.0, score))`.

### 4.2 Node Category Classification

#### node_category(label)

Classify a `NodeLabel` into one of these categories (used by collapse match):

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

### 4.3 Collapse-Match Similarity

#### collapse_match(tree_a, tree_b)

- REQUIRES: Both are valid `ExprTree` instances.
- ENSURES: Returns a float in [0.0, 1.0] representing structural similarity.

Algorithm (recursive):
1. If both roots have the same label: score 1.0 for this node, then recurse into children pairwise (matching by position). If child counts differ, unmatched children score 0.0.
2. If roots have different labels but the same category: score 0.5 for this node, recurse into children.
3. If roots have different categories: score 0.0 for this subtree (no recursion).

Final score: sum of all node scores / max(node_count(tree_a), node_count(tree_b)).

### 4.4 Fine-Ranking Weighted Sum

#### structural_score(wl_cosine, ted_similarity, collapse_match, const_jaccard, has_ted)

- REQUIRES: All scores are in [0.0, 1.0] (pre-clamped). `has_ted` indicates whether TED was computed.
- ENSURES: Returns the weighted sum.

**With TED** (`has_ted = True`; both query and candidate have node_count ≤ 50):

```
score = 0.15 * wl_cosine + 0.40 * ted_similarity + 0.30 * collapse_match + 0.15 * const_jaccard
```

**Without TED** (`has_ted = False`; either tree exceeds 50 nodes):

```
score = 0.25 * wl_cosine + 0.50 * collapse_match + 0.25 * const_jaccard
```

`wl_cosine` is the cosine similarity from WL screening — not separately computed.

### 4.5 Reciprocal Rank Fusion

#### rrf_fuse(ranked_lists, k)

- REQUIRES: `ranked_lists` is a list of ranked lists, where each list contains `(decl_id, score)` pairs ordered by score descending. `k = 60` (standard).
- ENSURES: Returns a single ranked list of `(decl_id, rrf_score)` pairs, ordered by RRF score descending.

Formula:
```
RRF_score(d) = Σ_c  1 / (k + rank_c(d))
```

Where `rank_c(d)` is the 1-based rank of declaration `d` in channel `c`. Declarations not present in a channel's list do not contribute to the sum for that channel.

### 4.6 Channel Contributions by Tool

| MCP Tool | Fusion Strategy |
|----------|----------------|
| `search_by_structure` | Fine-ranking weighted sum only (no RRF) |
| `search_by_symbols` | MePo only (no fusion) |
| `search_by_name` | FTS5 only (no fusion) |
| `search_by_type` | RRF across structural (weighted sum), MePo, and FTS5 |

## 5. Error Specification

| Condition | Outcome |
|-----------|---------|
| All channel scores are 0.0 | Structural score is 0.0 |
| Empty ranked list in RRF | That list contributes nothing; other lists proceed normally |
| All ranked lists empty | RRF returns empty list |

No errors are raised by fusion functions.

## 6. Examples

### Structural score with TED

Given: `wl_cosine=0.8, ted_similarity=0.9, collapse_match=0.7, const_jaccard=0.6`

When: `structural_score(0.8, 0.9, 0.7, 0.6, has_ted=True)`

Then: `0.15*0.8 + 0.40*0.9 + 0.30*0.7 + 0.15*0.6 = 0.12 + 0.36 + 0.21 + 0.09 = 0.78`

### Structural score without TED

Given: `wl_cosine=0.8, collapse_match=0.7, const_jaccard=0.6`

When: `structural_score(0.8, None, 0.7, 0.6, has_ted=False)`

Then: `0.25*0.8 + 0.50*0.7 + 0.25*0.6 = 0.20 + 0.35 + 0.15 = 0.70`

### RRF fusion

Given: Two ranked lists, each with 3 items. k=60.

List A: [d1 (rank 1), d2 (rank 2), d3 (rank 3)]
List B: [d2 (rank 1), d3 (rank 2), d4 (rank 3)]

Then:
- d1: 1/(60+1) = 0.0164
- d2: 1/(60+2) + 1/(60+1) = 0.0161 + 0.0164 = 0.0325
- d3: 1/(60+3) + 1/(60+2) = 0.0159 + 0.0161 = 0.0320
- d4: 1/(60+3) = 0.0159

Result: [d2, d3, d1, d4]

## 7. Language-Specific Notes (Python)

- Use `collections.defaultdict(float)` for RRF score accumulation.
- Collapse match can be recursive (trees are ≤ 50 nodes when used with TED, larger otherwise — but collapse match is always applied regardless of size).
- Package location: `src/wily_rooster/fusion/`.
