# Retrieval Pipeline

Technical design for the multi-channel retrieval pipeline and fusion logic.

**Feature**: [Multi-Channel Retrieval](../features/retrieval-channels.md)
**Stories**: [Epic 3: Retrieval Quality](../requirements/stories/tree-search-mcp.md#epic-3-retrieval-quality)
**Implementation spec**: [specification/](../../specification/) ([pipeline](../../specification/pipeline.md), [fusion](../../specification/fusion.md))

---

## Channel-to-Implementation Mapping

The feature document defines five retrieval channels by user-facing name. The table below maps each to its implementation algorithm and the section in this document that describes it.

| Feature Channel | Implementation Metric | Section |
|---|---|---|
| Structural | WL (Weisfeiler-Leman histogram cosine similarity) | WL Kernel Screening |
| Fine Structural | TED (Zhang-Shasha tree edit distance) | TED Fine Ranking |
| Symbol Overlap | MePo (iterative breadth-first symbol selection) | MePo Symbol Overlap |
| Constant Name | const_jaccard (Jaccard index over extracted constant names) | Fine-Ranking Metric Fusion |
| Lexical | FTS5 (SQLite full-text search with BM25 ranking) | FTS5 Full-Text Search |

`collapse_match` is an additional structural sub-metric used in the fine-ranking weighted sum; it does not correspond to a standalone feature channel.

## Neural Channel Integration

When a neural model checkpoint and precomputed embeddings are available, a neural retrieval channel participates in query processing. See [neural-retrieval.md](neural-retrieval.md) for the full technical design of the neural channel (encoder, embedding storage, similarity search, model management).

The neural channel is optional. When unavailable (no model checkpoint, no embeddings, or model hash mismatch), all query pipelines below operate identically to their non-neural versions — the neural step is simply skipped.

## Query Processing

### search_by_structure

```
1. Parse the query expression (via TypeExprParser) → ConstrNode (pure Python, no subprocess; instantiated on first structural query, kept alive for server lifetime)
2. coq_normalize(constr_node)            → normalized ExprTree (includes constr_to_tree + recompute_depths + assign_node_ids)
3. cse_normalize(tree)                   → CSE-reduced tree (recomputes depths + node_ids)
4. wl_histogram(tree, h=3)              → query histogram
5. wl_screen(histogram, library, N=500) → top-500 WL candidates
6. For candidates with node_count ≤ 50:
     compute ted_similarity, collapse_match, const_jaccard
     combine with weighted sum
7. For candidates with node_count > 50:
     compute collapse_match, const_jaccard
     combine with weighted sum
8. Rank by structural_score
9. Return top-N results (default N=50)
```

### search_by_type (multi-channel)

```
1. Parse and normalize the type expression (once — shared across all channels)
2. Run WL screening pipeline (above)                 → structural ranked list
3. Extract symbols from normalized tree, run MePo     → symbol ranked list
4. Run FTS5 query (`fts_query`) on the original user-provided type_expr string → lexical ranked list
5. If neural channel available:
     encode type_expr text via neural encoder         → neural ranked list
6. rrf_fuse([structural, symbol, lexical, neural?], k=60) → final ranked list
7. Return top-N results
```

Note: `extract_symbols` at query time is equivalent to `extract_consts` (const-jaccard) operating on the `ExprTree`. Implementations should reuse `extract_consts`.

### search_by_symbols

```
1. Accept a symbol list directly from the caller (names at any qualification level)
2. Resolve each symbol to FQN(s):
   a. If the name is an exact key in the inverted index → use directly
   b. Otherwise, suffix-match against all FQN keys in the inverted index
      (e.g., "Nat.add" matches "Coq.Init.Nat.add")
   c. Ambiguous names (matching multiple FQNs) expand to all matches
   d. Names matching zero FQNs are passed through as-is (MePo handles missing symbols gracefully)
3. Run MePo iterative selection with resolved FQN set (p=0.6, c=2.4, max_rounds=5)
4. Return ranked results
```

**Suffix index**: At server startup, build a reverse lookup from suffixes to FQNs using the inverted index keys. For each FQN like `Coq.Init.Nat.add`, index all proper suffixes: `Init.Nat.add`, `Nat.add`, `add`. If a suffix maps to multiple FQNs, store all of them (do not discard ambiguous suffixes — expand to the full set at query time to maximize recall).

Note: Const Jaccard refinement for `search_by_symbols` is deferred to Phase 2.

### search_by_name

```
1. Preprocess query for FTS5 via fts_query (qualified name → split on "." → AND terms, escape specials)
2. Run FTS5 MATCH with BM25 weights (name=10.0, statement=1.0, module=5.0)
3. Return ranked results
```

## WL Kernel Screening

Precompute WL histogram vectors for all declarations at h=3. On query:
1. Parse and normalize the query expression (normalization happens once and the normalized tree is shared across all channels — structural scoring, symbol extraction, and FTS)
2. Compute WL histogram at h=3
3. Apply size filter (see size filter thresholds below)
4. Cosine similarity against all precomputed vectors (sparse dot product, producing a float result)
5. Return top-N candidates (N=200-500, tunable for recall)

Sub-second on 100K items. Histograms loaded into memory at server startup (~100MB for 100K declarations).

**Critical constraint**: The query h value must match the indexed h value. Comparing histograms computed at different h values produces meaningless similarity scores because the label spaces differ.

**MD5 encoding**: All MD5 calls (in WL labeling and CSE hashing) produce lowercase 32-character hex strings from UTF-8-encoded input. This applies uniformly to all WL iterations including iteration 0: the simplified label string (e.g., `"Prod_d0"`) is MD5-hashed before being stored as a histogram key. This ensures all histogram keys have a uniform format (32-character lowercase hex).

**node_count definition**: `node_count` is computed on the post-CSE-normalized tree. Both the stored declaration `node_count` and the online query `node_count` must use the same measurement point for size filter consistency.

**Size filter thresholds**: For queries with fewer than 600 nodes, reject candidates with size ratio > 1.2. For queries with 600+ nodes, reject candidates with size ratio > 1.8.

**Query normalization failure**: If `recompute_depths()`, `assign_node_ids()`, or `cse_normalize()` fails on the query expression (e.g., recursion depth exceeded), return an empty candidate list and log a warning.

## MePo Symbol Overlap

Iterative breadth-first selection with inverse-frequency weighting:
- Weight function: `1.0 + 2.0 / log2(freq + 1)` — rare symbols get high weight
- Relevance: weighted overlap of candidate's symbols with working set, normalized by candidate's total weight
- Iterative expansion: each round adds selected declarations' symbols to the working set, with decaying threshold (`p * (1/c)^round`)
- Parameters: p=0.6, c=2.4, max_rounds=5
- **Batch expansion**: Symbol set expansion is batch — the working symbol set `S` is updated only after all candidates in a round are evaluated, not during iteration within a round
- **Missing symbol handling**: If a query-time symbol is not found in `symbol_freq` (i.e., it does not appear in any indexed declaration), treat its frequency as 1. This applies only to query-time symbols; declaration symbols are guaranteed to be in `symbol_freq` by the indexing invariant.
- **FQN assumption**: The inverted index, `symbol_freq` table, and `declaration_symbols` map all use fully qualified kernel names as keys (see [coq-extraction.md](coq-extraction.md#symbol-fqn-resolution)). Query symbols must be resolved to FQNs before being passed to `mepo_select`. For `search_by_type`, this happens automatically via `extract_consts` on the normalized tree (which contains the same short names as the index — internal consistency). For `search_by_symbols`, the caller-provided names are resolved via the suffix index (see query processing above).

**Constructor-to-inductive mapping**: `LConstruct` nodes store the parent inductive type's FQN as their name plus a zero-based constructor index (see [expression-tree.md](data-models/expression-tree.md)). All constructors of the same inductive type contribute the same symbol name (the parent inductive FQN). This mapping happens at tree construction time (coq-normalization), not at symbol extraction time — no additional mapping is needed during `extract_symbols`.

Typical runtime: <200ms for 100K declarations with inverted index.

## FTS5 Full-Text Search

SQLite FTS5 with Porter stemming and Unicode tokenization. BM25 ranking with column weights biased toward name matches. Queries preprocessed to handle qualified name patterns. Runtime: <10ms.

**Query classification priority**: Rule 1 (contains `.`) > Rule 2 (contains `_`, no spaces) > Rule 3 (everything else — the fallback for all remaining queries including mixed inputs).

**Rebuild idempotency**: The FTS5 `rebuild` command reconstructs the index from scratch each time and is idempotent — no guards against double-rebuild are needed.

**Token limit**: A 20-token safety limit is applied uniformly to all query types. For AND queries, dropping tokens makes the query less restrictive; for OR queries, dropping tokens reduces recall.

## TED Fine Ranking

Zhang-Shasha tree edit distance on CSE-normalized trees. Applied only to expression pairs where **both** trees have node_count ≤ 50. Cost model distinguishes leaf vs. interior operations and same-category vs. cross-category renames. Threshold can be raised to 200-500 nodes with an OCaml/Rust APTED implementation.

**Negative similarity**: The similarity formula `1.0 - edit_distance / max(node_count(T1), node_count(T2))` can produce negative values for sufficiently different trees. Clamp to 0.0 — no warning needed, as negative pre-clamp values are expected for structurally dissimilar trees (e.g., cross-category renames).

**Tree retrieval**: Candidate trees are deserialized from `declarations.constr_tree` BLOBs by the pipeline orchestrator before passing to `ted_rerank`. Use a batched `SELECT constr_tree FROM declarations WHERE id IN (...)` query rather than individual lookups.

## Fine-Ranking Metric Fusion

`wl_cosine` in the weighted sums below is the cosine similarity score from WL screening for the same query-candidate pair — not a separately computed value.

For candidates where **both** query and candidate have node_count ≤ 50 (TED available):

```
structural_score = 0.15 * wl_cosine
                 + 0.40 * ted_similarity
                 + 0.30 * collapse_match
                 + 0.15 * const_jaccard
```

For candidates without TED (node_count > 50):

```
structural_score = 0.25 * wl_cosine
                 + 0.50 * collapse_match
                 + 0.25 * const_jaccard
```

## Reciprocal Rank Fusion

```
RRF_score(d) = Σ_c  1 / (k + rank_c(d))
```

k=60 (standard). Each channel contributes independently. No learned weights.

### Channel Contributions by Tool

| MCP Tool | Channels Used |
|----------|--------------|
| `search_by_structure` | WL + TED + collapse-match + Const Jaccard, combined via weighted sum (no RRF — uses only the fine-ranking weighted sum) |
| `search_by_symbols` | MePo only in Phase 1. Const Jaccard refinement is deferred to Phase 2. |
| `search_by_name` | FTS5 only |
| `search_by_type` | WL + MePo + FTS5 + Neural (when available), fused with RRF |
