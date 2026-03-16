# Fusion: RRF and Fine-Ranking Metric Fusion

Combines the independent ranked lists produced by all channels into a single result. Two stages: (1) fine-ranking metric fusion for structural channels, (2) Reciprocal Rank Fusion across all channels.

Parent architecture: [doc/architecture/retrieval-pipeline.md](../doc/architecture/retrieval-pipeline.md)
Channels: [channel-wl-kernel.md](channel-wl-kernel.md), [channel-ted.md](channel-ted.md), [channel-const-jaccard.md](channel-const-jaccard.md), [channel-mepo.md](channel-mepo.md), [channel-fts.md](channel-fts.md)
Pipeline: [pipeline.md](pipeline.md)

---

## 1. Purpose

Provide parameter-free rank combination so that items appearing in multiple retrieval channels rank higher than items appearing in only one. Fine-ranking metric fusion handles structural sub-channels; RRF handles cross-channel combination.

---

## 2. Scope

Covers the RRF algorithm, fine-ranking weighted sums, and collapse-match similarity. Does not cover individual channel scoring (see channel specs) or the orchestration that decides which channels to invoke (see [pipeline.md](pipeline.md)).

---

## 3. Reciprocal Rank Fusion

All channels produce independent ranked lists. RRF combines them without learned weights.

```
function rrf_fuse(ranked_lists, k=60):
    scores = {}  # decl_id -> accumulated RRF score
    for channel_results in ranked_lists:
        for (rank, decl_id) in enumerate(channel_results, start=1):
            scores[decl_id] = scores.get(decl_id, 0) + 1.0 / (k + rank)

    fused = sorted(scores.items(), by=value, descending=True)
    return fused
```

### Channel Contributions by MCP Tool

Each MCP search tool invokes a different subset of channels:

| MCP Tool | Channels Used |
|----------|--------------|
| `search_by_structure` | WL screening + TED fine ranking + Const Jaccard, fused with RRF |
| `search_by_symbols` | MePo (primary), optionally Const Jaccard |
| `search_by_name` | FTS5 only |
| `search_by_type` | WL screening (on the parsed type expression) + MePo + FTS5, fused with RRF |

### Parameter k

`k = 60`.

---

## 4. Fine-Ranking Metric Fusion

When multiple structural metrics are computed for the same candidate (from `search_by_structure`), they are combined with a weighted sum before RRF fusion with other channels.

### Score Computation

For candidates with node_count <= 50 (TED available):

```
structural_score = 0.15 * wl_cosine
                 + 0.40 * ted_similarity
                 + 0.30 * collapse_match
                 + 0.15 * const_jaccard
```

For candidates with node_count > 50 (TED skipped):

```
structural_score = 0.25 * wl_cosine
                 + 0.50 * collapse_match
                 + 0.25 * const_jaccard
```


### Collapse-Match Similarity

Measures whether the query tree can "collapse onto" a candidate tree by merging nodes at matching levels.

```
function collapse_match(query, candidate):
    if query is a leaf and candidate is a leaf:
        if same_category(query.label, candidate.label):
            return 1.0
        else:
            return 0.0

    if query is a leaf:
        # leaf matches against any subtree of candidate
        return max(collapse_match(query, c) for c in candidate.children)
            if candidate.children else 0.0

    if candidate is a leaf:
        return 0.0

    if not same_category(query.label, candidate.label):
        return 0.0

    # Match children greedily left-to-right
    score = 0.0
    matched = 0
    for qc in query.children:
        best = 0.0
        for cc in candidate.children:
            best = max(best, collapse_match(qc, cc))
        score += best
        matched += 1

    if matched == 0:
        return 1.0 if same_category(query.label, candidate.label) else 0.0

    return score / max(len(candidate.children), matched)
```

This metric is asymmetric: it measures how well the query structure appears within the candidate, normalized by the candidate's size. A small query that matches a subtree of a large candidate scores well.

The `same_category` grouping uses the same node categories as the TED cost model (see [channel-ted.md](channel-ted.md#cost-model)).

---

## 5. Error Specification

| Error Condition | Classification | Outcome |
|-----------------|---------------|---------|
| All input ranked lists are empty | Normal case | Return empty fused list |
| Single ranked list provided to RRF | Normal case | Return that list re-scored with RRF formula (ranks preserved) |
| `collapse_match` receives tree with unbounded depth (stack overflow risk) | Invariant violation | Cap recursion depth at 200; return 0.0 beyond |
| `wl_cosine`, `ted_similarity`, `const_jaccard`, or `collapse_match` returns value outside [0, 1] | Invariant violation | Clamp to [0, 1]; log warning |

**Design rule**: Fusion never fails. Degenerate inputs produce degenerate (empty or single-source) outputs.

---

## 6. Examples

### Example: RRF with 3 channels

**Given**: Three ranked lists for `search_by_type`:
- WL channel: `[D1, D2, D3]` (D1 at rank 1)
- MePo channel: `[D2, D4, D1]`
- FTS5 channel: `[D3, D1, D5]`

**When**: `rrf_fuse([wl, mepo, fts5], k=60)`.

**Then**: RRF scores (k=60):
- D1: 1/(60+1) + 1/(60+3) + 1/(60+2) = 0.01639 + 0.01587 + 0.01613 = **0.04839**
- D2: 1/(60+2) + 1/(60+1) = 0.01613 + 0.01639 = **0.03252**
- D3: 1/(60+3) + 1/(60+1) = 0.01587 + 0.01639 = **0.03226**
- D4: 1/(60+2) = **0.01613**
- D5: 1/(60+3) = **0.01587**

Final ranking: D1, D2, D3, D4, D5. D1 ranks first because it appears in all 3 channels.

### Example: Fine-ranking with TED available

**Given**: Query tree has 20 nodes. Candidate C has 30 nodes. Metrics:
- `wl_cosine(query, C)` = 0.82
- `ted_similarity(query, C)` = 0.65
- `collapse_match(query, C)` = 0.71
- `const_jaccard(query, C)` = 0.50

**When**: Both trees ≤ 50 nodes, so TED formula applies.

**Then**: `structural_score = 0.15*0.82 + 0.40*0.65 + 0.30*0.71 + 0.15*0.50 = 0.123 + 0.260 + 0.213 + 0.075 = 0.671`

### Example: Fine-ranking without TED

**Given**: Query tree has 80 nodes (> 50). Same candidate C with:
- `wl_cosine` = 0.82, `collapse_match` = 0.71, `const_jaccard` = 0.50

**When**: Query exceeds 50 nodes, so no-TED formula applies.

**Then**: `structural_score = 0.25*0.82 + 0.50*0.71 + 0.25*0.50 = 0.205 + 0.355 + 0.125 = 0.685`
